"""Compare the frozen held-out intervention identities before and after edits."""
import csv
import json
import sqlite3
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from contextlib import closing
from math import isclose
from pathlib import Path
from statistics import mean

from .features import FEATURES
from .heldout import baseline_score, originals_for
from .heldout_protocol import protocol
from .isolation import IsolationForest, Split
from .monitoring_replay import sha256, verify_snapshot
from .perturbations import candidates, scenario
from .storage import replay


def average_precision(scores, labels):
    """Compute AP at distinct score thresholds, including all cutoff ties together."""
    if not labels or not labels <= scores.keys():
        raise ValueError("AP requires nonempty labels in the score population")
    population = Counter(scores.values())
    positive = Counter(scores[identity] for identity in labels)
    seen = hits = 0
    area = 0.0
    for score in sorted(population, reverse=True):
        seen += population[score]
        hits += positive[score]
        area += positive[score] * hits / seen
    return area / len(labels)


def paired_metrics(clean, edited, labels):
    if clean.keys() != edited.keys():
        raise ValueError("paired populations differ")
    clean_ap, edited_ap = (average_precision(scores, labels) for scores in (clean, edited))

    def percentiles(scores):
        ordered = sorted(scores.values())
        return {key: (bisect_left(ordered, scores[key]) + bisect_right(ordered, scores[key]))
                / (2 * len(ordered)) for key in labels}

    before, after = percentiles(clean), percentiles(edited)
    deltas = [edited[key] - clean[key] for key in sorted(labels)]
    return dict(clean_ap=clean_ap, edited_ap=edited_ap, ap_change=edited_ap - clean_ap,
                score_win_rate=mean((delta > 0) + .5 * (delta == 0) for delta in deltas),
                mean_score_change=mean(deltas),
                mean_rank_change_pp=100 * mean(after[key] - before[key] for key in sorted(labels)))


def score_function(model):
    parameters = model["parameters"]
    columns = model["columns"]
    indices = tuple(FEATURES.index(name) for name in columns)

    def node(value):
        if isinstance(value, dict):
            return Split(value["column"], value["cut"], node(value["left"]), node(value["right"]))
        return value

    if "trees" in parameters:
        forest = IsolationForest(tuple(parameters["columns"]), tuple(map(node, parameters["trees"])),
                                 parameters["normalizer"])
        score = forest.score
    else:
        def score(values):
            return baseline_score(values, names=columns, model=parameters)

    return lambda row: score(tuple(row[-1][i] for i in indices))


def concentration_changes(original, edited, labels, spillover):
    names = FEATURES
    hhi = names.index("sender_out_concentration")
    first_edit = min(original[key][0] for key in labels)
    if any(original[key][0] <= first_edit for key in spillover):
        raise ValueError("concentration spillover reached the first edited ledger or earlier")
    result = {}
    for group, ids in (("direct", labels), ("spillover", spillover)):
        differences = [tuple(b - a for a, b in zip(original[key][-1], edited[key][-1], strict=True))
                       for key in ids]
        result[group] = dict(
            rows=len(ids), changed_features={name: sum(row[i] != 0 for row in differences)
                                            for i, name in enumerate(names)},
            concentration_increased=sum(row[hhi] > 0 for row in differences),
            concentration_decreased=sum(row[hhi] < 0 for row in differences),
            concentration_equal=sum(row[hhi] == 0 for row in differences),
        )
    return result


def macro(rows):
    """Give each available block equal weight, then average its balanced scenario cells."""
    blocks = defaultdict(list)
    for row in rows:
        blocks[row["block"]].append(row)
    fields = ("clean_ap", "edited_ap", "ap_change", "score_win_rate",
              "mean_score_change", "mean_rank_change_pp")
    return {field: mean(mean(r[field] for r in block) for block in blocks.values()) for field in fields}


def run(source=Path("reports/generated/phase3b3"), processed=Path("data/processed")):
    paths = {name: source / name for name in ("evaluation.json", "models.json", "clean-scores.csv")}
    hashes = {name: sha256(path) for name, path in paths.items()}
    evaluation = json.loads(paths["evaluation.json"].read_bytes())
    models = json.loads(paths["models.json"].read_bytes())
    config, blocks = protocol()
    if evaluation["protocol"] != config or any(
        hashes[name] != evaluation["artifacts"][name] for name in ("models.json", "clean-scores.csv")
    ):
        raise ValueError("evaluation protocol or artifact hashes differ")
    clean = defaultdict(dict)
    with paths["clean-scores.csv"].open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            clean[int(row["block"]), row["model"]][row["identity"]] = float(row["score"])
    scorers = {name: score_function(model) for name, model in models.items()}
    frozen = {(r["block"], r["family"], r["level"], r["seed"], r["model"]): r
              for r in evaluation["synthetic"]}
    rows, concentration = [], []
    for number, block in enumerate(blocks[8:], 9):
        path = (processed / f"phase3b3-block-{number:02d}.sqlite").resolve()
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
            verify_snapshot(db, number, block["headers"], evaluation["snapshots"][str(number)])
            ledgers = list(replay(db))
        start = block["start"]
        original = originals_for(ledgers, start)
        eligible = candidates(ledgers, start, evaluation["amount_limits"])
        for entry in (r for r in evaluation["interventions"] if r["block"] == number):
            family, level, seed = (entry[key] for key in ("family", "level", "seed"))
            edited, labels, spill = scenario(ledgers, start, original, family, level, eligible[family], seed)
            if labels != set(entry["modified"]) or spill != set(entry["spillover"]):
                raise ValueError("replayed intervention identities differ")
            fields = dict(block=number, family=family, level=level, seed=seed)
            if family == "concentration":
                concentration.append(dict(**fields, **concentration_changes(original, edited, labels, spill)))
            for model, score in scorers.items():
                before = clean[number, model]
                if before.keys() != original.keys():
                    raise ValueError("clean score population differs from replay")
                after = before | {key: score(edited[key]) for key in labels | spill}
                metrics = paired_metrics(before, after, labels)
                expected = frozen[number, family, level, seed, model]
                for observed, saved in (("edited_ap", "ap"), ("score_win_rate", "matched_win_rate"),
                                        ("mean_score_change", "matched_mean_delta")):
                    if not isclose(metrics[observed], expected[saved], abs_tol=1e-14):
                        raise ValueError(f"frozen {saved} differs for {model}, {fields}")
                rows.append(dict(**fields, model=model, positives=len(labels), population=len(before), **metrics))
    if len(rows) != len(frozen):
        raise ValueError("incomplete frozen scenario coverage")
    return dict(inputs=hashes, snapshots=evaluation["snapshots"], rows=rows, concentration=concentration,
                macro={model: macro([r for r in rows if r["model"] == model]) for model in models})


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, allow_nan=False))

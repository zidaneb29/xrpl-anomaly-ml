"""Offline four-train/two-development detector comparison for Phase 3B.2."""
import argparse
import csv
import platform
import sqlite3
import subprocess
import time
from contextlib import closing
from itertools import groupby
from pathlib import Path
from statistics import mean, median

from . import baseline
from .expansion import FROZEN_DIGEST
from .expansion_report import report, scored_features
from .features import FEATURES
from .isolation import IsolationForest
from .perturbations import FAMILIES, SEEDS, candidates, scenario
from .pilot import digest, dump
from .storage import replay

OUTPUT = Path("reports/generated/phase3b2")
PROCESSED = Path("data/processed")
GROUPS = {
    "static": (0, 1),
    "temporal": tuple(i for i, name in enumerate(FEATURES[:18]) if "counterparties" not in name),
    "full": tuple(range(len(FEATURES))),
}
SIZES = (128, 256)
MODEL_SEEDS = (7, 29)
TREES = 64


def metrics(scores, positives):
    """Score-tie grouped average precision and deterministic 1% recall."""
    if not positives or not positives <= scores.keys():
        raise ValueError("expected observed intervention labels")
    ordered = sorted((baseline.alert_key(value, key) for key, value in scores.items()),
                     reverse=True)
    rank = count = 0
    precision_sum = 0.0
    for _, ties in groupby(ordered, key=lambda item: item[0]):
        members = list(ties)
        hits = sum(item[2] in positives for item in members)
        rank += len(members)
        count += hits
        precision_sum += hits * count / rank
    budget = len(ordered) // 100
    selected = sum(item[2] in positives for item in ordered[:budget])
    low = high = selected
    if budget:
        cutoff = ordered[budget - 1][0]
        above = [item for item in ordered if item[0] > cutoff]
        tied = [item for item in ordered if item[0] == cutoff]
        certain = sum(item[2] in positives for item in above)
        tied_hits = sum(item[2] in positives for item in tied)
        available = budget - len(above)
        low = certain + max(0, available - (len(tied) - tied_hits))
        high = certain + min(available, tied_hits)
    return dict(ap=precision_sum / count, recall=selected / count,
                recall_tie_bounds=[low / count, high / count],
                positives=count, prevalence=count / len(ordered), budget=budget)


def vector(row, columns):
    return tuple(row[-1][index] for index in columns)


def compare_ranks(left, right):
    def ranks(values):
        ordered = sorted(values, key=lambda key: values[key])
        result = {}
        rank = 0
        for _, keys in groupby(ordered, key=values.get):
            ties = list(keys)
            result.update((key, rank + (len(ties) + 1) / 2) for key in ties)
            rank += len(ties)
        return result

    def top(values):
        return set(sorted(values, key=lambda key: baseline.alert_key(values[key], key),
                          reverse=True)[:len(values) // 100])

    a, b = ranks(left), ranks(right)
    center = (len(a) + 1) / 2
    denominator = (sum((x - center) ** 2 for x in a.values()) *
                   sum((x - center) ** 2 for x in b.values())) ** 0.5
    correlation = sum((a[key] - center) * (b[key] - center) for key in a) / denominator if denominator else None
    return dict(spearman=correlation, top_overlap=len(top(left) & top(right)),
                top_budget=len(a) // 100)


def compare(streams, starts):
    """Fit on four original blocks, then compare matched scenarios in two later blocks."""
    if len(streams) != 6 or len(starts) != 6 or any(
            left[-1][0] >= right[0][0] or left[-1][1] >= right[0][1]
            for left, right in zip(streams, streams[1:])):
        raise ValueError("expected six disjoint chronological blocks")
    originals = [{row[2]: row for row in scored_features(stream, start)}
                 for stream, start in zip(streams, starts, strict=True)]
    identities = set()
    for stream, block in zip(streams, originals, strict=True):
        payment_ids = [payment[1] for _, _, rows in stream for payment in rows]
        unique_ids = set(payment_ids)
        if not block or len(unique_ids) != len(payment_ids) or identities.intersection(unique_ids):
            raise ValueError("empty scoring block or duplicate identity across blocks")
        identities.update(unique_ids)
    train = [row for block in originals[:4] for row in block.values()]
    train_amounts = sorted(payment[4] for stream, start in zip(streams[:4], starts[:4], strict=True)
                           for _, close, rows in stream if start <= close < start + 1800
                           for payment in rows)
    limit = len(train_amounts) // 100
    amount_limits = train_amounts[limit], train_amounts[-1 - limit]
    scenarios = []
    eligibility = {}
    for block in (4, 5):
        original = originals[block]
        eligible = candidates(streams[block], starts[block], amount_limits)
        eligibility[block + 1] = {}
        for family, levels in FAMILIES.items():
            units = [events for events in eligible[family].values()
                     if family != "concentration" or len(events) >= max(levels)]
            eligibility[block + 1][family] = dict(senders=len(units), events=sum(map(len, units)))
            for seed in SEEDS:
                for level in levels:
                    rows, labels, affected = scenario(streams[block], starts[block], original,
                                                      family, level, eligible[family], seed)
                    changed = {key: row for key, row in rows.items() if key in labels | affected}
                    scenarios.append((block, family, level, seed, changed, labels, affected))

    results, configs, predictions, timings = [], {}, {}, {}
    for group, columns in GROUPS.items():
        names = tuple(FEATURES[i] for i in columns)
        training = [vector(row, columns) for row in train]
        models = [("baseline", None, None)]
        models.extend(("isolation", size, seed) for size in SIZES for seed in MODEL_SEEDS)
        for method, size, model_seed in models:
            key = f"{method}-{group}"
            started = time.perf_counter()
            if method == "baseline":
                model = baseline.fit(training, names)

                def score(values):
                    return baseline.score(values, names, model)[0]

                configs[key] = dict(columns=names, scales=model, omitted=[
                    name for name in names if name not in model])
            else:
                key += f"-{size}-{model_seed}"
                model = IsolationForest.fit(training, size=size, seed=model_seed, trees=TREES)
                score = model.score
                configs[key] = dict(columns=names, size=size, fitted_size=min(size, len(training)),
                                    seed=model_seed, trees=TREES,
                                    omitted=[name for i, name in enumerate(names) if i not in model.columns])
            fit_seconds = time.perf_counter() - started
            started = time.perf_counter()
            original_scores = {block: {identity: score(vector(row, columns))
                                      for identity, row in originals[block].items()}
                               for block in (4, 5)}
            timings[key] = dict(fit_seconds=fit_seconds, original_scoring_seconds=time.perf_counter() - started)
            predictions[key] = original_scores
            for block, family, level, seed, changed, labels, affected in scenarios:
                scores = original_scores[block].copy()
                scores.update((identity, score(vector(row, columns))) for identity, row in changed.items())
                record = dict(model=key, method=method, group=group, size=size, model_seed=model_seed,
                              block=block + 1, family=family, level=level, seed=seed,
                              affected=len(affected), modified=len(labels))
                if labels:
                    record.update(metrics(scores, labels))
                    controls = original_scores[block]
                    record["matched_win_rate"] = mean((1 if scores[i] > controls[i] else
                                                        0.5 if scores[i] == controls[i] else 0)
                                                       for i in sorted(labels))
                    record["matched_mean_delta"] = mean(scores[i] - controls[i] for i in sorted(labels))
                results.append(record)

    selected = {}
    rank_comparisons = []
    cold_start = []
    unseen = [FEATURES.index(name) for name in ("sender_unseen", "receiver_unseen")]
    for group in GROUPS:
        objective = {}
        for size in SIZES:
            cells = [r["ap"] for r in results if r["group"] == group and r["size"] == size and "ap" in r]
            if cells:
                objective[size] = mean(cells)
        if objective:
            size = max(objective, key=lambda size: (objective[size], -size))
            selected[group] = dict(size=size, mean_ap=objective)
            for block in (4, 5):
                for seed in MODEL_SEEDS:
                    forest = predictions[f"isolation-{group}-{size}-{seed}"][block]
                    ranks = compare_ranks(predictions[f"baseline-{group}"][block], forest)
                    rank_comparisons.append(dict(group=group, block=block + 1, seed=seed, **ranks))
            for block in (4, 5):
                models = [f"baseline-{group}", *(f"isolation-{group}-{size}-{seed}" for seed in MODEL_SEEDS)]
                for key in models:
                    groups = {True: [], False: []}
                    for identity, value in predictions[key][block].items():
                        cold = any(originals[block][identity][-1][index] for index in unseen)
                        groups[cold].append(value)
                    for cold, values in groups.items():
                        if values:
                            cold_start.append(dict(model=key, block=block + 1, any_endpoint_unseen=cold,
                                                   rows=len(values), median_score=median(values)))
    return dict(amount_limits=amount_limits, configs=configs, results=results, selected=selected,
                rank_comparisons=rank_comparisons, cold_start=cold_start, eligibility=eligibility,
                scenarios=[dict(block=b + 1, family=f, level=l, seed=s, modified=sorted(labels),
                                affected=sorted(affected))
                           for b, f, l, s, _, labels, affected in scenarios]), originals, predictions, timings


def run(output=OUTPUT, *, figures=False):
    started = time.perf_counter()
    blocks = report(development=True, output=output, processed=PROCESSED)
    streams = []
    for block in blocks:
        path = PROCESSED / f"phase3b2-block-{block['block']:02d}.sqlite"
        with closing(sqlite3.connect(path)) as db:
            streams.append(list(replay(db)))
    result, originals, predictions, timings = compare(streams, [block["start"] for block in blocks])
    feature_path = output / "features.csv"
    with feature_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(("block", "ledger", "position", "identity", "close_unix", *FEATURES))
        for block, rows in enumerate(originals, 1):
            writer.writerows((block, *row[:4], *row[-1]) for row in rows.values())
    scores_path = output / "development-scores.csv"
    with scores_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(("model", "block", "identity", "score"))
        for model, scores in predictions.items():
            for block, rows in scores.items():
                writer.writerows((model, block + 1, identity, value) for identity, value in rows.items())
    result.update(protocol_version=1, plan_sha256=FROZEN_DIGEST, python=platform.python_version(),
                  git_head=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                  source_sha256={p.name: digest(p.read_bytes()) for p in sorted(Path(__file__).parent.glob("*.py"))},
                  snapshots={b["block"]: b["snapshot_sha256"] for b in blocks},
                  families=FAMILIES, perturbation_seeds=SEEDS,
                  artifacts={p.name: digest(p.read_bytes()) for p in (feature_path, scores_path)})
    dump(output / "evaluation.json", result)
    if figures:
        from .development_figures import render

        render(output, blocks, originals, predictions, result)
    dump(output / "timings.json", dict(platform=platform.platform(), processor=platform.processor(),
                                       scorer_threads=1, timings=timings,
                                       total_seconds=time.perf_counter() - started))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--figures", action="store_true")
    args = parser.parse_args()
    run(figures=args.figures)

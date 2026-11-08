"""Fit on four training blocks, calibrate on two and evaluate four final blocks."""
import argparse
import csv
import json
import platform
import sqlite3
import subprocess
import time
import tracemalloc
from collections import Counter
from contextlib import closing
from dataclasses import asdict
from functools import partial
from itertools import combinations
from pathlib import Path
from statistics import mean

from . import baseline
from .development import GROUPS, MODEL_SEEDS, TREES, compare_ranks, metrics, vector
from .expansion_report import report, scored_features
from .features import FEATURES
from .heldout_protocol import CONFIG, RAW, SIZES, protocol
from .isolation import IsolationForest
from .perturbations import FAMILIES, SEEDS, candidates, scenario
from .pilot import digest, dump
from .storage import replay

OUTPUT = Path("reports/generated/phase3b3")
PROCESSED = Path("data/processed")


def score_pairs(scores):
    return ((score, identity) for identity, score in scores.items())


def alerts(scores, cutoff):
    selected = {identity for score, identity in score_pairs(scores)
                if baseline.alert_key(score, identity) > cutoff}
    stats = baseline.budget_summary(score_pairs(scores), cutoff)
    return selected, dict(**stats, rate=len(selected) / len(scores), cutoff_score=cutoff[0])


def fixed_budget(scores):
    ordered = sorted((baseline.alert_key(score, identity) for identity, score in scores.items()), reverse=True)
    budget = len(ordered) // 100
    chosen = {key[2] for key in ordered[:budget]}
    boundary = ordered[budget - 1][0] if budget else None
    return chosen, dict(rows=len(ordered), alerts=budget, rate=budget / len(ordered), cutoff_score=boundary,
                        above_score=sum(boundary is not None and key[0] > boundary for key in ordered),
                        tied_score=sum(key[0] == boundary for key in ordered),
                        alerted_ties=sum(key[0] == boundary for key in ordered[:budget]))


def clean_summary(scores, cutoff, endpoints):
    values = sorted(scores.values())
    operating, fixed = alerts(scores, cutoff), fixed_budget(scores)
    result = dict(operating=operating[1], fixed_budget=fixed[1],
                  quantiles={str(p): values[(len(values) - 1) * p // 100]
                             for p in (0, 25, 50, 75, 90, 95, 99, 100)})
    for name, (chosen, stats) in zip(("operating", "fixed_budget"), (operating, fixed), strict=True):
        counts = [Counter(endpoints[i][side] for i in chosen) for side in (0, 1)]
        stats["concentration"] = [
            dict(distinct=len(count), top_share=max(count.values(), default=0) / len(chosen) if chosen else None,
                 hhi=sum(n * n for n in count.values()) / len(chosen) ** 2 if chosen else None)
            for count in counts
        ]
    return result


def synthetic_metrics(scores, original, labels, affected, cutoff):
    selected, operating = alerts(scores, cutoff)
    fixed, ranking = fixed_budget(scores)
    strata = {"direct": labels, "spillover": affected, "unchanged": scores.keys() - labels - affected}
    record = dict(operating=operating, fixed_budget=ranking, strata={
        name: dict(rows=len(ids), operating_alerts=len(ids & selected), fixed_alerts=len(ids & fixed))
        for name, ids in strata.items()
    })
    if labels:
        deltas = [scores[i] - original[i] for i in sorted(labels)]
        record.update(metrics(scores, labels), threshold_recall=len(labels & selected) / len(labels),
                      matched_clean_recall=sum(baseline.alert_key(original[i], i) > cutoff
                                               for i in labels) / len(labels),
                      matched_mean_delta=mean(deltas),
                      matched_win_rate=mean((delta > 0) + 0.5 * (delta == 0) for delta in deltas))
    return record


def aggregate(records):
    fields = ("ap", "prevalence", "recall", "threshold_recall", "matched_win_rate")
    cells = {}
    for row in records:
        if "ap" in row:
            key = row["group"], row["method"], row["block"], row["family"], row["level"]
            cells.setdefault(key, []).append(row)
    by_cell = [dict(group=g, method=m, block=b, family=f, level=l,
                    **{field: mean(row[field] for row in rows) for field in fields})
               for (g, m, b, f, l), rows in sorted(cells.items())]
    per_block = {}
    for row in by_cell:
        per_block.setdefault((row["group"], row["method"], row["block"]), []).append(row)
    by_block = [dict(group=g, method=m, block=b, available_cells=len(rows),
                     **{field: mean(row[field] for row in rows) for field in fields})
                for (g, m, b), rows in sorted(per_block.items())]
    comparison = {}
    for field in ("ap", "recall", "threshold_recall"):
        full = {(row["method"], row["block"]): row[field] for row in by_block if row["group"] == "full"}
        deltas = {b: full["isolation", b] - full["baseline", b] for m, b in full if m == "baseline"}
        comparison[field] = dict(block_deltas=deltas, mean=mean(deltas.values()) if deltas else None,
                                 block_range=[min(deltas.values()), max(deltas.values())] if deltas else None,
                                 leave_one_out={b: mean(v for i, v in deltas.items() if i != b)
                                                for b in deltas} if len(deltas) > 1 else {})
    return dict(by_cell=by_cell, by_block=by_block, full_paired=comparison)


def originals_for(stream, start):
    rows = {row[2]: row for row in scored_features(stream, start)}
    if not rows:
        raise ValueError("empty scoring block")
    return rows


def fit_models(train):
    scorers, artifacts, benchmark = {}, {}, {}
    for group, columns in GROUPS.items():
        names = tuple(FEATURES[i] for i in columns)
        training = [vector(row, columns) for row in train]
        for seed in (None, *MODEL_SEEDS):
            method = "baseline" if seed is None else "isolation"
            key = f"{method}-{group}" if seed is None else f"{method}-{group}-{seed}"
            started = time.perf_counter()
            if seed is None:
                model = baseline.fit(training, names)
                scorer = partial(baseline_score, names=names, model=model)
                parameters = model
                omitted = [name for name in names if name not in model]
            else:
                model = IsolationForest.fit(training, size=SIZES[group], seed=seed, trees=TREES)
                scorer = model.score
                parameters = asdict(model)
                omitted = [name for i, name in enumerate(names) if i not in model.columns]
            benchmark[key] = dict(fit_seconds=time.perf_counter() - started, blocks={})
            scorers[key] = (group, method, columns, scorer)
            artifacts[key] = dict(columns=names, omitted=omitted, parameters=parameters)
    return scorers, artifacts, benchmark


def baseline_score(values, *, names, model):
    return baseline.score(values, names, model)[0]


def predict(rows, columns, scorer):
    return {identity: scorer(vector(row, columns)) for identity, row in rows.items()}


def benchmark_score(rows, columns, scorer):
    vectors = [vector(row, columns) for row in rows.values()]
    times = []
    started = time.perf_counter_ns()
    for values in vectors:
        tick = time.perf_counter_ns()
        scorer(values)
        times.append(time.perf_counter_ns() - tick)
    seconds = (time.perf_counter_ns() - started) / 1e9
    times.sort()
    tracemalloc.start()
    try:
        for values in vectors:
            scorer(values)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return dict(rows=len(vectors), seconds=seconds, rows_per_second=len(vectors) / seconds,
                median_us=times[(len(times) - 1) // 2] / 1000,
                p95_us=times[(len(times) - 1) * 95 // 100] / 1000, scoring_peak_python_bytes=peak)


def run(output=OUTPUT, *, figures=False):
    config, _ = protocol()
    blocks = report(heldout_root=RAW, output=output, processed=PROCESSED)

    def load(number):
        with closing(sqlite3.connect(PROCESSED / f"phase3b3-block-{number:02d}.sqlite")) as db:
            return list(replay(db))

    train, amounts, seen = [], [], set()

    def read(block):
        number, start = block["block"], block["start"]
        stream = load(number)
        payments = [payment for _, _, rows in stream for payment in rows]
        identities = {payment[1] for payment in payments}
        if len(identities) != len(payments) or seen.intersection(identities):
            raise ValueError("duplicate identity within or across blocks")
        seen.update(identities)
        return stream, originals_for(stream, start)

    for block in blocks[:4]:
        stream, originals = read(block)
        train.extend(originals.values())
        amounts.extend(payment[4] for _, _, rows in stream for payment in rows if payment[1] in originals)
    amounts.sort()
    limit = len(amounts) // 100
    amount_limits = amounts[limit], amounts[-1 - limit]
    scorers, artifacts, benchmark = fit_models(train)
    del train, amounts
    clean, results, stability, interventions = [], [], [], []
    pooled = {key: {} for key in scorers}
    calibration = {}
    for block in blocks[6:8]:
        stream, rows = read(block)
        endpoints = {p[1]: p[2:4] for _, _, payments in stream for p in payments}
        scores = {key: predict(rows, columns, scorer) for key, (_, _, columns, scorer) in scorers.items()}
        calibration[block["block"]] = scores, endpoints
        for key, values in scores.items():
            pooled[key].update(values)
    cutoffs = {key: baseline.alert_cutoff(score_pairs(values)) for key, values in pooled.items()}
    for key, values in pooled.items():
        artifacts[key]["cutoff"] = cutoffs[key]
        artifacts[key]["calibration"] = alerts(values, cutoffs[key])[1]
    model_path = output / "models.json"
    dump(model_path, artifacts)
    scores_path = output / "clean-scores.csv"
    with scores_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file, lineterminator="\n")
        writer.writerow(("block", "model", "identity", "score"))
        for number, (scores, endpoints) in calibration.items():
            for key, values in scores.items():
                clean.append(dict(block=number, model=key, **clean_summary(values, cutoffs[key], endpoints)))
                writer.writerows((number, key, identity, value) for identity, value in values.items())
        for block in blocks[8:]:
            number, start = block["block"], block["start"]
            stream, rows = read(block)
            endpoints = {p[1]: p[2:4] for _, _, payments in stream for p in payments}
            scores = {}
            for key, (_, _, columns, scorer) in scorers.items():
                values = scores[key] = predict(rows, columns, scorer)
                clean.append(dict(block=number, model=key, **clean_summary(values, cutoffs[key], endpoints)))
                writer.writerows((number, key, identity, value) for identity, value in values.items())
                benchmark[key]["blocks"][number] = benchmark_score(rows, columns, scorer)
            for group in GROUPS:
                keys = [f"baseline-{group}", *(f"isolation-{group}-{seed}" for seed in MODEL_SEEDS)]
                for a, b in combinations(keys, 2):
                    stability.append(dict(block=number, left=a, right=b, **compare_ranks(scores[a], scores[b])))
            eligible = candidates(stream, start, amount_limits)
            for family, levels in FAMILIES.items():
                eligible_senders = sum(family != "concentration" or len(events) >= max(levels)
                                       for events in eligible[family].values())
                for level in levels:
                    for seed in SEEDS:
                        modified, labels, affected = scenario(stream, start, rows, family, level, eligible[family], seed)
                        changed = {identity: modified[identity] for identity in sorted(labels | affected)}
                        metadata = dict(block=number, family=family, level=level, seed=seed)
                        interventions.append(dict(**metadata, eligible_senders=eligible_senders,
                                                  target_sender_units=max(1, len(rows) // 100),
                                                  modified=sorted(labels), spillover=sorted(affected)))
                        for key, (group, method, columns, scorer) in scorers.items():
                            values = scores[key] | predict(changed, columns, scorer)
                            results.append(dict(**metadata, group=group, model=key, method=method,
                                                **synthetic_metrics(values, scores[key], labels, affected, cutoffs[key])))
    for key, artifact in artifacts.items():
        benchmark[key]["compact_model_json_bytes"] = len(json.dumps(artifact, separators=(",", ":")).encode())
    result = dict(protocol=config, protocol_sha256=digest(CONFIG.read_bytes().replace(b"\r\n", b"\n")),
                  git_head=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                  python=platform.python_version(), sqlite=sqlite3.sqlite_version,
                  source_sha256={p.name: digest(p.read_bytes()) for p in sorted(Path(__file__).parent.glob("*.py"))},
                  snapshots={b["block"]: b["snapshot_sha256"] for b in blocks}, amount_limits=amount_limits,
                  clean=clean, calibration={k: v["calibration"] for k, v in artifacts.items()},
                  stability=stability, interventions=interventions, synthetic=results, aggregate=aggregate(results),
                  artifacts={p.name: digest(p.read_bytes()) for p in (model_path, scores_path)})
    dump(output / "evaluation.json", result)
    dump(output / "benchmark.json", dict(platform=platform.platform(), scorer_threads=1, models=benchmark))
    if figures:
        from .heldout_figures import render

        render(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--figures", action="store_true")
    args = parser.parse_args()
    run(args.output, figures=args.figures)

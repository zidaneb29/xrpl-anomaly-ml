"""Replay a cached pilot offline and produce a local baseline report."""
import argparse
import csv
import importlib.metadata
import json
import platform
import sqlite3
import subprocess
import sys
from collections import Counter
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from statistics import median

from . import baseline
from .features import FEATURES, SCHEMA_VERSION, WINDOW, features
from .pilot import digest, dump
from .storage import connect, ingest, replay


def summarize(values):
    if not values:
        return None
    ordered = sorted(values)
    return {"min": ordered[0], "median": median(ordered),
            "p99_nearest_rank": ordered[(99 * len(ordered) - 1) // 100], "max": ordered[-1]}


def analyze(directory, db_path, output, render=False, *, legacy_resolution=False):
    policy = "phase2_observed_resolution" if legacy_resolution else "phase3a_positive_dispersion"
    previous_summary = output / "summary.json"
    if previous_summary.exists():
        previous_policy = json.loads(previous_summary.read_bytes()).get(
            "scaling_policy", "phase2_observed_resolution")
        if previous_policy != policy:
            raise ValueError("use a separate output directory for a different scaling policy")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    with closing(connect(db_path)) as db:
        manifest = ingest(db, directory)
        ledgers = list(replay(db))
    if not ledgers:
        raise ValueError("no verified ledgers")
    start, end = manifest["configuration"]["range"]
    if manifest["gaps"] or len(ledgers) != end - start + 1:
        raise ValueError("baseline requires the complete frozen pilot")
    observed = [item for item in manifest["ledgers"].values()]
    exclusions = Counter()
    for item in observed:
        exclusions.update(item["exclusions"])
    payments = [row for _, _, rows in ledgers for row in rows]
    accounts = Counter(account for row in payments for account in row[2:4])
    edges = Counter((row[2], row[3]) for row in payments)
    closes = [close for _, close, _ in ledgers]
    first = next((idx for idx, close, _ in ledgers if close - closes[0] >= WINDOW), end + 1)
    # Freeze chronological boundaries by ledger/time coverage, before inspecting scores.
    available = end - first + 1
    train_end = first + available // 2
    calibration_end = first + 3 * available // 4
    bounds = {"train": [first, train_end - 1], "calibration": [train_end, calibration_end - 1],
              "test": [calibration_end, end]}
    snapshot = digest(json.dumps([(i, manifest["ledgers"][str(i)]["sha256"])
                                  for i in range(start, end + 1)]).encode())
    source = Path(__file__).parent
    code = {path.name: digest(path.read_bytes()) for path in sorted(source.glob("*.py"))}
    try:
        revision = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=source,
                                  capture_output=True, text=True, check=False).stdout.strip()
    except FileNotFoundError:
        revision = None
    report = {
        "snapshot_sha256": snapshot, "configuration_digest": manifest["configuration_digest"],
        "manifest_sha256": digest((directory / "manifest.json").read_bytes()),
        "code_sha256": code, "git_revision": revision or None,
        "environment": {"python": sys.version, "sqlite": sqlite3.sqlite_version,
                        "platform": platform.platform(), "processor": platform.processor(),
                        "packages": {d.metadata["Name"]: d.version
                                     for d in importlib.metadata.distributions()}},
        "command_arguments": sys.argv,
        "feature_schema_version": SCHEMA_VERSION, "window_seconds": WINDOW,
        "range": [start, end], "close_utc": [datetime.fromtimestamp(t, UTC).isoformat()
                                             for t in (closes[0], closes[-1])],
        "ledgers": len(ledgers), "all_transactions": sum(item["total"] for item in observed),
        "eligible_payments": len(payments), "exclusions": dict(exclusions),
        "total_delivered_drops": sum(row[4] for row in payments),
        "empty_eligible_ledgers": sum(not rows for _, _, rows in ledgers),
        "distinct_accounts": len(accounts), "repeated_accounts": sum(n > 1 for n in accounts.values()),
        "distinct_edges": len(edges), "repeated_edges": sum(n > 1 for n in edges.values()),
        "payments_on_repeated_edges": sum(n for n in edges.values() if n > 1),
        "ledger_latency_seconds": summarize([item["latency_seconds"] for item in observed]),
        "splits": bounds,
    }
    rows = list(features(ledgers))
    full = [row for row in rows if row[4]]
    report["warmup_payments"] = len(rows) - len(full)
    report["complete_feature_rows"] = len(full)
    report["complete_rows_with_prior_edge"] = sum(row[-1][-3] > 0 for row in full)
    report["sender_unseen"] = sum(row[-1][7] for row in full)
    report["receiver_unseen"] = sum(row[-1][15] for row in full)
    with (output / "features.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("snapshot_sha256", "schema", "ledger_index", "position", "hash",
                         "close_unix", "complete", *FEATURES))
        for index, position, identity, close, complete, values in rows:
            writer.writerow((snapshot, SCHEMA_VERSION, index, position, identity, close, int(complete),
                             *values, *[""] * (len(FEATURES) - len(values))))

    split_rows = {name: [row for row in full if lo <= row[0] <= hi]
                  for name, (lo, hi) in bounds.items()}
    report["split_counts"] = {name: len(block) for name, block in split_rows.items()}
    if all(split_rows.values()):
        train = [row[-1] for row in split_rows["train"]]
        model = baseline.fit(train, FEATURES, legacy_resolution=legacy_resolution)
        constants = {}
        omitted = []
        for name, column in zip(FEATURES, zip(*train, strict=True), strict=True):
            if name not in model:
                if min(column) == max(column):
                    constants[name] = column[0]
                else:
                    omitted.append(name)
        report["scaling_policy"] = policy
        report["model"] = model
        report["training_constants"] = constants
        report["omitted_zero_dispersion_features"] = omitted
        scored = {name: [(row, *baseline.score(row[-1], FEATURES, model)) for row in block]
                  for name, block in split_rows.items() if name != "train"}
        cutoff = baseline.threshold([value for _, value, _ in scored["calibration"]])
        report["threshold"] = cutoff
        report["calibration_policy"] = "1% budget, alert only on score strictly greater than cutoff"
        report["score_summary"] = {}
        with (output / "scores.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(("split", "ledger_index", "position", "hash", "score", "driver", "alert"))
            for name, block in scored.items():
                alerts = sum(value > cutoff for _, value, _ in block)
                report["score_summary"][name] = {
                    "scores": summarize([value for _, value, _ in block]),
                    "alerts": alerts, "alert_rate": alerts / len(block),
                    "new_variation_counts": {
                        feature: sum(row[-1][i] != constants[feature] for row, _, _ in block)
                        for i, feature in enumerate(FEATURES) if feature in constants},
                    "alert_drivers": dict(Counter(driver for _, value, driver in block if value > cutoff)),
                }
                for row, value, driver in block:
                    writer.writerow((name, *row[:3], value, driver, int(value > cutoff)))
    else:
        report["baseline_limit"] = "Insufficient rows for a complete chronological split."
    dump(output / "summary.json", report)
    if render:
        from .plots import plot
        plot(ledgers, full, report, output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("database", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--figures", action="store_true")
    parser.add_argument("--legacy-resolution", action="store_true",
                        help="reproduce the Phase 2 scoring policy")
    args = parser.parse_args()
    analyze(args.directory, args.database, args.output, args.figures,
            legacy_resolution=args.legacy_resolution)

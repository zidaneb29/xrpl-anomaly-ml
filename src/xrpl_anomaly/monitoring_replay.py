"""Replay existing calibration and final-test vectors for local monitoring."""
import argparse
import json
import platform
import re
import sqlite3
import subprocess
from contextlib import closing
from hashlib import file_digest
from math import log1p
from pathlib import Path

from .expansion_report import scored_features
from .features import FEATURES, SCHEMA_VERSION
from .heldout_protocol import protocol
from .model_artifact import VERSION, load
from .monitoring import DRIFT_GUIDE, MIN_DRIFT_N, alert_summary, distribution, drift
from .package_models import MODELS, OUTPUT as MODEL_DIR
from .pilot import digest
from .storage import replay

OUTPUT = Path("reports/generated")
PROCESSED = Path("data/processed")
WINDOW_SECONDS = 600
REFERENCE_BLOCK = 7
SCENARIO_BLOCK = 8
FEE_DROPS = 100_000
FEE_COLUMN = FEATURES.index("log_fee_drops")


def sha256(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def verify_snapshot(db, number, headers, expected_digest):
    rows = db.execute("SELECT idx, hash, parent, close_unix, digest FROM ledger ORDER BY idx").fetchall()
    low, high = headers[0][0], headers[-2][0]
    if [row[0] for row in rows] != list(range(low, high + 1)):
        raise ValueError(f"block {number}: database ledger range does not match frozen range {low}–{high}")
    for index, close, identity in headers[:-1]:
        if (rows[index - low][3], rows[index - low][1]) != (close, identity):
            raise ValueError(f"block {number}: frozen boundary mismatch at ledger {index}")
    for previous, current in zip(rows, rows[1:]):
        if current[2] != previous[1] or current[3] <= previous[3]:
            raise ValueError(f"block {number}: broken ledger chain at ledger {current[0]}")
    # Match the frozen snapshot encoding in expansion_report, independent of SQLite file layout.
    snapshot = [(index, checksum) for index, _, _, _, checksum in rows]
    if digest(json.dumps(snapshot).encode()) != expected_digest:
        raise ValueError(f"block {number}: database snapshot digest does not match the frozen bundle")


def block_windows(rows, start):
    """Partition the frozen 30-minute scoring interval without splitting ledgers."""
    windows = [[] for _ in range(3)]
    previous = None
    for ledger, position, identity, close, complete, values in rows:
        key = ledger, position
        if (not complete or not start <= close < start + 3 * WINDOW_SECONDS
                or previous is not None and (key <= previous[0] or close < previous[1])):
            raise ValueError("invalid chronological scoring row")
        windows[(close - start) // WINDOW_SECONDS].append((identity, values))
        previous = key, close
    return windows


def intervene(rows):
    """Set the prepared fee coordinate to the transform of a fixed integer fee."""
    fee = log1p(FEE_DROPS)
    return [(identity, (*values[:FEE_COLUMN], fee, *values[FEE_COLUMN + 1:])) for identity, values in rows]


def scored(detector, rows):
    scores, alerts = [], []
    for identity, values in rows:
        result = detector.score(values, feature_names=FEATURES, feature_schema_version=SCHEMA_VERSION)
        scores.append(result.anomaly_score)
        alerts.append(detector.alerts(result, identity=identity))
    return scores, alerts


def columns(rows):
    return {name: [values[i] for _, values in rows] for i, name in enumerate(FEATURES)}


def compare(detector, reference, reference_scores, rows):
    scores, alerts = scored(detector, rows)
    return {"n": len(rows), "features": {name: drift(reference[name], values)
                                       for name, values in columns(rows).items()},
            "scores": drift(reference_scores, scores), "frozen_alerts": alert_summary(alerts)}


def run(model_id):
    config, blocks = protocol()
    model_path = MODEL_DIR / f"{model_id}.json"
    detector = load(model_path)
    if detector.model_id != model_id:
        raise ValueError("bundle identity does not match selected model")
    result = {"model": {"id": detector.model_id, "type": detector.model_type,
                        "version": VERSION, "artifact_sha256": detector.artifact_sha256,
                        "bundle_file_sha256": sha256(model_path)},
              "feature_schema": {"version": SCHEMA_VERSION, "names": FEATURES},
              "settings": {"window_seconds": WINDOW_SECONDS, "minimum_observed_n": MIN_DRIFT_N,
                           "ks_distance_guide": DRIFT_GUIDE, "synthetic_fee_drops": FEE_DROPS,
                           "synthetic_window": 2, "seed": None},
              "protocol": config, "inputs": {}, "historical": [], "scenario": [],
              "provenance": {"git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                             "python": platform.python_version(), "platform": platform.platform(),
                             "sqlite": sqlite3.sqlite_version,
                             "source_sha256": {path.name: sha256(path) for path in
                                               sorted(Path(__file__).parent.glob("*.py"))}}}
    for number in range(REFERENCE_BLOCK, 13):
        block = blocks[number - 1]
        start = block["start"]
        path = (PROCESSED / f"phase3b3-block-{number:02d}.sqlite").resolve()
        result["inputs"][number] = {"sqlite_sha256": sha256(path), "role": block["role"]}
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
            verify_snapshot(db, number, block["headers"], detector.snapshots[str(number)])
            windows = block_windows(scored_features(replay(db), start), start)
        if number == REFERENCE_BLOCK:
            rows = [row for window in windows for row in window]
            reference = columns(rows)
            reference_scores, alerts = scored(detector, rows)
            result["reference"] = {"block": number, "role": block["role"], "n": len(rows),
                                   "start_unix_utc": start, "end_unix_utc_exclusive": start + 1800,
                                   "features": {name: distribution(values) for name, values in reference.items()},
                                   "scores": distribution(reference_scores), "frozen_alerts": alert_summary(alerts)}
        for index, rows in enumerate(windows):
            begin = start + index * WINDOW_SECONDS
            metadata = {"block": number, "role": block["role"], "window": index + 1,
                        "start_unix_utc": begin, "end_unix_utc_exclusive": begin + WINDOW_SECONDS}
            clean = compare(detector, reference, reference_scores, rows)
            result["historical"].append({**metadata, **clean})
            if number == SCENARIO_BLOCK:
                stage = ("normal", "synthetic shift", "recovery")[index]
                scenario_rows = intervene(rows) if index == 1 else rows
                shifted = compare(detector, reference, reference_scores, scenario_rows) if index == 1 else clean
                result["scenario"].append({**metadata, **shifted, "stage": stage,
                                           "modified": sum(a != b for a, b in zip(rows, scenario_rows, strict=True))})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-name", default="phase4d")
    parser.add_argument("--model", choices=MODELS, default="baseline-full")
    parser.add_argument("--figures", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"phase4d(?:-[a-z0-9]+)*", args.run_name):
        parser.error("use a fresh run name beginning with phase4d")
    output = OUTPUT / args.run_name
    output.mkdir(parents=True, exist_ok=False)
    report = run(args.model)
    path = output / "monitoring.json"
    path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    if args.figures:
        from .monitoring_figures import render

        render(report, output, sha256(path))


if __name__ == "__main__":
    main()

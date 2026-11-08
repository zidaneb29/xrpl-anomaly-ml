"""Verify loaded scores against the historical clean score table without fitting."""
import csv
import sqlite3
from collections import Counter
from contextlib import closing
from hashlib import file_digest
from pathlib import Path

from .expansion_report import scored_features
from .features import FEATURES, SCHEMA_VERSION
from .heldout_protocol import protocol
from .model_artifact import load, require
from .package_models import HISTORICAL, MODELS, OUTPUT, verified_history
from .storage import replay


def verify():
    evaluation, _, _, _ = verified_history(HISTORICAL)
    _, blocks = protocol()
    path = HISTORICAL / "clean-scores.csv"
    with path.open("rb") as stream:
        require(file_digest(stream, "sha256").hexdigest() == evaluation["artifacts"][path.name],
                "historical score table digest mismatch")
    detectors = {name: load(OUTPUT / f"{name}.json") for name in MODELS}
    expected = {}
    with path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            model = row["model"]
            if model in detectors:
                key = int(row["block"]), model, row["identity"]
                require(key not in expected, "duplicate historical score")
                expected[key] = float(row["score"])
    count = len(expected)
    alerts = Counter()
    for number in range(7, 13):
        path = Path(f"data/processed/phase3b3-block-{number:02d}.sqlite").resolve()
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
            for _, _, identity, _, _, values in scored_features(replay(db), blocks[number - 1]["start"]):
                for model, detector in detectors.items():
                    score = detector.score(values, feature_names=FEATURES, feature_schema_version=SCHEMA_VERSION)
                    prior = expected.pop((number, model, identity), None)
                    require(score.anomaly_score == prior, f"historical score mismatch in block {number}: {model}")
                    alerts[number, model] += detector.alerts(score, identity=identity)
    require(not expected, "historical score rows missing from replay")
    for row in evaluation["clean"]:
        if row["model"] in detectors:
            require(alerts[row["block"], row["model"]] == row["operating"]["alerts"],
                    "historical alert count mismatch")
    return count


if __name__ == "__main__":
    print(f"{verify()} exact score matches and all 18 operating alert counts matched")

"""Package the frozen Phase 3B.3 fits without training or changing old outputs."""
import argparse
import json
import os
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile

from .features import FEATURES, SCHEMA_VERSION, WINDOW
from .heldout_protocol import CONFIG, protocol
from .model_artifact import FEATURE_TYPES, FORMAT, POLICY, VERSION, decode, encode, require

HISTORICAL = Path("reports/generated/phase3b3")
OUTPUT = Path("artifacts/phase4a/models")
SOURCE_CHECKPOINT = "893e8f6149c4804a145bc504065842edc313f60a"
MODELS = {"baseline-full": ("robust_baseline", None),
          "isolation-full-7": ("isolation_forest", 7),
          "isolation-full-29": ("isolation_forest", 29)}
FIGURES = ("ablation-and-blocks.png", "alerts-and-stability.png", "calibration.png",
           "performance-and-cost.png", "synthetic-families.png")


def digest(body):
    return sha256(body).hexdigest()


def verified_history(directory):
    frozen, _ = protocol()
    evaluation_body = (directory / "evaluation.json").read_bytes()
    evaluation = json.loads(evaluation_body)
    models_body = (directory / "models.json").read_bytes()
    figures_body = (directory / "figure-metadata.json").read_bytes()
    figures = json.loads(figures_body)
    hashes = {"evaluation.json": digest(evaluation_body), "models.json": digest(models_body)}
    require(evaluation["protocol"] == frozen and
            evaluation["protocol_sha256"] == digest(CONFIG.read_bytes().replace(b"\r\n", b"\n")),
            "historical evaluation uses another protocol")
    for name in ("baseline.py", "features.py", "isolation.py", "heldout.py"):
        raw = Path(__file__).with_name(name).read_bytes()
        lf = raw.replace(b"\r\n", b"\n")
        require(evaluation["source_sha256"][name] in (digest(raw), digest(lf), digest(lf.replace(b"\n", b"\r\n"))),
                f"historical source mismatch: {name}")
    require(evaluation["artifacts"]["models.json"] == hashes["models.json"]
            and all(figures["inputs"][name] == value for name, value in hashes.items())
            and figures["inputs"]["clean-scores.csv"] == evaluation["artifacts"]["clean-scores.csv"],
            "historical model, evaluation or figure input hash mismatch")
    require(set(figures["figures"]) == set(FIGURES), "unexpected historical figure set")
    return evaluation, json.loads(models_body), figures, hashes


def bundles(evaluation, models, hashes):
    frozen = evaluation["protocol"]
    provenance = dict(
        experiment="phase3b3-heldout", recorded_git_head=evaluation["git_head"],
        source_checkpoint=SOURCE_CHECKPOINT, source_sha256=evaluation["source_sha256"],
        protocol_sha256=evaluation["protocol_sha256"], evaluation_sha256=hashes["evaluation.json"],
        models_sha256=hashes["models.json"], snapshots=evaluation["snapshots"],
        training_runtime=dict(python=evaluation["python"], sqlite=evaluation["sqlite"],
                              third_party_scoring_dependencies=[]),
    )
    for model_id, (kind, seed) in MODELS.items():
        old = models[model_id]
        configuration = (frozen["baseline"] if seed is None else
                         dict(seed=seed, size=frozen["forest"]["sizes"]["full"], trees=frozen["forest"]["trees"]))
        require(evaluation["calibration"][model_id] == old["calibration"]
                and old["calibration"]["cutoff_score"] == old["cutoff"][0], "calibration record mismatch")
        yield dict(
            format=FORMAT, version=VERSION, model_id=model_id, model_type=kind,
            feature_schema=dict(version=frozen["feature_schema"], names=old["columns"],
                                types=list(FEATURE_TYPES), lookback_seconds=frozen["lookback_seconds"],
                                preprocessing="prepared_no_imputation"),
            training=dict(blocks=[1, 2, 3, 4], scoring_seconds=frozen["scoring_seconds"],
                          configuration=configuration),
            fitted=dict(parameters=old["parameters"], omitted=old["omitted"]),
            calibration=dict(blocks=[7, 8], cutoff=old["cutoff"], policy=POLICY),
            provenance=provenance,
        )


def save(path, bundle):
    decode(bundle)
    body = encode(bundle)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        require(path.read_bytes() == body, f"refusing to replace a different artifact: {path}")
        return
    with NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        staging = Path(stream.name)
        try:
            stream.write(body)
            stream.close()
            # Publish atomically without overwriting another writer's result.
            if os.name == "nt":
                staging.rename(path)
            else:
                path.hardlink_to(staging)
        except FileExistsError:
            require(path.read_bytes() == body, f"concurrent artifact conflict: {path}")
        finally:
            stream.close()
            staging.unlink(missing_ok=True)


def package(directory=HISTORICAL, output=OUTPUT):
    evaluation, models, _, hashes = verified_history(directory)
    for bundle in bundles(evaluation, models, hashes):
        path = output / f"{bundle['model_id']}.json"
        save(path, bundle)
        print(f"{digest(path.read_bytes())}  {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    package(output=parser.parse_args().output)

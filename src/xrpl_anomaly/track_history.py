"""Import verified Phase 3B.3 results into a project-local MLflow store."""
import json
import os
from importlib.metadata import version
from pathlib import Path
from statistics import mean
from tempfile import TemporaryDirectory

from .model_artifact import encode, require
from .package_models import FIGURES, HISTORICAL, MODELS, OUTPUT, bundles, digest, verified_history

TRACKING = Path("artifacts/phase4a/tracking")
EXPERIMENT = "xrpl-phase3b3-historical"


def historical_metrics(evaluation, benchmark):
    metrics = {}
    for method in ("baseline", "isolation"):
        records = [row for row in evaluation["aggregate"]["by_block"]
                   if row["group"] == "full" and row["method"] == method]
        require(sorted(row["block"] for row in records) == [9, 10, 11, 12], "missing test block metrics")
        for field in ("ap", "recall", "threshold_recall", "prevalence"):
            metrics[f"synthetic.{method}.macro_{field}"] = mean(row[field] for row in records)
    for model_id in MODELS:
        runtime = benchmark["models"][model_id]
        blocks = list(runtime["blocks"].values())
        require(set(runtime["blocks"]) == {"9", "10", "11", "12"}, "missing benchmark blocks")
        metrics[f"runtime.{model_id}.prepared_rows_per_second"] = (
            sum(row["rows"] for row in blocks) / sum(row["seconds"] for row in blocks))
        for field in ("fit_seconds", "compact_model_json_bytes"):
            metrics[f"runtime.{model_id}.{field}"] = runtime[field]
        for row in evaluation["clean"]:
            if row["model"] == model_id:
                metrics[f"clean.{model_id}.block_{row['block']}.alert_rate"] = row["operating"]["rate"]
    return metrics


def track():
    evaluation, old_models, figures, hashes = verified_history(HISTORICAL)
    benchmark_body = (HISTORICAL / "benchmark.json").read_bytes()
    benchmark = json.loads(benchmark_body)
    payload = {}
    for bundle in bundles(evaluation, old_models, hashes):
        name = f"{bundle['model_id']}.json"
        path = OUTPUT / name
        require(path.read_bytes() == encode(bundle), f"package differs from historical fit: {name}")
        payload[f"models/{name}"] = path
    for name in FIGURES:
        path = HISTORICAL / name
        require(digest(path.read_bytes()) == figures["figures"][name]["sha256"], f"figure hash mismatch: {name}")
        payload[f"figures/{name}"] = path
    payload["evidence/figure-metadata.json"] = HISTORICAL / "figure-metadata.json"
    payload["evidence/benchmark.json"] = HISTORICAL / "benchmark.json"
    summaries = {"evidence/synthetic-aggregate.json": encode(evaluation["aggregate"]),
                 "evidence/calibration-summary.json": encode(evaluation["calibration"])}
    payload_hashes = {name: digest(path.read_bytes()) for name, path in payload.items()}
    payload_hashes.update({name: digest(body) for name, body in summaries.items()})
    require(payload_hashes["evidence/benchmark.json"] == digest(benchmark_body), "benchmark changed during import")
    manifest = dict(origin="historical_import", source_hashes=hashes, logged_files=payload_hashes,
                    protocol_sha256=evaluation["protocol_sha256"], original_git_head=evaluation["git_head"])
    summaries["evidence/import.json"] = encode(manifest)
    fingerprint = digest(summaries["evidence/import.json"])
    expected_files = {**payload_hashes, "evidence/import.json": fingerprint}
    metrics = historical_metrics(evaluation, benchmark)

    os.environ["MLFLOW_DISABLE_TELEMETRY"] = "true"
    os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"
    from mlflow import MlflowClient

    root = TRACKING.resolve()
    root.mkdir(parents=True, exist_ok=True)
    artifact_root = root / "files"
    client = MlflowClient(tracking_uri=f"sqlite:///{(root / 'tracking.sqlite').as_posix()}")
    experiment = client.get_experiment_by_name(EXPERIMENT)
    experiment_id = (experiment.experiment_id if experiment else
                     client.create_experiment(EXPERIMENT, artifact_location=artifact_root.as_uri()))
    require(client.get_experiment(experiment_id).artifact_location == artifact_root.as_uri(),
            "unexpected experiment artifact location")
    prior = client.search_runs([experiment_id], f"tags.import_sha256 = '{fingerprint}'")
    for run in prior:
        if run.info.status == "FINISHED":
            for name, expected in expected_files.items():
                local = artifact_root / run.info.run_id / "artifacts" / name
                require(digest(local.read_bytes()) == expected, f"recorded artifact differs: {name}")
            return run.info.run_id

    run = client.create_run(experiment_id, run_name="Phase 3B.3 frozen classical evaluation",
                            tags={"origin": "historical_import", "import_sha256": fingerprint,
                                  "model_fit_executed": "false", "labels": "synthetic_interventions"})
    run_id = run.info.run_id
    local_root = artifact_root / run_id / "artifacts"
    try:
        require(run.info.artifact_uri == local_root.as_uri(), "unexpected run artifact location")
        parameters = dict(feature_schema=evaluation["protocol"]["feature_schema"],
                          protocol_sha256=evaluation["protocol_sha256"],
                          historical_python=evaluation["python"], tracker_version=version("mlflow-skinny"),
                          model_ids=",".join(MODELS))
        for key, value in parameters.items():
            client.log_param(run_id, key, value, synchronous=True)
        for key, value in metrics.items():
            client.log_metric(run_id, key, value, synchronous=True)
        with TemporaryDirectory(dir=root) as staging:
            for name, body in summaries.items():
                path = Path(staging) / Path(name).name
                path.write_bytes(body)
                payload[name] = path
            for name, path in payload.items():
                client.log_artifact(run_id, str(path), name.split("/")[0])
                require(digest((local_root / name).read_bytes()) == expected_files[name],
                        f"logged artifact differs: {name}")
    except BaseException:
        client.set_terminated(run_id, "FAILED")
        raise
    client.set_terminated(run_id, "FINISHED")
    return run_id


if __name__ == "__main__":
    print(track())

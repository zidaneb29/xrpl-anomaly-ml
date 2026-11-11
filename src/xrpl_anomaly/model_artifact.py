"""Versioned JSON bundles and prepared-feature inference."""
import json
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from math import isfinite
from pathlib import Path
from re import fullmatch
from types import MappingProxyType

from . import baseline
from .features import FEATURES, SCHEMA_VERSION, WINDOW
from .isolation import IsolationForest, Split

FORMAT = "xrpl-anomaly-model"
VERSION = 1
POLICY = {"name": "pooled_clean_key_at_k_strict_greater", "divisor": 100,
          "tie_domain": "xrpl-alert-budget-v1"}
BASELINE_CONFIG = {"legacy_resolution": False, "mad_multiplier": 1.4826, "iqr_divisor": 1.349}
FEATURE_TYPES = tuple("integer" if name.endswith(("_seconds", "_unseen", "_no_outgoing"))
                      else "number" for name in FEATURES)
MAX_BYTES = 2 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def fields(value, *names):
    require(type(value) is dict and value.keys() == set(names),
            f"expected fields: {', '.join(names)}")


def number(value):
    return type(value) in (float, int) and abs(value) <= 1.7976931348623157e308 and isfinite(value)


def hex_string(value, length):
    return (type(value) is str and len(value) == length
            and all(c in "0123456789abcdef" for c in value))


def read_json(path, limit):
    def unique(pairs):
        result = dict(pairs)
        require(len(result) == len(pairs), "duplicate JSON field")
        return result

    with Path(path).open("rb") as stream:
        body = stream.read(limit + 1)
    require(len(body) <= limit, "JSON file exceeds size limit")
    try:
        return json.loads(body.decode("utf-8"), object_pairs_hook=unique)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("invalid JSON encoding or nesting") from exc


def encode(bundle):
    """Stable UTF-8 encoding, independent of the tracking run and packaging time."""
    return (json.dumps(bundle, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


@dataclass(frozen=True)
class Score:
    anomaly_score: float
    model_id: str
    model_type: str
    model_version: int
    feature_schema_version: int
    artifact_sha256: str


@dataclass(frozen=True)
class Detector:
    model_id: str
    model_type: str
    cutoff: tuple
    artifact_sha256: str
    snapshots: Mapping[str, str]
    _score: object

    def score(self, values, *, feature_names, feature_schema_version):
        require(type(feature_schema_version) is int and feature_schema_version == SCHEMA_VERSION
                and type(feature_names) in (tuple, list) and tuple(feature_names) == FEATURES,
                "incompatible feature schema or order")
        require(type(values) in (list, tuple) and len(values) == len(FEATURES), "invalid feature vector")
        for name, kind, value in zip(FEATURES, FEATURE_TYPES, values):
            valid = number(value) and value >= 0
            if kind == "integer":
                valid = valid and type(value) is int and value <= (WINDOW if name.endswith("_seconds") else 1)
            if name == "sender_out_concentration":
                valid = valid and value <= 1
            require(valid, f"invalid feature: {name}")
        result = self._score(values)
        require(number(result), "non-finite anomaly score")
        return Score(result, self.model_id, self.model_type, VERSION, SCHEMA_VERSION, self.artifact_sha256)

    def alerts(self, score, *, identity):
        require(type(score) is Score and score.artifact_sha256 == self.artifact_sha256,
                "score belongs to an incompatible model")
        return baseline.alert_key(score.anomaly_score, identity) > self.cutoff


def _baseline(parameters, config, omitted):
    require(config == BASELINE_CONFIG, "unsupported robust training configuration")
    require(type(parameters) is dict and set(parameters) <= set(FEATURES), "unknown baseline feature")
    require(omitted == [name for name in FEATURES if name not in parameters], "invalid omitted features")
    for state in parameters.values():
        fields(state, "median", "scale", "method")
        require(number(state["median"]) and state["median"] >= 0 and number(state["scale"])
                and state["scale"] > 0 and state["method"] in ("mad", "iqr"), "invalid robust state")
    return lambda values: baseline.score(values, FEATURES, parameters)[0]


def _forest(parameters, config, omitted):
    fields(config, "size", "seed", "trees")
    require(all(type(v) is int for v in config.values()) and config["size"] == 256
            and config["seed"] in (7, 29) and config["trees"] == 64, "unsupported forest configuration")
    fields(parameters, "columns", "trees", "normalizer")
    columns = parameters["columns"]
    require(type(columns) is list and all(type(i) is int and 0 <= i < len(FEATURES) for i in columns)
            and columns == sorted(set(columns)), "invalid forest columns")
    require(omitted == [name for i, name in enumerate(FEATURES) if i not in columns],
            "invalid omitted features")
    corrections = {0.0: 1}
    correction = 0.0
    for size in range(2, config["size"] + 1):
        correction += 2 / size
        corrections[correction] = size
    require(parameters["normalizer"] == correction * config["trees"], "invalid forest normalizer")

    def parse(node, depth):
        if number(node) and node in corrections:
            return node, corrections[node]
        fields(node, "column", "cut", "left", "right")
        require(depth and type(node["column"]) is int and node["column"] in columns
                and number(node["cut"]) and node["cut"] >= 0, "invalid forest split")
        left, left_count = parse(node["left"], depth - 1)
        right, right_count = parse(node["right"], depth - 1)
        return Split(node["column"], node["cut"], left, right), left_count + right_count

    trees = parameters["trees"]
    require(type(trees) is list and len(trees) == config["trees"], "invalid forest tree count")
    parsed = [parse(node, (config["size"] - 1).bit_length()) for node in trees]
    require(all(count == config["size"] for _, count in parsed), "invalid forest subsample count")
    return IsolationForest(tuple(columns), tuple(node for node, _ in parsed), parameters["normalizer"]).score


def _provenance(value):
    fields(value, "experiment", "recorded_git_head", "source_checkpoint", "source_sha256",
           "protocol_sha256", "evaluation_sha256", "models_sha256", "snapshots", "training_runtime")
    require(value["experiment"] == "phase3b3-heldout", "unknown source experiment")
    for key in ("recorded_git_head", "source_checkpoint"):
        require(hex_string(value[key], 40), f"invalid {key}")
    for key in ("protocol_sha256", "evaluation_sha256", "models_sha256"):
        require(hex_string(value[key], 64), f"invalid {key}")
    snapshots = value["snapshots"]
    fields(snapshots, *(str(i) for i in range(1, 13)))
    require(all(hex_string(item, 64) for item in snapshots.values()), "invalid snapshot hashes")
    source = value["source_sha256"]
    require(type(source) is dict and {"baseline.py", "features.py", "isolation.py", "heldout.py"} <= source.keys()
            and all(hex_string(item, 64) for item in source.values()), "invalid source hashes")
    runtime = value["training_runtime"]
    fields(runtime, "python", "sqlite", "third_party_scoring_dependencies")
    require(all(type(runtime[key]) is str and runtime[key] for key in ("python", "sqlite"))
            and runtime["third_party_scoring_dependencies"] == [], "invalid training runtime")


def decode(bundle):
    fields(bundle, "format", "version", "model_id", "model_type", "feature_schema", "training",
           "fitted", "calibration", "provenance")
    require(bundle["format"] == FORMAT and type(bundle["version"]) is int and bundle["version"] == VERSION,
            "unsupported artifact format or version")
    schema = bundle["feature_schema"]
    fields(schema, "version", "names", "types", "lookback_seconds", "preprocessing")
    require(type(schema["version"]) is int and schema["version"] == SCHEMA_VERSION
            and schema["names"] == list(FEATURES) and schema["types"] == list(FEATURE_TYPES)
            and schema["lookback_seconds"] == WINDOW and schema["preprocessing"] == "prepared_no_imputation",
            "incompatible artifact feature schema")
    _provenance(bundle["provenance"])
    training = bundle["training"]
    fields(training, "blocks", "scoring_seconds", "configuration")
    require(training["blocks"] == [1, 2, 3, 4] and all(type(i) is int for i in training["blocks"])
            and training["scoring_seconds"] == 1800,
            "invalid training split")
    fitted = bundle["fitted"]
    fields(fitted, "parameters", "omitted")
    config = training["configuration"]
    kind = bundle["model_type"]
    if kind == "robust_baseline":
        scorer = _baseline(fitted["parameters"], config, fitted["omitted"])
        model_id = "baseline-full"
    elif kind == "isolation_forest":
        scorer = _forest(fitted["parameters"], config, fitted["omitted"])
        model_id = f"isolation-full-{config['seed']}"
    else:
        raise ValueError("unsupported model type")
    require(bundle["model_id"] == model_id, "incompatible model identifier")
    calibration = bundle["calibration"]
    fields(calibration, "blocks", "policy", "cutoff")
    require(calibration["blocks"] == [7, 8] and all(type(i) is int for i in calibration["blocks"])
            and calibration["policy"] == POLICY,
            "unsupported calibration policy")
    cutoff = calibration["cutoff"]
    require(type(cutoff) is list and len(cutoff) == 3 and number(cutoff[0]) and cutoff[0] >= 0
            and (kind != "isolation_forest" or 0 < cutoff[0] <= 1)
            and hex_string(cutoff[1], 64) and type(cutoff[2]) is str
            and fullmatch(r"[0-9A-F]{64}", cutoff[2])
            and tuple(cutoff) == baseline.alert_key(cutoff[0], cutoff[2]), "invalid calibration key")
    snapshots = MappingProxyType(dict(bundle["provenance"]["snapshots"]))
    return Detector(model_id, kind, tuple(cutoff), sha256(encode(bundle)).hexdigest(), snapshots, scorer)


def load(path):
    return decode(read_json(path, MAX_BYTES))

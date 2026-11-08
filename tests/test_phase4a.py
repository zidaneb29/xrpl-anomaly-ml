import copy
import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from xrpl_anomaly import baseline
from xrpl_anomaly.features import FEATURES, SCHEMA_VERSION, WINDOW
from xrpl_anomaly.isolation import IsolationForest
from xrpl_anomaly.model_artifact import (
    BASELINE_CONFIG, FEATURE_TYPES, FORMAT, POLICY, VERSION, decode, encode, load,
)
from xrpl_anomaly.package_models import save

SCHEMA = dict(feature_names=FEATURES, feature_schema_version=SCHEMA_VERSION)
ROWS = [(float(i),) + (0,) * (len(FEATURES) - 1) for i in range(256)]


def fixture(model_id, kind, configuration, parameters, omitted, cutoff):
    return dict(format=FORMAT, version=VERSION, model_id=model_id, model_type=kind,
                feature_schema=dict(version=SCHEMA_VERSION, names=list(FEATURES), types=list(FEATURE_TYPES),
                                    lookback_seconds=WINDOW, preprocessing="prepared_no_imputation"),
                training=dict(blocks=[1, 2, 3, 4], scoring_seconds=1800, configuration=configuration),
                fitted=dict(parameters=parameters, omitted=omitted),
                calibration=dict(blocks=[7, 8], cutoff=list(cutoff), policy=POLICY),
                provenance=dict(experiment="phase3b3-heldout", recorded_git_head="a" * 40,
                                source_checkpoint="b" * 40, protocol_sha256="c" * 64,
                                evaluation_sha256="d" * 64, models_sha256="e" * 64,
                                snapshots={str(i): "f" * 64 for i in range(1, 13)},
                                source_sha256={name: "1" * 64 for name in
                                               ("baseline.py", "features.py", "isolation.py", "heldout.py")},
                                training_runtime=dict(python="3.14.7", sqlite="3.50.4",
                                                      third_party_scoring_dependencies=[])))


class ModelArtifactTests(unittest.TestCase):
    def setUp(self):
        self.parameters = baseline.fit(ROWS, FEATURES)
        self.value = baseline.score(ROWS[20], FEATURES, self.parameters)[0]
        self.cutoff = baseline.alert_key(self.value, "boundary")
        self.bundle = fixture("baseline-full", "robust_baseline", BASELINE_CONFIG, self.parameters,
                              list(FEATURES[1:]), self.cutoff)

    def test_baseline_round_trip_and_fresh_process(self):
        with tempfile.TemporaryDirectory(dir=".") as temp:
            first, second = (Path(temp) / name for name in ("first.json", "second.json"))
            save(first, self.bundle)
            save(second, self.bundle)
            save(first, self.bundle)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(json.loads(first.read_bytes())["provenance"], self.bundle["provenance"])
            model = load(first)
            score = model.score(ROWS[20], **SCHEMA)
            self.assertEqual(score.anomaly_score, self.value)
            self.assertEqual(score, model.score(ROWS[20], **SCHEMA))
            self.assertEqual(model.cutoff, self.cutoff)
            self.assertFalse(model.alerts(score, identity="boundary"))
            for identity in ("a", "b", "c", "d", "e"):
                self.assertEqual(model.alerts(score, identity=identity),
                                 baseline.alert_key(self.value, identity) > self.cutoff)
            script = ("import sys; sys.path.insert(0, 'src'); "
                      "from xrpl_anomaly.model_artifact import load; "
                      "from xrpl_anomaly.features import FEATURES, SCHEMA_VERSION; "
                      "print(load(sys.argv[1]).score((20.0,) + (0,) * (len(FEATURES)-1), "
                      "feature_names=FEATURES, feature_schema_version=SCHEMA_VERSION).anomaly_score)")
            result = subprocess.check_output([sys.executable, "-I", "-B", "-c", script, str(first)], text=True)
            self.assertEqual(float(result), self.value)
            changed = copy.deepcopy(self.bundle)
            changed["provenance"]["recorded_git_head"] = "9" * 40
            with self.assertRaisesRegex(ValueError, "different artifact"):
                save(first, changed)
            with self.assertRaises(ValueError):
                decode(changed).alerts(score, identity="boundary")

    def test_forest_round_trip(self):
        config = dict(size=256, seed=7, trees=64)
        forest = IsolationForest.fit(ROWS, **config)
        cutoff = baseline.alert_key(forest.score(ROWS[0]), "boundary")
        bundle = fixture("isolation-full-7", "isolation_forest", config, asdict(forest),
                         list(FEATURES[1:]), cutoff)
        # Historical fitted state uses JSON arrays for forest columns and trees.
        bundle = json.loads(encode(bundle))
        with tempfile.TemporaryDirectory(dir=".") as temp:
            path = Path(temp) / "forest.json"
            save(path, bundle)
            loaded = load(path)
            for values in ROWS[::13]:
                self.assertEqual(loaded.score(values, **SCHEMA).anomaly_score, forest.score(values))
            self.assertEqual(loaded.cutoff, cutoff)
        bundle["fitted"]["parameters"]["trees"][0]["column"] = -1
        with self.assertRaisesRegex(ValueError, "forest split"):
            decode(bundle)

    def test_invalid_features(self):
        model = decode(self.bundle)
        cases = [([], SCHEMA), (ROWS[0], dict(SCHEMA, feature_names=FEATURES[::-1])),
                 (ROWS[0], dict(SCHEMA, feature_schema_version=99))]
        for index, invalid in ((0, True), (0, float("nan")), (0, "1"), (0, -1), (6, 1.5),
                               (6, 601), (7, 2), (19, 1.1)):
            row = list(ROWS[0])
            row[index] = invalid
            cases.append((row, SCHEMA))
        for row, schema in cases:
            with self.subTest(row=row, schema=schema), self.assertRaises(ValueError):
                model.score(row, **schema)

    def test_invalid_artifacts(self):
        for section, key, invalid in (
            ("feature_schema", "version", 2), ("feature_schema", "names", list(reversed(FEATURES))),
            ("provenance", "source_checkpoint", "latest"), ("calibration", "cutoff", [1, "0" * 64, "id"]),
            ("fitted", "parameters", {FEATURES[0]: dict(median=0, scale=0, method="mad")}),
        ):
            bundle = copy.deepcopy(self.bundle)
            bundle[section][key] = invalid
            with self.subTest(section=section, key=key), self.assertRaises(ValueError):
                decode(bundle)
        with tempfile.TemporaryDirectory(dir=".") as temp:
            path = Path(temp) / "bad.json"
            for payload in (b'{"version":1,"version":2}', b"not JSON", b" " * (2 * 1024 * 1024 + 1)):
                path.write_bytes(payload)
                with self.assertRaises(ValueError):
                    load(path)

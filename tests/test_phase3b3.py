"""Offline checks for the frozen held-out workflow."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_phase3b2 import sample
from xrpl_anomaly import baseline, heldout, heldout_protocol
from xrpl_anomaly.expansion_report import report


class HeldoutTests(unittest.TestCase):
    def test_frozen_config_and_acquisition_scope(self):
        config, blocks = heldout_protocol.protocol()
        self.assertEqual([b["role"] for b in blocks], config["roles"])
        self.assertEqual(sum(b["headers"][4][0] - b["headers"][0][0] + 1 for b in blocks[6:]), 3668)
        with patch.object(heldout_protocol, "acquire_stage") as acquire:
            heldout_protocol.acquire()
            acquire.assert_called_once_with(heldout_protocol.RAW, blocks[6:], 7,
                                            heldout_protocol.LIMITS, heldout_protocol.STORAGE)
        config["forest"]["sizes"]["full"] = 128
        with tempfile.TemporaryDirectory(dir=".") as folder:
            path = Path(folder) / "protocol.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            with patch.object(heldout_protocol, "CONFIG", path), self.assertRaisesRegex(ValueError, "differs"):
                heldout_protocol.protocol()

    def test_missing_manifest_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=".") as folder:
            path = Path(folder)
            with self.assertRaisesRegex(ValueError, "missing manifest for block 1"):
                report(root=path, heldout_root=path, output=path)

    def test_frozen_cutoff_and_rank_ties(self):
        calibration = {f"cal-{i}": 3.0 for i in range(200)}
        cutoff = baseline.alert_cutoff(heldout.score_pairs(calibration))
        self.assertEqual(heldout.alerts(calibration, cutoff)[1]["alerts"], 2)
        test = {"direct": 4.0, "spillover": 4.0, **{f"test-{i}": 2.0 for i in range(98)}}
        record = heldout.synthetic_metrics(test, {**test, "direct": 1.0},
                                           {"direct"}, {"spillover"}, cutoff)
        self.assertEqual(record["ap"], 0.5)
        self.assertEqual(record["threshold_recall"], 1)
        self.assertEqual(record["matched_clean_recall"], 0)
        self.assertEqual(record["recall_tie_bounds"], [0, 1])
        self.assertEqual(record["fixed_budget"]["tied_score"], 2)
        self.assertEqual(record["fixed_budget"]["alerts"], 1)
        self.assertEqual(record["operating"]["alerts"], 2)
        self.assertEqual(record["strata"]["spillover"]["operating_alerts"], 1)

    def test_repeated_evaluation_and_figures(self):
        config, plan = heldout_protocol.protocol()
        samples = [sample(i) for i in range(12)]
        blocks = [dict(block=i, role=entry["role"], start=start, snapshot_sha256=str(i))
                  for i, (entry, (_, start)) in enumerate(zip(plan, samples, strict=True), 1)]
        loaded = []

        def replay(connection):
            db_path = connection.execute("PRAGMA database_list").fetchone()[2]
            block = int(Path(db_path).stem.rsplit("-", 1)[1])
            loaded.append(block)
            return iter(samples[block - 1][0])

        figures = importlib.util.find_spec("matplotlib") is not None
        with tempfile.TemporaryDirectory(dir=".") as folder:
            root = Path(folder)
            first, second = root / "first", root / "second"
            first.mkdir()
            second.mkdir()
            with (patch.object(heldout, "report", return_value=blocks),
                  patch.object(heldout, "PROCESSED", root), patch.object(heldout, "replay", replay)):
                for output in (first, second):
                    heldout.run(output, figures=figures)
            self.assertEqual(loaded, [1, 2, 3, 4, 7, 8, 9, 10, 11, 12] * 2)
            deterministic = [p.name for p in first.iterdir() if p.name != "benchmark.json"]
            for name in deterministic:
                self.assertEqual((first / name).read_bytes(), (second / name).read_bytes(), name)
            result = json.loads((first / "evaluation.json").read_bytes())
            self.assertEqual(result["protocol"], config)
            self.assertEqual({r["block"] for r in result["synthetic"]}, {9, 10, 11, 12})
            self.assertEqual({r["group"] for r in result["synthetic"]}, {"static", "temporal", "full"})
            self.assertTrue(any(r["spillover"] for r in result["interventions"]))
            if figures:
                self.assertEqual(len(list(first.glob("*.png"))), 5)

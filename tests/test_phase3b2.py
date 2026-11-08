"""Deterministic fixture checks for the Phase 3B.2 protocol."""
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from xrpl_anomaly.development import GROUPS, compare, compare_ranks, metrics
from test_phase2 import BIG, encoded, fixture, identity
from xrpl_anomaly.expansion import FROZEN_DIGEST, PLAN, acquire_locked, acquire_next, development_plan
from xrpl_anomaly.expansion_report import report, scored_features
from xrpl_anomaly.features import FEATURES
from xrpl_anomaly.isolation import IsolationForest
from xrpl_anomaly.ledger import RIPPLE_EPOCH
from xrpl_anomaly.perturbations import FAMILIES, candidates, scenario
from xrpl_anomaly.pilot import dump


def sample(block=0):
    start = block * 5000 + 600
    ledgers = []
    for index in range(181):
        close = start - 600 + index * 5
        rows = ()
        if index % 4 == 0:
            destination = "C" if index % 12 == 0 else "B"
            rows = ((0, f"{block}-a-{index}", "A", destination, 60 + index, 10),
                    (1, f"{block}-b-{index}", "D", "E", 2 + index % 20, 11),
                    (2, f"{block}-c-{index}", "F", "A", 1000 + 2 * index, 12))
        ledgers.append((block * 200 + index, close, rows))
    return ledgers, start


class DevelopmentTests(unittest.TestCase):
    def test_frozen_scope_and_modified_manifest(self):
        blocks = development_plan(PLAN)
        self.assertEqual([b["role"] for b in blocks], ["train"] * 4 + ["development"] * 2)
        with tempfile.TemporaryDirectory(dir=".") as folder:
            root = Path(folder)
            with patch("xrpl_anomaly.expansion.acquire_locked") as acquire:
                acquire_next(PLAN, root)
                args, options = acquire.call_args
                self.assertEqual(args, (root, blocks[2:], FROZEN_DIGEST))
                self.assertEqual(options["first_number"], 3)
                with self.assertRaisesRegex(RuntimeError, "storage ceiling"):
                    options["reserve_cache"](513 * 1024**2)
            modified = root / "manifest.json"
            content = json.loads(PLAN.read_bytes())
            content["blocks"][2]["headers"][0][2] = "A" * 64
            dump(modified, content)
            with self.assertRaisesRegex(ValueError, "original frozen manifest"):
                development_plan(modified)

    def test_isolation_training_constants_and_seed(self):
        rows = [(float(i % 4), 0.0, float(i == 25)) for i in range(30)]
        model = IsolationForest.fit(rows, size=30, seed=7)
        self.assertEqual(model, IsolationForest.fit(rows, size=30, seed=7))
        self.assertEqual(model.columns, (0, 2))
        self.assertEqual(model.score((0, 0, 0)), model.score((0, 1000, 0)))
        self.assertGreater(model.score(rows[25]), model.score(rows[1]))
        self.assertEqual(IsolationForest.fit([(0,), (0,)], size=2, seed=7).score((2,)), 0.5)

    def test_offline_multi_block_sqlite_integration(self):
        blocks, responses = [], {}
        for number in range(6):
            first = 33000 + number * 1000
            start = RIPPLE_EPOCH + first + 600
            bounds = [(first, start - 600, identity(first)), None, None,
                      (first + 1, start, identity(first + 1)),
                      (first + 2, start + 5, identity(first + 2)), None]
            blocks.append(dict(role="train" if number < 4 else "development",
                               start=start, headers=bounds))
            for offset, seconds in enumerate((0, 600, 605)):
                body = fixture(first + offset)
                body["result"]["ledger"]["close_time"] = first + seconds
                responses[first + offset] = encoded(body)

        with tempfile.TemporaryDirectory(dir=".") as folder:
            path = Path(folder)
            root, next_root = path / "initial", path / "next"
            root.mkdir()
            next_root.mkdir()
            with patch("xrpl_anomaly.pilot.Client.get", side_effect=lambda _, i, expanded: responses[i]):
                acquire_locked(root, blocks[:2], FROZEN_DIGEST)
                acquire_locked(next_root, blocks[2:], FROZEN_DIGEST, first_number=3)
            options = dict(development=True, next_root=next_root, output=path / "report",
                           processed=path / "processed")
            with patch("xrpl_anomaly.expansion_report.development_plan", return_value=blocks):
                results = report(PLAN, root, **options)
                repeat = report(PLAN, root, **options)
                self.assertEqual([b["feature_sha256"] for b in results],
                                 [b["feature_sha256"] for b in repeat])
                self.assertEqual([b["feature_counts"]["rows"] for b in results], [2] * 6)
                for db_path in options["processed"].glob("*.sqlite"):
                    with closing(sqlite3.connect(db_path)) as db:
                        self.assertEqual(db.execute("SELECT DISTINCT amount FROM payment").fetchall(), [(BIG,)])
                manifest_path = next_root / "block-06" / "manifest.json"
                manifest = json.loads(manifest_path.read_bytes())
                manifest["cross_checks"].clear()
                dump(manifest_path, manifest)
                with self.assertRaisesRegex(ValueError, "independent checks"):
                    report(PLAN, root, **options)

    def test_replay_and_matched_severities(self):
        ledgers, start = sample()
        snapshot = list(ledgers)
        original = {r[2]: r for r in scored_features(ledgers, start)}
        eligible = candidates(ledgers, start, (1, 2000))
        for family, (lower, upper) in FAMILIES.items():
            with self.subTest(family=family):
                rows, labels, affected = scenario(ledgers, start, original, family, lower,
                                                  eligible[family], 17)
                _, severe, _ = scenario(ledgers, start, original, family, upper,
                                        eligible[family], 17)
                self.assertTrue(labels)
                self.assertTrue(labels <= severe)
                self.assertTrue(affected)
                self.assertFalse(labels & affected)
                self.assertEqual(rows.keys(), original.keys())
                first_change = min(min(rows[key][0], original[key][0]) for key in labels)
                for key, row in rows.items():
                    if row[0] < first_change:
                        self.assertEqual(row, original[key])
        self.assertEqual(ledgers, snapshot)

    def test_tie_metrics(self):
        scores = {str(i): 1.0 for i in range(100)}
        stats = metrics(scores, {"0", "1"})
        self.assertEqual(stats["ap"], 0.02)
        self.assertEqual(stats["recall_tie_bounds"], [0.0, 0.5])
        self.assertEqual(metrics(dict(reversed(list(scores.items()))), {"0", "1"}), stats)
        self.assertEqual(compare_ranks(scores, scores)["top_overlap"], 1)
        self.assertIsNone(compare_ranks(scores, scores)["spearman"])

    def test_comparison_and_artifact_reproducibility(self):
        streams, starts = zip(*(sample(block) for block in range(6)))
        with self.assertRaisesRegex(ValueError, "chronological"):
            compare(streams[::-1], starts)
        self.assertEqual(len(FEATURES), 21)
        self.assertEqual(tuple(map(len, GROUPS.values())), (2, 14, 21))
        with (patch("xrpl_anomaly.development.TREES", 4),
              patch("xrpl_anomaly.development.SIZES", (8, 16))):
            result, originals, predictions, _ = compare(streams, starts)
            again, _, again_predictions, _ = compare(streams, starts)
        self.assertEqual(result, again)
        self.assertEqual(predictions, again_predictions)
        self.assertEqual(set(result["selected"]), set(GROUPS))
        self.assertTrue(all(r["block"] in (5, 6) for r in result["results"]))
        try:
            import matplotlib
        except ImportError:
            return
        from xrpl_anomaly.development_figures import render

        blocks = [dict(block=i, role="train" if i <= 4 else "development",
                       total_transactions=50, eligible_payments=len(rows),
                       feature_counts=dict(rows=len(rows), sender_seen=1, receiver_seen=1, prior_edge=1))
                  for i, rows in enumerate(originals, 1)]
        with tempfile.TemporaryDirectory(dir=".") as folder:
            output = Path(folder)
            result["artifacts"] = {}
            result["families"] = FAMILIES
            dump(output / "evaluation.json", result)
            render(output, blocks, originals, predictions, result)
            metadata = json.loads((output / "figure-metadata.json").read_bytes())
            self.assertEqual(len(metadata["outputs"]), 7)
            render(output, blocks, originals, predictions, result)
            self.assertEqual(metadata, json.loads((output / "figure-metadata.json").read_bytes()))

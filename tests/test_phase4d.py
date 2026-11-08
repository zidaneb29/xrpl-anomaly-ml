"""Offline checks for bounded monitoring, chronological replay and the API."""
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from test_phase4a import ROWS
from test_phase4b import request, service_fixture
from xrpl_anomaly import baseline, monitoring_replay
from xrpl_anomaly.features import FEATURES, SCHEMA_VERSION
from xrpl_anomaly.monitoring import (
    SERVICE_WINDOW, RequestEvent, ServiceMetrics, alert_summary, distribution, drift,
)
from xrpl_anomaly.package_models import save
from xrpl_anomaly.storage import connect


class MonitoringTests(unittest.TestCase):
    def test_empirical_distance_and_quantiles(self):
        left = [0] * 75 + [1000] * 25
        right = [0] * 25 + [1] * 50 + [1000] * 25 + [None]
        result = drift(left, right)
        self.assertEqual(result["ks_distance"], .5)
        self.assertEqual(result["reference_n"], 100)
        self.assertTrue(result["flag"])
        self.assertEqual(result["comparison"],
                         dict(n=100, missing=1, zero_rate=.25, p05=0, p50=1, p95=1000))
        self.assertEqual(drift([0] * 100, [0] * 100)["ks_distance"], 0)
        self.assertEqual(drift([0] * 100, [1] * 100)["ks_distance"], 1)
        for sample in ([], [None], [0] * 99):
            self.assertIsNone(drift(left, sample)["flag"])
        self.assertIsNone(distribution([])["p95"])
        for invalid in (True, "3", float("nan"), float("inf"), 10 ** 1000):
            with self.subTest(invalid=type(invalid)), self.assertRaises(ValueError):
                drift(left, [invalid])

    def test_operation_window_and_alert_denominators(self):
        metrics = ServiceMetrics()
        self.assertIsNone(metrics.snapshot()["operations"]["score_request_rejection_rate"])
        for i in range(SERVICE_WINDOW + 1):
            metrics.events.append(RequestEvent(str(i), 200, True, True, float(i), 0.0, False, None))
        snapshot = metrics.snapshot()
        self.assertEqual(snapshot["window"]["first_completed_at"], "1")
        self.assertEqual(snapshot["operations"]["requests"], SERVICE_WINDOW)
        self.assertEqual(snapshot["operations"]["inference_ms"], dict(n=1024, p50=512, p95=973))
        self.assertEqual(snapshot["model_statistics"]["frozen_alerts"]["unknown"], SERVICE_WINDOW)
        self.assertEqual(alert_summary([True, False, None]), dict(alerts=1, decisions=2, unknown=1, rate=.5))

    def test_window_boundaries_and_order(self):
        row = (1, 0, "A", 30, True, ROWS[0])
        second = (2, 0, "B", 630, True, ROWS[1])
        self.assertEqual(monitoring_replay.block_windows(iter((row, second)), 30),
                         [[("A", ROWS[0])], [("B", ROWS[1])], []])
        for invalid in ((second, row), (row, row), ((1, 0, "A", 1830, True, ROWS[0]),),
                        ((1, 0, "A", 30, False, ROWS[0]),)):
            with self.assertRaises(ValueError):
                monitoring_replay.block_windows(iter(invalid), 30)

    def test_read_only_replay_repeats_and_preserves_frozen_ties(self):
        bundle, boundary = service_fixture()
        # A fixture using only the fee column so the intervention is observable.
        cutoff = baseline.alert_key(0.0, boundary)
        bundle["calibration"]["cutoff"] = list(cutoff)
        bundle["fitted"] = {
            "parameters": {"log_fee_drops": {"median": 0.0, "scale": 1.0, "method": "mad"}},
            "omitted": [name for name in FEATURES if name != "log_fee_drops"],
        }
        with tempfile.TemporaryDirectory(dir=".") as folder:
            root = Path(folder)
            save(root / "baseline-full.json", bundle)
            paths = [root / f"phase3b3-block-{i:02d}.sqlite" for i in range(7, 13)]
            expected = []
            for path in paths:
                with closing(connect(path)) as db, db:
                    for idx, close in enumerate(range(0, 2400, 300), 1):
                        db.execute("INSERT INTO ledger VALUES (?, ?, ?, ?, ?)", (idx, str(idx), "", close, ""))
                        for position in range(100):
                            identity = boundary if idx == 3 and position == 0 else f"{idx * 100 + position:064X}"
                            db.execute("INSERT INTO payment VALUES (?, ?, ?, ?, ?, ?, ?)",
                                       (idx, position, identity, "A", "B", 1, 0))
                            if path == paths[0] and idx in (3, 4):
                                expected.append(baseline.alert_key(0.0, identity) > cutoff)
            before = [monitoring_replay.sha256(path) for path in paths]
            config = {"roles": ["train"] * 4 + ["development"] * 2 + ["calibration"] * 2 + ["test"] * 4}
            blocks = [{"start": 600, "role": role} for role in config["roles"]]
            with (patch.object(monitoring_replay, "MODEL_DIR", root),
                  patch.object(monitoring_replay, "PROCESSED", root),
                  patch.object(monitoring_replay, "protocol", return_value=(config, blocks))):
                first = monitoring_replay.run("baseline-full")
                self.assertEqual(first, monitoring_replay.run("baseline-full"))
            self.assertEqual(before, [monitoring_replay.sha256(path) for path in paths])
        self.assertEqual(first["feature_schema"]["names"], FEATURES)
        self.assertEqual(len(first["historical"]), 18)
        self.assertEqual(first["historical"][0]["frozen_alerts"]["alerts"], sum(expected))
        normal, shift, recovery = first["scenario"]
        self.assertEqual([r["modified"] for r in first["scenario"]], [0, 200, 0])
        self.assertEqual([r["scores"]["ks_distance"] for r in first["scenario"]], [0, 1, 0])
        self.assertEqual(shift["frozen_alerts"]["rate"], 1)
        self.assertEqual(normal["frozen_alerts"], first["historical"][3]["frozen_alerts"])
        self.assertEqual(recovery["frozen_alerts"], first["historical"][5]["frozen_alerts"])


@unittest.skipUnless(importlib.util.find_spec("fastapi"), "optional FastAPI environment required")
class ApiMonitoringTests(unittest.IsolatedAsyncioTestCase):
    async def test_metrics_follow_requests_and_reset_on_restart(self):
        from xrpl_anomaly.service import create_app

        folder = self.enterContext(tempfile.TemporaryDirectory(dir="."))
        path = Path(folder) / "model.json"
        bundle, boundary = service_fixture()
        save(path, bundle)
        app = create_app(path)
        payload = dict(feature_schema_version=SCHEMA_VERSION, feature_names=FEATURES, values=ROWS[20])
        async with app.router.lifespan_context(app):
            for body in (payload, dict(payload, transaction_id=boundary), dict(payload, values=[]),
                         dict(payload, feature_names=FEATURES[::-1])):
                await request(app, "POST", "/v1/score", json.dumps(body).encode())
            await request(app, "POST", "/v1/score", b"{")
            await request(app, "POST", "/v1/score", host="external.invalid")
            await request(app, "GET", "/missing")
            self.assertEqual((await request(app, "GET", "/v1/metrics", host="external.invalid"))[0], 400)
            status, report = await request(app, "GET", "/v1/metrics")
            self.assertEqual(status, 200)
            self.assertEqual(report, (await request(app, "GET", "/v1/metrics"))[1])
            operations = report["operations"]
            self.assertEqual(operations["status_codes"], {"200": 2, "400": 1, "404": 1, "422": 3})
            self.assertEqual(operations["score_request_rejection_rate"], 4 / 6)
            self.assertEqual(operations["score_validation_failure_rate"], .5)
            self.assertEqual(operations["complete_vector_rate"], .75)
            self.assertEqual(operations["scorer_validation_failures"], 1)
            self.assertEqual(operations["inference_ms"]["n"], 2)
            self.assertIsNone(operations["inference_ms"]["p95"])
            self.assertEqual(report["model_statistics"]["frozen_alerts"],
                             dict(alerts=0, decisions=1, unknown=1, rate=0))
            self.assertEqual(report["model"]["version"], 1)
            self.assertNotIn(boundary, json.dumps(report))
        async with app.router.lifespan_context(app):
            self.assertEqual((await request(app, "GET", "/v1/metrics"))[1]["window"]["n"], 0)

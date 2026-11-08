"""Offline transport and alert policy checks."""
import json
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from test_phase2 import encoded, fixture
from xrpl_anomaly.baseline import alert_cutoff, alert_key, budget_summary
from xrpl_anomaly.expansion import PLAN, acquire_locked, validate_plan
from xrpl_anomaly.expansion_report import scored_features
from xrpl_anomaly.features import FEATURES
from xrpl_anomaly.pilot import Client, MIB


class DeadlineTests(unittest.TestCase):
    def test_stalled_body_is_killed_and_retried(self):
        body = encoded(fixture())
        stall = threading.Event()
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append(self.path)
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if len(requests) == 1:
                    self.wfile.write(body[:32])
                    self.wfile.flush()
                    stall.wait(10)
                else:
                    self.wfile.write(body)

            def log_message(self, *args):
                pass

        with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                endpoint = f"http://127.0.0.1:{server.server_port}/"
                client = Client(timeout=1.5)
                processes = []
                launch = subprocess.Popen

                def tracked_launch(*args, **kwargs):
                    process = launch(*args, **kwargs)
                    processes.append(process)
                    return process

                started = time.monotonic()
                with (patch("xrpl_anomaly.pilot.time.sleep"),
                      patch("xrpl_anomaly.pilot.subprocess.Popen", side_effect=tracked_launch)):
                    self.assertEqual(client.get(endpoint, 10, True), body)
                self.assertLess(time.monotonic() - started, 4)
                self.assertEqual(requests, ["/", "/"])
                self.assertEqual((client.attempts, client.retries), (2, 1))
                self.assertEqual(client.bytes, 8 * MIB + len(body))
                self.assertEqual(client.observed_bytes, 32 + len(body))
                self.assertEqual(len(processes), 2)
                self.assertNotIn(processes[0].returncode, (None, 0))
                self.assertEqual(processes[1].returncode, 0)
            finally:
                stall.set()
                server.shutdown()
                thread.join()


class AlertBudgetTests(unittest.TestCase):
    def test_calibration_ties_and_permutation(self):
        rows = [(10, str(i)) for i in range(6)] + [(1, str(i)) for i in range(6, 423)]
        cutoff = alert_cutoff(rows)
        self.assertEqual(alert_cutoff(reversed(rows)), cutoff)
        self.assertEqual(budget_summary(rows, cutoff),
                         {"rows": 423, "alerts": 4, "above_score": 0,
                          "tied_score": 6, "alerted_ties": 4})
        self.assertGreater(alert_key(11, "new"), cutoff)
        self.assertEqual(budget_summary(rows[:6], alert_cutoff(rows[:6]))["alerts"], 0)


class BlockTests(unittest.TestCase):
    def test_frozen_manifest_and_invalid_bracket(self):
        plan = json.loads(PLAN.read_bytes())
        validate_plan(plan)
        plan["blocks"][1]["headers"][1][0] += 1
        with self.assertRaisesRegex(ValueError, "nonadjacent"):
            validate_plan(plan)

    def test_fresh_history_even_when_block_indexes_touch(self):
        payment = ((0, "tx", "sender", "receiver", 100, 1),)
        first = [(1, 0, ()), (2, 600, payment)]
        second = [(3, 601, ()), (4, 1201, payment)]
        self.assertEqual(len(list(scored_features(first, 600))), 1)
        row, = scored_features(second, 1201)
        values = dict(zip(FEATURES, row[-1], strict=True))
        self.assertEqual(values["sender_unseen"], 1)
        self.assertEqual(values["log_prior_edge_count"], 0)
        with self.assertRaisesRegex(ValueError, "lacks complete"):
            list(scored_features([(3, 601, ()), (4, 1200, payment)], 1200))

    def test_stage_resume_keeps_budget_and_verified_cache(self):
        first, stop = 33000, 33001
        body = encoded(fixture(first))
        identity = fixture(first)["result"]["ledger_hash"]
        block = {"headers": [[first, 946684800 + first, identity], None, None,
                             [first, 946684800 + first, identity],
                             [stop, 0, identity], None]}
        with tempfile.TemporaryDirectory(dir=".") as tmp:
            root = Path(tmp)
            budget_path = root / "budget.json"
            for exchange_replies, attempts in (([(["ok"], body), (["ok"], body),
                                                   (["invalid", "interrupted"], b"")], 3),
                                                 ([(["invalid", "interrupted"], b"")], 4)):
                with patch.object(Client, "exchange", side_effect=exchange_replies) as exchange:
                    with patch("xrpl_anomaly.pilot.time.sleep"):
                        with self.assertRaisesRegex(ValueError, "interrupted"):
                            acquire_locked(root, [block], "test")
                self.assertEqual(exchange.call_count, len(exchange_replies))
                budget = json.loads(budget_path.read_bytes())
                self.assertEqual(budget["attempts"], attempts)
                self.assertFalse(budget["active"])
                cache = root / "block-01"
                manifest = json.loads((cache / "manifest.json").read_bytes())
                self.assertEqual(manifest["observed_range"], [first, first])
                self.assertEqual(list(manifest["ledgers"]), [str(first)])
                self.assertEqual(len(list(cache.glob("*.json.gz"))), 1)

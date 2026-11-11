"""Deterministic Phase 2 fixtures and local integration checks."""
import gzip
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from math import log1p
from pathlib import Path
from unittest.mock import Mock, patch

from xrpl_anomaly.baseline import fit, score, threshold
from xrpl_anomaly.features import FEATURES, features
from xrpl_anomaly.ledger import RIPPLE_EPOCH, parse
from xrpl_anomaly.pilot import Client, acquire, cached, digest
from xrpl_anomaly.plots import graph_data, minute_bins, plot
from xrpl_anomaly.storage import connect, replay, store

SENDER = "rHb9CJAWyB4rj91VRWn96DkukG4bwdtyTh"
RECEIVER = "rPEPPER7kfTD9w2To4CQk6UCfuHM9c6GDY"
BIG = 9_007_199_254_740_993


def identity(number):
    return f"{number:064X}"


def fixture(index=10):
    return {"result": {"status": "success", "validated": True,
                       "ledger_hash": identity(index), "ledger_index": index,
                       "ledger": {"ledger_hash": identity(index), "ledger_index": str(index),
                                  "parent_hash": identity(index - 1), "close_time": index,
                                  "transactions": [{
                                      "hash": identity(index + 100),
                                      "tx_json": {"Account": SENDER, "Destination": RECEIVER,
                                                  "TransactionType": "Payment",
                                                  "DeliverMax": str(BIG + 1), "Fee": "12"},
                                      "meta": {"TransactionResult": "tesSUCCESS",
                                               "TransactionIndex": 0, "delivered_amount": str(BIG)},
                                  }]}}}


def encoded(body):
    return json.dumps(body).encode()


def rows(amount=BIG, second=False):
    row = (0, identity(100), SENDER, RECEIVER, amount, 12)
    return (row, (1, identity(101), *row[2:])) if second else (row,)


class LedgerTests(unittest.TestCase):
    def test_exact_drops_and_v1_compatibility(self):
        sample = fixture()
        ledger = parse(encoded(sample), 10)
        self.assertEqual((ledger.close, ledger.payments[0][-2:]), (RIPPLE_EPOCH + 10, (BIG, 12)))
        entry = sample["result"]["ledger"]["transactions"][0]
        tx = entry.pop("tx_json")
        tx["Amount"] = tx.pop("DeliverMax")
        entry.update(tx, metaData=entry.pop("meta"))
        self.assertEqual(parse(encoded(sample), 10), ledger)

    def test_missing_amount_and_exclusion_categories(self):
        for change, reason in [
            ({"delivered_amount": "unavailable"}, "invalid_amount_fee_or_flags"),
            ({"delivered_amount": "1.1"}, "invalid_amount_fee_or_flags"),
            ({"delivered_amount": 1}, "invalid_amount_fee_or_flags"),
            ({"delivered_amount": {"currency": "USD"}}, "token_payment"),
            ({"TransactionResult": "tecPATH_DRY"}, "failed_payment"),
        ]:
            with self.subTest(reason=reason, change=change):
                sample = fixture()
                sample["result"]["ledger"]["transactions"][0]["meta"].update(change)
                self.assertEqual(parse(encoded(sample), 10).exclusions, {reason: 1})

    def test_unvalidated_wrong_index_missing_array_and_duplicate(self):
        with self.assertRaises(ValueError):
            parse(encoded(fixture()), 11)
        sample = fixture()
        sample["result"]["validated"] = False
        with self.assertRaises(ValueError):
            parse(encoded(sample), 10)
        sample["result"]["validated"] = True
        entries = sample["result"]["ledger"]["transactions"]
        entries.append(entries[0])
        with self.assertRaises(ValueError):
            parse(encoded(sample), 10)
        del sample["result"]["ledger"]["transactions"]
        with self.assertRaises(KeyError):
            parse(encoded(sample), 10)

    def test_empty_confirmed_ledger(self):
        sample = fixture()
        sample["result"]["ledger"]["transactions"] = []
        self.assertEqual(parse(encoded(sample), 10).total, 0)

    def test_sqlite_replay_idempotence_conflicts_and_rollback(self):
        with tempfile.TemporaryDirectory(dir=".") as directory:
            db = connect(Path(directory) / "payments.sqlite")
            try:
                first = parse(encoded(fixture()), 10)
                second = parse(encoded(fixture(11)), 11)
                store(db, first, "first")
                store(db, first, "first")
                with self.assertRaises(ValueError):
                    store(db, first, "different")
                with self.assertRaises(ValueError):
                    store(db, replace(second, parent=identity(123)), "second")
                conflicting = (0, first.payments[0][1], *second.payments[0][2:])
                with self.assertRaises(sqlite3.IntegrityError):
                    store(db, replace(second, payments=(conflicting,)), "second")
                self.assertEqual(len(list(replay(db))), 1)
                store(db, second, "second")
                self.assertEqual([item[2][0][4] for item in replay(db)], [BIG, BIG])
            finally:
                db.close()


    def test_sqlite_reingestion_rejects_changed_payment_rows(self):
        first = parse(encoded(fixture()), 10)
        for sql in (
            "UPDATE payment SET amount = amount - 1",
            "DELETE FROM payment",
            "INSERT INTO payment SELECT ledger_idx, position + 1, 'extra', sender, receiver, amount, fee FROM payment",
        ):
            with self.subTest(sql=sql):
                db = connect(":memory:")
                try:
                    store(db, first, "first")
                    with db:
                        db.execute(sql)
                    before = list(replay(db))
                    with self.assertRaisesRegex(ValueError, "normalized payments.*10"):
                        store(db, first, "first")
                    self.assertEqual(list(replay(db)), before)
                    self.assertFalse(db.in_transaction)
                finally:
                    db.close()


class FeatureTests(unittest.TestCase):
    def test_strict_prior_same_ledger_future_and_window_expiry(self):
        input_rows = [(1, 0, rows()), (2, 600, rows(second=True)), (3, 601, rows())]
        actual = list(features(input_rows))
        self.assertFalse(actual[0][4])
        a, b = [dict(zip(FEATURES, row[-1], strict=True)) for row in actual[1:3]]
        self.assertEqual(a, b)
        self.assertEqual(a["log_prior_edge_count"], log1p(1))
        self.assertEqual(a["sender_log_out_drops"], log1p(BIG))
        self.assertEqual(a["sender_out_concentration"], 1)
        self.assertEqual(actual[-1][-1][18], log1p(2))
        changed_peer = (2, 600, (rows(amount=1)[0], rows(second=True)[1]))
        self.assertEqual(actual[2], list(features([input_rows[0], changed_peer]))[2])
        changed = list(features([*input_rows[:2], (3, 601, rows(amount=1))]))
        self.assertEqual(actual[:-1], changed[:-1])
        self.assertEqual(actual[1:3], list(features([input_rows[0], (2, 600, rows(second=True)),
                                                      (3, 1000, ())]))[1:3])

    def test_graph_exact_aggregation_and_gap_reset(self):
        other = "rThird"
        prior = ((0, "a", SENDER, RECEIVER, 2**62, 0),
                 (1, "b", SENDER, RECEIVER, 2**62, 0),
                 (2, "c", SENDER, other, 2**62, 0))
        actual = list(features([(1, 0, prior), (2, 600, rows()),
                                (4, 1200, ()), (5, 1800, rows())]))
        values = dict(zip(FEATURES, actual[-2][-1], strict=True))
        self.assertEqual(values["sender_log_out_drops"], log1p(3 * 2**62))
        self.assertAlmostEqual(values["sender_out_concentration"], 5 / 9)
        self.assertEqual(values["sender_log_out_counterparties"], log1p(2))
        cold = dict(zip(FEATURES, actual[-1][-1], strict=True))
        self.assertEqual(cold["sender_unseen"], 1)
        self.assertEqual(cold["sender_recency_seconds"], 600)
        self.assertFalse(list(features([(1, 0, prior), (3, 600, rows())]))[-1][4])


class BaselineTests(unittest.TestCase):
    def test_mad_iqr_resolution_and_constant(self):
        names = ("mad", "iqr", "sparse", "constant")
        rows = list(zip(range(9), [0]*5 + [1]*4, [0]*7 + [18, 18.000001], [3]*9))
        model = fit(rows, names)
        self.assertEqual([v["method"] for v in model.values()], ["mad", "iqr"])
        self.assertEqual(score((4, 0, 25, 999), names, model), (0, "mad"))
        self.assertEqual(score((25,), ("sparse",), fit([(0,)] * 7 + [(18,), (19,)],
                                                       ("sparse",))), (0, None))
        model = fit(rows, names, legacy_resolution=True)
        self.assertEqual([v["method"] for v in model.values()], ["mad", "iqr", "observed_resolution"])
        self.assertEqual(model["sparse"]["scale"], 18.000001 - 18)
        self.assertEqual(score((4, 0, 25, 999), names, model)[1], "sparse")
        self.assertEqual(threshold([10, 10] + [0] * 98), 10)
        self.assertEqual(threshold([11, 10] + [0] * 98), 10)


class AcquisitionTests(unittest.TestCase):
    def test_interrupted_pilot_resumes_at_first_missing_ledger(self):
        first = 33000

        def initial_fetch(endpoint, index, expanded):
            if index == first + 1:
                raise ValueError("lgrNotFound")
            return encoded(fixture(index))

        def resumed_fetch(endpoint, index, expanded):
            if index == first + 2:
                raise ValueError("lgrNotFound")
            return encoded(fixture(index))

        with tempfile.TemporaryDirectory(dir=".") as directory:
            root = Path(directory)
            with patch.object(Client, "get", side_effect=initial_fetch):
                with self.assertRaisesRegex(ValueError, "lgrNotFound"):
                    acquire(root, first + 255)
            before = json.loads((root / "manifest.json").read_bytes())
            self.assertEqual(before["observed_range"], [first, first])
            self.assertIn(first + 1, before["gaps"])
            with patch.object(Client, "get", side_effect=resumed_fetch) as fetch:
                with self.assertRaisesRegex(ValueError, "lgrNotFound"):
                    acquire(root, first + 255)
                self.assertEqual([call.args[1] for call in fetch.call_args_list],
                                 [first + 1, first + 2])
            after = json.loads((root / "manifest.json").read_bytes())
            self.assertEqual(after["ledgers"][str(first)], before["ledgers"][str(first)])
            self.assertEqual(after["observed_range"], [first, first + 1])

    def test_cache_digest_verification(self):
        body = encoded(fixture())
        item = {"bytes": len(body), "sha256": digest(body)}
        with tempfile.TemporaryDirectory(dir=".") as directory:
            root = Path(directory)
            path = root / (item["sha256"] + ".json.gz")
            path.write_bytes(gzip.compress(body, mtime=0))
            self.assertEqual(cached(root, item), body)
            path.write_bytes(gzip.compress(b"x" * len(body)))
            with self.assertRaises(ValueError):
                cached(root, item)

    def test_retry_throttling_and_historical_error(self):
        client = Client()
        client.exchange = Mock(side_effect=[
            (["http", 429, "2"], b""), (["ok"], encoded(fixture()))])
        with patch("xrpl_anomaly.pilot.time.sleep") as sleep:
            self.assertEqual(client.get("https://example.com", 10, True), encoded(fixture()))
            self.assertGreater(sleep.call_args.args[0], 1)
        self.assertEqual((client.attempts, client.retries), (2, 1))
        missing = encoded({"result": {"status": "error", "error": "lgrNotFound"}})
        client.exchange.side_effect = [(["ok"], missing)]
        with patch("xrpl_anomaly.pilot.time.sleep"), self.assertRaisesRegex(ValueError, "lgrNotFound"):
            client.get("https://example.com", 11, True)
        self.assertEqual(client.attempts, 3)

    def test_attempt_budget_stops_without_io(self):
        client = Client()
        client.exchange = Mock()
        client.attempts = 320
        with self.assertRaisesRegex(RuntimeError, "budget"):
            client.get("https://example.com", 10, True)
        client.exchange.assert_not_called()


class PlotTests(unittest.TestCase):
    def test_bins_and_induced_graph(self):
        data = [(1, 59, rows(1)), (2, 60, ()), (3, 120, rows(1_000_000))]
        self.assertEqual(minute_bins(data), [(0, 1, 1), (60, 0, 0), (120, 1, 1_000_000)])
        self.assertEqual(minute_bins(data[::2]), [(0, None, None), (60, None, None), (120, None, None)])
        sizes, edges = graph_data(data)
        self.assertEqual(sizes, [2, 2])
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0][-1], 2)

    @unittest.skipUnless(importlib.util.find_spec("matplotlib") and importlib.util.find_spec("networkx"),
                         "optional plotting environment")
    def test_repeatable_fixture_render(self):
        data = [(1, 0, rows()), (2, 600, rows())]
        report = {"close_utc": ["1970-01-01T00:00:00Z", "1970-01-01T00:10:00Z"],
                  "eligible_payments": 2, "snapshot_sha256": "synthetic",
                  "manifest_sha256": "synthetic", "git_revision": None,
                  "code_sha256": {}, "command_arguments": [], "environment": {}, "range": [1, 2]}
        full = [row for row in features(data) if row[4]]
        with tempfile.TemporaryDirectory(dir=".") as directory:
            output = Path(directory)
            plot(data, full, report, output)
            before = (output / "figure-metadata.json").read_bytes()
            self.assertEqual(len(list(output.glob("*.png"))), 5)
            plot(data, full, report, output)
            self.assertEqual(before, (output / "figure-metadata.json").read_bytes())

    def test_induced_graph_keeps_isolates_and_shared_recipient_edges(self):
        # Synthetic payments reproduce the published graph's topology by rank.
        pairs = [(sender, receiver) for sender in (1, 2) for receiver in (4, 5, 7, 9, 10)]
        pairs += [(3, 7), (6, 7), (6, 10), (11, 7), (13, 7),
                  (14, 0), (14, 7), (15, 7), (15, 9)]
        transfers = [(str(sender), str(receiver)) for sender, receiver in pairs]
        transfers.append(("1", "4"))  # The ordered pair is still one edge.
        for rank in range(16):
            account = str(rank)
            degree = sum(account in pair for pair in transfers)
            transfers.extend((account, f"outside-{rank}-{i}") for i in range(32 - rank - degree))
        payments = [(i, str(i), sender, receiver, 1, 1)
                    for i, (sender, receiver) in enumerate(transfers)]
        sizes, edges = graph_data([(1, 0, payments)])
        self.assertEqual(sizes, list(range(32, 16, -1)))
        self.assertEqual(len(edges), 19)
        self.assertEqual({(u, v) for u, v, _ in edges}, set(pairs))
        self.assertIn((1, 4, 2), edges)

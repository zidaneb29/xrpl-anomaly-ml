"""Check paired AP, rank denominators, and block weighting."""
import unittest

from xrpl_anomaly.audit_supplement import average_precision, macro, paired_metrics


class AuditSupplementTests(unittest.TestCase):
    def test_pairing_keeps_population_and_groups_score_ties(self):
        clean = {"a": 3, "b": 1, "c": 3, "d": 0}
        edited = clean | {"b": 4}
        labels = {"a", "b"}
        result = paired_metrics(clean, edited, labels)
        self.assertAlmostEqual(result["clean_ap"], 7 / 12)
        self.assertAlmostEqual(result["edited_ap"], 5 / 6)
        self.assertAlmostEqual(result["ap_change"], 1 / 4)
        self.assertEqual(result["score_win_rate"], .75)
        self.assertEqual(result["mean_score_change"], 1.5)
        self.assertEqual(result["mean_rank_change_pp"], 12.5)
        self.assertEqual(average_precision(dict(reversed(list(clean.items()))), labels), result["clean_ap"])
        with self.assertRaisesRegex(ValueError, "populations differ"):
            paired_metrics(clean, {"a": 3, "b": 1}, labels)
        with self.assertRaisesRegex(ValueError, "nonempty labels"):
            average_precision(clean, set())

    def test_equal_block_weight_does_not_pool_scenario_rows(self):
        low = paired_metrics({"a": 0, "b": 1}, {"a": 0, "b": 1}, {"a"})
        high = paired_metrics({"a": 1, "b": 0}, {"a": 1, "b": 0}, {"a"})
        rows = [dict(block=9, **low)] * 3 + [dict(block=10, **high)]
        self.assertEqual(macro(rows)["clean_ap"], .75)

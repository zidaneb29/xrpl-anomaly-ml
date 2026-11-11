"""Numerical plotting contracts independent of image hashes."""
import importlib.util
import unittest
from bisect import bisect_right
from collections import Counter

from xrpl_anomaly.heldout_figures import FULL, calibration_figure, empirical_survival
from xrpl_anomaly.development_figures import detector_score_figure, score_multiplicity


class SurvivalTests(unittest.TestCase):
    def test_strict_survival_at_and_between_ties_and_cutoff(self):
        values = [0, 0, 1, 2, 2, 2, 5]
        x, survival = empirical_survival(values)
        for query in (-1, 0, .5, 1, 1.25, 2, 3, 5, 6):
            # A direct count is independent of the grouped step calculation.
            plotted = survival[max(0, bisect_right(x, query) - 1)]
            self.assertEqual(plotted, sum(value > query for value in values) / len(values))
        self.assertEqual(x[1:], [0, 1, 2, 5])
        self.assertEqual(survival[-1], 0)
        # A strict score boundary excludes all ties; a digest can select some of them.
        self.assertEqual(survival[bisect_right(x, 2) - 1], 1 / 7)
        self.assertEqual(sum(value >= 2 for value in values) / len(values), 4 / 7)
        self.assertEqual(empirical_survival([3] * 4)[1], [1, 0])

    def test_pair_counts_preserve_coordinates_and_population(self):
        robust = {"a": 0, "b": 0, "c": 1}
        forest = {"a": .5, "b": .5, "c": .7}
        self.assertEqual(dict(score_multiplicity(robust, forest)), {(0, .5): 2, (1, .7): 1})
        with self.assertRaisesRegex(ValueError, "identical observation"):
            score_multiplicity(robust, {"a": .5})


@unittest.skipUnless(importlib.util.find_spec("matplotlib"), "optional plotting environment required")
class PlotSemanticsTests(unittest.TestCase):
    def setUp(self):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        self.addCleanup(plt.close, "all")

    def test_calibration_artists_use_post_steps_and_explicit_zero_marks(self):
        scores = {(block, model): [0, 0, 1, 2] for block in ("7", "8") for model in FULL}
        models = {model: {"cutoff": [1]} for model in FULL}
        fig = calibration_figure(scores, models)
        for ax in fig.axes:
            for line in (ax.lines[0], ax.lines[2]):
                self.assertEqual(line.get_drawstyle(), "steps-post")
                self.assertEqual(list(line.get_ydata()), [1, .5, .25, 0])
            self.assertEqual(ax.lines[1].get_markerfacecolor(), "none")
            self.assertIn("P(score > x)", ax.get_ylabel())

    def report(self):
        def row(block, window):
            begin = (block - 7) * (3 * 86400 + 1800) + (window - 1) * 600
            return dict(block=block, window=window, n=100,
                        start_unix_utc=begin, end_unix_utc_exclusive=begin + 600,
                        role="calibration", scores=dict(ks_distance=.1 * window,
                        comparison=dict(p05=window, p50=window + 2, p95=window + 4)),
                        features={name: dict(ks_distance=.05 * window)
                                  for name in ("log_fee_drops", "log_prior_edge_count")},
                        frozen_alerts=dict(rate=window / 100))
        historical = [row(block, window) for block in (7, 8) for window in (1, 2, 3)]
        scenario = [row(8, window) for window in (1, 2, 3)]
        scenario[1]["scores"]["comparison"] = dict(p05=9, p50=9, p95=9)
        return dict(model=dict(id="baseline-full"), settings=dict(ks_distance_guide=.2),
                    reference=dict(block=7, n=300, scores=dict(p50=3), frozen_alerts=dict(rate=.0085)),
                    historical=historical, scenario=scenario)

    def test_historical_lines_stop_at_unsampled_gaps_and_references_are_labeled(self):
        from xrpl_anomaly.monitoring_figures import historical_figure, historical_positions
        report = self.report()
        self.assertEqual(historical_positions(report["historical"]), ([0, 1, 2, 4, 5, 6], [(3, 259200)]))
        fig = historical_figure(report)
        distance, alerts = fig.axes
        self.assertEqual(list(distance.lines[0].get_xdata()), [0, 1, 2])
        self.assertEqual(list(distance.lines[1].get_xdata()), [4, 5, 6])
        self.assertEqual(list(distance.lines[0].get_ydata()), [.1, .2, .1 * 3])
        self.assertEqual([bar.get_height() for bar in alerts.patches[:6]], [1, 2, 3, 1, 2, 3])
        references = {line.get_label(): line.get_ydata()[0] for line in alerts.lines}
        self.assertAlmostEqual(references["Block 7 reference (0.850%)"], .85)
        self.assertEqual(references["Pooled calibration budget target (1%)"], 1)

    def test_both_score_intervals_and_degenerate_range_are_visible(self):
        from xrpl_anomaly.monitoring_figures import shift_figure
        report = self.report()
        fig = shift_figure(report)
        score_axis = fig.axes[1]
        for container, rows in zip(score_axis.containers,
                                   (report["scenario"], report["historical"][3:]), strict=True):
            median_line, caps, bars = container.lines
            self.assertEqual(list(median_line.get_ydata()), [r["scores"]["comparison"]["p50"] for r in rows])
            self.assertTrue(caps)
            for segment, row in zip(bars[0].get_segments(), rows, strict=True):
                self.assertEqual(list(segment[:, 1]),
                                 [row["scores"]["comparison"][key] for key in ("p05", "p95")])
        self.assertTrue(any("p05 = median = p95" in text.get_text() for text in score_axis.texts))
        self.assertIn("Original input restored", fig.axes[-1].get_xticklabels()[-1].get_text())

    def test_scatter_color_counts_exact_pairs_with_a_shared_scale(self):
        robust = {"a": 0, "b": 0, "c": 1}
        forest = {"a": .5, "b": .5, "c": .7}
        predictions = {"baseline-full": {4: robust, 5: robust},
                       "isolation-full-256-7": {4: forest, 5: forest}}
        fig = detector_score_figure(predictions, 256)
        for ax in fig.axes[:2]:
            dots = ax.collections[0]
            reconstructed = {tuple(pair): int(count) for pair, count in zip(
                dots.get_offsets(), dots.get_array(), strict=True)}
            self.assertEqual(reconstructed, Counter([(0, .5), (0, .5), (1, .7)]))
            self.assertEqual(sum(reconstructed.values()), 3)
            self.assertEqual((dots.norm.vmin, dots.norm.vmax), (1, 2))
        self.assertIs(fig.axes[0].collections[0].norm, fig.axes[1].collections[0].norm)

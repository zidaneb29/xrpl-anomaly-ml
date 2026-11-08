"""Render the historical and controlled-shift monitoring figures."""
import json

import matplotlib
from matplotlib import pyplot as plt

from .monitoring_replay import sha256


def render(report, output, input_hash):
    reference = report["reference"]
    title = f'{report["model"]["id"]} against calibration block {reference["block"]} (n={reference["n"]:,})'
    guide = report["settings"]["ks_distance_guide"]
    metadata = {}

    def save(fig, name, caption):
        path = output / name
        fig.savefig(path, dpi=150)
        plt.close(fig)
        metadata[name] = {"sha256": sha256(path), "caption": caption}

    rows = report["historical"]
    x = range(len(rows))
    fig, (distance, alerts) = plt.subplots(2, 1, sharex=True, figsize=(13, 6), layout="constrained")
    distance.plot(x, [row["scores"]["ks_distance"] for row in rows], "o-", label="Score")
    for name in ("log_fee_drops", "log_prior_edge_count"):
        distance.plot(x, [row["features"][name]["ks_distance"] for row in rows], ".-", label=name)
    distance.axhline(guide, ls="--", color="0.45", label="Descriptive guide")
    distance.set(ylabel="ECDF distance", title=title)
    distance.legend(ncol=4)
    def alert_percent(row):
        rate = row["frozen_alerts"]["rate"]
        return 100 * rate if rate is not None else float("nan")

    alerts.bar(x, [alert_percent(row) for row in rows])
    alerts.axhline(100 * reference["frozen_alerts"]["rate"], ls="--", color="0.45")
    alerts.set(ylabel="Frozen alerts (%)", xlabel="Block.window and sample size (each window is 10 minutes)")
    alerts.set_xticks(list(x), [f'{r["block"]}.{r["window"]}\n{r["n"]:,}' for r in rows])
    for axis in (distance, alerts):
        axis.axvline(5.5, ls=":", color="0.4")
    distance.text(.01, .95, "Calibration", transform=distance.transAxes, va="top")
    distance.text(.97, .95, "Final test", transform=distance.transAxes, va="top", ha="right")
    save(fig, "historical-monitoring.png", "Chronological clean windows. Block 7 windows overlap their reference.")

    rows = report["scenario"]
    paired = [row for row in report["historical"] if row["block"] == rows[0]["block"]]
    x = range(len(rows))
    fig, axes = plt.subplots(3, 1, sharex=True, figsize=(8, 8), layout="constrained")
    series = (
        ("Fee ECDF distance", lambda r: r["features"]["log_fee_drops"]["ks_distance"], guide),
        ("Anomaly score p05–p95", lambda r: r["scores"]["comparison"]["p50"],
         reference["scores"]["p50"]),
        ("Frozen alerts (%)", alert_percent, alert_percent(reference)),
    )
    for axis, (label, value, line) in zip(axes, series, strict=True):
        axis.axvspan(.6, 1.4, color="#f6d7a8", alpha=.55)
        axis.axhline(line, ls=":", color="0.4")
        axis.plot(x, [value(r) for r in rows], "o-", label="Scenario")
        axis.plot(x, [value(r) for r in paired], "x--", label="Unchanged counterpart")
        axis.set_ylabel(label)
    low = [r["scores"]["comparison"]["p05"] for r in rows]
    high = [r["scores"]["comparison"]["p95"] for r in rows]
    axes[1].vlines(list(x), low, high, alpha=.6)
    axes[0].set_title(title)
    axes[0].legend()
    axes[-1].set_xticks(list(x), [f'{r["stage"]}\nn={r["n"]:,}' for r in rows])
    save(fig, "shift-recovery.png", "Block 8, fixed synthetic fee in the middle window. Scores show the median and "
         "p05–p95 range. Dotted guides mark the fee distance guide, reference score median and reference alert rate.")
    (output / "figure-metadata.json").write_text(json.dumps(
        {"input_sha256": input_hash, "matplotlib": matplotlib.__version__, "figures": metadata}, indent=2
    ) + "\n", encoding="utf-8")

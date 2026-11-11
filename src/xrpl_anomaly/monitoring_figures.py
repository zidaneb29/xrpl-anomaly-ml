"""Render the historical and controlled-shift monitoring figures."""
import json
from itertools import groupby
from pathlib import Path

import matplotlib
from matplotlib import pyplot as plt

from .monitoring_replay import sha256


def alert_percent(row):
    rate = row["frozen_alerts"]["rate"]
    return 100 * rate if rate is not None else float("nan")


def historical_positions(rows):
    """Retain row order and reserve a visible slot at each unsampled block boundary."""
    positions, gaps = [], []
    for index, row in enumerate(rows):
        if index and row["block"] != rows[index - 1]["block"]:
            seconds = row["start_unix_utc"] - rows[index - 1]["end_unix_utc_exclusive"]
            gaps.append((index + len(gaps), seconds))
        positions.append(index + len(gaps))
    return positions, gaps


def historical_figure(report):
    reference = report["reference"]
    rows = report["historical"]
    x, gaps = historical_positions(rows)
    fig, (distance, alerts) = plt.subplots(2, 1, sharex=True, figsize=(13, 6.5), layout="constrained")
    series = (("Score", "C0", lambda r: r["scores"]["ks_distance"]),
              ("log_fee_drops", "C1", lambda r: r["features"]["log_fee_drops"]["ks_distance"]),
              ("log_prior_edge_count", "C2", lambda r: r["features"]["log_prior_edge_count"]["ks_distance"]))
    for label, color, value in series:
        for index, (_, members) in enumerate(groupby(range(len(rows)), key=lambda i: rows[i]["block"])):
            members = list(members)
            distance.plot([x[i] for i in members], [value(rows[i]) for i in members],
                          "o-", color=color, label=label if index == 0 else None, markersize=4)
    distance.axhline(report["settings"]["ks_distance_guide"], ls="--", color="0.45",
                     label="Descriptive guide (0.20)")
    distance.set(ylabel="ECDF distance",
                 title=f'{report["model"]["id"]} against block {reference["block"]} (n={reference["n"]:,})'
                       "\nCalibration blocks 7–8; test blocks 9–12")
    distance.legend(ncol=4, fontsize=9, loc="upper left", bbox_to_anchor=(0, 1.01))
    alerts.bar(x, [alert_percent(row) for row in rows])
    alerts.axhline(alert_percent(reference), ls="--", color="0.35",
                   label=f'Block {reference["block"]} reference ({alert_percent(reference):.3f}%)')
    alerts.axhline(1, ls=":", color="#8b4513", label="Pooled calibration budget target (1%)")
    alerts.legend(loc="upper left", fontsize=9, ncol=2)
    alerts.set(ylabel="Frozen alerts (%)",
               xlabel="Block.window and sample size. Windows are 10 minutes; shaded gaps are compressed.")
    alerts.set_xticks(x, [f'{r["block"]}.{r["window"]}\n{r["n"]:,}' for r in rows])
    for center, seconds in gaps:
        for axis in (distance, alerts):
            axis.axvspan(center - .45, center + .45, color="0.92", zorder=0)
        distance.text(center, .48, f"{seconds / 86400:.2f} d unsampled",
                      transform=distance.get_xaxis_transform(), rotation=90, ha="center", va="center", fontsize=8)
    boundary = next((x[i] - .5 for i, row in enumerate(rows)
                     if row["role"] == "test"), None)
    if boundary is not None:
        for axis in (distance, alerts):
            axis.axvline(boundary, ls=":", color="0.4")
    return fig


def shift_figure(report):
    reference = report["reference"]
    rows = report["scenario"]
    paired = [row for row in report["historical"] if row["block"] == rows[0]["block"]]
    fig, axes = plt.subplots(3, 1, sharex=True, figsize=(9, 9), layout="constrained")
    for axis in axes:
        axis.axvspan(.6, 1.4, color="#f6d7a8", alpha=.55)
    for cohort, color, marker, label, offset in (
        (rows, "C0", "o", "Fee override in middle window", -.055),
        (paired, "C1", "x", "Original fees, same rows", .055),
    ):
        axes[0].plot(range(3), [r["features"]["log_fee_drops"]["ks_distance"] for r in cohort],
                     marker=marker, color=color, label=label)
        quantiles = [r["scores"]["comparison"] for r in cohort]
        median = [q["p50"] for q in quantiles]
        axes[1].errorbar([i + offset for i in range(3)], median,
                         yerr=([q["p50"] - q["p05"] for q in quantiles],
                               [q["p95"] - q["p50"] for q in quantiles]),
                         fmt=marker, color=color, capsize=5, label=label)
        axes[2].plot(range(3), [alert_percent(r) for r in cohort],
                     marker=marker, color=color, label=label)
    axes[0].axhline(report["settings"]["ks_distance_guide"], ls=":", color="0.4", label="ECDF guide (0.20)")
    axes[1].axhline(reference["scores"]["p50"], ls=":", color="0.4", label="Block 7 reference median")
    axes[2].axhline(alert_percent(reference), ls=":", color="0.4",
                    label=f"Block 7 reference ({alert_percent(reference):.3f}%)")
    for i, row in enumerate(rows):
        q = row["scores"]["comparison"]
        if q["p05"] == q["p95"]:
            axes[1].annotate(f'p05 = median = p95\n{q["p50"]:.2f}',
                             (i - .055, q["p50"]), xytext=(12, -28),
                             textcoords="offset points", fontsize=9)
    axes[0].set(ylabel="Fee ECDF distance",
                title=f'Synthetic fee override in block {rows[0]["block"]}; reference block 7 (n={reference["n"]:,})')
    axes[1].set_ylabel("Anomaly score\nmedian and p05–p95")
    axes[2].set_ylabel("Frozen alerts (%)")
    axes[0].legend(fontsize=9, loc="upper left")
    axes[1].legend(fontsize=8, loc="upper left")
    axes[2].legend(fontsize=8, loc="upper left")
    axes[-1].set_xticks(range(3), [f'{stage}\nn={r["n"]:,}' for stage, r in zip(
        ("Original input", "Synthetic fee override", "Original input restored"), rows, strict=True)])
    axes[-1].set_xlabel("Restored input reuses the next unchanged window; the scorer has no recovery state.")
    return fig


def render(report, output, input_hash):
    metadata = {}
    for name, figure, caption in (
        ("historical-monitoring.png", historical_figure,
         "Original windows in chronological order. Lines stop between blocks; shaded multi-day gaps "
         "are compressed. Block 7 overlaps its reference. Reference alert rate and 1% target are labeled."),
        ("shift-recovery.png", shift_figure,
         "Synthetic prepared-fee override in the middle block 8 window. Both series show median and "
         "p05–p95 with capped intervals; coincident quantiles are annotated. Original input restored "
         "means the next unchanged window, with no state recovery or incident labels."),
    ):
        fig = figure(report)
        path = output / name
        fig.savefig(path, dpi=150)
        plt.close(fig)
        metadata[name] = {"sha256": sha256(path), "caption": caption}
    (output / "figure-metadata.json").write_text(json.dumps(
        {"input_sha256": input_hash, "source_sha256": sha256(Path(__file__)),
         "matplotlib": matplotlib.__version__, "figures": metadata}, indent=2
    ) + "\n", encoding="utf-8")

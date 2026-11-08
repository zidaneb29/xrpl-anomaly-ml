"""Render held-out figures from deterministic Phase 3B.3 artifacts."""
import csv
import json
from collections import defaultdict
from statistics import mean

from .pilot import digest, dump

FULL = ("baseline-full", "isolation-full-7", "isolation-full-29")
LABELS = ("Robust baseline", "Forest seed 7", "Forest seed 29")


def render(output):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    result_path, scores_path, models_path = (output / name for name in
                                            ("evaluation.json", "clean-scores.csv", "models.json"))
    data = json.loads(result_path.read_bytes())
    models = json.loads(models_path.read_bytes())
    block_rows = data["aggregate"]["by_block"]
    cells = data["aggregate"]["by_cell"]
    metadata = {}

    def save(fig, name, caption):
        path = output / (name + ".png")
        fig.tight_layout()
        fig.savefig(path, dpi=140)
        plt.close(fig)
        metadata[path.name] = dict(sha256=digest(path.read_bytes()), caption=caption)

    scores = defaultdict(list)
    with scores_path.open(encoding="utf-8", newline="") as file:
        for row in csv.DictReader(file):
            if row["block"] in ("7", "8") and row["model"] in FULL:
                scores[row["block"], row["model"]].append(float(row["score"]))
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.6))
    for ax, key, label in zip(axes, FULL, LABELS, strict=True):
        for block in ("7", "8"):
            values = sorted(scores[block, key])
            ax.step(values, [(len(values) - i) / len(values) for i in range(len(values))],
                    label=f"Block {block}, n={len(values):,}")
        ax.axvline(models[key]["cutoff"][0], color="black", linestyle="--", label="Pooled score cutoff")
        ax.set(title=label, xlabel="Anomaly score", ylabel="Empirical survival", yscale="log")
        ax.legend(fontsize=7)
    save(fig, "calibration", "Clean calibration blocks 7 and 8. Vertical lines show the score component of "
         "each frozen cutoff. The persisted digest resolves score ties.")

    def paired_bars(ax, groups, select, *, metric="ap"):
        for offset, (method, label) in enumerate(zip(("baseline", "isolation"), LABELS[:2], strict=True)):
            values = [[row[metric] for row in select(group) if row["method"] == method] for group in groups]
            ax.bar([i + (offset - 0.5) * 0.35 for i in range(len(groups))],
                   [mean(rows) if rows else float("nan") for rows in values], width=0.35,
                   label="Isolation Forest" if method == "isolation" else label)
        ax.legend(fontsize=8)

    levels = sorted({(row["family"], row["level"]) for row in cells})
    fig, ax = plt.subplots(figsize=(9, 4))
    paired_bars(ax, levels, lambda pair: [r for r in cells if r["group"] == "full"
                                         and (r["family"], r["level"]) == pair])
    ax.set_xticks(range(len(levels)), [f"{family}\n{level}" for family, level in levels])
    ax.set(ylabel="Average precision", title="Full detectors by synthetic intervention")
    save(fig, "synthetic-families", "Average precision on full synthetic test copies, averaged over available "
         "blocks and prespecified seeds. Label prevalence varies across intervention families and levels.")

    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    groups = ["static", "temporal", "full"]
    paired_bars(axes[0], groups, lambda group: [r for r in block_rows if r["group"] == group])
    axes[0].set_xticks(range(len(groups)), ["Static", "Static + temporal", "Full"])
    axes[0].set(title="Feature ablations", ylabel="Macro average precision")
    blocks = [9, 10, 11, 12]
    paired_bars(axes[1], blocks, lambda block: [r for r in block_rows if r["block"] == block and r["group"] == "full"])
    axes[1].set_xticks(range(4), blocks)
    axes[1].set(title="Full detectors by test block", xlabel="Chronological block", ylabel="Macro average precision")
    save(fig, "ablation-and-blocks", "Macro average precision on synthetic copies. Forest feature sets use "
         "their respective development-selected subsamples. Blocks can share accounts.")

    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    for key, label in zip(FULL, LABELS, strict=True):
        rows = [r for r in data["clean"] if r["model"] == key]
        axes[0].plot([r["block"] for r in rows], [100 * r["operating"]["rate"] for r in rows],
                     marker="o", label=label)
    rows = [r for r in data["clean"] if r["model"] == FULL[0]]
    axes[0].plot([r["block"] for r in rows], [100 * r["fixed_budget"]["rate"] for r in rows],
                 color="black", linestyle="--", label="Fixed rank budget")
    axes[0].set(xlabel="Calibration (7–8) and test (9–12) block", ylabel="Alert rate (%)")
    axes[0].legend(fontsize=7)
    pairs = sorted({(r["left"], r["right"]) for r in data["stability"] if r["left"] in FULL})
    for left, right in pairs:
        rows = [r for r in data["stability"] if (r["left"], r["right"]) == (left, right)]
        axes[1].plot([r["block"] for r in rows], [r["spearman"] for r in rows],
                     marker="o", label=f"{left} / {right}")
    axes[1].set(xlabel="Test block", ylabel="Spearman rank correlation")
    axes[1].legend(fontsize=7)
    save(fig, "alerts-and-stability", "Observed scores on original payments. The cutoff transfers unchanged "
         "from pooled calibration. Rank stability compares models on identical observations within each block.")

    fig, ax = plt.subplots(figsize=(7, 4))
    for key, model in models.items():
        values = [r["ap"] for r in data["synthetic"] if r["model"] == key and "ap" in r]
        if values:
            size = len(json.dumps(model, separators=(",", ":")).encode())
            ax.scatter(size / 1024, mean(values), label=key)
    ax.set(xscale="log", xlabel="Compact serialized model (KiB)", ylabel="Mean synthetic average precision")
    ax.legend(fontsize=7, ncol=2)
    save(fig, "performance-and-cost", "Available-cell mean synthetic average precision versus compact JSON "
         "artifact size, including fitted parameters and cutoff. Runtime benchmarks are recorded separately.")
    dump(output / "figure-metadata.json", dict(matplotlib=matplotlib.__version__, figures=metadata,
         inputs={p.name: digest(p.read_bytes()) for p in (result_path, scores_path, models_path)}))

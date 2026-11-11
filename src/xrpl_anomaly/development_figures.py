"""Reproducible Phase 3B.2 plots using the existing optional plotting environment."""
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

from .features import FEATURES
from .pilot import digest, dump


def score_multiplicity(robust, forest):
    if robust.keys() != forest.keys():
        raise ValueError("score pairs require identical observation identities")
    return sorted(Counter((robust[i], forest[i]) for i in robust).items(), key=lambda item: (item[1], item[0]))


def detector_score_figure(predictions, size):
    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm
    from matplotlib.ticker import ScalarFormatter

    key = f"isolation-full-{size}-7"
    pairs = [score_multiplicity(predictions["baseline-full"][i], predictions[key][i]) for i in (4, 5)]
    maximum = max(count for block in pairs for _, count in block)
    norm = LogNorm(vmin=1, vmax=max(2, maximum))
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.5), layout="constrained")
    for index, ax, block in zip((4, 5), axes, pairs, strict=True):
        points = [pair for pair, _ in block]
        counts = [count for _, count in block]
        dots = ax.scatter([x for x, _ in points], [y for _, y in points], c=counts,
                          s=10, norm=norm, cmap="viridis", linewidths=0)
        ax.set(xscale="symlog", xlabel="Robust deviation (symlog)", ylabel="Isolation score",
               title=f"Block {index + 1}: n={sum(counts):,}; {len(points):,} score pairs")
    bar = fig.colorbar(dots, ax=axes, label="Payments per exact score pair (log color scale)")
    ticks = sorted({1, maximum, *(n for n in (2, 5, 10, 20, 50, 100) if n <= maximum)})
    bar.set_ticks(ticks)
    bar.ax.yaxis.set_major_formatter(ScalarFormatter())
    bar.ax.minorticks_off()
    fig.suptitle("Development scores; identical pairs counted together")
    return fig


def render_detector_scores(source, output):
    """Render only the affected scatterplot from the frozen score table."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    evaluation = json.loads((source / "evaluation.json").read_bytes())
    predictions = defaultdict(lambda: defaultdict(dict))
    with (source / "development-scores.csv").open(encoding="utf-8", newline="") as file:
        for row in csv.DictReader(file):
            predictions[row["model"]][int(row["block"]) - 1][row["identity"]] = float(row["score"])
    fig = detector_score_figure(predictions, evaluation["selected"]["full"]["size"])
    path = output / "detector-scores.png"
    fig.savefig(path, dpi=150, metadata={"Software": "xrpl-anomaly-ml"})
    plt.close(fig)
    dump(output / "figure-metadata.json", dict(
        matplotlib=matplotlib.__version__, source_sha256=digest(Path(__file__).read_bytes()),
        inputs={name: digest((source / name).read_bytes()) for name in ("evaluation.json", "development-scores.csv")},
        outputs={path.name: digest(path.read_bytes())},
        caption="Exact score pairs retain their coordinates. Logarithmic color encodes payment multiplicity, "
                "with one shared color scale across both development blocks. No jitter or score changes."))


def render(output, blocks, originals, predictions, evaluation):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    files = {}

    def save(fig, name):
        path = output / f"{name}.png"
        fig.savefig(path, dpi=150, metadata={"Software": "xrpl-anomaly-ml"})
        plt.close(fig)
        files[path.name] = digest(path.read_bytes())

    labels = [f"{b['block']}\n{b['role']}" for b in blocks]
    fig, axes = plt.subplots(2, 1, figsize=(8, 6), layout="constrained")
    axes[0].bar(labels, [b["total_transactions"] for b in blocks], color="#336790")
    axes[0].set(ylabel="Transactions examined")
    axes[1].bar(labels, [b["eligible_payments"] for b in blocks], color="#9db4c5", label="Including warm-up")
    axes[1].bar(labels, [b["feature_counts"]["rows"] for b in blocks], color="#336790", label="Scoring window")
    axes[1].set(ylabel="Eligible XRP payments")
    axes[1].legend()
    save(fig, "block-comparison")

    fig, axes = plt.subplots(1, 3, figsize=(12, 4), layout="constrained")
    for axis, name in zip(axes, ("log_amount_drops", "sender_recency_seconds", "log_prior_edge_count"),
                          strict=True):
        column = FEATURES.index(name)
        groups = [[row[-1][column] for rows in chunk for row in rows.values()]
                  for chunk in (originals[:4], originals[4:])]
        combined = groups[0] + groups[1]
        low, high = min(combined), max(combined)
        if low == high:
            high += 1
        bins = [low + (high - low) * i / 30 for i in range(31)]
        for label, values in zip(("Train", "Development"), groups, strict=True):
            axis.hist(values, bins=bins, weights=[1 / len(values)] * len(values),
                      histtype="step", linewidth=1.8, label=label)
        axis.set(xlabel=name.replace("_", " "), ylabel="Fraction per bin")
    axes[0].legend()
    save(fig, "feature-distributions")

    fig, ax = plt.subplots(figsize=(9, 7), layout="constrained")
    train = [row[-1] for rows in originals[:4] for row in rows.values()]
    dev = [row[-1] for rows in originals[4:] for row in rows.values()]
    zero = [[sum(row[i] == 0 for row in rows) / len(rows) for rows in (train, dev)]
            for i in range(len(FEATURES))]
    heat = ax.imshow(zero, aspect="auto", vmin=0, vmax=1, cmap="Blues")
    ax.set(xticks=[0, 1], xticklabels=["Train", "Development"],
           yticks=range(len(FEATURES)), yticklabels=FEATURES)
    fig.colorbar(heat, ax=ax, label="Fraction equal to zero")
    save(fig, "sparse-features")

    fig, ax = plt.subplots(figsize=(8, 4), layout="constrained")
    for name, label in (("sender_seen", "Sender"), ("receiver_seen", "Receiver"), ("prior_edge", "Directed edge")):
        ax.plot(labels, [b["feature_counts"].get(name, 0) / b["feature_counts"]["rows"] for b in blocks],
                marker="o", label=label)
    ax.set(ylabel="Fraction observed in earlier 600 s", ylim=(0, 1))
    ax.legend()
    save(fig, "graph-recurrence")

    selected = evaluation["selected"]
    records = [r for r in evaluation["results"] if "ap" in r and
               (r["method"] == "baseline" or r["size"] == selected[r["group"]]["size"])]
    if "full" in selected:
        fig = detector_score_figure(predictions, selected["full"]["size"])
        save(fig, "detector-scores")

    if records:
        fig, axes = plt.subplots(1, 3, figsize=(11, 4), layout="constrained")
        for ax, (family, levels) in zip(axes, evaluation["families"].items(), strict=True):
            for method, label in (("baseline", "Robust deviation"), ("isolation", "Isolation Forest")):
                points = [[r["recall"] for r in records if r["group"] == "full" and r["family"] == family
                           and r["level"] == level and r["method"] == method] for level in levels]
                valid = [(level, mean(values)) for level, values in zip(levels, points, strict=True) if values]
                if valid:
                    ax.plot(*zip(*valid), marker="o", label=label)
            ax.set(title=family.capitalize(), xlabel="Intervention level", xticks=levels,
                   ylabel="Recall at 1% budget", ylim=(0, 1))
        if axes[0].lines:
            axes[0].legend()
        fig.suptitle("Synthetic development interventions, full feature set")
        save(fig, "synthetic-severity")

        fig, ax = plt.subplots(figsize=(7, 4), layout="constrained")
        for method, label in (("baseline", "Robust deviation"), ("isolation", "Isolation Forest")):
            groups = [(group, [r["ap"] for r in records if r["group"] == group and r["method"] == method])
                      for group in ("static", "temporal", "full")]
            points = [(group, mean(values)) for group, values in groups if values]
            if points:
                ax.plot(*zip(*points), marker="o", label=label)
        ax.set(ylabel="Macro mean average precision", ylim=(0, 1),
               title="Synthetic development feature ablation")
        ax.legend()
        save(fig, "feature-ablation")

    dump(output / "figure-metadata.json",
         dict(matplotlib=matplotlib.__version__, inputs=evaluation["artifacts"],
              evaluation_sha256=digest((output / "evaluation.json").read_bytes()),
              source_sha256=digest(Path(__file__).read_bytes()), outputs=files,
              command="python -B -m xrpl_anomaly.development --figures"))

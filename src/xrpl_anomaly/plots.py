"""Render local Phase 2 scientific figures from verified pilot records."""
from collections import Counter
from datetime import UTC, datetime
from math import log1p

from .pilot import digest, dump

BIN = 60
SEED = 42
MAX_NODES = 16
PILOT_SNAPSHOT = "a90ec409114ee4043b5b0f9b66583900ec159a645a634afa1633e38b26e36ce4"
# Rank-indexed coordinates for the frozen pilot. Put the two senders on
# opposite sides of their five shared recipients, with isolates at lower right.
PILOT_LAYOUT = (
    (3.9, -.6), (-7, 0), (7, 0), (-.8, -4.4), (0, 6), (0, 3),
    (-1.5, -1.1), (0, -3), (4.8, -5.5), (0, -6), (0, 0), (-1.95, -3.45),
    (6.1, -5.5), (.65, -1.35), (2.1, -.8), (.9, -4.1),
)


def minute_bins(ledgers):
    first, last = ledgers[0][1] // BIN, ledgers[-1][1] // BIN
    counts, volume, gaps = Counter(), Counter(), set()
    previous = None
    for index, close, rows in ledgers:
        minute = close // BIN
        counts[minute] += len(rows)
        volume[minute] += sum(row[4] for row in rows)
        if previous and index != previous[0] + 1:
            gaps.update(range(previous[1], minute + 1))
        previous = index, minute
    return [(minute * BIN, counts[minute] if minute not in gaps else None,
             volume[minute] if minute not in gaps else None) for minute in range(first, last + 1)]


def graph_data(ledgers):
    incident, edges = Counter(), Counter()
    for _, _, rows in ledgers:
        for _, _, sender, receiver, _, _ in rows:
            incident.update((sender, receiver))
            edges[sender, receiver] += 1
    selected = sorted(incident, key=lambda account: (-incident[account], account))[:MAX_NODES]
    numbering = {account: i for i, account in enumerate(selected)}
    induced = sorted((numbering[sender], numbering[receiver], count)
                     for (sender, receiver), count in edges.items()
                     if sender in numbering and receiver in numbering)
    return [incident[account] for account in selected], induced


def plot(ledgers, full, report, output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as dates
    import matplotlib.pyplot as plt
    import networkx as nx

    matplotlib.rcParams.update({"font.size": 10, "axes.spines.top": False,
                                "axes.spines.right": False, "figure.dpi": 140})
    files = {}
    scope = (f"XRPL Mainnet | {report['close_utc'][0]} to {report['close_utc'][1]}\n"
             f"Ledgers {ledgers[0][0]}–{ledgers[-1][0]} | "
             f"{report['eligible_payments']:,} eligible payments | "
             f"Snapshot {report['snapshot_sha256'][:12]}")

    def save(fig, name, caption):
        fig.text(.04, .025, f"{scope}\n{caption}", fontsize=8, color="#334155", va="bottom")
        fig.tight_layout(rect=(0, .14, 1, 1))
        filename = name + ".png"
        fig.savefig(output / filename)
        plt.close(fig)
        files[filename] = {"caption": caption, "sha256": digest((output / filename).read_bytes())}

    bins = minute_bins(ledgers)
    for column, name, title, unit in (
        (1, "payment-counts", "Eligible payments by UTC minute", "Payments"),
        (2, "xrp-volume", "Delivered XRP by UTC minute", "Delivered XRP"),
    ):
        fig, ax = plt.subplots(figsize=(9, 4.4))
        for i, row in enumerate(bins):
            when = datetime.fromtimestamp(row[0], UTC)
            value = row[column]
            if value is None:
                ax.axvspan(dates.date2num(when), dates.date2num(when) + BIN / 86400,
                           color="#ef4444", alpha=.25)
                continue
            ax.bar(when, value / (1_000_000 if column == 2 else 1), width=BIN / 86400 * .86,
                   align="edge", color="#94a3b8" if i in (0, len(bins) - 1) else "#176780")
        ax.xaxis.set_major_formatter(dates.DateFormatter("%H:%M"))
        ax.set(title=title, xlabel="UTC minute start", ylabel=unit)
        save(fig, name, "Gray bars mark boundary minutes. Red shading marks coverage gaps if present.")

    fig, axes = plt.subplots(1, 2, figsize=(9, 4.4))
    all_payments = [row for _, _, rows in ledgers for row in rows]
    for ax, column, label in zip(axes, (4, 5), ("Delivered amount", "Fee"), strict=True):
        ax.hist([log1p(row[column]) for row in all_payments], bins=35, color="#176780")
        ax.set(title=label, xlabel="ln(1 + drops)", ylabel="Payments")
    save(fig, "amount-fee", "Histograms use 35 equal-width bins on the transformed scale.")

    if full:
        fig, axes = plt.subplots(1, 3, figsize=(10, 4.5))
        for ax, column, label in zip(axes, (3, 18, 19),
                                    ("ln(1 + sender outgoing count)",
                                     "ln(1 + prior directed edge count)",
                                     "Sender outgoing concentration"), strict=True):
            ax.hist([row[-1][column] for row in full], bins=25, color="#176780")
            ax.set(xlabel=label, ylabel="Payments")
        fig.suptitle("Earlier-ledger features")
        save(fig, "history-features",
             f"Complete 10-minute history only, n={len(full):,}. Prior activity is limited to eligible payments.")

    sizes, edges = graph_data(ledgers)
    layout_name = None
    layout_seed = None
    if edges:
        graph = nx.DiGraph()
        graph.add_nodes_from(range(len(sizes)))
        graph.add_weighted_edges_from(edges)
        frozen_pilot = report["snapshot_sha256"] == PILOT_SNAPSHOT and len(sizes) == len(PILOT_LAYOUT)
        fig, ax = plt.subplots(figsize=(11, 7) if frozen_pilot else (9, 6))
        if frozen_pilot:
            layout = dict(enumerate(PILOT_LAYOUT))
            layout_name = "frozen-pilot"
        else:
            layout = nx.spring_layout(graph, seed=SEED)
            layout_name, layout_seed = "spring", SEED
        node_areas = [35 + 12 * log1p(n) ** 2 for n in sizes]
        nx.draw_networkx_nodes(graph, layout, node_size=node_areas, node_color="#176780", ax=ax)
        nx.draw_networkx_edges(graph, layout, width=[.5 + .5 * log1p(graph[u][v]["weight"])
                                                    for u, v in graph.edges],
                               node_size=node_areas, arrowsize=9 if frozen_pilot else 12,
                               connectionstyle="arc3,rad=0" if frozen_pilot else "arc3,rad=0.15",
                               ax=ax)
        ax.set_title("Directed payments among the most active accounts")
        ax.set_axis_off()
        save(fig, "directed-network",
             f"Full pilot slice, top {len(sizes)} by incident payments, {len(edges)} induced edges. "
             "Node area and edge width grow with activity.")
    # Bind the render to the resolved environment and the analysis inputs.
    dump(output / "figure-metadata.json", {
        "snapshot_sha256": report["snapshot_sha256"], "manifest_sha256": report["manifest_sha256"],
        "git_revision": report["git_revision"], "code_sha256": report["code_sha256"],
        "command_arguments": report["command_arguments"],
        "environment": report["environment"], "matplotlib": matplotlib.__version__,
        "networkx": nx.__version__, "bin_seconds": BIN, "amount_histogram_bins": 35,
        "feature_histogram_bins": 25, "graph_layout": layout_name, "layout_seed": layout_seed,
        "graph_max_nodes": MAX_NODES,
        "graph_slice": report["range"], "graph_selection": "incident payment count descending, address ascending",
        "graph_edges": len(edges), "graph_nodes": len(sizes), "files": files,
    })

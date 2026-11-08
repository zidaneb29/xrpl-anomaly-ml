"""Verify and summarize the locally staged training snapshot."""
import argparse
import csv
import json
import platform
import sqlite3
import time
from collections import Counter
from contextlib import closing
from hashlib import sha256
from pathlib import Path

from .baseline import alert_cutoff, budget_summary
from .expansion import FROZEN_DIGEST, NEXT_ROOT, PLAN, ROOT, development_plan, validate_plan
from .features import FEATURES, SCHEMA_VERSION, WINDOW, features
from .pilot import digest, dump
from .storage import connect, ingest, replay


def scored_features(ledgers, start):
    # Each invocation starts from a fresh block-local history.
    for row in features(ledgers):
        if start <= row[3] < start + 1800:
            if not row[4]:
                raise ValueError("scoring ledger lacks complete earlier history")
            yield row


def report(path=PLAN, root=ROOT, *, figures=False, development=False, next_root=NEXT_ROOT,
           output=None, processed=Path("data/processed")):
    if development:
        blocks = development_plan(path)
        plan_digest = FROZEN_DIGEST
    else:
        plan_body = path.read_bytes()
        plan = json.loads(plan_body)
        validate_plan(plan)
        blocks = plan["blocks"][:2]
        plan_digest = digest(plan_body)
    previous_accounts, previous_edges = set(), set()
    results = []
    for number, block in enumerate(blocks, 1):
        directory = (root if number < 3 else next_root) / f"block-{number:02d}"
        manifest_path = directory / "manifest.json"
        if not manifest_path.is_file():
            if development:
                raise ValueError(f"missing manifest for block {number}")
            continue
        manifest_body = manifest_path.read_bytes()
        manifest = json.loads(manifest_body)
        config = manifest["configuration"]
        if (config["plan_sha256"] != plan_digest or config["block"] != number
                or config["range"] != [block["headers"][0][0], block["headers"][-2][0]]
                or manifest["configuration_digest"] != digest(json.dumps(config, sort_keys=True).encode())):
            raise ValueError("manifest is from another sampling plan")
        if development and (manifest["gaps"] or manifest["errors"]):
            raise ValueError(f"incomplete block {number}")
        db_prefix = "phase3b2" if development else "phase3b"
        db_path = processed / f"{db_prefix}-block-{number:02d}.sqlite"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        with closing(connect(db_path)) as db:
            ingest(db, directory)
            ledger_count, = db.execute("SELECT COUNT(*) FROM ledger").fetchone()
            if development:
                low, high = config["range"]
                if ledger_count != high - low + 1:
                    raise ValueError(f"incomplete ledger range for block {number}")
                for index, close, identity in (block["headers"][i] for i in (0, 3, 4)):
                    actual = db.execute("SELECT close_unix, hash FROM ledger WHERE idx=?",
                                        (index,)).fetchone()
                    if actual != (close, identity):
                        raise ValueError(f"frozen boundary mismatch in block {number}")
            if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ValueError("SQLite integrity check failed")
            if db.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("SQLite foreign key check failed")
            if db.execute("""SELECT 1 FROM payment
                             WHERE typeof(amount) != 'integer' OR typeof(fee) != 'integer'
                             LIMIT 1""").fetchone():
                raise ValueError("SQLite failed to preserve integer drops")
            indexes = db.execute("SELECT idx, hash, parent, close_unix FROM ledger ORDER BY idx")
            previous = None
            for index, identity, parent, close in indexes:
                if previous and (index != previous[0] + 1 or parent != previous[1]
                                 or close <= previous[2]):
                    raise ValueError("broken parent chain in staged database")
                previous = index, identity, close
            if not manifest["gaps"]:
                low, high = config["range"]
                expected_checks = {str(index) for index in (low, (low + high) // 2, high)}
                if (set(manifest["cross_checks"]) != expected_checks
                        or any(identity != manifest["ledgers"][index]["ledger_hash"]
                               for index, identity in manifest["cross_checks"].items())):
                    raise ValueError("complete block lacks matching independent checks")
            ingest_seconds = time.monotonic() - started
            started = time.monotonic()
            start = block["start"]
            senders, receivers, edges = Counter(), Counter(), Counter()
            drops = total_payments = 0
            for _, close, rows in replay(db):
                for _, _, sender, receiver, amount, _ in rows:
                    total_payments += 1
                    drops += amount
                    if start <= close < start + 1800:
                        senders[sender] += 1
                        receivers[receiver] += 1
                        edges[sender, receiver] += 1
            scored = Counter()
            feature_hash = sha256()
            names = ("sender_unseen", "receiver_unseen", "log_prior_edge_count")
            si, ri, ei = (FEATURES.index(name) for name in names)
            for row in scored_features(replay(db), start):
                values = row[-1]
                scored["rows"] += 1
                scored["sender_seen"] += values[si] == 0
                scored["receiver_seen"] += values[ri] == 0
                scored["prior_edge"] += values[ei] > 0
                feature_hash.update((json.dumps(row, separators=(",", ":")) + "\n").encode())
            if scored["rows"] != sum(edges.values()):
                raise ValueError("feature replay lost scoring observations")
        items = [item for key, item in manifest["ledgers"].items() if key not in manifest["errors"]]
        snapshot = [(index, manifest["ledgers"][str(index)]["sha256"])
                    for index in range(config["range"][0], config["range"][1] + 1)
                    if str(index) in manifest["ledgers"] and str(index) not in manifest["errors"]]
        if len(items) != ledger_count or sum(item["eligible"] for item in items) != total_payments:
            raise ValueError("SQLite totals differ from the verified raw cache")
        exclusions = Counter()
        for item in items:
            exclusions.update(item["exclusions"])
        if total_payments + sum(exclusions.values()) != sum(item["total"] for item in items):
            raise ValueError("normalization accounting does not balance")
        accounts = set(senders) | set(receivers)
        results.append({
            "block": number, "complete": not manifest["gaps"], "ledgers": ledger_count,
            "observed_range": manifest["observed_range"], "missing_ledgers": len(manifest["gaps"]),
            "eligible_payments": total_payments, "exclusions": dict(exclusions),
            "cross_checks": manifest["cross_checks"], "amount_drops": drops,
            "decoded_cached_bytes": sum(item["bytes"] for item in items),
            "gzip_bytes": sum(p.stat().st_size for p in directory.glob("*.json.gz")),
            "sqlite_bytes": db_path.stat().st_size, "manifest_sha256": digest(manifest_body),
            "snapshot_sha256": digest(json.dumps(snapshot).encode()),
            "feature_sha256": feature_hash.hexdigest(), "feature_counts": dict(scored),
            "distinct_accounts": len(accounts), "distinct_edges": len(edges),
            "repeat_senders": sum(count > 1 for count in senders.values()),
            "repeat_receivers": sum(count > 1 for count in receivers.values()),
            "repeat_edges": sum(count > 1 for count in edges.values()),
            "accounts_in_earlier_blocks": len(accounts & previous_accounts),
            "edges_in_earlier_blocks": len(set(edges) & previous_edges),
            "ingest_seconds": ingest_seconds, "replay_seconds": time.monotonic() - started,
        })
        if development:
            results[-1].update(role=block["role"], start=start,
                               total_transactions=sum(item["total"] for item in items),
                               acquisition_runs=manifest["runs"],
                               structurally_invalid_ledgers=len(manifest["errors"]),
                               invalid_payment_records=sum(
                                   exclusions[name] for name in ("invalid_or_same_account",
                                                                  "invalid_amount_fee_or_flags")))
        previous_accounts.update(accounts)
        previous_edges.update(edges)
    if output is None:
        output = Path("reports/generated/phase3b2" if development else
                      "reports/generated/phase3b-training")
    output.mkdir(parents=True, exist_ok=True)
    source_dir = Path(__file__).parent
    budget_path = (next_root if development else root) / "budget.json"
    dump(output / "summary.json", {"plan_sha256": plan_digest, "python": platform.python_version(),
                                   "platform": platform.platform(),
                                   "sqlite": sqlite3.sqlite_version,
                                   "feature_schema_version": SCHEMA_VERSION, "window_seconds": WINDOW,
                                   "acquisition": json.loads(budget_path.read_bytes())
                                   if budget_path.exists() else None,
                                   "source_sha256": {p.name: digest(p.read_bytes())
                                                     for p in sorted(source_dir.glob("*.py"))},
                                   "blocks": results})
    if figures:
        render(output, results)
    return results


def render(output, blocks):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    pilot = Path("reports/generated/phase3a-pilot-108187602")
    feature_path, score_path = pilot / "features.csv", pilot / "scores.csv"
    with feature_path.open(newline="") as stream:
        values = [float(row["sender_log_in_drops"]) for row in csv.DictReader(stream)
                  if 108187494 <= int(row["ledger_index"]) <= 108187547 and row["complete"] == "1"]
    with score_path.open(newline="") as stream:
        calibration = [(float(row["score"]), row["hash"]) for row in csv.DictReader(stream)
                       if row["split"] == "calibration"]
    cutoff = alert_cutoff(calibration)
    counts = budget_summary(calibration, cutoff)
    positive = sorted(value for value in values if value > 0)
    fig, (sparse, ties) = plt.subplots(1, 2, figsize=(9, 3.5), layout="constrained")
    sparse.step(positive, [(i + 1) / len(positive) for i in range(len(positive))], where="post")
    sparse.set(xlabel="log(1 + prior incoming drops)", ylabel="Conditional cumulative fraction",
               title=f"Pilot training, {len(values) - len(positive)}/{len(values)} zeros excluded")
    ties.bar(["Above cutoff", "Alerted ties", "Other ties"],
             [counts["above_score"], counts["alerted_ties"],
              counts["tied_score"] - counts["alerted_ties"]])
    ties.set(ylabel="Calibration observations", title=f"Pilot score cutoff {cutoff[0]:.4f}")
    fig.savefig(output / "pilot-sparsity-and-ties.png", dpi=150)
    plt.close(fig)
    names = ["pilot-sparsity-and-ties.png"]
    if blocks and all(b["complete"] and b["feature_counts"].get("rows") for b in blocks):
        fig, axes = plt.subplots(1, len(blocks), figsize=(8, 3.5), squeeze=False, layout="constrained")
        for ax, block in zip(axes[0], blocks, strict=True):
            metrics = block["feature_counts"]
            ax.bar(["Sender", "Receiver", "Directed edge"],
                   [metrics[k] / metrics["rows"] for k in ("sender_seen", "receiver_seen", "prior_edge")])
            ax.set(ylim=(0, 1), ylabel="Fraction seen in preceding 10 minutes",
                   title=f"Training block {block['block']} (n={metrics['rows']:,})")
        names.append("training-recurrence.png")
        fig.savefig(output / names[-1], dpi=150)
        plt.close(fig)
    dump(output / "figure-metadata.json", {
        "matplotlib": matplotlib.__version__,
        "inputs": {str(p): digest(p.read_bytes())
                   for p in (feature_path, score_path, output / "summary.json")},
        "source_sha256": digest(Path(__file__).read_bytes()),
        "outputs": {name: digest((output / name).read_bytes()) for name in names},
        "calibration_counts": counts,
        "command": "python -B -m xrpl_anomaly.expansion_report --figures",
    })


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--figures", action="store_true")
    report(figures=parser.parse_args().figures)

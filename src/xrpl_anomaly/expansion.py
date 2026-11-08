"""Freeze validated UTC boundaries and stage the first two training blocks."""
import argparse
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .ledger import RIPPLE_EPOCH, digest_id, header, result, uint
from .pilot import MIB, PRIMARY, SECONDARY, SETTINGS, Client, acquire_range, digest, dump

PLAN = Path("docs/phase3b-blocks.json")
ROOT = Path("data/raw/phase3b-training")
MAX_ATTEMPTS = 1500
MAX_BYTES = 1024 * MIB
MAX_SECONDS = 3600
NEXT_ROOT = Path("data/raw/phase3b2")
NEXT_NUMBERS = range(3, 7)
NEXT_LIMITS = (3000, 2 * 1024 * MIB, 7200)
NEXT_STORAGE = 512 * MIB
FROZEN_DIGEST = "9f483936a72cb36fa4fe08cf61b694aaea7ae417af6fa607be65e766bfa44e24"
WEEK_ZERO = datetime(2026, 9, 21, tzinfo=UTC)
ROLES = ("train", "train", "development", "calibration", "test", "test")


def schedule():
    for week, role in enumerate(ROLES):
        monday = WEEK_ZERO + timedelta(weeks=week)
        for day, hour in ((2, (0, 8, 16)[week % 3]), (5, (16, 0, 8)[week % 3])):
            start = int((monday + timedelta(days=day, hours=hour)).timestamp())
            yield role, start


def validate_plan(plan):
    if plan["schema"] != 1 or (plan["primary"], plan["secondary"]) != (PRIMARY, SECONDARY):
        raise ValueError("unexpected plan schema or endpoint")
    previous = 32569
    for block, (role, start) in zip(plan["blocks"], schedule(), strict=True):
        if (block["role"], block["start"]) != (role, start):
            raise ValueError("block differs from the predeclared schedule")
        anchor, after_anchor, before_start, first, last, after_last = block["headers"]
        for index, close, identity in block["headers"]:
            if type(index) is not int or type(close) is not int:
                raise ValueError("invalid boundary metadata")
            digest_id(identity)
        if not (previous < anchor[0] < after_anchor[0] <= before_start[0] < first[0]
                <= last[0] < after_last[0]):
            raise ValueError("unordered or overlapping ledger ranges")
        for before, after in ((anchor, after_anchor), (before_start, first), (last, after_last)):
            if before[0] + 1 != after[0] or before[1] >= after[1]:
                raise ValueError("nonadjacent or unordered boundary headers")
        if not (anchor[1] <= start - 600 < after_anchor[1]
                and before_start[1] < start <= first[1] <= last[1] < start + 1800 <= after_last[1]):
            raise ValueError("headers do not bracket UTC boundaries")
        for endpoint in (PRIMARY, SECONDARY):
            spans = plan["coverage"][endpoint].split(",")
            if not any(int(low) <= anchor[0] <= last[0] <= int(high)
                       for low, high in (span.split("-") for span in spans)):
                raise ValueError("block falls outside advertised history")
        previous = last[0]


def freeze(path):
    if path.exists():
        raise FileExistsError(path)
    started = time.monotonic()
    client = Client(max_attempts=240, max_bytes=16 * MIB, end=started + 900)
    coverage = {}
    for endpoint in (PRIMARY, SECONDARY):
        info = result(client.rpc(endpoint, "server_info", {"api_version": 2}))["info"]
        if info.get("network_id") != 0:
            raise ValueError("expected Mainnet network ID")
        coverage[endpoint] = info["complete_ledgers"]

    def fetch(index):
        body = client.get(PRIMARY, index, False)
        ledger, identity = header(result(body), index)
        return [index, RIPPLE_EPOCH + uint(ledger["close_time"]), identity]

    def bracket(second):
        reply = result(client.rpc(PRIMARY, "ledger_index", {
            "api_version": 2, "date": datetime.fromtimestamp(second, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}))
        index = uint(reply["ledger_index"])
        left = fetch(index)
        if reply.get("validated") is not True or digest_id(reply["ledger_hash"]) != left[2]:
            raise ValueError("ledger_index lookup disagrees with validated header")
        for _ in range(6):
            if left[1] > second:
                left = fetch(left[0] - 1)
                continue
            right = fetch(left[0] + 1)
            if right[1] > second:
                return left, right
            left = right
        raise ValueError("ledger_index lookup failed to bracket close time")

    blocks = []
    for role, start in schedule():
        bounds = [*bracket(start - 600), *bracket(start - 1), *bracket(start + 1799)]
        blocks.append({"role": role, "start": start, "headers": bounds})
        print(f"{datetime.fromtimestamp(start, UTC).isoformat()} {bounds[0][0]}–{bounds[-2][0]}",
              flush=True)
    plan = {"schema": 1, "primary": PRIMARY, "secondary": SECONDARY,
            "coverage": coverage, "blocks": blocks, "frozen_utc": datetime.now(UTC).isoformat(),
            "probes": {"attempts": client.attempts, "decoded_bytes": client.observed_bytes,
                       "budget_bytes": client.bytes, "seconds": time.monotonic() - started}}
    validate_plan(plan)
    dump(path, plan)


def acquire_initial(path, root):
    import msvcrt

    body = path.read_bytes()
    plan = json.loads(body)
    validate_plan(plan)
    blocks = plan["blocks"][:2]
    minimum = sum(b["headers"][-2][0] - b["headers"][0][0] + 4 for b in blocks)
    if minimum > MAX_ATTEMPTS:
        raise ValueError("two blocks require more attempts than the stage allows")
    root.mkdir(parents=True, exist_ok=True)
    with (root / "stage.lock").open("a+b") as lock:
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        acquire_locked(root, blocks, digest(body))


def development_plan(path):
    return frozen_plan(path)[:6]


def frozen_plan(path):
    # Accept Git's Windows line-ending conversion, but no content changes.
    body = path.read_bytes().replace(b"\r\n", b"\n")
    if digest(body) != FROZEN_DIGEST:
        raise ValueError("expected the original frozen manifest")
    plan = json.loads(body)
    validate_plan(plan)
    return plan["blocks"]


def acquire_next(path=PLAN, root=NEXT_ROOT):
    acquire_stage(root, development_plan(path)[2:], 3, NEXT_LIMITS, NEXT_STORAGE)


def acquire_stage(root, blocks, first_number, limits, storage):
    import msvcrt
    import shutil

    minimum = sum(b["headers"][-2][0] - b["headers"][0][0] + 4 for b in blocks)
    if minimum > limits[0]:
        raise ValueError("frozen ranges exceed the request ceiling")
    root.mkdir(parents=True, exist_ok=True)
    with (root / "stage.lock").open("a+b") as lock:
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        existing = sum(p.stat().st_size for p in root.rglob("*") if p.is_file())
        if shutil.disk_usage(root).free < storage - existing + 64 * MIB:
            raise RuntimeError("insufficient free space for the bounded stage")
        # Leave 16 MiB for manifests and their atomic replacements.
        remaining = storage - 16 * MIB - existing

        def reserve_cache(size):
            nonlocal remaining
            if size > remaining:
                raise RuntimeError("stage storage ceiling reached")
            remaining -= size

        acquire_locked(root, blocks, FROZEN_DIGEST, first_number=first_number,
                       limits=limits, reserve_cache=reserve_cache)


def acquire_locked(root, blocks, plan_digest, *, first_number=1,
                   limits=(MAX_ATTEMPTS, MAX_BYTES, MAX_SECONDS), reserve_cache=None):
    max_attempts, max_bytes, max_seconds = limits
    budget = root / "budget.json"
    state = json.loads(budget.read_bytes()) if budget.exists() else {
        "plan_sha256": plan_digest, "attempts": 0, "budget_bytes": 0, "observed_bytes": 0,
        "retries": 0, "seconds": 0}
    if state["plan_sha256"] != plan_digest:
        raise ValueError("existing stage belongs to a different frozen plan")
    started = time.monotonic()
    prior_seconds = state["seconds"]
    if state.get("active"):
        prior_seconds += max(0, time.time() - state["charged_through_unix"])
    if prior_seconds >= max_seconds:
        raise RuntimeError("acquisition time budget exhausted")
    client = Client(max_attempts=max_attempts, max_bytes=max_bytes,
                    end=started + max_seconds - prior_seconds)
    client.attempts = state["attempts"]
    client.bytes = state["budget_bytes"]
    client.observed_bytes = state["observed_bytes"]
    client.retries = state["retries"]

    def checkpoint(until, active=True):
        until = min(until, client.end)
        dump(budget, dict(plan_sha256=plan_digest, attempts=client.attempts,
                          budget_bytes=client.bytes, observed_bytes=client.observed_bytes,
                          retries=client.retries,
                          seconds=prior_seconds + until - started, active=active,
                          charged_through_unix=time.time() + until - time.monotonic()))

    client.checkpoint = checkpoint
    checkpoint(started)
    try:
        for number, block in enumerate(blocks, first_number):
            anchor, _, _, first, last, _ = block["headers"]
            start, end = anchor[0], last[0]
            config = {"schema": 2, "range": [start, end], "endpoint": PRIMARY,
                      "cross_endpoint": SECONDARY, "settings": SETTINGS,
                      "plan_sha256": plan_digest, "block": number}
            expected = {index: (close, identity) for index, close, identity in (anchor, first, last)}
            acquire_range(root / f"block-{number:02d}", config, client,
                          {start, (start + end) // 2, end}, expected, reserve_cache=reserve_cache)
    finally:
        checkpoint(time.monotonic(), active=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["freeze", "acquire", "acquire-next"])
    args = parser.parse_args()
    if args.action == "freeze":
        freeze(PLAN)
    elif args.action == "acquire":
        acquire_initial(PLAN, ROOT)
    else:
        acquire_next()

"""Bounded JSON-RPC acquisition with immutable, digest-addressed cache bodies."""
import argparse
import gzip
import json
import random
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from .ledger import header, parse, result

PRIMARY = "https://s2.ripple.com:51234/"
SECONDARY = "https://xrplcluster.com/"
MIB = 1024**2
SETTINGS = {"api_version": 2, "transactions": True, "expand": True,
            "binary": False, "full": False}


class Client:
    def __init__(self, *, max_attempts=320, max_bytes=256 * MIB,
                 end=float("inf"), timeout=20):
        self.attempts = self.bytes = self.retries = 0
        self.observed_bytes = 0
        self.max_attempts = max_attempts
        self.max_bytes = max_bytes
        self.end = end
        self.timeout = timeout
        self.next_start = 0
        self.checkpoint = None

    def exchange(self, endpoint, payload, limit, deadline):
        worker = Path(__file__).with_name("http_worker.py")
        spool = Path("artifacts/http-spool")
        spool.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=spool) as output, tempfile.TemporaryFile(dir=spool) as status:
            timeout = deadline - time.monotonic()
            if timeout <= 0:
                raise RuntimeError("acquisition time budget exhausted")
            # Reserve first so cancellation and unreported reads cannot undercount.
            self.bytes += limit
            if self.checkpoint:
                self.checkpoint(deadline)
            with subprocess.Popen([sys.executable, "-I", "-B", str(worker), endpoint,
                                   payload, str(limit), str(timeout)],
                                  stdin=subprocess.DEVNULL, stdout=output, stderr=status) as process:
                try:
                    process.wait(timeout=max(0, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait()
            output.seek(0)
            body = output.read(limit)
            self.observed_bytes += len(body)
            if time.monotonic() >= deadline:
                return ["retry", "HTTP wall-clock deadline exceeded"], b""
            if process.returncode:
                return ["retry", f"HTTP worker exited with {process.returncode}"], b""
            status.seek(0)
            reply = json.load(status)
            if reply[0] != "retry":
                self.bytes -= limit - len(body)
            return reply, body

    def get(self, endpoint, index, expanded):
        settings = SETTINGS if expanded else {"api_version": 2}
        return self.rpc(endpoint, "ledger", dict(settings, ledger_index=index))

    def rpc(self, endpoint, method, settings):
        payload = json.dumps({"method": method, "params": [settings]})
        for attempt in range(3):
            if self.attempts >= self.max_attempts or self.bytes >= self.max_bytes:
                raise RuntimeError(f"acquisition budget exhausted for {method}")
            delay = max(0, self.next_start - time.monotonic())
            if time.monotonic() + delay >= self.end:
                raise RuntimeError("acquisition time budget exhausted")
            time.sleep(delay)
            self.next_start = time.monotonic() + 1
            deadline = min(time.monotonic() + self.timeout, self.end)
            limit = min(8 * MIB, self.max_bytes - self.bytes)
            self.attempts += 1
            self.retries += int(attempt > 0)
            try:
                (kind, *detail), body = self.exchange(endpoint, payload, limit, deadline)
            finally:
                if self.checkpoint:
                    self.checkpoint(time.monotonic())
            retry_after = 0
            if kind == "ok":
                document = json.loads(body)
                reply = document["result"]
                if reply.get("warning") == "load" or document.get("warning") == "load":
                    self.next_start = time.monotonic() + 5
                if reply.get("error") not in {"tooBusy", "slowDown", "overloaded"}:
                    result(body)
                    return body
                error = reply["error"]
            elif kind == "http":
                code, hint = detail
                if code not in {429, 500, 502, 503, 504}:
                    raise RuntimeError(f"HTTP {code} from {endpoint}")
                if not hint.isdecimal() or int(hint) > 30:
                    raise RuntimeError("server requested a longer retry delay")
                retry_after = int(hint)
                error = f"HTTP {code}"
            elif kind == "limit":
                raise RuntimeError("response byte budget reached")
            elif kind == "retry":
                error, = detail
            else:
                raise ValueError(detail[0])
            if attempt == 2:
                raise RuntimeError(f"persistent transport failure for {method}: {error}")
            self.next_start = max(self.next_start, time.monotonic() +
                                  max(retry_after, 2**attempt + random.random()))


def digest(body):
    return sha256(body).hexdigest()


def write_atomic(path, data):
    staging = path.with_suffix(path.suffix + ".tmp")
    staging.write_bytes(data)
    staging.replace(path)


def dump(path, value):
    write_atomic(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode())


def acquire(directory, tip):
    if not 32570 + 255 <= tip <= 2**32 - 1:
        raise ValueError("pilot range is outside available Mainnet ledger indexes")
    start = tip - 255
    config = {"schema": 1, "range": [start, tip], "endpoint": PRIMARY,
              "cross_endpoint": SECONDARY, "settings": SETTINGS}
    acquire_range(directory, config, Client(), {start, start + 128, tip})


def acquire_range(directory, config, client, cross_indexes, expected=None):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "manifest.json"
    start, tip = config["range"]
    manifest = json.loads(path.read_bytes()) if path.exists() else {
        "configuration": config, "configuration_digest": digest(json.dumps(config, sort_keys=True).encode()),
        "ledgers": {}, "cross_checks": {}, "errors": {}}
    if manifest["configuration"] != config:
        raise ValueError("snapshot configuration differs")
    before = client.attempts, client.bytes, client.retries, client.observed_bytes
    run_start = time.monotonic()
    previous = None
    all_hashes = set()
    try:
        for index in range(start, tip + 1):
            if time.monotonic() >= client.end:
                raise RuntimeError("acquisition time budget exhausted")
            key = str(index)
            body = None
            try:
                item = manifest["ledgers"].get(key)
                if item and (directory / (item["sha256"] + ".json.gz")).is_file():
                    body = cached(directory, item)
                    elapsed = item["latency_seconds"]
                    retrieved = item["retrieved_utc"]
                else:
                    started = time.monotonic()
                    body = client.get(config["endpoint"], index, True)
                    elapsed = time.monotonic() - started
                    retrieved = datetime.now(UTC).isoformat()
                ledger = parse(body, index)
                if expected and index in expected and (ledger.close, ledger.hash) != expected[index]:
                    raise ValueError("ledger differs from frozen boundary header")
                if previous and (previous.hash != ledger.parent or previous.close >= ledger.close):
                    raise ValueError("parent hash or close time conflict")
                if all_hashes.intersection(ledger.transaction_ids):
                    raise ValueError("transaction hash repeated across ledgers")
                if index in cross_indexes:
                    if key not in manifest["cross_checks"]:
                        cross = client.get(config["cross_endpoint"], index, False)
                        _, alternate = header(result(cross), index)
                        if alternate != ledger.hash:
                            raise ValueError("secondary hash conflict")
                        manifest["cross_checks"][key] = alternate
                    elif manifest["cross_checks"][key] != ledger.hash:
                        raise ValueError("cached secondary hash conflict")
                checksum = digest(body)
                if item and checksum != item["sha256"]:
                    raise ValueError("replacement body conflicts with the immutable snapshot")
                cache = directory / (checksum + ".json.gz")
                if not cache.exists():
                    write_atomic(cache, gzip.compress(body, mtime=0))
                elif not item:
                    cached(directory, {"sha256": checksum, "bytes": len(body)})
                manifest["ledgers"][key] = {
                    "sha256": checksum, "bytes": len(body), "ledger_hash": ledger.hash,
                    "parent_hash": ledger.parent, "close_unix": ledger.close, "total": ledger.total,
                    "eligible": len(ledger.payments), "exclusions": ledger.exclusions,
                    "retrieved_utc": retrieved, "latency_seconds": elapsed}
                manifest["errors"].pop(key, None)
                previous = ledger
                all_hashes.update(ledger.transaction_ids)
            except Exception as exc:
                manifest["errors"][key] = f"{type(exc).__name__}: {exc}"
                if body is not None:
                    quarantine = directory / "quarantine"
                    quarantine.mkdir(exist_ok=True)
                    write_atomic(quarantine / f"{index}-{digest(body)}.json.gz",
                                 gzip.compress(body, mtime=0))
                raise
            finally:
                manifest["observed_range"] = [start, previous.index] if previous else None
                manifest["gaps"] = [i for i in range(start, tip + 1)
                                    if str(i) not in manifest["ledgers"] or str(i) in manifest["errors"]]
                dump(path, manifest)
            if (index - start + 1) % 32 == 0:
                print(f"Verified {index - start + 1}/{tip - start + 1} ledgers", flush=True)
    finally:
        manifest.setdefault("runs", []).append({
            "finished_utc": datetime.now(UTC).isoformat(), "attempts": client.attempts - before[0],
            "decoded_bytes": client.observed_bytes - before[3],
            "budget_bytes": client.bytes - before[1], "retries": client.retries - before[2],
            "elapsed_seconds": time.monotonic() - run_start})
        dump(path, manifest)


def cached(directory, item):
    checksum = item["sha256"]
    if len(checksum) != 64 or any(c not in "0123456789abcdef" for c in checksum):
        raise ValueError("invalid cache digest")
    with gzip.open(directory / (checksum + ".json.gz"), "rb") as stream:
        body = stream.read(8 * MIB + 1)
    if len(body) > 8 * MIB or digest(body) != checksum or len(body) != item["bytes"]:
        raise ValueError("cache integrity check failed")
    return body


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("tip", type=int)
    args = parser.parse_args()
    acquire(args.directory, args.tip)

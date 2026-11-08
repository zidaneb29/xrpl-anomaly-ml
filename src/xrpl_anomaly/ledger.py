"""Validate expanded XRPL ledgers and normalize eligible payments."""
import json
import re
from collections import Counter
from dataclasses import dataclass
from hashlib import sha256

RIPPLE_EPOCH = 946684800
BASE58 = "rpshnaf39wBUDNEGHJKLM4PQRST7VWXYZ2bcdeCg65jkm8oFqi1tuvAxyz"


def digest_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise ValueError("invalid hash")
    return value.upper()


def uint(value):
    if type(value) is int and 0 <= value <= 2**32 - 1:
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,10}", value):
        return uint(int(value))
    raise ValueError("invalid unsigned integer")


def drops(value, minimum):
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,19}", value):
        number = int(value)
        if minimum <= number <= 2**63 - 1:
            return number
    raise ValueError("invalid integer drops")


def classic(value):
    if not isinstance(value, str) or not 25 <= len(value) <= 35 or not value.startswith("r"):
        return False
    number = 0
    for character in value:
        digit = BASE58.find(character)
        if digit < 0:
            return False
        number = number * 58 + digit
    decoded = b"\0" * (len(value) - len(value.lstrip("r")))
    decoded += number.to_bytes((number.bit_length() + 7) // 8, "big")
    return len(decoded) == 25 and sha256(sha256(decoded[:-4]).digest()).digest()[:4] == decoded[-4:]


@dataclass(frozen=True)
class Ledger:
    index: int
    hash: str
    parent: str
    close: int
    total: int
    exclusions: dict
    payments: tuple
    transaction_ids: tuple


def result(body):
    reply = json.loads(body)["result"]
    if reply.get("status") != "success":
        raise ValueError(str(reply.get("error", "unsuccessful RPC response")))
    return reply


def header(reply, expected):
    ledger = reply["ledger"]
    index = uint(reply["ledger_index"])
    identity = digest_id(reply["ledger_hash"])
    if (reply.get("validated") is not True or index != expected
            or uint(ledger["ledger_index"]) != index
            or digest_id(ledger["ledger_hash"]) != identity):
        raise ValueError(f"unvalidated or inconsistent ledger {expected}")
    return ledger, identity


def payment(tx, meta):
    if tx["TransactionType"] != "Payment":
        return "other_type", None
    if meta["TransactionResult"] != "tesSUCCESS":
        return "failed_payment", None
    if isinstance(tx.get("DeliverMax", tx.get("Amount")), dict) or isinstance(meta.get("delivered_amount"), dict):
        return "token_payment", None
    try:
        flags = uint(tx.get("Flags", 0))
        if flags & 0x20000 or any(key in tx for key in ("Paths", "SendMax", "DeliverMin")):
            return "routed_or_partial", None
        sender, receiver = tx.get("Account"), tx.get("Destination")
        if sender == receiver or not classic(sender) or not classic(receiver):
            return "invalid_or_same_account", None
        drops(tx.get("DeliverMax", tx.get("Amount")), 1)
        return None, (sender, receiver, drops(meta.get("delivered_amount"), 1), drops(tx.get("Fee"), 0))
    except ValueError:
        return "invalid_amount_fee_or_flags", None


def parse(body, expected):
    ledger, identity = header(result(body), expected)
    transactions = ledger["transactions"]
    if not isinstance(transactions, list):
        raise ValueError("expected expanded transaction array")
    counts, rows, hashes, positions = Counter(), [], set(), set()
    for entry in transactions:
        tx = entry.get("tx_json", entry)
        meta = entry.get("meta", entry.get("metaData"))
        tx_hash = digest_id(entry["hash"])
        position = uint(meta["TransactionIndex"])
        if (tx_hash in hashes or position in positions
                or not isinstance(tx["TransactionType"], str)
                or not isinstance(meta["TransactionResult"], str)):
            raise ValueError("duplicate transaction or invalid required fields")
        hashes.add(tx_hash)
        positions.add(position)
        reason, fields = payment(tx, meta)
        if reason:
            counts[reason] += 1
        else:
            rows.append((position, tx_hash, *fields))
    if positions != set(range(len(transactions))):
        raise ValueError("transaction index gap")
    return Ledger(expected, identity, digest_id(ledger["parent_hash"]),
                  RIPPLE_EPOCH + uint(ledger["close_time"]), len(transactions),
                  dict(counts), tuple(sorted(rows)), tuple(sorted(hashes)))

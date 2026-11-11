"""Atomic SQLite ingestion and ordered replay."""
import json
import sqlite3
from pathlib import Path

from .ledger import parse
from .pilot import cached

SCHEMA = """
CREATE TABLE IF NOT EXISTS ledger (
    idx INTEGER PRIMARY KEY,
    hash TEXT NOT NULL UNIQUE,
    parent TEXT NOT NULL,
    close_unix INTEGER NOT NULL,
    digest TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS payment (
    ledger_idx INTEGER NOT NULL REFERENCES ledger(idx),
    position INTEGER NOT NULL,
    hash TEXT NOT NULL UNIQUE,
    sender TEXT NOT NULL,
    receiver TEXT NOT NULL,
    amount INTEGER NOT NULL CHECK (amount > 0),
    fee INTEGER NOT NULL CHECK (fee >= 0),
    PRIMARY KEY (ledger_idx, position)
);
"""


def connect(path):
    db = sqlite3.connect(path)
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(SCHEMA)
    return db


def store(db, ledger, checksum):
    fields = (ledger.index, ledger.hash, ledger.parent, ledger.close, checksum)
    db.execute("BEGIN IMMEDIATE")
    with db:
        existing = db.execute("SELECT * FROM ledger WHERE idx=?", (ledger.index,)).fetchone()
        if existing:
            if existing != fields:
                raise ValueError(f"conflicting ledger {ledger.index}")
            if payment_rows(db, ledger.index) != ledger.payments:
                raise ValueError(f"mismatched normalized payments for ledger {ledger.index}")
            return
        prior = db.execute("SELECT hash, close_unix FROM ledger WHERE idx=?",
                           (ledger.index - 1,)).fetchone()
        later = db.execute("SELECT parent, close_unix FROM ledger WHERE idx=?",
                            (ledger.index + 1,)).fetchone()
        if ((prior and (prior[0] != ledger.parent or prior[1] >= ledger.close))
                or (later and (later[0] != ledger.hash or later[1] <= ledger.close))):
            raise ValueError(f"broken ledger chain at {ledger.index}")
        db.execute("INSERT INTO ledger VALUES (?, ?, ?, ?, ?)", fields)
        db.executemany("INSERT INTO payment VALUES (?, ?, ?, ?, ?, ?, ?)",
                       ((ledger.index, *row) for row in ledger.payments))


def ingest(db, directory):
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_bytes())
    start, end = manifest["configuration"]["range"]
    existing = db.execute("SELECT idx, digest FROM ledger")
    for idx, checksum in existing:
        item = manifest["ledgers"].get(str(idx), {})
        if (not start <= idx <= end or str(idx) in manifest["errors"]
                or item.get("sha256") != checksum):
            raise ValueError("database contains records from a different snapshot")
    for index in range(start, end + 1):
        item = manifest["ledgers"].get(str(index))
        if item and str(index) not in manifest["errors"]:
            ledger = parse(cached(directory, item), index)
            if (ledger.hash != item["ledger_hash"] or ledger.parent != item["parent_hash"]
                    or ledger.close != item["close_unix"] or ledger.total != item["total"]
                    or len(ledger.payments) != item["eligible"] or ledger.exclusions != item["exclusions"]):
                raise ValueError(f"cache and manifest disagree for ledger {index}")
            store(db, ledger, item["sha256"])
    return manifest


def payment_rows(db, index):
    return tuple(db.execute(
        """SELECT position, hash, sender, receiver, amount, fee
           FROM payment WHERE ledger_idx=? ORDER BY position""", (index,)))


def replay(db):
    for index, close in db.execute("SELECT idx, close_unix FROM ledger ORDER BY idx"):
        yield index, close, payment_rows(db, index)

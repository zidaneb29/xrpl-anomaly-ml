"""Offline checks for the Phase 1 source layout and local storage capability."""

import importlib
import sqlite3
import tomllib
import unittest
from contextlib import closing
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FoundationTests(unittest.TestCase):
    def test_source_package_imports_from_workspace(self):
        package = importlib.import_module("xrpl_anomaly")
        expected = ROOT / "src" / "xrpl_anomaly" / "__init__.py"
        self.assertEqual(Path(package.__file__).resolve(), expected)

    def test_project_metadata_declares_no_runtime_dependencies(self):
        with (ROOT / "pyproject.toml").open("rb") as file:
            project = tomllib.load(file)["project"]
        self.assertEqual(project["name"], "xrpl-anomaly-ml")
        self.assertEqual(project["dependencies"], [])

    def test_sqlite_round_trips_integer_drops(self):
        drops = 2**53 + 1
        with closing(sqlite3.connect(":memory:")) as connection:
            connection.execute("CREATE TABLE probe (drops INTEGER NOT NULL) STRICT")
            connection.execute("INSERT INTO probe VALUES (?)", (drops,))
            row = connection.execute("SELECT drops, typeof(drops) FROM probe").fetchone()
        self.assertEqual(row, (drops, "integer"))

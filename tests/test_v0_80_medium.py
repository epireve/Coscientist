"""v0.80 — medium-tier improvements.

  - Plugin pyproject.toml parity (3 plugins).
  - Each MCP server.py defines a `main()` console-script entry.
  - prune_writes_all_dbs sweeps both runs/ and projects/.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests
from lib import skill_persist
from lib.cache import run_db_path
from lib.db_notify import prune_writes_all_dbs


_REPO = Path(__file__).resolve().parents[1]


def _new_run_db(rid: str) -> Path:
    db = run_db_path(rid)
    schema = (_REPO / "lib" / "sqlite_schema.sql").read_text()
    con = sqlite3.connect(db)
    con.executescript(schema)
    con.close()
    from lib.migrations import ensure_current
    ensure_current(db)
    return db


class PluginPyprojectTests(TestCase):
    PLUGINS = (
        "coscientist-retraction-mcp",
        "coscientist-manuscript-mcp",
        "coscientist-graph-query-mcp",
    )

    def test_every_mcp_plugin_has_pyproject(self):
        for name in self.PLUGINS:
            pp = _REPO / "plugin" / name / "pyproject.toml"
            self.assertTrue(pp.exists(),
                            f"missing pyproject.toml for {name}")

    def test_pyproject_has_console_script(self):
        for name in self.PLUGINS:
            pp = _REPO / "plugin" / name / "pyproject.toml"
            text = pp.read_text()
            self.assertIn("[project.scripts]", text,
                          f"{name} pyproject missing scripts section")
            # Console script name follows the plugin name.
            self.assertIn(f"{name} = ", text,
                          f"{name} pyproject missing console-script entry")

    def test_pyproject_pins_mcp(self):
        for name in self.PLUGINS:
            pp = _REPO / "plugin" / name / "pyproject.toml"
            self.assertIn("mcp>=1.0", pp.read_text(),
                          f"{name} pyproject doesn't pin mcp dep")

    def test_version_matches_plugin_json(self):
        for name in self.PLUGINS:
            pp = _REPO / "plugin" / name / "pyproject.toml"
            pj = _REPO / "plugin" / name / ".claude-plugin" / "plugin.json"
            pj_data = json.loads(pj.read_text())
            self.assertIn(f'version = "{pj_data["version"]}"',
                          pp.read_text(),
                          f"{name} pyproject version != plugin.json")


class ServerMainEntryTests(TestCase):
    """Each MCP server.py must expose `def main()`."""

    SERVERS = (
        _REPO / "mcp" / "retraction-mcp" / "server.py",
        _REPO / "mcp" / "manuscript-mcp" / "server.py",
        _REPO / "mcp" / "graph-query-mcp" / "server.py",
    )

    def test_each_server_has_main(self):
        for path in self.SERVERS:
            self.assertTrue(path.exists())
            text = path.read_text()
            self.assertIn("def main(", text,
                          f"{path} missing main() entry")

    def test_plugin_servers_match_source_after_main_addition(self):
        """Resync verification — plugin/<...>/server/server.py must
        byte-match mcp/<...>/server.py after the v0.80 main() add."""
        pairs = (
            (_REPO / "mcp" / "retraction-mcp" / "server.py",
             _REPO / "plugin" / "coscientist-retraction-mcp" / "server" / "server.py"),
            (_REPO / "mcp" / "manuscript-mcp" / "server.py",
             _REPO / "plugin" / "coscientist-manuscript-mcp" / "server" / "server.py"),
            (_REPO / "mcp" / "graph-query-mcp" / "server.py",
             _REPO / "plugin" / "coscientist-graph-query-mcp" / "server" / "server.py"),
        )
        for src, plug in pairs:
            self.assertEqual(
                src.read_text(), plug.read_text(),
                f"{plug} drifted from {src}",
            )


class PruneWritesAllDbsTests(TestCase):
    def test_empty_cache_returns_zero(self):
        with isolated_cache() as root:
            res = prune_writes_all_dbs(root)
            self.assertEqual(res["dbs_scanned"], 0)
            self.assertEqual(res["total_deleted"], 0)
            self.assertEqual(res["per_db"], [])

    def test_sweeps_run_dbs(self):
        with isolated_cache() as root:
            db = _new_run_db("sweep_run")
            for i in range(3):
                skill_persist.persist_citation_resolution(
                    db, run_id="sweep_run", input_text=f"x{i}",
                    partial={}, matched=False, score=0.1, threshold=0.5,
                )
            res = prune_writes_all_dbs(root)
            # At least the run DB should be scanned + still hold rows.
            self.assertGreaterEqual(res["dbs_scanned"], 1)
            run_entries = [
                e for e in res["per_db"] if "sweep_run" in e["path"]
            ]
            self.assertEqual(len(run_entries), 1)
            self.assertEqual(run_entries[0]["remaining"], 3)

    def test_keep_last_n_global(self):
        with isolated_cache() as root:
            db = _new_run_db("keep_run")
            for i in range(8):
                skill_persist.persist_citation_resolution(
                    db, run_id="keep_run", input_text=f"x{i}",
                    partial={}, matched=False, score=0.1, threshold=0.5,
                )
            res = prune_writes_all_dbs(root, keep_last_n=2)
            run_entry = next(
                e for e in res["per_db"] if "keep_run" in e["path"]
            )
            self.assertEqual(run_entry["remaining"], 2)
            self.assertEqual(run_entry["deleted"], 6)


if __name__ == "__main__":
    raise SystemExit(run_tests(
        PluginPyprojectTests,
        ServerMainEntryTests,
        PruneWritesAllDbsTests,
    ))

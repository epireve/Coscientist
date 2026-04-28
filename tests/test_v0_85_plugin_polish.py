"""v0.85 — plugin uninstall cleanup + checksums."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from lib import plugin_checksums, plugin_cleanup, project
from tests.harness import TestCase, isolated_cache, run_tests

_REPO = Path(__file__).resolve().parents[1]


class PluginCleanupTests(TestCase):
    def test_unknown_plugin_errors(self):
        out = plugin_cleanup.cleanup("nonsense")
        self.assertIn("error", out)

    def test_manuscript_mcp_no_op(self):
        with isolated_cache():
            out = plugin_cleanup.cleanup("manuscript-mcp")
            self.assertEqual(out["n_rows_total"], 0)
            self.assertIn("note", out)

    def test_graph_query_mcp_no_op(self):
        with isolated_cache():
            out = plugin_cleanup.cleanup("graph-query-mcp")
            self.assertEqual(out["n_rows_total"], 0)

    def test_deep_research_no_op(self):
        with isolated_cache():
            out = plugin_cleanup.cleanup("deep-research")
            self.assertEqual(out["n_rows_total"], 0)

    def test_retraction_dry_run(self):
        with isolated_cache():
            pid = project.create("retraction cleanup")
            db = project.project_db_path(pid)
            con = sqlite3.connect(db)
            with con:
                con.execute("""
                    CREATE TABLE IF NOT EXISTS retraction_flags (
                        flag_id      INTEGER PRIMARY KEY AUTOINCREMENT,
                        canonical_id TEXT NOT NULL UNIQUE,
                        retracted    INTEGER NOT NULL,
                        source       TEXT NOT NULL,
                        detail       TEXT,
                        checked_at   TEXT NOT NULL
                    )
                """)
                con.execute(
                    "INSERT INTO retraction_flags "
                    "(canonical_id, retracted, source, detail, checked_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    ("paper_a", 1, "retraction-mcp", None,
                     "2026-04-28T00:00:00+00:00"),
                )
            con.close()
            out = plugin_cleanup.cleanup("retraction-mcp", confirm=False)
            self.assertEqual(out["n_rows_total"], 1)
            self.assertEqual(out["n_deleted"], 0)
            self.assertFalse(out["confirmed"])

    def test_retraction_confirm_deletes(self):
        with isolated_cache():
            pid = project.create("retraction cleanup confirm")
            db = project.project_db_path(pid)
            con = sqlite3.connect(db)
            with con:
                con.execute("""
                    CREATE TABLE IF NOT EXISTS retraction_flags (
                        flag_id      INTEGER PRIMARY KEY AUTOINCREMENT,
                        canonical_id TEXT NOT NULL UNIQUE,
                        retracted    INTEGER NOT NULL,
                        source       TEXT NOT NULL,
                        detail       TEXT,
                        checked_at   TEXT NOT NULL
                    )
                """)
                con.execute(
                    "INSERT INTO retraction_flags "
                    "(canonical_id, retracted, source, detail, checked_at) "
                    "VALUES (?, 1, 'retraction-mcp', NULL, ?)",
                    ("p1", "2026-04-28T00:00:00+00:00"),
                )
                con.execute(
                    "INSERT INTO retraction_flags "
                    "(canonical_id, retracted, source, detail, checked_at) "
                    "VALUES (?, 1, 'semantic-scholar', NULL, ?)",
                    ("p2", "2026-04-28T00:00:00+00:00"),
                )
            con.close()
            out = plugin_cleanup.cleanup("retraction-mcp", confirm=True)
            self.assertEqual(out["n_deleted"], 1)
            # Other source untouched
            con = sqlite3.connect(db)
            try:
                rem = con.execute(
                    "SELECT canonical_id FROM retraction_flags"
                ).fetchall()
            finally:
                con.close()
            self.assertEqual([r[0] for r in rem], ["p2"])


class PluginChecksumsTests(TestCase):
    def test_all_plugins_have_checksums(self):
        for d in plugin_checksums.all_plugins():
            cs = d / "CHECKSUMS.txt"
            self.assertTrue(
                cs.exists(),
                f"missing CHECKSUMS.txt for {d.name} — run "
                "`uv run python -m lib.plugin_checksums generate`",
            )

    def test_verify_passes_for_each_plugin(self):
        for d in plugin_checksums.all_plugins():
            res = plugin_checksums.verify_manifest(d)
            self.assertTrue(
                res.ok,
                f"{d.name}: {res.issues[:3]}",
            )

    def test_excludes_pycache(self):
        # Walk should never include __pycache__ files.
        for d in plugin_checksums.all_plugins():
            cs = (d / "CHECKSUMS.txt").read_text()
            self.assertNotIn("__pycache__", cs)
            self.assertNotIn(".pyc", cs)


if __name__ == "__main__":
    raise SystemExit(run_tests(PluginCleanupTests, PluginChecksumsTests))

"""v0.190 — phase-name canonicalization in papers_in_run + migration v16."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from lib.migrations import ALL_VERSIONS, ensure_current
from tests.harness import TestCase, isolated_cache, run_tests


_LEGACY_TO_CANONICAL = {
    "social": "scout",
    "grounder": "cartographer",
    "historian": "chronicler",
    "gaper": "surveyor",
    "vision": "synthesist",
    "theorist": "architect",
    "rude": "inquisitor",
    "synthesizer": "weaver",
    "thinker": "visionary",
    "scribe": "steward",
}


def _make_papers_in_run_db(path: Path, rows: list[tuple[str, str, str]]) -> None:
    """rows: [(run_id, canonical_id, added_in_phase), ...]."""
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS papers_in_run (
            run_id TEXT NOT NULL,
            canonical_id TEXT NOT NULL,
            added_in_phase TEXT NOT NULL,
            PRIMARY KEY (run_id, canonical_id)
        );
    """)
    for rid, cid, phase in rows:
        con.execute("INSERT OR IGNORE INTO runs (run_id) VALUES (?)", (rid,))
        con.execute(
            "INSERT INTO papers_in_run (run_id, canonical_id, added_in_phase) "
            "VALUES (?, ?, ?)",
            (rid, cid, phase),
        )
    con.commit()
    con.close()


class V0190PhaseCanonicalizationTests(TestCase):

    def test_all_versions_includes_16(self):
        self.assertIn(16, ALL_VERSIONS)

    def test_v16_canonicalizes_social_to_scout(self):
        with isolated_cache() as cache:
            db = Path(cache) / "runs" / "run-x.db"
            _make_papers_in_run_db(db, [("r1", "p1", "social")])
            ensure_current(db)
            con = sqlite3.connect(db)
            row = con.execute(
                "SELECT added_in_phase FROM papers_in_run WHERE canonical_id='p1'"
            ).fetchone()
            con.close()
            self.assertEqual(row[0], "scout")

    def test_v16_canonicalizes_all_aliases(self):
        with isolated_cache() as cache:
            db = Path(cache) / "runs" / "run-y.db"
            rows = [
                ("r1", f"p_{legacy}", legacy)
                for legacy in _LEGACY_TO_CANONICAL
            ]
            _make_papers_in_run_db(db, rows)
            ensure_current(db)
            con = sqlite3.connect(db)
            for legacy, canonical in _LEGACY_TO_CANONICAL.items():
                row = con.execute(
                    "SELECT added_in_phase FROM papers_in_run "
                    "WHERE canonical_id=?",
                    (f"p_{legacy}",),
                ).fetchone()
                self.assertEqual(
                    row[0], canonical,
                    f"{legacy!r} should canonicalize to {canonical!r}",
                )
            con.close()

    def test_v16_idempotent_already_canonical(self):
        # Already-canonical rows stay as-is on re-run.
        with isolated_cache() as cache:
            db = Path(cache) / "runs" / "run-z.db"
            _make_papers_in_run_db(db, [
                ("r1", "p1", "scout"),
                ("r1", "p2", "weaver"),
            ])
            ensure_current(db)
            ensure_current(db)  # second time = no-op
            con = sqlite3.connect(db)
            phases = sorted(
                r[0] for r in con.execute(
                    "SELECT added_in_phase FROM papers_in_run"
                )
            )
            con.close()
            self.assertEqual(phases, ["scout", "weaver"])

    def test_v16_recorded_in_schema_versions(self):
        with isolated_cache() as cache:
            db = Path(cache) / "runs" / "run-rec.db"
            _make_papers_in_run_db(db, [("r1", "p1", "social")])
            ensure_current(db)
            con = sqlite3.connect(db)
            versions = {
                r[0] for r in con.execute("SELECT version FROM schema_versions")
            }
            con.close()
            self.assertIn(16, versions)

    def test_v16_skips_when_no_papers_in_run_table(self):
        # Direct unit test of the gate: _ensure_v16_columns is a no-op
        # when papers_in_run is absent.
        from lib.migrations import _ensure_v16_columns
        with isolated_cache() as cache:
            db = Path(cache) / "runs" / "no-pir.db"
            db.parent.mkdir(parents=True, exist_ok=True)
            con = sqlite3.connect(db)
            con.execute("CREATE TABLE other (x INT)")
            con.commit()
            # Should be a no-op (silent return, no error).
            _ensure_v16_columns(con)
            con.close()

    def test_v16_handles_fresh_db_no_legacy_rows(self):
        # Fresh DB with only canonical rows — no-op, no errors.
        with isolated_cache() as cache:
            db = Path(cache) / "runs" / "fresh.db"
            _make_papers_in_run_db(db, [("r1", "p1", "scout")])
            ensure_current(db)
            con = sqlite3.connect(db)
            count = con.execute(
                "SELECT COUNT(*) FROM papers_in_run WHERE added_in_phase='scout'"
            ).fetchone()[0]
            con.close()
            self.assertEqual(count, 1)

    def test_merge_py_writes_canonical_phase_name(self):
        # Static check: merge.py source no longer hardcodes "social".
        merge = (
            Path(__file__).resolve().parent.parent
            / ".claude/skills/paper-discovery/scripts/merge.py"
        )
        txt = merge.read_text()
        self.assertNotIn('"social"', txt)
        self.assertIn('"scout"', txt)

    def test_v16_sql_file_exists(self):
        sql = (
            Path(__file__).resolve().parent.parent
            / "lib/migrations_sql/v16.sql"
        )
        self.assertEqual(sql.exists(), True)
        self.assertIn("scout", sql.read_text())

    def test_v16_vendored_to_plugin(self):
        plugin_sql = (
            Path(__file__).resolve().parent.parent
            / "plugin/coscientist-graph-query-mcp/lib/migrations_sql/v16.sql"
        )
        self.assertEqual(plugin_sql.exists(), True)


if __name__ == "__main__":
    raise SystemExit(run_tests(V0190PhaseCanonicalizationTests))

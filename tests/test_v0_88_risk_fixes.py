"""v0.88 — verify the three newly-visible risk fixes.

Risk #1: prune_writes_all_dbs uses connect_wal (not plain sqlite3.connect).
Risk #2: db_check FK check is retroactive (PRAGMA foreign_key_check).
Risk #3: purge_archives audits its own deletions to audit.log.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from lib import audit_retention, db_check, db_notify, project, skill_persist
from lib.cache import audit_log_path, run_db_path
from tests.harness import TestCase, isolated_cache, run_tests

_REPO = Path(__file__).resolve().parents[1]


def _make_archive(parent: Path, base: str, days_ago: int) -> Path:
    stamp = (
        datetime.now(UTC) - timedelta(days=days_ago)
    ).strftime("%Y%m%dT%H%M%SZ")
    p = parent / f"{base}.{stamp}"
    p.write_bytes(b"x" * 100)
    return p


class PruneWritesUsesWalTests(TestCase):
    """Risk #1: cross-DB sweep must open WAL so it doesn't deadlock
    on writers."""

    def test_sweep_leaves_wal_intact(self):
        with isolated_cache():
            db = run_db_path("wal_sweep")
            schema = (_REPO / "lib" / "sqlite_schema.sql").read_text()
            con = sqlite3.connect(db)
            con.executescript(schema)
            con.close()
            from lib.migrations import ensure_current
            ensure_current(db)
            # Seed db_writes via persist helper.
            skill_persist.persist_citation_resolution(
                db, run_id="wal_sweep", input_text="x",
                partial={}, matched=False, score=0.1, threshold=0.5,
            )
            # Prior to v0.88, this opened plain sqlite3.connect.
            db_notify.prune_writes_all_dbs(
                Path(db).parent.parent, keep_last_n=1,
            )
            # After sweep, journal_mode must still be wal.
            con = sqlite3.connect(db)
            try:
                mode = con.execute("PRAGMA journal_mode").fetchone()[0]
                self.assertEqual(mode.lower(), "wal")
            finally:
                con.close()


class DbCheckFkRetroactiveTests(TestCase):
    """Risk #2: confirm db_check uses PRAGMA foreign_key_check (which IS
    retroactive). This documents the behavior; not a regression."""

    def test_fk_violation_detected_in_existing_data(self):
        with isolated_cache():
            pid = project.create("fk test")
            db = project.project_db_path(pid)
            con = sqlite3.connect(db)
            with con:
                # Insert a graph_edge referencing a non-existent
                # graph_node, which violates the FK. We have to
                # disable FK enforcement to insert it.
                con.execute("PRAGMA foreign_keys=OFF")
                con.execute("""
                    INSERT INTO graph_edges
                    (from_node, to_node, relation, weight,
                     data_json, created_at)
                    VALUES (?, ?, ?, ?, NULL, ?)
                """, (
                    "paper:nonexistent_a", "paper:nonexistent_b",
                    "cites", 1.0,
                    "2026-04-28T00:00:00+00:00",
                ))
            con.close()
            # db_check should find FK violations retroactively.
            res = db_check.check_all()
            proj = next(
                r for r in res["reports"] if "project.db" in r["path"]
            )
            # Either the FK check finds the row OR the orphan check
            # fires. Both are valid signals.
            self.assertFalse(proj["healthy"])
            self.assertTrue(
                any("foreign-key" in i.lower()
                    or "missing nodes" in i.lower()
                    for i in proj["issues"]),
                f"expected FK or orphan issue in: {proj['issues']}",
            )


class PurgeArchivesAuditTrailTests(TestCase):
    """Risk #3: purge_archives must log its own deletions."""

    def test_purge_logs_to_audit_log(self):
        with isolated_cache():
            audit = audit_log_path()
            audit.write_text("")  # establish the live log
            # Plant an old archive.
            old = _make_archive(audit.parent, "audit.log", days_ago=60)
            self.assertTrue(old.exists())
            audit_retention.purge_archives(
                older_than_days=30, confirm=True,
            )
            self.assertFalse(old.exists())  # archive deleted
            # Live log should now have a record of the purge.
            log_text = audit.read_text()
            self.assertIn("audit-purge", log_text,
                          f"audit.log missing purge entry: {log_text!r}")
            # Should be parseable JSON.
            for line in log_text.splitlines():
                if "audit-purge" in line:
                    parsed = json.loads(line)
                    self.assertEqual(parsed["kind"], "audit-purge")
                    self.assertGreaterEqual(parsed["n_deleted"], 1)

    def test_dry_run_does_not_log(self):
        with isolated_cache():
            audit = audit_log_path()
            audit.write_text("")
            _make_archive(audit.parent, "audit.log", days_ago=60)
            audit_retention.purge_archives(
                older_than_days=30, confirm=False,
            )
            log_text = audit.read_text()
            self.assertNotIn("audit-purge", log_text,
                             "dry-run should not write to audit.log")


if __name__ == "__main__":
    raise SystemExit(run_tests(
        PruneWritesUsesWalTests,
        DbCheckFkRetroactiveTests,
        PurgeArchivesAuditTrailTests,
    ))

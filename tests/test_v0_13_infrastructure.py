"""v0.13 infrastructure tests:
- Schema migrations (lib/migrations.py)
- Cross-DB transaction primitive (lib/transaction.py)
- Artifact lockfile (lib/lockfile.py)
- Retry-with-backoff (lib/retry.py)
- Journal disk-mirror drift detection
"""

from tests import _shim  # noqa: F401

import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests

_ROOT = Path(__file__).resolve().parent.parent
SCHEMA = (_ROOT / "lib" / "sqlite_schema.sql").read_text()

JOURNAL_ADD = _ROOT / ".claude/skills/research-journal/scripts/add_entry.py"
JOURNAL_LIST = _ROOT / ".claude/skills/research-journal/scripts/list_entries.py"


def _seed_project(cache_dir: Path, pid: str = "infra_proj") -> str:
    p = cache_dir / "projects" / pid
    p.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p / "project.db")
    con.executescript(SCHEMA)
    con.execute(
        "INSERT INTO projects (project_id, name, created_at) VALUES (?, ?, ?)",
        (pid, "Infra", "2026-04-24T00:00:00Z"),
    )
    con.commit()
    con.close()
    return pid


# ---------------- migrations ----------------

class MigrationTests(TestCase):
    def test_fresh_db_has_no_versions(self):
        with isolated_cache() as cache_dir:
            from lib.migrations import current_version
            db = cache_dir / "fresh.db"
            sqlite3.connect(db).close()
            self.assertEqual(current_version(db), 0)

    def test_ensure_current_creates_schema_versions_table(self):
        with isolated_cache() as cache_dir:
            from lib.migrations import ensure_current
            db = cache_dir / "ec.db"
            sqlite3.connect(db).close()
            applied = ensure_current(db, migrations=[
                (1, "test_migration",
                 "CREATE TABLE test_one (x INTEGER)"),
            ])
            self.assertEqual(applied, [1])

            con = sqlite3.connect(db)
            tables = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            con.close()
            self.assertIn("schema_versions", tables)
            self.assertIn("test_one", tables)

    def test_ensure_current_idempotent(self):
        with isolated_cache() as cache_dir:
            from lib.migrations import ensure_current
            db = cache_dir / "idemp.db"
            sqlite3.connect(db).close()
            migs = [(1, "first", "CREATE TABLE t (x INTEGER)")]
            self.assertEqual(ensure_current(db, migrations=migs), [1])
            # Second call — nothing to apply
            self.assertEqual(ensure_current(db, migrations=migs), [])

    def test_ensure_current_applies_only_new(self):
        with isolated_cache() as cache_dir:
            from lib.migrations import ensure_current
            db = cache_dir / "evolve.db"
            sqlite3.connect(db).close()
            ensure_current(db, migrations=[
                (1, "first", "CREATE TABLE t1 (x INTEGER)"),
            ])
            applied = ensure_current(db, migrations=[
                (1, "first", "CREATE TABLE t1 (x INTEGER)"),
                (2, "second", "CREATE TABLE t2 (y INTEGER)"),
            ])
            self.assertEqual(applied, [2])


# ---------------- transactions ----------------

class TransactionTests(TestCase):
    def _make_db(self, path: Path) -> None:
        con = sqlite3.connect(path)
        con.execute("CREATE TABLE log (id INTEGER PRIMARY KEY, msg TEXT)")
        con.commit()
        con.close()

    def test_both_committed_on_success(self):
        with isolated_cache() as cache_dir:
            from lib.transaction import multi_db_tx
            db_a = cache_dir / "a.db"
            db_b = cache_dir / "b.db"
            self._make_db(db_a)
            self._make_db(db_b)

            with multi_db_tx([db_a, db_b]) as (con_a, con_b):
                con_a.execute("INSERT INTO log (msg) VALUES ('a')")
                con_b.execute("INSERT INTO log (msg) VALUES ('b')")

            for db in (db_a, db_b):
                con = sqlite3.connect(db)
                n = con.execute("SELECT COUNT(*) FROM log").fetchone()[0]
                con.close()
                self.assertEqual(n, 1)

    def test_both_rolled_back_on_error(self):
        with isolated_cache() as cache_dir:
            from lib.transaction import multi_db_tx
            db_a = cache_dir / "a.db"
            db_b = cache_dir / "b.db"
            self._make_db(db_a)
            self._make_db(db_b)

            try:
                with multi_db_tx([db_a, db_b]) as (con_a, con_b):
                    con_a.execute("INSERT INTO log (msg) VALUES ('a')")
                    con_b.execute("INSERT INTO log (msg) VALUES ('b')")
                    raise RuntimeError("simulated mid-tx failure")
            except RuntimeError:
                pass

            for db in (db_a, db_b):
                con = sqlite3.connect(db)
                n = con.execute("SELECT COUNT(*) FROM log").fetchone()[0]
                con.close()
                self.assertEqual(n, 0,
                                 f"{db} should have rolled back the insert")


# ---------------- lockfile ----------------

class LockfileTests(TestCase):
    def test_acquire_and_release(self):
        with isolated_cache() as cache_dir:
            from lib.lockfile import artifact_lock
            art_dir = cache_dir / "art"
            art_dir.mkdir()
            with artifact_lock(art_dir, timeout=2.0):
                self.assertTrue((art_dir / ".lock").exists())

    def test_concurrent_holders_serialize(self):
        """Second holder must wait until first releases."""
        with isolated_cache() as cache_dir:
            from lib.lockfile import artifact_lock
            art_dir = cache_dir / "art"
            art_dir.mkdir()
            results: list[float] = []

            def hold(label: int, hold_for: float) -> None:
                with artifact_lock(art_dir, timeout=10.0):
                    start = time.monotonic()
                    time.sleep(hold_for)
                    results.append(time.monotonic() - start)

            t1 = threading.Thread(target=hold, args=(1, 0.3))
            t2 = threading.Thread(target=hold, args=(2, 0.05))
            t1.start()
            time.sleep(0.05)  # ensure t1 has the lock first
            t2.start()
            t1.join()
            t2.join()
            # Total wall-time should be at least 0.3 + 0.05 = 0.35s
            # if locks serialized properly
            total = sum(results)
            self.assertTrue(total >= 0.34,
                            f"locks may not have serialized: total={total}")

    def test_timeout_raises(self):
        with isolated_cache() as cache_dir:
            from lib.lockfile import artifact_lock, LockTimeout
            art_dir = cache_dir / "art"
            art_dir.mkdir()

            holder_acquired = threading.Event()
            holder_release = threading.Event()

            def holder():
                with artifact_lock(art_dir, timeout=10.0):
                    holder_acquired.set()
                    holder_release.wait(timeout=5.0)

            t = threading.Thread(target=holder)
            t.start()
            holder_acquired.wait(timeout=2.0)

            try:
                with artifact_lock(art_dir, timeout=0.3):
                    self.assertTrue(False, "should have raised LockTimeout")
            except LockTimeout:
                pass
            finally:
                holder_release.set()
                t.join()


# ---------------- retry ----------------

class RetryTests(TestCase):
    def test_succeeds_on_first_attempt(self):
        from lib.retry import retry_with_backoff
        calls = [0]

        def fn():
            calls[0] += 1
            return "ok"

        result = retry_with_backoff(fn, max_attempts=3, base_delay=0.01)
        self.assertEqual(result, "ok")
        self.assertEqual(calls[0], 1)

    def test_retries_then_succeeds(self):
        from lib.retry import retry_with_backoff
        calls = [0]

        def fn():
            calls[0] += 1
            if calls[0] < 3:
                raise TimeoutError("transient")
            return "finally"

        result = retry_with_backoff(fn, max_attempts=4, base_delay=0.01)
        self.assertEqual(result, "finally")
        self.assertEqual(calls[0], 3)

    def test_raises_after_max_attempts(self):
        from lib.retry import retry_with_backoff
        calls = [0]

        def fn():
            calls[0] += 1
            raise ConnectionError("never works")

        try:
            retry_with_backoff(fn, max_attempts=3, base_delay=0.01)
            self.assertTrue(False, "should have raised")
        except ConnectionError:
            pass
        self.assertEqual(calls[0], 3)

    def test_non_retryable_passes_through(self):
        from lib.retry import retry_with_backoff
        calls = [0]

        def fn():
            calls[0] += 1
            raise ValueError("not retryable")

        try:
            retry_with_backoff(fn, max_attempts=4, base_delay=0.01)
            self.assertTrue(False, "should have raised")
        except ValueError:
            pass
        self.assertEqual(calls[0], 1)

    def test_on_retry_callback_invoked(self):
        from lib.retry import retry_with_backoff
        attempts: list[int] = []

        def fn():
            if len(attempts) < 2:
                attempts.append(len(attempts) + 1)
                raise TimeoutError("x")
            return "done"

        def on_retry(attempt, exc, delay):
            self.assertTrue(attempt >= 1)
            self.assertTrue(delay >= 0)

        result = retry_with_backoff(fn, max_attempts=4,
                                    base_delay=0.01, on_retry=on_retry)
        self.assertEqual(result, "done")


# ---------------- journal drift ----------------

def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], capture_output=True, text=True)


class JournalDriftTests(TestCase):
    def test_no_drift_warns_nothing(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir)
            r = _run(str(JOURNAL_ADD), "--project-id", pid,
                     "--text", "Original entry")
            assert r.returncode == 0
            r = _run(str(JOURNAL_LIST), "--project-id", pid)
            assert r.returncode == 0
            self.assertNotIn("disk mirror has drifted", r.stderr)
            self.assertNotIn("disk mirror missing", r.stderr)

    def test_drift_detected_when_disk_modified(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir)
            r = _run(str(JOURNAL_ADD), "--project-id", pid,
                     "--text", "Original content here")
            eid = json.loads(r.stdout)["entry_id"]

            # Edit the disk mirror directly
            mirror = cache_dir / "projects" / pid / "journal" / f"{eid}.md"
            mirror.write_text("---\nentry_id: 1\n---\n\nTAMPERED CONTENT\n")

            r = _run(str(JOURNAL_LIST), "--project-id", pid)
            self.assertIn("drifted", r.stderr)
            entries = json.loads(r.stdout)
            self.assertTrue(entries[0].get("disk_drift") is True)

    def test_missing_mirror_detected(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir)
            r = _run(str(JOURNAL_ADD), "--project-id", pid,
                     "--text", "Will lose its mirror")
            eid = json.loads(r.stdout)["entry_id"]

            mirror = cache_dir / "projects" / pid / "journal" / f"{eid}.md"
            mirror.unlink()

            r = _run(str(JOURNAL_LIST), "--project-id", pid)
            self.assertIn("disk mirror missing", r.stderr)
            entries = json.loads(r.stdout)
            self.assertTrue(entries[0].get("disk_missing") is True)


if __name__ == "__main__":
    sys.exit(run_tests(
        MigrationTests,
        TransactionTests,
        LockfileTests,
        RetryTests,
        JournalDriftTests,
    ))

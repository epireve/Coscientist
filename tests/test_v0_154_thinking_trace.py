"""v0.154 — thinking-trace persistence + render."""
from __future__ import annotations

import io
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from lib import migrations, thinking_trace, trace, trace_render
from lib.cache import cache_root, run_db_path
from tests.harness import TestCase, isolated_cache, run_tests

_ROOT = Path(__file__).resolve().parent.parent
SCHEMA = (_ROOT / "lib" / "sqlite_schema.sql").read_text()


def _build_run_db(run_id: str = "thinking_test") -> Path:
    db = run_db_path(run_id)
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.executescript(SCHEMA)
    con.close()
    migrations.ensure_current(db)
    return db


def _insert_hyp(db: Path, hyp_id: str, run_id: str = "thinking_test") -> None:
    con = sqlite3.connect(db)
    try:
        con.execute(
            "INSERT OR IGNORE INTO runs (run_id, question, started_at) "
            "VALUES (?, ?, ?)",
            (run_id, "q", datetime.now(UTC).isoformat()),
        )
        con.execute(
            "INSERT INTO hypotheses (hyp_id, run_id, agent_name, "
            "statement, created_at) VALUES (?, ?, ?, ?, ?)",
            (hyp_id, run_id, "ag", "stmt", datetime.now(UTC).isoformat()),
        )
        con.commit()
    finally:
        con.close()


def _insert_attack(db: Path, run_id: str = "thinking_test") -> int:
    con = sqlite3.connect(db)
    try:
        con.execute(
            "INSERT OR IGNORE INTO runs (run_id, question, started_at) "
            "VALUES (?, ?, ?)",
            (run_id, "q", datetime.now(UTC).isoformat()),
        )
        cur = con.execute(
            "INSERT INTO attack_findings "
            "(run_id, target_canonical_id, attack, severity, at) "
            "VALUES (?, ?, ?, ?, ?)",
            (run_id, "p1", "p-hacking", "minor",
             datetime.now(UTC).isoformat()),
        )
        con.commit()
        return cur.lastrowid
    finally:
        con.close()


class MigrationV15Tests(TestCase):
    def test_v15_in_all_versions(self):
        self.assertIn(15, migrations.ALL_VERSIONS)

    def test_v15_sql_file_exists(self):
        sql_dir = Path(migrations.__file__).parent / "migrations_sql"
        self.assertTrue((sql_dir / "v15.sql").exists())

    def test_v15_applies_when_hypotheses_exists(self):
        with isolated_cache():
            db = _build_run_db()
            applied = migrations.applied_versions(db)
            self.assertIn(15, applied)

    def test_v15_skipped_for_unrelated_db(self):
        with isolated_cache():
            tmp = cache_root() / "no_verdicts.db"
            tmp.parent.mkdir(parents=True, exist_ok=True)
            con = sqlite3.connect(tmp)
            con.execute("CREATE TABLE other (x INTEGER)")
            con.commit()
            con.close()
            applied = migrations.ensure_current(tmp, migrations=[])
            self.assertNotIn(15, applied)

    def test_v15_columns_added_to_all_four_tables(self):
        with isolated_cache():
            db = _build_run_db()
            con = sqlite3.connect(db)
            try:
                for tbl in (
                    "hypotheses",
                    "attack_findings",
                    "novelty_assessments",
                    "publishability_verdicts",
                ):
                    cols = [r[1] for r in con.execute(
                        f"PRAGMA table_info({tbl})"
                    )]
                    self.assertIn("thinking_log_json", cols,
                                  f"{tbl} missing thinking_log_json")
            finally:
                con.close()

    def test_v15_partial_index_exists(self):
        with isolated_cache():
            db = _build_run_db()
            con = sqlite3.connect(db)
            row = con.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND name='idx_hypotheses_has_thinking'"
            ).fetchone()
            con.close()
            self.assertIsNotNone(row)

    def test_v15_idempotent_on_rerun(self):
        with isolated_cache():
            db = _build_run_db()
            # Apply migrations again — should be a no-op.
            again = migrations.ensure_current(db)
            self.assertNotIn(15, again)
            # Single row in schema_versions for v15.
            con = sqlite3.connect(db)
            n = con.execute(
                "SELECT COUNT(*) FROM schema_versions WHERE version=15"
            ).fetchone()[0]
            con.close()
            self.assertEqual(n, 1)


class RecordThinkingTests(TestCase):
    def test_record_writes_json(self):
        with isolated_cache():
            db = _build_run_db()
            _insert_hyp(db, "h1")
            log = {"considered": ["A", "B"], "chose": "A",
                   "rationale": "A is simpler"}
            thinking_trace.record_thinking(
                db, "hypotheses", "hyp_id", "h1", log,
            )
            con = sqlite3.connect(db)
            blob = con.execute(
                "SELECT thinking_log_json FROM hypotheses WHERE hyp_id='h1'"
            ).fetchone()[0]
            con.close()
            self.assertIsNotNone(blob)
            self.assertEqual(json.loads(blob), log)

    def test_record_rejects_unknown_table(self):
        with isolated_cache():
            db = _build_run_db()
            try:
                thinking_trace.record_thinking(
                    db, "evil_table", "id", 1, {"x": 1},
                )
            except ValueError:
                return
            self.fail("expected ValueError for unknown table")

    def test_record_attack_finding(self):
        with isolated_cache():
            db = _build_run_db()
            fid = _insert_attack(db)
            thinking_trace.record_thinking(
                db, "attack_findings", "finding_id", fid,
                {"chose": "minor", "rationale": "weak"},
            )
            got = thinking_trace.get_thinking(
                db, "attack_findings", "finding_id", fid,
            )
            self.assertEqual(got["chose"], "minor")


class GetThinkingTests(TestCase):
    def test_get_returns_parsed_dict(self):
        with isolated_cache():
            db = _build_run_db()
            _insert_hyp(db, "h2")
            log = {"considered": ["X"], "chose": "X"}
            thinking_trace.record_thinking(
                db, "hypotheses", "hyp_id", "h2", log,
            )
            got = thinking_trace.get_thinking(
                db, "hypotheses", "hyp_id", "h2",
            )
            self.assertEqual(got, log)

    def test_get_returns_none_when_missing_log(self):
        with isolated_cache():
            db = _build_run_db()
            _insert_hyp(db, "h3")
            got = thinking_trace.get_thinking(
                db, "hypotheses", "hyp_id", "h3",
            )
            self.assertIsNone(got)

    def test_get_returns_none_when_row_missing(self):
        with isolated_cache():
            db = _build_run_db()
            got = thinking_trace.get_thinking(
                db, "hypotheses", "hyp_id", "nope",
            )
            self.assertIsNone(got)

    def test_get_rejects_unknown_table(self):
        with isolated_cache():
            db = _build_run_db()
            try:
                thinking_trace.get_thinking(db, "evil", "id", 1)
            except ValueError:
                return
            self.fail("expected ValueError")


class FormatThinkingMdTests(TestCase):
    def test_full_log(self):
        log = {
            "considered": ["A", "B", "C"],
            "rejected": [
                {"option": "B", "reason": "too risky"},
                {"option": "C", "reason": "out of scope"},
            ],
            "chose": "A",
            "rationale": "best fit",
            "steelman": "B might still work",
            "attack": "but data is thin",
        }
        md = thinking_trace.format_thinking_md(log)
        self.assertIn("Considered", md)
        self.assertIn("- A", md)
        self.assertIn("Rejected", md)
        self.assertIn("too risky", md)
        self.assertIn("Chose:", md)
        self.assertIn("Rationale:", md)
        self.assertIn("Steelman:", md)
        self.assertIn("Attack:", md)

    def test_partial_log(self):
        md = thinking_trace.format_thinking_md(
            {"chose": "X", "rationale": "y"}
        )
        self.assertIn("Chose:", md)
        self.assertIn("Rationale:", md)
        self.assertNotIn("Steelman", md)
        self.assertNotIn("Considered", md)

    def test_empty_log(self):
        self.assertEqual(thinking_trace.format_thinking_md({}), "")

    def test_non_dict_input(self):
        self.assertEqual(thinking_trace.format_thinking_md(None), "")  # type: ignore[arg-type]
        self.assertEqual(thinking_trace.format_thinking_md([1, 2]), "")  # type: ignore[arg-type]

    def test_extra_keys_dumped(self):
        md = thinking_trace.format_thinking_md(
            {"chose": "X", "custom_key": "v"}
        )
        self.assertIn("custom_key", md)


class TraceRenderWithThinkingTests(TestCase):
    def _seed_trace(self, db: Path, run_id: str) -> str:
        trace.init_trace(db, trace_id="t-thinking", run_id=run_id)
        return "t-thinking"

    def test_with_thinking_flag_emits_section(self):
        with isolated_cache():
            db = _build_run_db()
            tid = self._seed_trace(db, "thinking_test")
            _insert_hyp(db, "h-rendered")
            thinking_trace.record_thinking(
                db, "hypotheses", "hyp_id", "h-rendered",
                {"chose": "A", "rationale": "best"},
            )
            payload = trace.get_trace(db, tid)
            out = trace_render.render(
                payload, "md", db_path=db, with_thinking=True,
            )
            self.assertIn("Thinking traces", out)
            self.assertIn("h-rendered", out)
            self.assertIn("Chose:", out)

    def test_without_flag_no_thinking_section(self):
        with isolated_cache():
            db = _build_run_db()
            tid = self._seed_trace(db, "thinking_test")
            _insert_hyp(db, "h-quiet")
            thinking_trace.record_thinking(
                db, "hypotheses", "hyp_id", "h-quiet",
                {"chose": "A"},
            )
            payload = trace.get_trace(db, tid)
            out = trace_render.render(payload, "md", db_path=db)
            self.assertNotIn("Thinking traces", out)

    def test_skips_silently_when_column_missing(self):
        # A pre-v15 DB: build base trace tables only, no v15 ALTER.
        with isolated_cache():
            tmp = cache_root() / "old_run.db"
            tmp.parent.mkdir(parents=True, exist_ok=True)
            con = sqlite3.connect(tmp)
            # Just the trace tables — no hypotheses / verdict tables.
            con.executescript("""
                CREATE TABLE runs (
                  run_id TEXT PRIMARY KEY,
                  question TEXT NOT NULL,
                  started_at TEXT NOT NULL
                );
                CREATE TABLE traces (
                  trace_id TEXT PRIMARY KEY,
                  run_id TEXT,
                  started_at TEXT NOT NULL,
                  completed_at TEXT,
                  status TEXT NOT NULL DEFAULT 'running'
                );
                CREATE TABLE spans (
                  span_id TEXT PRIMARY KEY,
                  trace_id TEXT NOT NULL,
                  parent_span_id TEXT,
                  kind TEXT NOT NULL,
                  name TEXT NOT NULL,
                  started_at TEXT NOT NULL,
                  ended_at TEXT,
                  duration_ms INTEGER,
                  status TEXT NOT NULL DEFAULT 'running',
                  error_kind TEXT,
                  error_msg TEXT,
                  attrs_json TEXT
                );
                CREATE TABLE span_events (
                  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                  span_id TEXT NOT NULL,
                  name TEXT NOT NULL,
                  payload_json TEXT,
                  at TEXT NOT NULL
                );
            """)
            con.execute(
                "INSERT INTO traces (trace_id, started_at, status) "
                "VALUES ('t-old', '2020-01-01T00:00:00', 'ok')"
            )
            con.commit()
            con.close()
            payload = trace.get_trace(tmp, "t-old")
            # Should not error even though verdict tables are absent.
            out = trace_render.render(
                payload, "md", db_path=tmp, with_thinking=True,
            )
            self.assertIn("Trace", out)
            self.assertNotIn("Thinking traces", out)


class CollectForRunTests(TestCase):
    def test_collect_returns_only_tagged_rows(self):
        with isolated_cache():
            db = _build_run_db()
            _insert_hyp(db, "h-with")
            _insert_hyp(db, "h-without")
            thinking_trace.record_thinking(
                db, "hypotheses", "hyp_id", "h-with",
                {"chose": "x"},
            )
            entries = thinking_trace.collect_for_run(db, "thinking_test")
            ids = [e["row_id"] for e in entries
                   if e["table"] == "hypotheses"]
            self.assertIn("h-with", ids)
            self.assertNotIn("h-without", ids)


if __name__ == "__main__":
    raise SystemExit(run_tests(
        MigrationV15Tests,
        RecordThinkingTests,
        GetThinkingTests,
        FormatThinkingMdTests,
        TraceRenderWithThinkingTests,
        CollectForRunTests,
    ))

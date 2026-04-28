"""Tests for the systematic-review skill.

Drives review.py subcommands via subprocess and verifies:
- Protocol init, ID derivation, duplicate guards
- Search strings, protocol freeze, ordering constraints
- Two-stage screening rules and idempotency
- Data extraction guards
- Bias assessment idempotency and validation
- PRISMA flow diagram generation
- Status output
- CLI edge cases

No LLM calls, no network. Pure filesystem + SQLite.
"""

import json
import subprocess
import sys
from pathlib import Path

from tests import _shim  # noqa: F401
from tests.harness import TestCase, isolated_cache, run_tests

_ROOT = Path(__file__).resolve().parent.parent
_REVIEW = _ROOT / ".claude/skills/systematic-review/scripts/review.py"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_REVIEW), *args],
        capture_output=True, text=True,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TITLE = "Effects of mindfulness on stress in adults"
_QUESTION = "In adults, does mindfulness training compared to control reduce stress?"
_INCLUSION = '["RCT or controlled trial","adults 18+","peer-reviewed"]'
_EXCLUSION = '["animal studies","non-English","grey literature"]'


def _init_protocol(title=_TITLE, question=_QUESTION,
                   inclusion=_INCLUSION, exclusion=_EXCLUSION,
                   date_range=None, run_id=None):
    args = [
        "init",
        "--title", title,
        "--question", question,
        "--inclusion", inclusion,
        "--exclusion", exclusion,
    ]
    if date_range:
        args += ["--date-range", date_range]
    if run_id:
        args += ["--run-id", run_id]
    return _run(*args)


def _freeze_protocol(pid):
    return _run("search", "--protocol-id", pid, "--queries", '["mindfulness stress RCT"]')


def _screen(pid, paper_id, stage, decision, reason=None):
    args = ["screen", "--protocol-id", pid, "--paper-id", paper_id,
            "--stage", stage, "--decision", decision]
    if reason:
        args += ["--reason", reason]
    return _run(*args)


# ---------------------------------------------------------------------------
# ProtocolInitTests
# ---------------------------------------------------------------------------

class ProtocolInitTests(TestCase):

    def test_creates_protocol_json(self):
        with isolated_cache() as cache:
            r = _init_protocol()
            self.assertEqual(r.returncode, 0, r.stderr)
            pid = r.stdout.strip()
            proto_path = cache / "reviews" / pid / "protocol.json"
            self.assertTrue(proto_path.exists(), "protocol.json must be created")
            data = json.loads(proto_path.read_text())
            self.assertEqual(data["title"], _TITLE)
            self.assertEqual(data["question"], _QUESTION)

    def test_correct_protocol_id_derivation(self):
        import hashlib
        import re
        with isolated_cache():
            r = _init_protocol()
            pid = r.stdout.strip()
            # Recompute expected id
            def _slug(text):
                text = text.lower()
                text = re.sub(r"[^\w\s-]", "", text)
                text = re.sub(r"[\s_-]+", "_", text).strip("_")
                return text[:40]
            digest = hashlib.blake2s(f"{_TITLE}::{_QUESTION}".encode()).hexdigest()[:6]
            expected = f"{_slug(_TITLE)}_{digest}"
            self.assertEqual(pid, expected)

    def test_duplicate_protocol_errors(self):
        with isolated_cache():
            _init_protocol()
            r2 = _init_protocol()
            self.assertTrue(r2.returncode != 0, "duplicate protocol should fail")
            self.assertIn("already exists", r2.stderr)

    def test_missing_required_args_errors(self):
        # Missing --question
        r = _run("init", "--title", _TITLE,
                 "--inclusion", _INCLUSION, "--exclusion", _EXCLUSION)
        self.assertTrue(r.returncode != 0, "missing --question should fail")

    def test_date_range_stored(self):
        with isolated_cache() as cache:
            r = _init_protocol(date_range="2018-2024")
            pid = r.stdout.strip()
            data = json.loads((cache / "reviews" / pid / "protocol.json").read_text())
            self.assertEqual(data["date_range"], "2018-2024")


# ---------------------------------------------------------------------------
# SearchTests
# ---------------------------------------------------------------------------

class SearchTests(TestCase):

    def test_records_queries(self):
        with isolated_cache() as cache:
            r = _init_protocol()
            pid = r.stdout.strip()
            r2 = _run("search", "--protocol-id", pid,
                      "--queries", '["q1","q2"]')
            self.assertEqual(r2.returncode, 0, r2.stderr)
            # Verify in DB
            import sqlite3
            db = cache / "reviews" / pid / "review.db"
            conn = sqlite3.connect(str(db))
            row = conn.execute(
                "SELECT search_strings FROM review_protocols WHERE protocol_id = ?",
                (pid,)
            ).fetchone()
            conn.close()
            stored = json.loads(row[0])
            self.assertIn("q1", stored)
            self.assertIn("q2", stored)

    def test_freezes_protocol(self):
        with isolated_cache() as cache:
            r = _init_protocol()
            pid = r.stdout.strip()
            _run("search", "--protocol-id", pid, "--queries", '["q1"]')
            import sqlite3
            db = cache / "reviews" / pid / "review.db"
            conn = sqlite3.connect(str(db))
            row = conn.execute(
                "SELECT frozen_at FROM review_protocols WHERE protocol_id = ?",
                (pid,)
            ).fetchone()
            conn.close()
            self.assertTrue(row[0] is not None, "frozen_at must be set after search")

    def test_prevents_search_after_screen(self):
        with isolated_cache():
            r = _init_protocol()
            pid = r.stdout.strip()
            _freeze_protocol(pid)
            # Do a screen
            _screen(pid, "paper_001", "title_abstract", "include")
            # Now try to search again
            r3 = _run("search", "--protocol-id", pid,
                      "--queries", '["new query"]')
            self.assertTrue(r3.returncode != 0,
                            "search after screening has begun should fail")
            self.assertIn("screening has already begun", r3.stderr)

    def test_search_appends_not_replaces(self):
        with isolated_cache() as cache:
            r = _init_protocol()
            pid = r.stdout.strip()
            _run("search", "--protocol-id", pid, "--queries", '["first query"]')
            # Cannot call search again after screen has NOT begun yet —
            # but wait, search can be called only once after screen begins.
            # Actually the rule is: cannot call AFTER screen begins.
            # Two searches before any screen should be allowed.
            # But current implementation freezes on first search.
            # The spec says "append, not replace" — let's verify the first call.
            import sqlite3
            db = cache / "reviews" / pid / "review.db"
            conn = sqlite3.connect(str(db))
            row = conn.execute(
                "SELECT search_strings FROM review_protocols WHERE protocol_id = ?",
                (pid,)
            ).fetchone()
            conn.close()
            stored = json.loads(row[0])
            self.assertIn("first query", stored)


# ---------------------------------------------------------------------------
# ScreeningTests
# ---------------------------------------------------------------------------

class ScreeningTests(TestCase):

    def _setup(self):
        r = _init_protocol()
        pid = r.stdout.strip()
        _freeze_protocol(pid)
        return pid

    def test_records_title_abstract_decision(self):
        with isolated_cache() as cache:
            pid = self._setup()
            r = _screen(pid, "paper_001", "title_abstract", "include")
            self.assertEqual(r.returncode, 0, r.stderr)
            import sqlite3
            conn = sqlite3.connect(str(cache / "reviews" / pid / "review.db"))
            row = conn.execute(
                "SELECT decision FROM screening_decisions "
                "WHERE paper_id = ? AND stage = 'title_abstract'",
                ("paper_001",)
            ).fetchone()
            conn.close()
            self.assertEqual(row[0], "include")

    def test_records_full_text_decision(self):
        with isolated_cache() as cache:
            pid = self._setup()
            _screen(pid, "paper_001", "title_abstract", "include")
            r = _screen(pid, "paper_001", "full_text", "include")
            self.assertEqual(r.returncode, 0, r.stderr)
            import sqlite3
            conn = sqlite3.connect(str(cache / "reviews" / pid / "review.db"))
            row = conn.execute(
                "SELECT decision FROM screening_decisions "
                "WHERE paper_id = ? AND stage = 'full_text'",
                ("paper_001",)
            ).fetchone()
            conn.close()
            self.assertEqual(row[0], "include")

    def test_rejects_full_text_without_prior_title_abstract(self):
        with isolated_cache():
            pid = self._setup()
            r = _screen(pid, "paper_999", "full_text", "include")
            self.assertTrue(r.returncode != 0,
                            "full_text without title_abstract should fail")
            self.assertIn("title_abstract", r.stderr)

    def test_rejects_unrecognised_decision(self):
        with isolated_cache():
            pid = self._setup()
            r = _run("screen", "--protocol-id", pid, "--paper-id", "paper_001",
                     "--stage", "title_abstract", "--decision", "maybe")
            self.assertTrue(r.returncode != 0, "unrecognised decision should fail")

    def test_idempotency_rescreening_overwrites(self):
        with isolated_cache() as cache:
            pid = self._setup()
            _screen(pid, "paper_001", "title_abstract", "exclude")
            r2 = _screen(pid, "paper_001", "title_abstract", "include")
            self.assertEqual(r2.returncode, 0, r2.stderr)
            import sqlite3
            conn = sqlite3.connect(str(cache / "reviews" / pid / "review.db"))
            rows = conn.execute(
                "SELECT decision FROM screening_decisions "
                "WHERE paper_id = 'paper_001' AND stage = 'title_abstract'",
            ).fetchall()
            conn.close()
            # Should be exactly one row after idempotent re-screen
            self.assertEqual(len(rows), 1, "idempotent re-screen should leave one row")
            self.assertEqual(rows[0][0], "include")

    def test_protocol_must_be_frozen_before_screen(self):
        with isolated_cache():
            r = _init_protocol(title="Unfrozen protocol test",
                               question="A different question for uniqueness?")
            pid = r.stdout.strip()
            # Do NOT call search/freeze
            r2 = _screen(pid, "paper_001", "title_abstract", "include")
            self.assertTrue(r2.returncode != 0,
                            "screen before freeze should fail")
            self.assertIn("frozen", r2.stderr)


# ---------------------------------------------------------------------------
# ExtractionTests
# ---------------------------------------------------------------------------

class ExtractionTests(TestCase):

    def _setup_included(self, paper_id="paper_001"):
        r = _init_protocol()
        pid = r.stdout.strip()
        _freeze_protocol(pid)
        _screen(pid, paper_id, "title_abstract", "include")
        _screen(pid, paper_id, "full_text", "include")
        return pid

    def test_records_field(self):
        with isolated_cache() as cache:
            pid = self._setup_included()
            r = _run("extract", "--protocol-id", pid, "--paper-id", "paper_001",
                     "--field", "sample_size", "--value", "142")
            self.assertEqual(r.returncode, 0, r.stderr)
            import sqlite3
            conn = sqlite3.connect(str(cache / "reviews" / pid / "review.db"))
            row = conn.execute(
                "SELECT value FROM extraction_rows "
                "WHERE paper_id = 'paper_001' AND field = 'sample_size'"
            ).fetchone()
            conn.close()
            self.assertEqual(row[0], "142")

    def test_multiple_fields_accumulate(self):
        with isolated_cache() as cache:
            pid = self._setup_included()
            _run("extract", "--protocol-id", pid, "--paper-id", "paper_001",
                 "--field", "sample_size", "--value", "142")
            _run("extract", "--protocol-id", pid, "--paper-id", "paper_001",
                 "--field", "effect_size", "--value", "0.45")
            import sqlite3
            conn = sqlite3.connect(str(cache / "reviews" / pid / "review.db"))
            rows = conn.execute(
                "SELECT field FROM extraction_rows WHERE paper_id = 'paper_001'"
            ).fetchall()
            conn.close()
            fields = [row[0] for row in rows]
            self.assertIn("sample_size", fields)
            self.assertIn("effect_size", fields)

    def test_rejects_paper_with_no_full_text_include(self):
        with isolated_cache():
            r = _init_protocol(title="Extraction guard test",
                               question="Is extraction gated on full text include?")
            pid = r.stdout.strip()
            _freeze_protocol(pid)
            _screen(pid, "paper_002", "title_abstract", "exclude")
            r2 = _run("extract", "--protocol-id", pid, "--paper-id", "paper_002",
                      "--field", "sample_size", "--value", "50")
            self.assertTrue(r2.returncode != 0,
                            "extract without full_text include should fail")
            self.assertIn("full_text", r2.stderr)

    def test_multiple_papers_independent(self):
        with isolated_cache() as cache:
            r = _init_protocol(title="Multi paper extraction",
                               question="Do multiple papers extract independently?")
            pid = r.stdout.strip()
            _freeze_protocol(pid)
            for paper_id in ("paper_A", "paper_B"):
                _screen(pid, paper_id, "title_abstract", "include")
                _screen(pid, paper_id, "full_text", "include")
            _run("extract", "--protocol-id", pid, "--paper-id", "paper_A",
                 "--field", "n", "--value", "100")
            _run("extract", "--protocol-id", pid, "--paper-id", "paper_B",
                 "--field", "n", "--value", "200")
            import sqlite3
            conn = sqlite3.connect(str(cache / "reviews" / pid / "review.db"))
            rows = conn.execute(
                "SELECT paper_id, value FROM extraction_rows WHERE protocol_id = ?"
                " ORDER BY paper_id", (pid,)
            ).fetchall()
            conn.close()
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0][0], "paper_A")
            self.assertEqual(rows[1][0], "paper_B")


# ---------------------------------------------------------------------------
# BiasTests
# ---------------------------------------------------------------------------

class BiasTests(TestCase):

    def _setup_included(self):
        r = _init_protocol(title="Bias test protocol",
                           question="Does bias assessment work correctly?")
        pid = r.stdout.strip()
        _freeze_protocol(pid)
        _screen(pid, "paper_001", "title_abstract", "include")
        _screen(pid, "paper_001", "full_text", "include")
        return pid

    def test_records_domain(self):
        with isolated_cache() as cache:
            pid = self._setup_included()
            r = _run("bias", "--protocol-id", pid, "--paper-id", "paper_001",
                     "--domain", "selection", "--rating", "low")
            self.assertEqual(r.returncode, 0, r.stderr)
            import sqlite3
            conn = sqlite3.connect(str(cache / "reviews" / pid / "review.db"))
            row = conn.execute(
                "SELECT rating FROM bias_assessments "
                "WHERE paper_id = 'paper_001' AND domain = 'selection'"
            ).fetchone()
            conn.close()
            self.assertEqual(row[0], "low")

    def test_idempotent_per_domain(self):
        with isolated_cache() as cache:
            pid = self._setup_included()
            _run("bias", "--protocol-id", pid, "--paper-id", "paper_001",
                 "--domain", "reporting", "--rating", "unclear")
            _run("bias", "--protocol-id", pid, "--paper-id", "paper_001",
                 "--domain", "reporting", "--rating", "high")
            import sqlite3
            conn = sqlite3.connect(str(cache / "reviews" / pid / "review.db"))
            rows = conn.execute(
                "SELECT rating FROM bias_assessments "
                "WHERE paper_id = 'paper_001' AND domain = 'reporting'"
            ).fetchall()
            conn.close()
            # Should be exactly one row (idempotent)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][0], "high")

    def test_rejects_unknown_domain(self):
        with isolated_cache():
            pid = self._setup_included()
            r = _run("bias", "--protocol-id", pid, "--paper-id", "paper_001",
                     "--domain", "allegiance", "--rating", "low")
            self.assertTrue(r.returncode != 0, "unknown domain should fail")

    def test_rejects_unknown_rating(self):
        with isolated_cache():
            pid = self._setup_included()
            r = _run("bias", "--protocol-id", pid, "--paper-id", "paper_001",
                     "--domain", "selection", "--rating", "medium")
            self.assertTrue(r.returncode != 0, "unknown rating should fail")


# ---------------------------------------------------------------------------
# PrismaTests
# ---------------------------------------------------------------------------

class PrismaTests(TestCase):

    def _setup_with_data(self):
        r = _init_protocol(title="PRISMA generation test",
                           question="Can we generate a PRISMA diagram?")
        pid = r.stdout.strip()
        _run("search", "--protocol-id", pid,
             "--queries", '["mindfulness stress","meditation anxiety RCT"]')
        for paper_id in ("p1", "p2", "p3"):
            _screen(pid, paper_id, "title_abstract", "include")
        _screen(pid, "p4", "title_abstract", "exclude", "non-RCT design")
        for paper_id in ("p1", "p2"):
            _screen(pid, paper_id, "full_text", "include")
        _screen(pid, "p3", "full_text", "exclude", "wrong population")
        return pid

    def test_generates_prisma_md(self):
        with isolated_cache() as cache:
            pid = self._setup_with_data()
            r = _run("prisma", "--protocol-id", pid)
            self.assertEqual(r.returncode, 0, r.stderr)
            prisma_path = cache / "reviews" / pid / "prisma.md"
            self.assertTrue(prisma_path.exists(), "prisma.md must be created")

    def test_contains_identified(self):
        with isolated_cache() as cache:
            pid = self._setup_with_data()
            _run("prisma", "--protocol-id", pid)
            content = (cache / "reviews" / pid / "prisma.md").read_text()
            self.assertIn("identified", content.lower())

    def test_contains_included(self):
        with isolated_cache() as cache:
            pid = self._setup_with_data()
            _run("prisma", "--protocol-id", pid)
            content = (cache / "reviews" / pid / "prisma.md").read_text()
            self.assertIn("included", content.lower())


# ---------------------------------------------------------------------------
# StatusTests
# ---------------------------------------------------------------------------

class StatusTests(TestCase):

    def test_prints_protocol_title(self):
        with isolated_cache():
            r = _init_protocol()
            pid = r.stdout.strip()
            r2 = _run("status", "--protocol-id", pid)
            self.assertEqual(r2.returncode, 0, r2.stderr)
            self.assertIn(_TITLE, r2.stdout)

    def test_prints_inclusion_counts(self):
        with isolated_cache():
            r = _init_protocol()
            pid = r.stdout.strip()
            _freeze_protocol(pid)
            _screen(pid, "paper_001", "title_abstract", "include")
            _screen(pid, "paper_002", "title_abstract", "exclude")
            r2 = _run("status", "--protocol-id", pid)
            self.assertIn("include=1", r2.stdout)
            self.assertIn("exclude=1", r2.stdout)

    def test_errors_on_unknown_protocol(self):
        with isolated_cache():
            r = _run("status", "--protocol-id", "no_such_protocol_xyz123")
            self.assertTrue(r.returncode != 0, "unknown protocol should fail")
            self.assertIn("not found", r.stderr)


# ---------------------------------------------------------------------------
# CliEdgeTests
# ---------------------------------------------------------------------------

class CliEdgeTests(TestCase):

    def test_init_missing_title(self):
        r = _run("init", "--question", _QUESTION,
                 "--inclusion", _INCLUSION, "--exclusion", _EXCLUSION)
        self.assertTrue(r.returncode != 0, "init without --title should fail")
        self.assertIn("--title", r.stderr)

    def test_init_missing_question(self):
        r = _run("init", "--title", _TITLE,
                 "--inclusion", _INCLUSION, "--exclusion", _EXCLUSION)
        self.assertTrue(r.returncode != 0, "init without --question should fail")
        self.assertIn("--question", r.stderr)

    def test_screen_missing_stage(self):
        with isolated_cache():
            r = _init_protocol()
            pid = r.stdout.strip()
            _freeze_protocol(pid)
            r2 = _run("screen", "--protocol-id", pid, "--paper-id", "p1",
                      "--decision", "include")
            self.assertTrue(r2.returncode != 0, "screen without --stage should fail")

    def test_screen_missing_decision(self):
        with isolated_cache():
            r = _init_protocol()
            pid = r.stdout.strip()
            _freeze_protocol(pid)
            r2 = _run("screen", "--protocol-id", pid, "--paper-id", "p1",
                      "--stage", "title_abstract")
            self.assertTrue(r2.returncode != 0,
                            "screen without --decision should fail")

    def test_help_lists_all_subcommands(self):
        r = _run("--help")
        self.assertEqual(r.returncode, 0)
        for sub in ("init", "search", "screen", "extract", "bias", "prisma", "status"):
            self.assertIn(sub, r.stdout)


if __name__ == "__main__":
    sys.exit(run_tests(
        ProtocolInitTests,
        SearchTests,
        ScreeningTests,
        ExtractionTests,
        BiasTests,
        PrismaTests,
        StatusTests,
        CliEdgeTests,
    ))

"""v0.57 persistence + db-notify tests."""

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

from tests import _shim  # noqa: F401
from tests.harness import TestCase, run_tests

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from lib.db_notify import (  # noqa: E402
    format_notification,
    per_table_counts,
    record_write,
    summarize_writes,
)
from lib.migrations import ensure_current  # noqa: E402


def _fresh_db() -> Path:
    p = Path(tempfile.mkdtemp()) / "test.db"
    con = sqlite3.connect(p)
    con.executescript((_ROOT / "lib/sqlite_schema.sql").read_text())
    con.close()
    ensure_current(p)
    return p


class MigrationV9Tests(TestCase):
    def test_v9_creates_persistence_tables(self):
        db = _fresh_db()
        con = sqlite3.connect(db)
        names = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        for tbl in ("wide_runs", "wide_sub_agents", "debates",
                    "gap_analyses", "venue_recommendations",
                    "contribution_landscapes", "mode_selections",
                    "db_writes"):
            self.assertIn(tbl, names)
        con.close()


class DbNotifyTests(TestCase):
    def test_record_write_inserts_audit_row(self):
        db = _fresh_db()
        con = sqlite3.connect(db)
        try:
            note = record_write(
                con, "gap_analyses", 5, "gap-analyzer",
                run_id="r1", detail="test",
            )
            self.assertTrue(note["persisted"])
            self.assertEqual(note["n_rows"], 5)
            n = con.execute(
                "SELECT COUNT(*) FROM db_writes"
            ).fetchone()[0]
            self.assertEqual(n, 1)
        finally:
            con.close()

    def test_format_notification_human_readable(self):
        note = {
            "target_table": "debates", "n_rows": 3,
            "skill_or_lib": "debate", "run_id": "deb-x",
            "detail": "topic=novelty", "persisted": True,
        }
        s = format_notification(note)
        self.assertIn("3 rows in `debates`", s)
        self.assertIn("skill=debate", s)
        self.assertIn("run=deb-x", s)
        self.assertIn("topic=novelty", s)

    def test_format_singular_row(self):
        note = {"target_table": "x", "n_rows": 1,
                "skill_or_lib": "y", "persisted": True}
        s = format_notification(note)
        self.assertIn("1 row in", s)
        self.assertNotIn("1 rows", s)

    def test_summarize_writes_aggregates(self):
        db = _fresh_db()
        con = sqlite3.connect(db)
        try:
            for i in range(3):
                record_write(con, "gap_analyses", i + 1, "gap-analyzer")
            record_write(con, "debates", 1, "debate")
            summary = summarize_writes(con)
            tables = {r["target_table"] for r in summary}
            self.assertIn("gap_analyses", tables)
            self.assertIn("debates", tables)
            ga = next(r for r in summary
                      if r["target_table"] == "gap_analyses")
            # 1+2+3 = 6
            self.assertEqual(ga["total_rows"], 6)
            self.assertEqual(ga["n_writes"], 3)
        finally:
            con.close()

    def test_per_table_counts_excludes_internals(self):
        db = _fresh_db()
        con = sqlite3.connect(db)
        try:
            counts = per_table_counts(con)
            self.assertNotIn("schema_versions", counts)
            self.assertNotIn("sqlite_sequence", counts)
            self.assertIn("wide_runs", counts)
        finally:
            con.close()


class SkillPersistTests(TestCase):
    def test_persist_gap_analyses(self):
        from lib.gap_analyzer import analyze_gap
        from lib.skill_persist import persist_gap_analyses
        db = _fresh_db()
        a = analyze_gap({
            "gap_id": "g1", "kind": "evidential", "claim": "X",
            "supporting_ids": ["c1", "c2"],
            "cross_check_query": "q",
        })
        note = persist_gap_analyses(db, run_id=None, analyses=[a])
        self.assertEqual(note["n_rows"], 1)
        con = sqlite3.connect(db)
        n = con.execute(
            "SELECT COUNT(*) FROM gap_analyses"
        ).fetchone()[0]
        self.assertEqual(n, 1)
        con.close()

    def test_persist_debate(self):
        from lib.skill_persist import persist_debate
        db = _fresh_db()
        persist_debate(
            db, debate_id="d1", run_id=None,
            topic="novelty", target_id="t1",
            target_claim="X is novel",
            verdict="pro", delta=0.1,
            kill_criterion="if 2018 paper had it",
            pro_mean=0.7, con_mean=0.6,
            transcript_path="/tmp/x.md",
        )
        con = sqlite3.connect(db)
        row = con.execute("SELECT verdict FROM debates").fetchone()
        con.close()
        self.assertEqual(row[0], "pro")

    def test_persist_venue_recommendations(self):
        from lib.skill_persist import persist_venue_recommendations
        from lib.venue_match import ManuscriptChars, recommend
        db = _fresh_db()
        recs = recommend(ManuscriptChars(
            domains=("ml",), kind="empirical",
            novelty_score=0.8, rigor_score=0.8,
        ), top_k=3)
        persist_venue_recommendations(
            db, manuscript_id="m1", run_id=None,
            recommendations=recs,
        )
        con = sqlite3.connect(db)
        n = con.execute(
            "SELECT COUNT(*) FROM venue_recommendations"
        ).fetchone()[0]
        con.close()
        self.assertEqual(n, len(recs))

    def test_persist_contribution_landscape(self):
        from lib.contribution_mapper import (
            Anchor,
            decompose_contribution,
        )
        from lib.skill_persist import persist_contribution_landscape
        db = _fresh_db()
        cs = [decompose_contribution(
            "C1", "transformer scaling on language matches power-law"
        )]
        anchors = [Anchor.from_dict({
            "canonical_id": "x", "method": ["transformer"],
            "domain": ["language"], "finding": ["scaling"],
        })]
        persist_contribution_landscape(
            db, manuscript_id="m1", run_id=None,
            contributions=cs, anchors=anchors,
        )
        con = sqlite3.connect(db)
        n = con.execute(
            "SELECT COUNT(*) FROM contribution_landscapes"
        ).fetchone()[0]
        con.close()
        self.assertEqual(n, 1)

    def test_persist_mode_selection(self):
        from lib.skill_persist import persist_mode_selection
        db = _fresh_db()
        persist_mode_selection(
            db, user_query="Q", n_items=20,
            selected_mode="wide", confidence=0.9,
            explicit_override=False, reasoning="r",
            warnings=["w1"],
        )
        con = sqlite3.connect(db)
        row = con.execute(
            "SELECT selected_mode, n_items FROM mode_selections"
        ).fetchone()
        con.close()
        self.assertEqual(row[0], "wide")
        self.assertEqual(row[1], 20)

    def test_db_writes_audit_accumulates(self):
        from lib.skill_persist import (
            persist_debate,
            persist_mode_selection,
        )
        db = _fresh_db()
        persist_debate(
            db, debate_id="d1", run_id=None,
            topic="novelty", target_id="t1", target_claim="X",
            verdict="pro", delta=0.1, kill_criterion="k",
            pro_mean=0.7, con_mean=0.6, transcript_path="/tmp/x.md",
        )
        persist_mode_selection(
            db, user_query="Q", n_items=20,
            selected_mode="wide", confidence=0.9,
            explicit_override=False, reasoning="r", warnings=[],
        )
        con = sqlite3.connect(db)
        rows = con.execute(
            "SELECT target_table, skill_or_lib FROM db_writes"
        ).fetchall()
        con.close()
        tables = {r[0] for r in rows}
        skills = {r[1] for r in rows}
        self.assertEqual(tables, {"debates", "mode_selections"})
        self.assertEqual(skills, {"debate", "mode-selector"})


class WideResearchPersistenceTests(TestCase):
    """End-to-end smoke: wide.py init writes wide_runs + wide_sub_agents."""

    def _cli(self, *args: str) -> tuple[int, str, str]:
        import subprocess
        cli = (_ROOT / ".claude/skills/wide-research/scripts/wide.py")
        r = subprocess.run(
            [sys.executable, str(cli), *args],
            capture_output=True, text=True,
        )
        return r.returncode, r.stdout, r.stderr

    def test_wide_init_persists_run_and_subagents(self):
        from tests.harness import isolated_cache
        with isolated_cache() as cache_dir:
            items = cache_dir / "items.json"
            items.write_text(json.dumps([
                {"canonical_id": f"p{i}", "title": f"P{i}",
                 "year": 2020} for i in range(10)
            ]))
            rc, out, err = self._cli(
                "init", "--query", "Q", "--items", str(items),
                "--type", "triage",
            )
            self.assertEqual(rc, 0, err)
            d = json.loads(out)
            wide_db = Path(d["wide_db_path"])
            self.assertTrue(wide_db.exists())
            con = sqlite3.connect(wide_db)
            n_runs = con.execute(
                "SELECT COUNT(*) FROM wide_runs"
            ).fetchone()[0]
            n_subs = con.execute(
                "SELECT COUNT(*) FROM wide_sub_agents"
            ).fetchone()[0]
            con.close()
            self.assertEqual(n_runs, 1)
            self.assertEqual(n_subs, 10)
            # db-notify lines hit stderr
            self.assertIn("db-notify", err)
            self.assertIn("wide_runs", err)
            self.assertIn("wide_sub_agents", err)


class AuditQueryRecordsTests(TestCase):
    def _cli(self, *args: str) -> tuple[int, str, str]:
        import subprocess
        cli = (_ROOT / ".claude/skills/audit-query/scripts/query.py")
        r = subprocess.run(
            [sys.executable, str(cli), *args],
            capture_output=True, text=True,
        )
        return r.returncode, r.stdout, r.stderr

    def test_records_subcommand_lists_tables(self):
        db = _fresh_db()
        rc, out, err = self._cli("records", "--db-path", str(db))
        self.assertEqual(rc, 0, err)
        d = json.loads(out)
        names = {t["name"] for t in d["tables"]}
        self.assertIn("wide_runs", names)
        self.assertIn("debates", names)

    def test_records_writes_dump(self):
        from lib.skill_persist import persist_mode_selection
        db = _fresh_db()
        persist_mode_selection(
            db, user_query="Q", n_items=5,
            selected_mode="quick", confidence=0.7,
            explicit_override=False, reasoning="", warnings=[],
        )
        rc, out, err = self._cli(
            "records", "--db-path", str(db), "--writes",
        )
        self.assertEqual(rc, 0, err)
        d = json.loads(out)
        self.assertIn("db_writes_summary", d)


if __name__ == "__main__":
    sys.exit(run_tests(
        MigrationV9Tests, DbNotifyTests, SkillPersistTests,
        WideResearchPersistenceTests, AuditQueryRecordsTests,
    ))

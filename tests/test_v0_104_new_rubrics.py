"""v0.104 — rubrics for cartographer/chronicler/inquisitor/visionary/steward."""
from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests
from lib import agent_quality
from lib.cache import run_db_path


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


def _write(payload):
    tf = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False,
    )
    json.dump(payload, tf)
    tf.close()
    return Path(tf.name)


class NewRubricsRegisteredTests(TestCase):
    def test_all_five_registered(self):
        for name in ("cartographer", "chronicler", "inquisitor",
                     "visionary", "steward"):
            self.assertIn(name, agent_quality.RUBRICS,
                           f"{name} rubric missing")


class CartographerRubricTests(TestCase):
    def test_high_score_complete_artifact(self):
        with isolated_cache():
            db = _new_run_db("rid-c1")
            p = _write({
                "phase": "cartographer",
                "summary": "Field has clear seminal lineage.",
                "seminals": [
                    {"canonical_id": f"p{i}", "title": f"T{i}",
                     "why_seminal": "core paper"}
                    for i in range(4)
                ],
                "tensions": [],
            })
            try:
                res = agent_quality.score_auto(
                    db_path=db, run_id="rid-c1", span_id=None,
                    agent_name="cartographer", artifact_path=p,
                )
                self.assertTrue(res.get("ok"))
                self.assertGreater(res["score_total"], 0.8)
            finally:
                p.unlink()

    def test_low_score_missing_summary(self):
        with isolated_cache():
            db = _new_run_db("rid-c2")
            p = _write({
                "phase": "cartographer",
                "summary": "",
                "seminals": [],
            })
            try:
                res = agent_quality.score_auto(
                    db_path=db, run_id="rid-c2", span_id=None,
                    agent_name="cartographer", artifact_path=p,
                )
                self.assertLess(res["score_total"], 0.5)
            finally:
                p.unlink()


class InquisitorRubricTests(TestCase):
    def test_full_steelman_killer_survival(self):
        with isolated_cache():
            db = _new_run_db("rid-iq")
            p = _write({
                "phase": "inquisitor",
                "summary": "Survival assessed.",
                "evaluations": [
                    {"hyp_id": "hyp-1", "steelman": "strong case",
                     "killer_experiment": "do X",
                     "survival": 4},
                ],
            })
            try:
                res = agent_quality.score_auto(
                    db_path=db, run_id="rid-iq", span_id=None,
                    agent_name="inquisitor", artifact_path=p,
                )
                self.assertTrue(res.get("ok"))
                self.assertEqual(res["score_total"], 1.0)
            finally:
                p.unlink()

    def test_missing_steelman_lowers(self):
        with isolated_cache():
            db = _new_run_db("rid-iq2")
            p = _write({
                "phase": "inquisitor", "summary": "x",
                "evaluations": [
                    {"hyp_id": "h1", "killer_experiment": "x",
                     "survival": 3},
                ],
            })
            try:
                res = agent_quality.score_auto(
                    db_path=db, run_id="rid-iq2", span_id=None,
                    agent_name="inquisitor", artifact_path=p,
                )
                self.assertLess(res["score_total"], 1.0)
            finally:
                p.unlink()


class StewardRubricTests(TestCase):
    def test_full_pass(self):
        with isolated_cache():
            db = _new_run_db("rid-st")
            p = _write({
                "phase": "steward",
                "brief_path": "/tmp/brief.md",
                "map_path": "/tmp/map.md",
                "claims_cited": 30,
                "papers_cited": 50,
                "eval_passed": True,
                "hedge_word_hits": 0,
            })
            try:
                res = agent_quality.score_auto(
                    db_path=db, run_id="rid-st", span_id=None,
                    agent_name="steward", artifact_path=p,
                )
                self.assertTrue(res.get("ok"))
                self.assertEqual(res["score_total"], 1.0)
            finally:
                p.unlink()

    def test_eval_failed_drops_score(self):
        with isolated_cache():
            db = _new_run_db("rid-st2")
            p = _write({
                "phase": "steward",
                "brief_path": "/tmp/b", "map_path": "/tmp/m",
                "claims_cited": 30, "papers_cited": 50,
                "eval_passed": False,
                "hedge_word_hits": 0,
            })
            try:
                res = agent_quality.score_auto(
                    db_path=db, run_id="rid-st2", span_id=None,
                    agent_name="steward", artifact_path=p,
                )
                self.assertLess(res["score_total"], 1.0)
            finally:
                p.unlink()

    def test_hedge_words_drop_score(self):
        with isolated_cache():
            db = _new_run_db("rid-st3")
            p = _write({
                "phase": "steward",
                "brief_path": "/tmp/b", "map_path": "/tmp/m",
                "claims_cited": 30, "papers_cited": 50,
                "eval_passed": True,
                "hedge_word_hits": 5,
            })
            try:
                res = agent_quality.score_auto(
                    db_path=db, run_id="rid-st3", span_id=None,
                    agent_name="steward", artifact_path=p,
                )
                self.assertLess(res["score_total"], 1.0)
            finally:
                p.unlink()


class ChroniclerRubricTests(TestCase):
    def test_passes_with_timeline(self):
        with isolated_cache():
            db = _new_run_db("rid-ch")
            p = _write({
                "phase": "chronicler",
                "summary": "Chronological arc tracked.",
                "timeline": [
                    {"year_range": "1990-2000", "event": "x"},
                    {"year_range": "2000-2010", "event": "y"},
                    {"year_range": "2010-2020", "event": "z"},
                ],
            })
            try:
                res = agent_quality.score_auto(
                    db_path=db, run_id="rid-ch", span_id=None,
                    agent_name="chronicler", artifact_path=p,
                )
                self.assertTrue(res.get("ok"))
                self.assertGreater(res["score_total"], 0.8)
            finally:
                p.unlink()


class VisionaryRubricTests(TestCase):
    def test_passes_with_directions(self):
        with isolated_cache():
            db = _new_run_db("rid-vs")
            p = _write({
                "phase": "visionary",
                "summary": "x",
                "directions": [
                    {"hyp_id": "h1", "first_step": "do X",
                     "why_underexplored": "no one tried"},
                    {"hyp_id": "h2", "first_step": "do Y",
                     "why_underexplored": "expensive"},
                ],
            })
            try:
                res = agent_quality.score_auto(
                    db_path=db, run_id="rid-vs", span_id=None,
                    agent_name="visionary", artifact_path=p,
                )
                self.assertTrue(res.get("ok"))
                self.assertGreater(res["score_total"], 0.8)
            finally:
                p.unlink()


class AutoQualityHookV0_104Tests(TestCase):
    """v0.104 — cartographer auto-scores via record-phase
    --quality-artifact (output_json works too since shape matches)."""

    def test_cartographer_auto_scored_from_output_json(self):
        import subprocess, sys
        with isolated_cache():
            db_py = (_REPO / ".claude" / "skills" / "deep-research"
                     / "scripts" / "db.py")
            r = subprocess.run(
                [sys.executable, str(db_py), "init",
                 "--question", "test"],
                capture_output=True, text=True, cwd=str(_REPO),
            )
            rid = r.stdout.strip().split()[-1]
            artifact = _write({
                "phase": "cartographer",
                "summary": "Field roots traced.",
                "seminals": [
                    {"canonical_id": f"p{i}", "title": f"T{i}",
                     "why_seminal": "x"} for i in range(3)
                ],
                "tensions": [],
            })
            try:
                for flag in ("--start", "--complete"):
                    args = [sys.executable, str(db_py),
                            "record-phase", "--run-id", rid,
                            "--phase", "cartographer", flag]
                    if flag == "--complete":
                        # record-phase contract gets dict; rubric
                        # also reads dict — same artifact works.
                        args += ["--output-json", str(artifact),
                                  "--quality-artifact", str(artifact)]
                    r = subprocess.run(args, capture_output=True,
                                        text=True, cwd=str(_REPO))
                    self.assertEqual(r.returncode, 0, r.stderr)
                db = run_db_path(rid)
                con = sqlite3.connect(db)
                try:
                    rows = con.execute(
                        "SELECT agent_name, score_total "
                        "FROM agent_quality WHERE run_id=?",
                        (rid,),
                    ).fetchall()
                finally:
                    con.close()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0][0], "cartographer")
                self.assertGreater(rows[0][1], 0.7)
            finally:
                artifact.unlink()


if __name__ == "__main__":
    raise SystemExit(run_tests(
        NewRubricsRegisteredTests,
        CartographerRubricTests, InquisitorRubricTests,
        StewardRubricTests, ChroniclerRubricTests,
        VisionaryRubricTests, AutoQualityHookV0_104Tests,
    ))

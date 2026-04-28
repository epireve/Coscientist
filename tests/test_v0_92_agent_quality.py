"""v0.92 — agent quality scoring tests."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests
from lib import agent_quality, trace, trace_render
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


def _write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))
    return path


class MigrationV12Tests(TestCase):
    def test_v12_creates_agent_quality(self):
        with isolated_cache():
            db = _new_run_db("aq_v12")
            con = sqlite3.connect(db)
            try:
                tables = {
                    r[0] for r in con.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
            finally:
                con.close()
            self.assertIn("agent_quality", tables)


class CheckHelperTests(TestCase):
    def test_count_at_least(self):
        self.assertEqual(agent_quality.count_at_least([], 5), 0.0)
        self.assertAlmostEqual(
            agent_quality.count_at_least([1, 2], 5), 0.4,
            places=4,
        )
        self.assertEqual(agent_quality.count_at_least([1] * 5, 5), 1.0)
        self.assertEqual(agent_quality.count_at_least([1] * 10, 5), 1.0)

    def test_every_item_has_fields(self):
        items = [{"a": 1, "b": 2}, {"a": 1}]
        self.assertEqual(
            agent_quality.every_item_has_fields(items, ["a", "b"]),
            0.5,
        )
        self.assertEqual(
            agent_quality.every_item_has_fields([], ["a"]), 0.0,
        )

    def test_fraction_with_field(self):
        items = [{"a": 1}, {"a": ""}, {"a": "x"}]
        self.assertAlmostEqual(
            agent_quality.fraction_with_field(items, "a"),
            2 / 3, places=4,
        )

    def test_unique_kind_count(self):
        items = [{"k": "x"}, {"k": "y"}, {"k": "x"}]
        self.assertAlmostEqual(
            agent_quality.unique_kind_count(items, "k", min_unique=3),
            2 / 3, places=4,
        )


class ScoreAutoTests(TestCase):
    def test_scout_high_score(self):
        with isolated_cache() as root:
            db = _new_run_db("auto_scout")
            artifact = _write_json(root / "scout.json", [
                {"canonical_id": f"p{i}", "title": f"T{i}",
                 "source": ["arxiv", "s2", "consensus"][i % 3]}
                for i in range(40)
            ])
            res = agent_quality.score_auto(
                db, run_id="auto_scout", span_id=None,
                agent_name="scout", artifact_path=artifact,
            )
            self.assertTrue(res["ok"])
            self.assertGreaterEqual(res["score_total"], 0.95)
            self.assertEqual(res["judge"], "auto-rubric")

    def test_scout_low_score_empty(self):
        with isolated_cache() as root:
            db = _new_run_db("auto_scout_low")
            artifact = _write_json(root / "scout.json", [])
            res = agent_quality.score_auto(
                db, run_id="auto_scout_low", span_id=None,
                agent_name="scout", artifact_path=artifact,
            )
            self.assertEqual(res["score_total"], 0.0)

    def test_unknown_agent_errors(self):
        with isolated_cache() as root:
            db = _new_run_db("aq_unknown")
            res = agent_quality.score_auto(
                db, run_id="x", span_id=None,
                agent_name="not_a_real_persona",
                artifact_path=root / "x.json",
            )
            self.assertFalse(res["ok"])
            self.assertIn("error", res)

    def test_architect_partial_score(self):
        with isolated_cache() as root:
            db = _new_run_db("auto_arch")
            # v0.105: rubric updated to falsifiers + method_sketch
            # (matches actual persona spec).
            artifact = _write_json(root / "arch.json", [
                {"hyp_id": "h1", "method_sketch": "M1",
                 "falsifiers": ["x"]},
                {"hyp_id": "h2", "method_sketch": "M2"},  # no falsifiers
                {"hyp_id": "h3", "method_sketch": "M3",
                 "falsifiers": ["x"]},
            ])
            res = agent_quality.score_auto(
                db, run_id="auto_arch", span_id=None,
                agent_name="architect", artifact_path=artifact,
            )
            self.assertTrue(res["ok"])
            # 2/3 have falsifiers, 3/3 have method_sketch → partial.
            self.assertGreater(res["score_total"], 0.7)
            self.assertLess(res["score_total"], 1.0)

    def test_persists_to_db(self):
        with isolated_cache() as root:
            db = _new_run_db("auto_persist")
            artifact = _write_json(root / "s.json", [{"x": 1}] * 5)
            agent_quality.score_auto(
                db, run_id="auto_persist", span_id=None,
                agent_name="surveyor", artifact_path=artifact,
            )
            con = sqlite3.connect(db)
            try:
                row = con.execute(
                    "SELECT agent_name, judge, rubric_version "
                    "FROM agent_quality WHERE run_id=?",
                    ("auto_persist",),
                ).fetchone()
            finally:
                con.close()
            self.assertEqual(row[0], "surveyor")
            self.assertEqual(row[1], "auto-rubric")
            # v0.105 bumped surveyor rubric to 0.2.
            self.assertEqual(row[2], "0.2")


class JudgeProtocolTests(TestCase):
    def test_emit_judge_prompt_has_required_fields(self):
        with isolated_cache() as root:
            artifact = _write_json(root / "x.json", [{"key": 1}])
            prompt = agent_quality.emit_judge_prompt(
                "scout", artifact,
            )
            self.assertTrue(prompt["ok"])
            self.assertEqual(prompt["agent_name"], "scout")
            self.assertIn("criteria", prompt)
            self.assertGreater(len(prompt["criteria"]), 0)
            self.assertIn("instructions", prompt)
            self.assertIn("artifact_text", prompt)

    def test_emit_judge_prompt_unknown_agent(self):
        with isolated_cache() as root:
            artifact = _write_json(root / "x.json", [])
            prompt = agent_quality.emit_judge_prompt("nope", artifact)
            self.assertFalse(prompt["ok"])

    def test_persist_judge_result_writes_row(self):
        with isolated_cache() as root:
            db = _new_run_db("judge_run")
            artifact = _write_json(root / "x.json", [])
            judge_json = {
                "scores": {
                    "enough_candidates": 0.3,
                    "canonical_id_present": 0.9,
                    "title_present": 0.9,
                    "source_diversity": 0.5,
                },
                "reasoning": "Few candidates; structural fields ok.",
            }
            res = agent_quality.persist_judge_result(
                db, run_id="judge_run", span_id=None,
                agent_name="scout", artifact_path=artifact,
                judge_json=judge_json,
            )
            self.assertTrue(res["ok"])
            self.assertEqual(res["judge"], "llm-judge")
            con = sqlite3.connect(db)
            try:
                row = con.execute(
                    "SELECT judge, reasoning FROM agent_quality "
                    "WHERE run_id=?", ("judge_run",),
                ).fetchone()
            finally:
                con.close()
            self.assertEqual(row[0], "llm-judge")
            self.assertIn("Few candidates", row[1])

    def test_persist_judge_handles_missing_scores(self):
        with isolated_cache() as root:
            db = _new_run_db("judge_partial")
            artifact = _write_json(root / "x.json", [])
            res = agent_quality.persist_judge_result(
                db, run_id="judge_partial", span_id=None,
                agent_name="scout", artifact_path=artifact,
                judge_json={"scores": {}},  # all missing → 0.0
            )
            self.assertTrue(res["ok"])
            self.assertEqual(res["score_total"], 0.0)


class SummaryTests(TestCase):
    def test_summary_aggregates(self):
        with isolated_cache() as root:
            db = _new_run_db("sum_run")
            artifact = _write_json(root / "x.json", [
                {"canonical_id": f"p{i}", "title": f"T{i}",
                 "source": "arxiv"}
                for i in range(40)
            ])
            agent_quality.score_auto(
                db, run_id="sum_run", span_id=None,
                agent_name="scout", artifact_path=artifact,
            )
            agent_quality.score_auto(
                db, run_id="sum_run", span_id=None,
                agent_name="scout", artifact_path=artifact,
            )
            s = agent_quality.summary(db, run_id="sum_run")
            self.assertEqual(s["n_rows"], 2)
            self.assertIn("scout", s["by_agent"])
            self.assertEqual(s["by_agent"]["scout"]["n"], 2)


class RendererIntegrationTests(TestCase):
    def test_render_md_includes_quality_section(self):
        with isolated_cache() as root:
            db = _new_run_db("render_q")
            tid = "trace-q"
            trace.init_trace(db, trace_id=tid, run_id="render_q")
            with trace.start_span(db, tid, "phase", "scout"):
                pass
            trace.end_trace(db, tid, status="ok")
            artifact = _write_json(root / "q.json", [
                {"canonical_id": f"p{i}", "title": f"T{i}",
                 "source": "arxiv"}
                for i in range(40)
            ])
            agent_quality.score_auto(
                db, run_id="render_q", span_id=None,
                agent_name="scout", artifact_path=artifact,
            )
            payload = trace.get_trace(db, tid)
            md = trace_render.render(payload, "md", db_path=db)
            self.assertIn("Agent quality", md)
            self.assertIn("scout", md)

    def test_render_md_no_quality_section_without_runid(self):
        # render_agent_quality_section returns "" if run_id missing
        out = trace_render.render_agent_quality_section(
            Path("/dev/null"), None,
        )
        self.assertEqual(out, "")


if __name__ == "__main__":
    raise SystemExit(run_tests(
        MigrationV12Tests,
        CheckHelperTests,
        ScoreAutoTests,
        JudgeProtocolTests,
        SummaryTests,
        RendererIntegrationTests,
    ))

"""v0.105 — OG rubrics now accept dict-top (record-phase output_json).

Verifies _items_from extraction works for scout/surveyor/architect/
synthesist/weaver against actual persona output spec shapes.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

from lib import agent_quality
from lib.cache import run_db_path
from tests.harness import TestCase, isolated_cache, run_tests

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


class ItemsFromTests(TestCase):
    def test_list_top_returned_as_is(self):
        out = agent_quality._items_from([{"a": 1}], "x")
        self.assertEqual(out, [{"a": 1}])

    def test_dict_top_extracts_field(self):
        out = agent_quality._items_from(
            {"x": [{"a": 1}, {"b": 2}], "other": "y"}, "x",
        )
        self.assertEqual(len(out), 2)

    def test_dict_top_missing_field_returns_empty(self):
        out = agent_quality._items_from({"y": [1, 2]}, "x")
        self.assertEqual(out, [])

    def test_neither_list_nor_dict(self):
        self.assertEqual(agent_quality._items_from(None, "x"), [])
        self.assertEqual(agent_quality._items_from("foo", "x"), [])


class ScoutDictTopTests(TestCase):
    def test_scout_scores_dict_with_shortlist(self):
        with isolated_cache():
            db = _new_run_db("rid-scout-dict")
            sources = ["s2", "consensus", "arxiv"]
            payload = {
                "shortlist": [
                    {"canonical_id": f"p{i}", "title": f"T{i}",
                     "source": sources[i % 3]}
                    for i in range(30)
                ],
            }
            p = _write(payload)
            try:
                res = agent_quality.score_auto(
                    db_path=db, run_id="rid-scout-dict",
                    span_id=None, agent_name="scout",
                    artifact_path=p,
                )
                self.assertTrue(res.get("ok"))
                self.assertGreater(res["score_total"], 0.8)
            finally:
                p.unlink()


class SurveyorDictTopTests(TestCase):
    def test_surveyor_scores_dict_with_gaps(self):
        with isolated_cache():
            db = _new_run_db("rid-surveyor-dict")
            payload = {
                "phase": "surveyor", "summary": "x",
                "gaps": [
                    {"gap_id": f"g{i}", "kind": "evidential",
                     "why_matters": "important"}
                    for i in range(5)
                ],
            }
            p = _write(payload)
            try:
                res = agent_quality.score_auto(
                    db_path=db, run_id="rid-surveyor-dict",
                    span_id=None, agent_name="surveyor",
                    artifact_path=p,
                )
                self.assertTrue(res.get("ok"))
                self.assertGreater(res["score_total"], 0.8)
            finally:
                p.unlink()


class ArchitectDictTopTests(TestCase):
    def test_architect_scores_dict_with_hypotheses(self):
        with isolated_cache():
            db = _new_run_db("rid-arch-dict")
            payload = {
                "phase": "architect", "summary": "x",
                "hypotheses": [
                    {"hyp_id": "h1", "method_sketch": "X",
                     "falsifiers": ["a", "b"]},
                    {"hyp_id": "h2", "method_sketch": "Y",
                     "falsifiers": ["c"]},
                ],
            }
            p = _write(payload)
            try:
                res = agent_quality.score_auto(
                    db_path=db, run_id="rid-arch-dict",
                    span_id=None, agent_name="architect",
                    artifact_path=p,
                )
                self.assertTrue(res.get("ok"))
                self.assertEqual(res["score_total"], 1.0)
            finally:
                p.unlink()


class WeaverDictTopTests(TestCase):
    def test_weaver_scores_dict_per_v0_103_spec(self):
        with isolated_cache():
            db = _new_run_db("rid-weaver-dict")
            payload = {
                "phase": "weaver", "summary": "x",
                "sharpened_question": "How does X relate to Y?",
                "consensus": [
                    {"claim": "c1", "supporting_ids": ["p1", "p2"]},
                    {"claim": "c2", "supporting_ids": ["p3"]},
                ],
                "tensions": [
                    {"claim": "t1"},
                ],
            }
            p = _write(payload)
            try:
                res = agent_quality.score_auto(
                    db_path=db, run_id="rid-weaver-dict",
                    span_id=None, agent_name="weaver",
                    artifact_path=p,
                )
                self.assertTrue(res.get("ok"))
                self.assertEqual(res["score_total"], 1.0)
            finally:
                p.unlink()

    def test_weaver_low_score_no_sharpened_question(self):
        with isolated_cache():
            db = _new_run_db("rid-weaver-low")
            p = _write({
                "phase": "weaver", "summary": "x",
                "sharpened_question": "",
                "consensus": [], "tensions": [],
            })
            try:
                res = agent_quality.score_auto(
                    db_path=db, run_id="rid-weaver-low",
                    span_id=None, agent_name="weaver",
                    artifact_path=p,
                )
                self.assertEqual(res["score_total"], 0.0)
            finally:
                p.unlink()


class BackwardsCompatTests(TestCase):
    """List-top inputs (legacy --quality-artifact path) still work."""

    def test_scout_list_top_still_scores(self):
        with isolated_cache():
            db = _new_run_db("rid-bw")
            sources = ["s2", "consensus", "arxiv"]
            p = _write([
                {"canonical_id": f"p{i}", "title": f"T{i}",
                 "source": sources[i % 3]}
                for i in range(30)
            ])
            try:
                res = agent_quality.score_auto(
                    db_path=db, run_id="rid-bw", span_id=None,
                    agent_name="scout", artifact_path=p,
                )
                self.assertTrue(res.get("ok"))
                self.assertGreater(res["score_total"], 0.8)
            finally:
                p.unlink()


if __name__ == "__main__":
    raise SystemExit(run_tests(
        ItemsFromTests, ScoutDictTopTests, SurveyorDictTopTests,
        ArchitectDictTopTests, WeaverDictTopTests,
        BackwardsCompatTests,
    ))

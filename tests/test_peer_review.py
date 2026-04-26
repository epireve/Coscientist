"""Tests for the peer-review skill."""
from __future__ import annotations
import importlib.util as _ilu, json, sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

from tests.harness import CoscientistTestCase, isolated_cache  # noqa

def _load(name):
    spec = _ilu.spec_from_file_location(
        name, _REPO_ROOT / ".claude/skills/peer-review/scripts" / f"{name}.py"
    )
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ReviewTests(CoscientistTestCase):
    def test_generate_creates_review_json(self):
        with isolated_cache() as cache:
            mod = _load("review")
            r = mod.generate_review("ms1", "neurips", 1)
            self.assertEqual(r["round"], 1)
            self.assertEqual(r["venue"], "neurips")
            p = cache / "manuscripts/ms1/peer_review/round_1/review.json"
            self.assertTrue(p.exists())

    def test_neurips_has_3_reviewers(self):
        with isolated_cache():
            mod = _load("review")
            r = mod.generate_review("ms2", "neurips", 1)
            self.assertEqual(len(r["reviewers"]), 3)

    def test_generic_has_2_reviewers(self):
        with isolated_cache():
            mod = _load("review")
            r = mod.generate_review("ms3", "generic", 1)
            self.assertEqual(len(r["reviewers"]), 2)

    def test_duplicate_round_raises(self):
        with isolated_cache():
            mod = _load("review")
            mod.generate_review("ms4", "acl", 1)
            with self.assertRaises(FileExistsError):
                mod.generate_review("ms4", "acl", 1)

    def test_state_updated_after_review(self):
        with isolated_cache():
            mod = _load("review")
            mod.generate_review("ms5", "generic", 1)
            state = mod.load_state("ms5")
            self.assertEqual(state["state"], "reviewed")
            self.assertEqual(state["current_round"], 1)
            self.assertIn(1, state["rounds"])

    def test_multiple_rounds(self):
        with isolated_cache():
            mod = _load("review")
            mod.generate_review("ms6", "generic", 1)
            mod.generate_review("ms6", "generic", 2)
            state = mod.load_state("ms6")
            self.assertEqual(state["current_round"], 2)
            self.assertEqual(sorted(state["rounds"]), [1, 2])

    def test_auto_round_increment(self):
        with isolated_cache():
            mod = _load("review")
            mod.generate_review("ms7", "generic", 1)
            # next round auto = current + 1 = 2
            state = mod.load_state("ms7")
            next_round = state["current_round"] + 1
            r = mod.generate_review("ms7", "generic", next_round)
            self.assertEqual(r["round"], 2)

    def test_reviewer_ids(self):
        with isolated_cache():
            mod = _load("review")
            r = mod.generate_review("ms8", "generic", 1)
            ids = [rv["id"] for rv in r["reviewers"]]
            self.assertIn("R1", ids)
            self.assertIn("R2", ids)


class RespondTests(CoscientistTestCase):
    def _setup(self, mid, isolated):
        mod_r = _load("review")
        mod_r.generate_review(mid, "generic", 1)

    def test_respond_creates_response_json(self):
        with isolated_cache() as cache:
            self._setup("ms10", cache)
            mod = _load("respond")
            data = {"responses": [{"reviewer": "R1", "comment": "c1", "reply": "r1"}],
                    "cover_letter": "Dear editors", "changes_summary": "Fixed X"}
            result = mod.record_response("ms10", 1, data)
            self.assertEqual(result["round"], 1)
            p = cache / "manuscripts/ms10/peer_review/round_1/response.json"
            self.assertTrue(p.exists())

    def test_respond_updates_state(self):
        with isolated_cache():
            self._setup("ms11", None)
            mod_resp = _load("respond")
            mod_resp.record_response("ms11", 1, {"responses": [], "cover_letter": "", "changes_summary": ""})
            mod_rev = _load("review")
            state = mod_rev.load_state("ms11")
            self.assertEqual(state["state"], "responded")

    def test_respond_without_review_raises(self):
        with isolated_cache():
            mod = _load("respond")
            with self.assertRaises(FileNotFoundError):
                mod.record_response("noexist", 1, {})

    def test_respond_preserves_responses(self):
        with isolated_cache():
            self._setup("ms12", None)
            mod = _load("respond")
            responses = [{"reviewer": "R1", "comment": "x", "reply": "y"}]
            result = mod.record_response("ms12", 1, {"responses": responses, "cover_letter": "cl"})
            self.assertEqual(len(result["responses"]), 1)
            self.assertEqual(result["responses"][0]["reviewer"], "R1")


class DecideTests(CoscientistTestCase):
    def _setup(self, mid):
        mod_r = _load("review")
        mod_r.generate_review(mid, "generic", 1)

    def test_decide_creates_decision_json(self):
        with isolated_cache() as cache:
            self._setup("ms20")
            mod = _load("decide")
            result = mod.make_decision("ms20", "accept", "Strong contributions, all concerns addressed.")
            self.assertEqual(result["final_decision"], "accept")
            p = cache / "manuscripts/ms20/peer_review/decision.json"
            self.assertTrue(p.exists())

    def test_decide_updates_state(self):
        with isolated_cache():
            self._setup("ms21")
            mod_d = _load("decide")
            mod_d.make_decision("ms21", "reject", "Fundamental flaw in methodology.")
            mod_r = _load("review")
            state = mod_r.load_state("ms21")
            self.assertEqual(state["state"], "decided")
            self.assertEqual(state["final_decision"], "reject")

    def test_decide_no_reviews_raises(self):
        with isolated_cache():
            mod = _load("decide")
            with self.assertRaises(ValueError):
                mod.make_decision("noreviews", "accept", "rationale")

    def test_decide_invalid_decision_raises(self):
        with isolated_cache():
            self._setup("ms22")
            mod = _load("decide")
            with self.assertRaises(ValueError):
                mod.make_decision("ms22", "maybe", "rationale")

    def test_decide_includes_round_history(self):
        with isolated_cache():
            self._setup("ms23")
            mod = _load("decide")
            result = mod.make_decision("ms23", "minor_revision", "Almost there.")
            self.assertEqual(result["n_rounds"], 1)
            self.assertEqual(len(result["round_history"]), 1)


class StatusTests(CoscientistTestCase):
    def test_status_fresh(self):
        with isolated_cache():
            mod = _load("status")
            result = mod.get_status("noexist")
            self.assertEqual(result["state"], "pending")
            self.assertEqual(result["current_round"], 0)

    def test_status_after_review(self):
        with isolated_cache():
            mod_r = _load("review")
            mod_r.generate_review("ms30", "acl", 1)
            mod_s = _load("status")
            result = mod_s.get_status("ms30")
            self.assertEqual(result["state"], "reviewed")
            self.assertEqual(len(result["history"]), 1)
            self.assertTrue(result["history"][0]["has_review"])

    def test_status_table_format(self):
        with isolated_cache():
            mod_r = _load("review")
            mod_r.generate_review("ms31", "generic", 1)
            mod_s = _load("status")
            status = mod_s.get_status("ms31")
            table = mod_s._render_table(status)
            self.assertIn("ms31", table)
            self.assertIn("generic", table)

    def test_status_shows_final_decision(self):
        with isolated_cache():
            mod_r = _load("review")
            mod_r.generate_review("ms32", "generic", 1)
            mod_d = _load("decide")
            mod_d.make_decision("ms32", "accept", "Great paper.")
            mod_s = _load("status")
            result = mod_s.get_status("ms32")
            self.assertEqual(result["state"], "decided")
            self.assertTrue(result["final_decision_written"])

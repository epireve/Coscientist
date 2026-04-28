"""Tests for the reviewer-assistant skill."""
from __future__ import annotations

import importlib.util as _ilu
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

from tests.harness import CoscientistTestCase, isolated_cache  # noqa


def _load():
    spec = _ilu.spec_from_file_location(
        "review",
        _REPO_ROOT / ".claude/skills/reviewer-assistant/scripts/review.py",
    )
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _init_review(mod, **overrides):
    import argparse
    import contextlib
    import io
    base = dict(
        target_title="A Novel Approach to X",
        venue="generic",
        strengths_count=3,
        weaknesses_count=3,
        project_id=None,
        force=False,
    )
    base.update(overrides)
    args = argparse.Namespace(**base)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        mod.cmd_init(args)
    return json.loads(buf.getvalue())


class InitTests(CoscientistTestCase):
    def test_init_creates_files(self):
        with isolated_cache() as cache:
            mod = _load()
            result = _init_review(mod)
            rid = result["review_id"]
            rd = cache / "reviews" / rid
            self.assertTrue((rd / "manifest.json").exists())
            self.assertTrue((rd / "review.json").exists())

    def test_init_venues(self):
        with isolated_cache():
            mod = _load()
            for venue in ("neurips", "iclr", "nature", "generic"):
                result = _init_review(mod, target_title=f"Paper {venue}", venue=venue)
                self.assertEqual(result["venue"], venue)

    def test_init_unknown_venue_raises(self):
        with isolated_cache():
            mod = _load()
            with self.assertRaises(SystemExit):
                _init_review(mod, venue="bogus")

    def test_init_empty_title_raises(self):
        with isolated_cache():
            mod = _load()
            with self.assertRaises(SystemExit):
                _init_review(mod, target_title="   ")

    def test_init_duplicate_raises(self):
        with isolated_cache():
            mod = _load()
            _init_review(mod)
            with self.assertRaises(SystemExit):
                _init_review(mod)

    def test_init_force_overwrites(self):
        with isolated_cache():
            mod = _load()
            _init_review(mod)
            result = _init_review(mod, force=True)
            self.assertIn("review_id", result)

    def test_neurips_template_has_extras(self):
        with isolated_cache():
            mod = _load()
            result = _init_review(mod, venue="neurips")
            self.assertIn("soundness", result["extra_sections"])
            self.assertIn("questions", result["extra_sections"])


class AddCommentTests(CoscientistTestCase):
    def test_add_strengths_comment(self):
        with isolated_cache():
            mod = _load()
            r = _init_review(mod)
            rid = r["review_id"]
            import argparse
            import contextlib
            import io
            args = argparse.Namespace(
                review_id=rid, section="strengths",
                comment="Clear motivation; well-written abstract."
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_add_comment(args)
            self.assertEqual(json.loads(buf.getvalue())["current_count"], 1)

    def test_add_weaknesses_accumulate(self):
        with isolated_cache():
            mod = _load()
            r = _init_review(mod)
            rid = r["review_id"]
            import argparse
            import contextlib
            import io
            for i in range(3):
                args = argparse.Namespace(
                    review_id=rid, section="weaknesses",
                    comment=f"Weakness {i+1}."
                )
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    mod.cmd_add_comment(args)
            self.assertEqual(json.loads(buf.getvalue())["current_count"], 3)

    def test_add_summary_replaces(self):
        with isolated_cache():
            mod = _load()
            r = _init_review(mod)
            rid = r["review_id"]
            import argparse
            import contextlib
            import io
            for txt in ("First summary.", "Replacement summary."):
                args = argparse.Namespace(
                    review_id=rid, section="summary", comment=txt
                )
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    mod.cmd_add_comment(args)
            data = mod._load_review(rid)
            self.assertEqual(data["summary"], "Replacement summary.")

    def test_add_unknown_section_raises(self):
        with isolated_cache():
            mod = _load()
            r = _init_review(mod)
            import argparse
            args = argparse.Namespace(
                review_id=r["review_id"], section="bogus", comment="x"
            )
            with self.assertRaises(SystemExit):
                mod.cmd_add_comment(args)

    def test_add_empty_comment_raises(self):
        with isolated_cache():
            mod = _load()
            r = _init_review(mod)
            import argparse
            args = argparse.Namespace(
                review_id=r["review_id"], section="strengths", comment=" "
            )
            with self.assertRaises(SystemExit):
                mod.cmd_add_comment(args)

    def test_add_unknown_review_raises(self):
        with isolated_cache():
            mod = _load()
            import argparse
            args = argparse.Namespace(
                review_id="nonexistent", section="strengths", comment="x"
            )
            with self.assertRaises(FileNotFoundError):
                mod.cmd_add_comment(args)


class RecommendationTests(CoscientistTestCase):
    def _make(self, mod):
        return _init_review(mod)["review_id"]

    def test_set_recommendation(self):
        with isolated_cache():
            mod = _load()
            rid = self._make(mod)
            import argparse
            import contextlib
            import io
            args = argparse.Namespace(
                review_id=rid, decision="weak-accept", confidence=4
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_set_recommendation(args)
            result = json.loads(buf.getvalue())
            self.assertEqual(result["recommendation"], "weak-accept")
            self.assertEqual(result["confidence"], 4)

    def test_invalid_decision_raises(self):
        with isolated_cache():
            mod = _load()
            rid = self._make(mod)
            import argparse
            args = argparse.Namespace(
                review_id=rid, decision="meh", confidence=3
            )
            with self.assertRaises(SystemExit):
                mod.cmd_set_recommendation(args)

    def test_confidence_out_of_range_raises(self):
        with isolated_cache():
            mod = _load()
            rid = self._make(mod)
            import argparse
            args = argparse.Namespace(
                review_id=rid, decision="accept", confidence=7
            )
            with self.assertRaises(SystemExit):
                mod.cmd_set_recommendation(args)


class ExportTests(CoscientistTestCase):
    def test_export_markdown(self):
        with isolated_cache() as cache:
            mod = _load()
            r = _init_review(mod)
            rid = r["review_id"]
            import argparse
            import contextlib
            import io
            # Add a strength
            mod.cmd_add_comment(argparse.Namespace(
                review_id=rid, section="strengths",
                comment="Strong motivation."
            ))
            mod.cmd_add_comment(argparse.Namespace(
                review_id=rid, section="summary",
                comment="The paper proposes a new method for X."
            ))
            mod.cmd_set_recommendation(argparse.Namespace(
                review_id=rid, decision="accept", confidence=4
            ))

            args = argparse.Namespace(review_id=rid, format="markdown")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_export(args)
            output = buf.getvalue()
            self.assertIn("# Review of:", output)
            self.assertIn("Strong motivation", output)
            self.assertIn("accept", output)
            # Also written to disk
            source_md = cache / "reviews" / rid / "source.md"
            self.assertTrue(source_md.exists())

    def test_export_json(self):
        with isolated_cache():
            mod = _load()
            r = _init_review(mod)
            rid = r["review_id"]
            import argparse
            import contextlib
            import io
            args = argparse.Namespace(review_id=rid, format="json")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_export(args)
            data = json.loads(buf.getvalue())
            self.assertEqual(data["review_id"], rid)


class StatusTests(CoscientistTestCase):
    def test_status_empty(self):
        with isolated_cache():
            mod = _load()
            r = _init_review(mod)
            rid = r["review_id"]
            import argparse
            import contextlib
            import io
            args = argparse.Namespace(review_id=rid)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_status(args)
            status = json.loads(buf.getvalue())
            self.assertFalse(status["summary_set"])
            self.assertEqual(status["strengths_count"], 0)
            self.assertFalse(status["ready_to_submit"])

    def test_status_ready_when_complete(self):
        with isolated_cache():
            mod = _load()
            r = _init_review(mod)
            rid = r["review_id"]
            import argparse
            mod.cmd_add_comment(argparse.Namespace(
                review_id=rid, section="summary", comment="Summary text."
            ))
            mod.cmd_add_comment(argparse.Namespace(
                review_id=rid, section="strengths", comment="A strength."
            ))
            mod.cmd_add_comment(argparse.Namespace(
                review_id=rid, section="weaknesses", comment="A weakness."
            ))
            mod.cmd_set_recommendation(argparse.Namespace(
                review_id=rid, decision="accept", confidence=4
            ))
            import contextlib
            import io
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_status(argparse.Namespace(review_id=rid))
            status = json.loads(buf.getvalue())
            self.assertTrue(status["ready_to_submit"])

    def test_status_unknown_raises(self):
        with isolated_cache():
            mod = _load()
            import argparse
            args = argparse.Namespace(review_id="nonexistent")
            with self.assertRaises(FileNotFoundError):
                mod.cmd_status(args)


class IdStabilityTests(CoscientistTestCase):
    def test_id_stable_for_same_title(self):
        mod = _load()
        self.assertEqual(
            mod.make_review_id("Title A"),
            mod.make_review_id("Title A"),
        )

    def test_id_differs_for_different_titles(self):
        mod = _load()
        self.assertFalse(
            mod.make_review_id("Title A") == mod.make_review_id("Title B")
        )

"""Tests for the negative-results-logger skill."""
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
        "log",
        _REPO_ROOT / ".claude/skills/negative-results-logger/scripts/log.py",
    )
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_init_args(**overrides):
    import argparse
    base = dict(
        title="DopaminePredictsLearning",
        hypothesis="Tonic dopamine predicts trial-by-trial learning rate.",
        approach="Pharmacological depletion via AMPT in n=12 rats; track WM accuracy.",
        expected="Reduced learning rate under depletion vs. saline.",
        observed="No detectable difference (p=0.62, d=0.05).",
        project_id=None,
        force=False,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


class InitTests(CoscientistTestCase):
    def test_init_creates_files(self):
        with isolated_cache() as cache:
            mod = _load()
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_init(_make_init_args())
            result = json.loads(buf.getvalue())
            self.assertIn("result_id", result)
            self.assertEqual(result["state"], "logged")
            rd = cache / "negative_results" / result["result_id"]
            self.assertTrue((rd / "manifest.json").exists())
            self.assertTrue((rd / "result.json").exists())

    def test_init_record_content(self):
        with isolated_cache() as cache:
            mod = _load()
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_init(_make_init_args())
            rid = json.loads(buf.getvalue())["result_id"]
            record = json.loads((cache / "negative_results" / rid / "result.json").read_text())
            self.assertEqual(record["title"], "DopaminePredictsLearning")
            self.assertIn("Tonic dopamine", record["hypothesis"])
            self.assertEqual(record["state"], "logged")

    def test_init_id_stable(self):
        with isolated_cache():
            mod = _load()
            id1 = mod.make_result_id("Same Title")
            id2 = mod.make_result_id("Same Title")
            self.assertEqual(id1, id2)

    def test_init_id_different_for_different_titles(self):
        mod = _load()
        id1 = mod.make_result_id("Title A")
        id2 = mod.make_result_id("Title B")
        self.assertFalse(id1 == id2)

    def test_init_duplicate_raises(self):
        with isolated_cache():
            mod = _load()
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_init(_make_init_args())
            with self.assertRaises(SystemExit):
                mod.cmd_init(_make_init_args())

    def test_init_force_overwrites(self):
        with isolated_cache():
            mod = _load()
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_init(_make_init_args())
            buf2 = io.StringIO()
            with contextlib.redirect_stdout(buf2):
                mod.cmd_init(_make_init_args(force=True))
            self.assertIn("result_id", json.loads(buf2.getvalue()))

    def test_init_empty_field_raises(self):
        with isolated_cache():
            mod = _load()
            with self.assertRaises(SystemExit):
                mod.cmd_init(_make_init_args(hypothesis="   "))


class AnalyzeTests(CoscientistTestCase):
    def _make(self, mod, **overrides):
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            mod.cmd_init(_make_init_args(**overrides))
        return json.loads(buf.getvalue())["result_id"]

    def test_analyze_updates_state(self):
        with isolated_cache() as cache:
            mod = _load()
            rid = self._make(mod)
            import argparse, io, contextlib
            args = argparse.Namespace(
                result_id=rid,
                root_cause="AMPT may not deplete enough at the dose used.",
                lessons="Use 6-OHDA next time, validate depletion via HPLC.",
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_analyze(args)
            self.assertEqual(json.loads(buf.getvalue())["state"], "analyzed")
            record = json.loads((cache / "negative_results" / rid / "result.json").read_text())
            self.assertEqual(record["state"], "analyzed")
            self.assertIn("AMPT", record["root_cause"])

    def test_analyze_empty_root_cause_raises(self):
        with isolated_cache():
            mod = _load()
            rid = self._make(mod)
            import argparse
            args = argparse.Namespace(result_id=rid, root_cause="  ", lessons="x")
            with self.assertRaises(SystemExit):
                mod.cmd_analyze(args)

    def test_analyze_unknown_id_raises(self):
        with isolated_cache():
            mod = _load()
            import argparse
            args = argparse.Namespace(result_id="nonexistent", root_cause="x", lessons="y")
            with self.assertRaises(FileNotFoundError):
                mod.cmd_analyze(args)


class ShareTests(CoscientistTestCase):
    def _make_analyzed(self, mod):
        import argparse, io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            mod.cmd_init(_make_init_args())
        rid = json.loads(buf.getvalue())["result_id"]
        args = argparse.Namespace(
            result_id=rid, root_cause="x", lessons="y",
        )
        buf2 = io.StringIO()
        with contextlib.redirect_stdout(buf2):
            mod.cmd_analyze(args)
        return rid

    def test_share_advances_state(self):
        with isolated_cache():
            mod = _load()
            rid = self._make_analyzed(mod)
            import argparse, io, contextlib
            args = argparse.Namespace(
                result_id=rid, shared_via="preprint",
                url="https://example.org/preprint/abc",
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_share(args)
            self.assertEqual(json.loads(buf.getvalue())["state"], "shared")

    def test_share_invalid_via_raises(self):
        with isolated_cache():
            mod = _load()
            rid = self._make_analyzed(mod)
            import argparse
            args = argparse.Namespace(result_id=rid, shared_via="podcast", url=None)
            with self.assertRaises(SystemExit):
                mod.cmd_share(args)

    def test_share_before_analyze_raises(self):
        with isolated_cache():
            mod = _load()
            import argparse, io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_init(_make_init_args())
            rid = json.loads(buf.getvalue())["result_id"]
            args = argparse.Namespace(result_id=rid, shared_via="blog", url=None)
            with self.assertRaises(SystemExit):
                mod.cmd_share(args)


class StatusListTests(CoscientistTestCase):
    def test_status_returns_record(self):
        with isolated_cache():
            mod = _load()
            import argparse, io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_init(_make_init_args())
            rid = json.loads(buf.getvalue())["result_id"]

            args = argparse.Namespace(result_id=rid)
            buf2 = io.StringIO()
            with contextlib.redirect_stdout(buf2):
                mod.cmd_status(args)
            status = json.loads(buf2.getvalue())
            self.assertEqual(status["state"], "logged")
            self.assertIsNotNone(status["logged_at"])

    def test_list_empty(self):
        with isolated_cache():
            mod = _load()
            import argparse, io, contextlib
            args = argparse.Namespace(project_id=None, state=None)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_list(args)
            self.assertEqual(json.loads(buf.getvalue())["total"], 0)

    def test_list_after_two(self):
        with isolated_cache():
            mod = _load()
            import argparse, io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_init(_make_init_args(title="First Failure"))
                mod.cmd_init(_make_init_args(title="Second Failure"))

            args = argparse.Namespace(project_id=None, state=None)
            buf2 = io.StringIO()
            with contextlib.redirect_stdout(buf2):
                mod.cmd_list(args)
            self.assertEqual(json.loads(buf2.getvalue())["total"], 2)

    def test_list_filter_by_state(self):
        with isolated_cache():
            mod = _load()
            import argparse, io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_init(_make_init_args(title="Logged Only"))
            args = argparse.Namespace(project_id=None, state="analyzed")
            buf2 = io.StringIO()
            with contextlib.redirect_stdout(buf2):
                mod.cmd_list(args)
            self.assertEqual(json.loads(buf2.getvalue())["total"], 0)


class IntegrationTests(CoscientistTestCase):
    def test_full_lifecycle(self):
        with isolated_cache() as cache:
            mod = _load()
            import argparse, io, contextlib

            # Init
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_init(_make_init_args())
            rid = json.loads(buf.getvalue())["result_id"]

            # Analyze
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_analyze(argparse.Namespace(
                    result_id=rid,
                    root_cause="Insufficient depletion.",
                    lessons="Validate biochemistry first.",
                ))

            # Share
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_share(argparse.Namespace(
                    result_id=rid, shared_via="github", url="https://github.com/x/y",
                ))

            # Verify final state
            record = json.loads((cache / "negative_results" / rid / "result.json").read_text())
            self.assertEqual(record["state"], "shared")
            self.assertEqual(record["shared_via"], "github")
            self.assertIn("github.com", record["share_url"])

"""Tests for the experiment-design skill."""
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
        "design",
        _REPO_ROOT / ".claude/skills/experiment-design/scripts/design.py",
    )
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _init(mod, **overrides):
    import argparse, io, contextlib
    base = dict(
        title="Test X on Y",
        hypothesis="X improves Y by 10%",
        falsifier="X reduces Y by 5% (3 runs)",
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
            r = _init(mod)
            d = cache / "experiments" / r["experiment_id"]
            self.assertTrue((d / "manifest.json").exists())
            self.assertTrue((d / "protocol.json").exists())
            self.assertEqual(r["state"], "designed")

    def test_init_protocol_content(self):
        with isolated_cache() as cache:
            mod = _load()
            r = _init(mod, hypothesis="my hypothesis", falsifier="my falsifier")
            eid = r["experiment_id"]
            protocol = json.loads((cache / "experiments" / eid / "protocol.json").read_text())
            self.assertEqual(protocol["hypothesis"], "my hypothesis")
            self.assertEqual(protocol["falsifier"], "my falsifier")
            self.assertIsNone(protocol["primary_metric"])

    def test_init_empty_hypothesis_raises(self):
        with isolated_cache():
            mod = _load()
            with self.assertRaises(SystemExit):
                _init(mod, hypothesis=" ")

    def test_init_identical_hypothesis_falsifier_raises(self):
        with isolated_cache():
            mod = _load()
            with self.assertRaises(SystemExit):
                _init(mod, hypothesis="same", falsifier="same")

    def test_init_id_stable(self):
        mod = _load()
        self.assertEqual(
            mod.make_experiment_id("Same Title"),
            mod.make_experiment_id("Same Title"),
        )

    def test_init_duplicate_raises(self):
        with isolated_cache():
            mod = _load()
            _init(mod)
            with self.assertRaises(SystemExit):
                _init(mod)

    def test_init_force_overwrites(self):
        with isolated_cache():
            mod = _load()
            _init(mod)
            r = _init(mod, force=True)
            self.assertIn("experiment_id", r)


class VariableTests(CoscientistTestCase):
    def test_add_independent_variable(self):
        with isolated_cache():
            mod = _load()
            eid = _init(mod)["experiment_id"]
            import argparse, io, contextlib
            args = argparse.Namespace(
                experiment_id=eid, kind="independent",
                name="method", description="X vs baseline"
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_variable(args)
            self.assertEqual(json.loads(buf.getvalue())["total_in_kind"], 1)

    def test_add_three_kinds(self):
        with isolated_cache():
            mod = _load()
            eid = _init(mod)["experiment_id"]
            import argparse, io, contextlib
            for kind in ("independent", "dependent", "control"):
                args = argparse.Namespace(
                    experiment_id=eid, kind=kind,
                    name=f"v_{kind}", description=""
                )
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    mod.cmd_variable(args)
            protocol = mod._load_protocol(eid)
            self.assertEqual(len(protocol["variables"]["independent"]), 1)
            self.assertEqual(len(protocol["variables"]["dependent"]), 1)
            self.assertEqual(len(protocol["variables"]["control"]), 1)

    def test_add_duplicate_name_in_kind_raises(self):
        with isolated_cache():
            mod = _load()
            eid = _init(mod)["experiment_id"]
            import argparse, io, contextlib
            args = argparse.Namespace(
                experiment_id=eid, kind="independent",
                name="x", description=""
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_variable(args)
            with self.assertRaises(SystemExit):
                mod.cmd_variable(args)

    def test_invalid_kind_raises(self):
        with isolated_cache():
            mod = _load()
            eid = _init(mod)["experiment_id"]
            import argparse
            args = argparse.Namespace(
                experiment_id=eid, kind="bogus",
                name="x", description=""
            )
            with self.assertRaises(SystemExit):
                mod.cmd_variable(args)


class MetricTests(CoscientistTestCase):
    def test_set_metric(self):
        with isolated_cache():
            mod = _load()
            eid = _init(mod)["experiment_id"]
            import argparse, io, contextlib
            args = argparse.Namespace(
                experiment_id=eid, name="accuracy",
                type="scalar", target=0.85, comparison=">="
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_metric(args)
            r = json.loads(buf.getvalue())
            self.assertEqual(r["primary_metric"]["name"], "accuracy")
            self.assertEqual(r["primary_metric"]["target"], 0.85)

    def test_metric_replaces(self):
        """Single-metric discipline — second call replaces."""
        with isolated_cache():
            mod = _load()
            eid = _init(mod)["experiment_id"]
            import argparse, io, contextlib
            for name, target in [("acc", 0.8), ("f1", 0.9)]:
                args = argparse.Namespace(
                    experiment_id=eid, name=name,
                    type="scalar", target=target, comparison=">="
                )
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    mod.cmd_metric(args)
            protocol = mod._load_protocol(eid)
            self.assertEqual(protocol["primary_metric"]["name"], "f1")

    def test_invalid_comparison_raises(self):
        with isolated_cache():
            mod = _load()
            eid = _init(mod)["experiment_id"]
            import argparse
            args = argparse.Namespace(
                experiment_id=eid, name="x",
                type="scalar", target=1.0, comparison="!~"
            )
            with self.assertRaises(SystemExit):
                mod.cmd_metric(args)


class PreregisterTests(CoscientistTestCase):
    def _full_setup(self, mod):
        import argparse, io, contextlib
        eid = _init(mod)["experiment_id"]
        for kind, name in [("independent", "method"), ("dependent", "accuracy")]:
            args = argparse.Namespace(
                experiment_id=eid, kind=kind, name=name, description=""
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_variable(args)
        margs = argparse.Namespace(
            experiment_id=eid, name="accuracy",
            type="scalar", target=0.85, comparison=">="
        )
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            mod.cmd_metric(margs)
        return eid

    def test_preregister_passes_with_full_setup(self):
        with isolated_cache() as cache:
            mod = _load()
            eid = self._full_setup(mod)
            import argparse, io, contextlib
            args = argparse.Namespace(
                experiment_id=eid, rr_id=None,
                budget_seconds=3600, memory_mb=4096, force=False
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_preregister(args)
            r = json.loads(buf.getvalue())
            self.assertEqual(r["state"], "preregistered")
            prereg_md = cache / "experiments" / eid / "preregistration.md"
            self.assertTrue(prereg_md.exists())
            self.assertIn("Hypothesis", prereg_md.read_text())

    def test_preregister_fails_without_metric(self):
        with isolated_cache():
            mod = _load()
            eid = _init(mod)["experiment_id"]
            # Add vars but no metric
            import argparse, io, contextlib
            for kind, name in [("independent", "x"), ("dependent", "y")]:
                args = argparse.Namespace(
                    experiment_id=eid, kind=kind, name=name, description=""
                )
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    mod.cmd_variable(args)
            args = argparse.Namespace(
                experiment_id=eid, rr_id=None,
                budget_seconds=3600, memory_mb=4096, force=False
            )
            with self.assertRaises(SystemExit):
                mod.cmd_preregister(args)

    def test_preregister_fails_no_independent(self):
        with isolated_cache():
            mod = _load()
            eid = _init(mod)["experiment_id"]
            import argparse, io, contextlib
            # Only dependent + metric
            args = argparse.Namespace(
                experiment_id=eid, kind="dependent", name="y", description=""
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_variable(args)
            margs = argparse.Namespace(
                experiment_id=eid, name="y", type="scalar", target=1.0, comparison=">="
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_metric(margs)
            args2 = argparse.Namespace(
                experiment_id=eid, rr_id=None,
                budget_seconds=3600, memory_mb=4096, force=False
            )
            with self.assertRaises(SystemExit):
                mod.cmd_preregister(args2)

    def test_preregister_fails_zero_budget(self):
        with isolated_cache():
            mod = _load()
            eid = self._full_setup(mod)
            import argparse
            args = argparse.Namespace(
                experiment_id=eid, rr_id=None,
                budget_seconds=0, memory_mb=4096, force=False
            )
            with self.assertRaises(SystemExit):
                mod.cmd_preregister(args)

    def test_preregister_idempotent_via_force(self):
        with isolated_cache():
            mod = _load()
            eid = self._full_setup(mod)
            import argparse, io, contextlib
            args = argparse.Namespace(
                experiment_id=eid, rr_id=None,
                budget_seconds=3600, memory_mb=4096, force=False
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_preregister(args)
            # Second call without force should fail
            with self.assertRaises(SystemExit):
                mod.cmd_preregister(args)
            # With force, succeeds
            args.force = True
            buf2 = io.StringIO()
            with contextlib.redirect_stdout(buf2):
                mod.cmd_preregister(args)
            self.assertEqual(json.loads(buf2.getvalue())["state"], "preregistered")

    def test_preregister_with_rr_link(self):
        with isolated_cache() as cache:
            mod = _load()
            eid = self._full_setup(mod)
            # Create fake RR
            rr_dir = cache / "registered_reports" / "fake_rr_xyz"
            rr_dir.mkdir(parents=True)
            (rr_dir / "manifest.json").write_text(json.dumps({
                "rr_id": "fake_rr_xyz", "title": "Linked RR",
                "state": "stage-1-drafted", "created_at": "2026-04-27T10:00:00+00:00"
            }))
            import argparse, io, contextlib
            args = argparse.Namespace(
                experiment_id=eid, rr_id="fake_rr_xyz",
                budget_seconds=3600, memory_mb=4096, force=False
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_preregister(args)
            r = json.loads(buf.getvalue())
            self.assertEqual(r["linked_rr"], "fake_rr_xyz")

    def test_preregister_unknown_rr_raises(self):
        with isolated_cache():
            mod = _load()
            eid = self._full_setup(mod)
            import argparse
            args = argparse.Namespace(
                experiment_id=eid, rr_id="nonexistent_rr",
                budget_seconds=3600, memory_mb=4096, force=False
            )
            with self.assertRaises(SystemExit):
                mod.cmd_preregister(args)


class StatusListTests(CoscientistTestCase):
    def test_status_shows_completeness(self):
        with isolated_cache():
            mod = _load()
            eid = _init(mod)["experiment_id"]
            import argparse, io, contextlib
            args = argparse.Namespace(experiment_id=eid)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_status(args)
            r = json.loads(buf.getvalue())
            self.assertEqual(r["state"], "designed")
            self.assertTrue(r["completeness"]["hypothesis_set"])
            self.assertFalse(r["completeness"]["primary_metric_set"])
            self.assertFalse(r["completeness"]["ready_to_preregister"])

    def test_status_ready_when_complete(self):
        with isolated_cache():
            mod = _load()
            eid = _init(mod)["experiment_id"]
            import argparse, io, contextlib
            for kind, name in [("independent", "m"), ("dependent", "y")]:
                args = argparse.Namespace(
                    experiment_id=eid, kind=kind, name=name, description=""
                )
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    mod.cmd_variable(args)
            margs = argparse.Namespace(
                experiment_id=eid, name="y", type="scalar", target=1.0, comparison=">="
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_metric(margs)

            buf2 = io.StringIO()
            with contextlib.redirect_stdout(buf2):
                mod.cmd_status(argparse.Namespace(experiment_id=eid))
            r = json.loads(buf2.getvalue())
            self.assertTrue(r["completeness"]["ready_to_preregister"])

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
            _init(mod, title="A")
            _init(mod, title="B")
            import argparse, io, contextlib
            args = argparse.Namespace(project_id=None, state=None)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_list(args)
            self.assertEqual(json.loads(buf.getvalue())["total"], 2)

    def test_list_filter_by_state(self):
        with isolated_cache():
            mod = _load()
            _init(mod, title="A")
            import argparse, io, contextlib
            args = argparse.Namespace(project_id=None, state="preregistered")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_list(args)
            self.assertEqual(json.loads(buf.getvalue())["total"], 0)

"""Tests for the project-manager skill."""
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
        "manage",
        _REPO_ROOT / ".claude/skills/project-manager/scripts/manage.py",
    )
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _init(mod, name="My Project", **kw):
    import argparse
    import contextlib
    import io
    args = argparse.Namespace(name=name, question=kw.get("question"), description=kw.get("description"))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        mod.cmd_init(args)
    return json.loads(buf.getvalue())


class InitListTests(CoscientistTestCase):
    def test_init_creates_project(self):
        with isolated_cache():
            mod = _load()
            r = _init(mod, name="Thesis Plan", question="What's the question?")
            self.assertIn("project_id", r)
            self.assertEqual(r["name"], "Thesis Plan")

    def test_init_idempotent(self):
        with isolated_cache():
            mod = _load()
            r1 = _init(mod, name="Same Name")
            r2 = _init(mod, name="Same Name")
            self.assertEqual(r1["project_id"], r2["project_id"])

    def test_init_empty_name_raises(self):
        with isolated_cache():
            mod = _load()
            with self.assertRaises(SystemExit):
                _init(mod, name="  ")

    def test_list_empty(self):
        with isolated_cache():
            mod = _load()
            import argparse
            import contextlib
            import io
            args = argparse.Namespace(include_archived=False)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_list(args)
            r = json.loads(buf.getvalue())
            self.assertEqual(r["total"], 0)
            self.assertIsNone(r["active_project_id"])

    def test_list_after_init(self):
        with isolated_cache():
            mod = _load()
            _init(mod, name="P1")
            _init(mod, name="P2")
            import argparse
            import contextlib
            import io
            args = argparse.Namespace(include_archived=False)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_list(args)
            r = json.loads(buf.getvalue())
            self.assertEqual(r["total"], 2)


class ActiveMarkerTests(CoscientistTestCase):
    def test_activate(self):
        with isolated_cache() as cache:
            mod = _load()
            r = _init(mod, name="To Activate")
            pid = r["project_id"]
            import argparse
            import contextlib
            import io
            args = argparse.Namespace(project_id=pid)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_activate(args)
            self.assertTrue(json.loads(buf.getvalue())["active"])
            self.assertEqual(mod.get_active_project_id(), pid)

    def test_activate_unknown_raises(self):
        with isolated_cache():
            mod = _load()
            import argparse
            args = argparse.Namespace(project_id="nonexistent")
            with self.assertRaises(SystemExit):
                mod.cmd_activate(args)

    def test_current_no_active(self):
        with isolated_cache():
            mod = _load()
            import argparse
            import contextlib
            import io
            args = argparse.Namespace()
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_current(args)
            self.assertIsNone(json.loads(buf.getvalue())["active_project_id"])

    def test_current_after_activate(self):
        with isolated_cache():
            mod = _load()
            r = _init(mod, name="Active One")
            pid = r["project_id"]
            import argparse
            import contextlib
            import io
            mod.cmd_activate(argparse.Namespace(project_id=pid))
            args = argparse.Namespace()
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_current(args)
            r2 = json.loads(buf.getvalue())
            self.assertEqual(r2["project_id"], pid)
            self.assertTrue(r2["exists"])

    def test_deactivate(self):
        with isolated_cache():
            mod = _load()
            r = _init(mod)
            pid = r["project_id"]
            import argparse
            import contextlib
            import io
            mod.cmd_activate(argparse.Namespace(project_id=pid))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_deactivate(argparse.Namespace())
            r2 = json.loads(buf.getvalue())
            self.assertTrue(r2["deactivated"])
            self.assertEqual(r2["previous_project_id"], pid)
            self.assertIsNone(mod.get_active_project_id())

    def test_deactivate_when_none_active(self):
        with isolated_cache():
            mod = _load()
            import argparse
            import contextlib
            import io
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_deactivate(argparse.Namespace())
            r = json.loads(buf.getvalue())
            self.assertTrue(r["deactivated"])
            self.assertIsNone(r["previous_project_id"])


class ArchiveTests(CoscientistTestCase):
    def test_archive_excludes_from_default_list(self):
        with isolated_cache():
            mod = _load()
            r1 = _init(mod, name="Active")
            r2 = _init(mod, name="To Archive")
            import argparse
            import contextlib
            import io
            mod.cmd_archive(argparse.Namespace(project_id=r2["project_id"]))

            args = argparse.Namespace(include_archived=False)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_list(args)
            self.assertEqual(json.loads(buf.getvalue())["total"], 1)

    def test_archive_includes_when_flag_set(self):
        with isolated_cache():
            mod = _load()
            r = _init(mod, name="To Archive")
            import argparse
            import contextlib
            import io
            mod.cmd_archive(argparse.Namespace(project_id=r["project_id"]))

            args = argparse.Namespace(include_archived=True)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_list(args)
            self.assertEqual(json.loads(buf.getvalue())["total"], 1)

    def test_archive_double_raises(self):
        with isolated_cache():
            mod = _load()
            r = _init(mod)
            import argparse
            mod.cmd_archive(argparse.Namespace(project_id=r["project_id"]))
            with self.assertRaises(SystemExit):
                mod.cmd_archive(argparse.Namespace(project_id=r["project_id"]))

    def test_unarchive_restores(self):
        with isolated_cache():
            mod = _load()
            r = _init(mod)
            import argparse
            import contextlib
            import io
            mod.cmd_archive(argparse.Namespace(project_id=r["project_id"]))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_unarchive(argparse.Namespace(project_id=r["project_id"]))
            self.assertIsNone(json.loads(buf.getvalue())["archived_at"])

    def test_unarchive_non_archived_raises(self):
        with isolated_cache():
            mod = _load()
            r = _init(mod)
            import argparse
            with self.assertRaises(SystemExit):
                mod.cmd_unarchive(argparse.Namespace(project_id=r["project_id"]))

    def test_archiving_active_deactivates(self):
        with isolated_cache():
            mod = _load()
            r = _init(mod)
            pid = r["project_id"]
            import argparse
            import contextlib
            import io
            mod.cmd_activate(argparse.Namespace(project_id=pid))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_archive(argparse.Namespace(project_id=pid))
            self.assertTrue(json.loads(buf.getvalue())["deactivated"])
            self.assertIsNone(mod.get_active_project_id())

    def test_activate_archived_raises(self):
        with isolated_cache():
            mod = _load()
            r = _init(mod)
            import argparse
            mod.cmd_archive(argparse.Namespace(project_id=r["project_id"]))
            with self.assertRaises(SystemExit):
                mod.cmd_activate(argparse.Namespace(project_id=r["project_id"]))


class StatusTests(CoscientistTestCase):
    def test_status_shows_metadata(self):
        with isolated_cache():
            mod = _load()
            r = _init(mod, name="Status Test", question="Q", description="D")
            import argparse
            import contextlib
            import io
            args = argparse.Namespace(project_id=r["project_id"])
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_status(args)
            data = json.loads(buf.getvalue())
            self.assertEqual(data["name"], "Status Test")
            self.assertEqual(data["question"], "Q")
            self.assertFalse(data["is_active"])
            self.assertIn("artifact_counts", data)

    def test_status_active_flag(self):
        with isolated_cache():
            mod = _load()
            r = _init(mod)
            pid = r["project_id"]
            import argparse
            import contextlib
            import io
            mod.cmd_activate(argparse.Namespace(project_id=pid))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_status(argparse.Namespace(project_id=pid))
            self.assertTrue(json.loads(buf.getvalue())["is_active"])

    def test_status_unknown_raises(self):
        with isolated_cache():
            mod = _load()
            import argparse
            with self.assertRaises(SystemExit):
                mod.cmd_status(argparse.Namespace(project_id="nonexistent"))


class HelperTests(CoscientistTestCase):
    def test_get_active_returns_none_initially(self):
        with isolated_cache():
            mod = _load()
            self.assertIsNone(mod.get_active_project_id())

    def test_get_active_returns_pid_after_activate(self):
        with isolated_cache():
            mod = _load()
            r = _init(mod)
            import argparse
            mod.cmd_activate(argparse.Namespace(project_id=r["project_id"]))
            self.assertEqual(mod.get_active_project_id(), r["project_id"])

"""Tests for the credit-tracker skill."""
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
        "track",
        _REPO_ROOT / ".claude/skills/credit-tracker/scripts/track.py",
    )
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _assign(mod, mid, author, roles_csv):
    import argparse, io, contextlib
    args = argparse.Namespace(manuscript_id=mid, author=author, roles=roles_csv)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        mod.cmd_assign(args)
    return json.loads(buf.getvalue())


class AssignTests(CoscientistTestCase):
    def test_assign_single_role(self):
        with isolated_cache():
            mod = _load()
            result = _assign(mod, "ms_test", "Alice", "conceptualization")
            self.assertEqual(result["roles"], ["conceptualization"])

    def test_assign_multiple_roles(self):
        with isolated_cache():
            mod = _load()
            result = _assign(mod, "ms_test", "Alice", "conceptualization,methodology,software")
            self.assertEqual(set(result["roles"]),
                             {"conceptualization", "methodology", "software"})

    def test_assign_dedupes_roles(self):
        with isolated_cache():
            mod = _load()
            result = _assign(mod, "ms_test", "Alice",
                             "conceptualization,methodology,conceptualization")
            self.assertEqual(result["roles"].count("conceptualization"), 1)

    def test_assign_merges_with_existing(self):
        with isolated_cache():
            mod = _load()
            _assign(mod, "ms_test", "Alice", "conceptualization")
            result = _assign(mod, "ms_test", "Alice", "methodology")
            self.assertEqual(set(result["roles"]),
                             {"conceptualization", "methodology"})

    def test_assign_unknown_role_raises(self):
        with isolated_cache():
            mod = _load()
            with self.assertRaises(SystemExit):
                _assign(mod, "ms_test", "Alice", "fake-role")

    def test_assign_empty_roles_raises(self):
        with isolated_cache():
            mod = _load()
            with self.assertRaises(SystemExit):
                _assign(mod, "ms_test", "Alice", "")

    def test_assign_empty_author_raises(self):
        with isolated_cache():
            mod = _load()
            with self.assertRaises(SystemExit):
                _assign(mod, "ms_test", "  ", "conceptualization")

    def test_assign_persists_across_calls(self):
        with isolated_cache() as cache:
            mod = _load()
            _assign(mod, "ms_persist", "Alice", "conceptualization")
            _assign(mod, "ms_persist", "Bob", "investigation")
            data = mod._load("ms_persist")
            self.assertEqual(set(data.keys()), {"Alice", "Bob"})


class UnassignTests(CoscientistTestCase):
    def test_unassign_specific_role(self):
        with isolated_cache():
            mod = _load()
            _assign(mod, "ms_un", "Alice", "conceptualization,methodology")
            import argparse, io, contextlib
            args = argparse.Namespace(
                manuscript_id="ms_un", author="Alice", roles="methodology"
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_unassign(args)
            data = mod._load("ms_un")
            self.assertEqual(data["Alice"], ["conceptualization"])

    def test_unassign_all_removes_author(self):
        with isolated_cache():
            mod = _load()
            _assign(mod, "ms_all", "Alice", "conceptualization")
            import argparse, io, contextlib
            args = argparse.Namespace(
                manuscript_id="ms_all", author="Alice", roles=None
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_unassign(args)
            data = mod._load("ms_all")
            self.assertNotIn("Alice", data)

    def test_unassign_unknown_author_raises(self):
        with isolated_cache():
            mod = _load()
            import argparse
            args = argparse.Namespace(
                manuscript_id="ms_no_author", author="Ghost", roles=None
            )
            with self.assertRaises(SystemExit):
                mod.cmd_unassign(args)

    def test_unassign_last_role_removes_author(self):
        with isolated_cache():
            mod = _load()
            _assign(mod, "ms_last", "Alice", "methodology")
            import argparse, io, contextlib
            args = argparse.Namespace(
                manuscript_id="ms_last", author="Alice", roles="methodology"
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_unassign(args)
            data = mod._load("ms_last")
            self.assertNotIn("Alice", data)


class AuditTests(CoscientistTestCase):
    def test_audit_passes_with_required_roles(self):
        with isolated_cache():
            mod = _load()
            _assign(mod, "ms_pass", "Alice",
                    "conceptualization,methodology,writing-original-draft")
            import argparse, io, contextlib
            args = argparse.Namespace(manuscript_id="ms_pass")
            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf):
                    mod.cmd_audit(args)
                code = 0
            except SystemExit as e:
                code = e.code
            result = json.loads(buf.getvalue())
            self.assertTrue(result["passed"])
            self.assertEqual(result["missing_required_roles"], [])

    def test_audit_fails_missing_required(self):
        with isolated_cache():
            mod = _load()
            _assign(mod, "ms_fail", "Alice", "conceptualization")
            import argparse, io, contextlib
            args = argparse.Namespace(manuscript_id="ms_fail")
            buf = io.StringIO()
            with self.assertRaises(SystemExit):
                with contextlib.redirect_stdout(buf):
                    mod.cmd_audit(args)
            result = json.loads(buf.getvalue())
            self.assertFalse(result["passed"])
            self.assertIn("methodology", result["missing_required_roles"])

    def test_audit_flags_recommended(self):
        with isolated_cache():
            mod = _load()
            _assign(mod, "ms_rec", "Alice",
                    "conceptualization,methodology,writing-original-draft")
            import argparse, io, contextlib
            args = argparse.Namespace(manuscript_id="ms_rec")
            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf):
                    mod.cmd_audit(args)
            except SystemExit:
                pass
            result = json.loads(buf.getvalue())
            self.assertIn("formal-analysis", result["missing_recommended_roles"])

    def test_audit_role_coverage_count(self):
        with isolated_cache():
            mod = _load()
            _assign(mod, "ms_cov", "Alice", "conceptualization,methodology,writing-original-draft")
            _assign(mod, "ms_cov", "Bob", "methodology,investigation")
            import argparse, io, contextlib
            args = argparse.Namespace(manuscript_id="ms_cov")
            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf):
                    mod.cmd_audit(args)
            except SystemExit:
                pass
            result = json.loads(buf.getvalue())
            self.assertEqual(result["role_coverage"]["methodology"], 2)
            self.assertEqual(result["role_coverage"]["investigation"], 1)
            self.assertEqual(result["total_authors"], 2)


class StatementTests(CoscientistTestCase):
    def test_statement_narrative(self):
        with isolated_cache():
            mod = _load()
            _assign(mod, "ms_stmt", "Alice",
                    "conceptualization,methodology")
            import argparse, io, contextlib
            args = argparse.Namespace(manuscript_id="ms_stmt", style="narrative")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_statement(args)
            output = buf.getvalue()
            self.assertIn("**Alice**", output)
            self.assertIn("Conceptualization", output)
            self.assertIn("Methodology", output)

    def test_statement_table(self):
        with isolated_cache():
            mod = _load()
            _assign(mod, "ms_tbl", "Alice", "conceptualization")
            _assign(mod, "ms_tbl", "Bob", "investigation")
            import argparse, io, contextlib
            args = argparse.Namespace(manuscript_id="ms_tbl", style="table")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_statement(args)
            output = buf.getvalue()
            self.assertIn("| Author |", output)
            self.assertIn("Alice", output)
            self.assertIn("Bob", output)
            self.assertIn("✓", output)

    def test_statement_empty_raises(self):
        with isolated_cache():
            mod = _load()
            import argparse
            args = argparse.Namespace(manuscript_id="ms_empty", style="narrative")
            with self.assertRaises(SystemExit):
                mod.cmd_statement(args)


class RolesListTests(CoscientistTestCase):
    def test_roles_returns_14(self):
        with isolated_cache():
            mod = _load()
            import argparse, io, contextlib
            args = argparse.Namespace()
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_roles(args)
            result = json.loads(buf.getvalue())
            self.assertEqual(len(result["roles"]), 14)
            self.assertEqual(len(result["required"]), 3)
            self.assertEqual(len(result["recommended"]), 3)

    def test_roles_required_subset_of_all(self):
        with isolated_cache():
            mod = _load()
            self.assertTrue(mod.REQUIRED_ROLES.issubset(set(mod.CREDIT_ROLES)))
            self.assertTrue(mod.RECOMMENDED_ROLES.issubset(set(mod.CREDIT_ROLES)))


class ListTests(CoscientistTestCase):
    def test_list_empty(self):
        with isolated_cache():
            mod = _load()
            import argparse, io, contextlib
            args = argparse.Namespace(manuscript_id="ms_nothing")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_list(args)
            self.assertEqual(json.loads(buf.getvalue())["total_authors"], 0)

    def test_list_after_assign(self):
        with isolated_cache():
            mod = _load()
            _assign(mod, "ms_list", "Alice", "conceptualization")
            _assign(mod, "ms_list", "Bob", "investigation")
            import argparse, io, contextlib
            args = argparse.Namespace(manuscript_id="ms_list")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_list(args)
            result = json.loads(buf.getvalue())
            self.assertEqual(result["total_authors"], 2)
            self.assertIn("Alice", result["authors"])

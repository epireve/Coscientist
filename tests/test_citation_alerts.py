"""Tests for the citation-alerts skill."""
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
        _REPO_ROOT / ".claude/skills/citation-alerts/scripts/track.py",
    )
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _add(mod, project_id, canonical_id, label=None):
    import argparse
    import contextlib
    import io
    args = argparse.Namespace(
        project_id=project_id, canonical_id=canonical_id, label=label
    )
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        mod.cmd_add(args)
    return json.loads(buf.getvalue())


class AddRemoveTests(CoscientistTestCase):
    def test_add_creates_tracked(self):
        with isolated_cache():
            mod = _load()
            r = _add(mod, "p1", "smith_2023_x", label="My Paper")
            self.assertEqual(r["tracked_count"], 1)

    def test_add_duplicate_raises(self):
        with isolated_cache():
            mod = _load()
            _add(mod, "p1", "smith_2023_x")
            with self.assertRaises(SystemExit):
                _add(mod, "p1", "smith_2023_x")

    def test_remove_decrements(self):
        with isolated_cache():
            mod = _load()
            _add(mod, "p1", "smith_2023_x")
            _add(mod, "p1", "jones_2024_y")
            import argparse
            import contextlib
            import io
            args = argparse.Namespace(project_id="p1", canonical_id="smith_2023_x")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_remove(args)
            r = json.loads(buf.getvalue())
            self.assertEqual(r["tracked_count"], 1)

    def test_remove_unknown_raises(self):
        with isolated_cache():
            mod = _load()
            import argparse
            args = argparse.Namespace(project_id="p1", canonical_id="ghost")
            with self.assertRaises(SystemExit):
                mod.cmd_remove(args)


class ListTrackedTests(CoscientistTestCase):
    def test_list_empty(self):
        with isolated_cache():
            mod = _load()
            import argparse
            import contextlib
            import io
            args = argparse.Namespace(project_id="p1")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_list_tracked(args)
            self.assertEqual(json.loads(buf.getvalue())["total"], 0)

    def test_list_after_adds(self):
        with isolated_cache():
            mod = _load()
            _add(mod, "p1", "a")
            _add(mod, "p1", "b")
            import argparse
            import contextlib
            import io
            args = argparse.Namespace(project_id="p1")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_list_tracked(args)
            self.assertEqual(json.loads(buf.getvalue())["total"], 2)


class ListCheckTests(CoscientistTestCase):
    def test_list_unchecked_returns_to_check(self):
        with isolated_cache():
            mod = _load()
            _add(mod, "p1", "a")
            _add(mod, "p1", "b")
            import argparse
            import contextlib
            import io
            args = argparse.Namespace(project_id="p1", max_age_days=7)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_list(args)
            r = json.loads(buf.getvalue())
            self.assertEqual(len(r["to_check"]), 2)
            self.assertEqual(r["already_current"], 0)


class PersistTests(CoscientistTestCase):
    def _setup(self, mod):
        _add(mod, "p1", "a", label="Paper A")
        _add(mod, "p1", "b", label="Paper B")

    def test_persist_records_new_citers(self):
        with isolated_cache() as cache:
            mod = _load()
            self._setup(mod)
            results = [
                {
                    "canonical_id": "a",
                    "citers": [
                        {"canonical_id": "x", "title": "Citer X", "year": 2024},
                        {"canonical_id": "y", "title": "Citer Y", "year": 2024},
                    ],
                },
                {"canonical_id": "b", "citers": []},
            ]
            input_path = cache / "results.json"
            input_path.write_text(json.dumps(results))

            import argparse
            import contextlib
            import io
            args = argparse.Namespace(project_id="p1", input=str(input_path))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_persist(args)
            r = json.loads(buf.getvalue())
            self.assertEqual(r["new_citers_total"], 2)
            self.assertEqual(r["saved"], 2)

    def test_persist_idempotent(self):
        """Re-persisting same citers should not duplicate."""
        with isolated_cache() as cache:
            mod = _load()
            self._setup(mod)
            results = [{
                "canonical_id": "a",
                "citers": [{"canonical_id": "x", "title": "Citer X", "year": 2024}],
            }]
            input_path = cache / "results.json"
            input_path.write_text(json.dumps(results))

            import argparse
            import contextlib
            import io
            args = argparse.Namespace(project_id="p1", input=str(input_path))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_persist(args)
            self.assertEqual(json.loads(buf.getvalue())["new_citers_total"], 1)

            # Re-run with same data
            buf2 = io.StringIO()
            with contextlib.redirect_stdout(buf2):
                mod.cmd_persist(args)
            self.assertEqual(json.loads(buf2.getvalue())["new_citers_total"], 0)

    def test_persist_detects_new_citers(self):
        with isolated_cache() as cache:
            mod = _load()
            self._setup(mod)
            # Round 1: one citer
            results1 = [{"canonical_id": "a", "citers": [
                {"canonical_id": "x", "title": "X", "year": 2024}
            ]}]
            p1 = cache / "r1.json"
            p1.write_text(json.dumps(results1))
            import argparse
            import contextlib
            import io
            mod.cmd_persist(argparse.Namespace(project_id="p1", input=str(p1)))

            # Round 2: two citers (one new)
            results2 = [{"canonical_id": "a", "citers": [
                {"canonical_id": "x", "title": "X", "year": 2024},
                {"canonical_id": "z", "title": "Z", "year": 2025},
            ]}]
            p2 = cache / "r2.json"
            p2.write_text(json.dumps(results2))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_persist(argparse.Namespace(project_id="p1", input=str(p2)))
            r = json.loads(buf.getvalue())
            self.assertEqual(r["new_citers_total"], 1)

    def test_persist_invalid_format_raises(self):
        with isolated_cache() as cache:
            mod = _load()
            p = cache / "bad.json"
            p.write_text(json.dumps({"not": "a list"}))
            import argparse
            args = argparse.Namespace(project_id="p1", input=str(p))
            with self.assertRaises(SystemExit):
                mod.cmd_persist(args)


class DigestTests(CoscientistTestCase):
    def test_digest_lists_recent_citers(self):
        with isolated_cache() as cache:
            mod = _load()
            _add(mod, "p1", "a", label="Paper A")

            # Persist with one citer
            results = [{"canonical_id": "a", "citers": [
                {"canonical_id": "x", "title": "Citer X", "year": 2024}
            ]}]
            p = cache / "r.json"
            p.write_text(json.dumps(results))
            import argparse
            import contextlib
            import io
            mod.cmd_persist(argparse.Namespace(project_id="p1", input=str(p)))

            # Digest with 30-day window
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_digest(argparse.Namespace(project_id="p1", since_days=30))
            r = json.loads(buf.getvalue())
            self.assertEqual(r["new_citers_total"], 1)
            self.assertEqual(r["papers_with_new_citers"], 1)
            digest_path = Path(r["digest_path"])
            self.assertTrue(digest_path.exists())


class StatusTests(CoscientistTestCase):
    def test_status_empty(self):
        with isolated_cache():
            mod = _load()
            import argparse
            import contextlib
            import io
            args = argparse.Namespace(project_id="p1")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_status(args)
            r = json.loads(buf.getvalue())
            self.assertEqual(r["tracked_papers"], 0)
            self.assertEqual(r["total_citers"], 0)

    def test_status_after_persist(self):
        with isolated_cache() as cache:
            mod = _load()
            _add(mod, "p1", "a")
            results = [{"canonical_id": "a", "citers": [
                {"canonical_id": "x", "title": "X", "year": 2024},
                {"canonical_id": "y", "title": "Y", "year": 2024},
            ]}]
            p = cache / "r.json"
            p.write_text(json.dumps(results))
            import argparse
            import contextlib
            import io
            mod.cmd_persist(argparse.Namespace(project_id="p1", input=str(p)))

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_status(argparse.Namespace(project_id="p1"))
            r = json.loads(buf.getvalue())
            self.assertEqual(r["tracked_papers"], 1)
            self.assertEqual(r["total_citers"], 2)
            self.assertIsNotNone(r["most_recent_check"])

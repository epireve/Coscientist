"""Tests for the dataset-agent skill."""
from __future__ import annotations

import importlib.util as _ilu
import json
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

from tests.harness import CoscientistTestCase, isolated_cache  # noqa


def _load():
    spec = _ilu.spec_from_file_location(
        "register",
        _REPO_ROOT / ".claude/skills/dataset-agent/scripts/register.py",
    )
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_register_args(**overrides):
    import argparse
    base = dict(
        title="Brain MRI Cohort 2024",
        description="N=200 healthy controls, T1+T2 weighted MRI scans.",
        license="CC-BY-4.0",
        source_url=None,
        doi=None,
        paths=[],
        project_id=None,
        force=False,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


class RegisterTests(CoscientistTestCase):
    def test_register_creates_files(self):
        with isolated_cache() as cache:
            mod = _load()
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_register(_make_register_args())
            result = json.loads(buf.getvalue())
            did = result["dataset_id"]
            dd = cache / "datasets" / did
            self.assertTrue((dd / "manifest.json").exists())
            self.assertTrue((dd / "dataset.json").exists())
            self.assertTrue((dd / "versions.json").exists())

    def test_register_known_license_no_warning(self):
        with isolated_cache():
            mod = _load()
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_register(_make_register_args(license="MIT"))
            self.assertEqual(json.loads(buf.getvalue())["license_warnings"], [])

    def test_register_unknown_license_warns(self):
        with isolated_cache():
            mod = _load()
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_register(_make_register_args(license="MyCustomLicense"))
            warnings = json.loads(buf.getvalue())["license_warnings"]
            self.assertTrue(len(warnings) > 0)

    def test_register_duplicate_raises(self):
        with isolated_cache():
            mod = _load()
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_register(_make_register_args())
            with self.assertRaises(SystemExit):
                mod.cmd_register(_make_register_args())

    def test_register_force_overwrites(self):
        with isolated_cache():
            mod = _load()
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_register(_make_register_args())
            buf2 = io.StringIO()
            with contextlib.redirect_stdout(buf2):
                mod.cmd_register(_make_register_args(force=True))
            self.assertIn("dataset_id", json.loads(buf2.getvalue()))

    def test_id_stable(self):
        mod = _load()
        self.assertEqual(
            mod.make_dataset_id("Foo Bar"),
            mod.make_dataset_id("Foo Bar"),
        )


class HashTests(CoscientistTestCase):
    def test_hash_single_file(self):
        with isolated_cache() as cache:
            with tempfile.TemporaryDirectory() as td:
                f = Path(td) / "data.csv"
                f.write_text("col1,col2\n1,2\n3,4\n")

                mod = _load()
                import io, contextlib, argparse
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    mod.cmd_register(_make_register_args(paths=[str(f)]))
                did = json.loads(buf.getvalue())["dataset_id"]

                buf2 = io.StringIO()
                with contextlib.redirect_stdout(buf2):
                    mod.cmd_hash(argparse.Namespace(
                        dataset_id=did, algorithm="sha256", force_large=False
                    ))
                result = json.loads(buf2.getvalue())
                self.assertEqual(result["files_hashed"], 1)
                self.assertEqual(len(result["combined_hash"]), 64)  # sha256 hex length

    def test_hash_directory_recursive(self):
        with isolated_cache():
            with tempfile.TemporaryDirectory() as td:
                base = Path(td)
                (base / "a.txt").write_text("alpha")
                sub = base / "sub"
                sub.mkdir()
                (sub / "b.txt").write_text("beta")

                mod = _load()
                import io, contextlib, argparse
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    mod.cmd_register(_make_register_args(paths=[str(base)]))
                did = json.loads(buf.getvalue())["dataset_id"]

                buf2 = io.StringIO()
                with contextlib.redirect_stdout(buf2):
                    mod.cmd_hash(argparse.Namespace(
                        dataset_id=did, algorithm="sha256", force_large=False
                    ))
                result = json.loads(buf2.getvalue())
                self.assertEqual(result["files_hashed"], 2)

    def test_hash_blake2s_different_length(self):
        with isolated_cache():
            with tempfile.TemporaryDirectory() as td:
                f = Path(td) / "x.txt"
                f.write_text("hello")
                mod = _load()
                import io, contextlib, argparse
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    mod.cmd_register(_make_register_args(paths=[str(f)]))
                did = json.loads(buf.getvalue())["dataset_id"]

                buf2 = io.StringIO()
                with contextlib.redirect_stdout(buf2):
                    mod.cmd_hash(argparse.Namespace(
                        dataset_id=did, algorithm="blake2s", force_large=False
                    ))
                result = json.loads(buf2.getvalue())
                self.assertEqual(len(result["combined_hash"]), 64)  # blake2s default

    def test_hash_idempotent_same_content(self):
        with isolated_cache() as cache:
            with tempfile.TemporaryDirectory() as td:
                f = Path(td) / "a.txt"
                f.write_text("identical")
                mod = _load()
                import io, contextlib, argparse
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    mod.cmd_register(_make_register_args(paths=[str(f)]))
                did = json.loads(buf.getvalue())["dataset_id"]

                buf2 = io.StringIO()
                with contextlib.redirect_stdout(buf2):
                    mod.cmd_hash(argparse.Namespace(
                        dataset_id=did, algorithm="sha256", force_large=False
                    ))
                h1 = json.loads(buf2.getvalue())["combined_hash"]

                # Re-hash, same content
                buf3 = io.StringIO()
                with contextlib.redirect_stdout(buf3):
                    mod.cmd_hash(argparse.Namespace(
                        dataset_id=did, algorithm="sha256", force_large=False
                    ))
                h2 = json.loads(buf3.getvalue())["combined_hash"]
                self.assertEqual(h1, h2)

    def test_hash_changes_with_content(self):
        with isolated_cache():
            with tempfile.TemporaryDirectory() as td:
                f = Path(td) / "a.txt"
                f.write_text("first")
                mod = _load()
                import io, contextlib, argparse
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    mod.cmd_register(_make_register_args(paths=[str(f)]))
                did = json.loads(buf.getvalue())["dataset_id"]

                buf2 = io.StringIO()
                with contextlib.redirect_stdout(buf2):
                    mod.cmd_hash(argparse.Namespace(
                        dataset_id=did, algorithm="sha256", force_large=False
                    ))
                h1 = json.loads(buf2.getvalue())["combined_hash"]

                f.write_text("changed")
                buf3 = io.StringIO()
                with contextlib.redirect_stdout(buf3):
                    mod.cmd_hash(argparse.Namespace(
                        dataset_id=did, algorithm="sha256", force_large=False
                    ))
                h2 = json.loads(buf3.getvalue())["combined_hash"]
                self.assertFalse(h1 == h2)

    def test_hash_missing_path_recorded(self):
        with isolated_cache():
            mod = _load()
            import io, contextlib, argparse
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_register(_make_register_args(paths=["/nonexistent/path/xxx"]))
            did = json.loads(buf.getvalue())["dataset_id"]

            buf2 = io.StringIO()
            with contextlib.redirect_stdout(buf2):
                mod.cmd_hash(argparse.Namespace(
                    dataset_id=did, algorithm="sha256", force_large=False
                ))
            result = json.loads(buf2.getvalue())
            self.assertTrue(len(result["errors"]) > 0)


class VersionTests(CoscientistTestCase):
    def _make(self, mod):
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            mod.cmd_register(_make_register_args())
        return json.loads(buf.getvalue())["dataset_id"]

    def test_version_advances_state(self):
        with isolated_cache() as cache:
            mod = _load()
            did = self._make(mod)
            import argparse, io, contextlib
            args = argparse.Namespace(
                dataset_id=did, label="v1", notes="initial release"
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_version(args)
            result = json.loads(buf.getvalue())
            self.assertEqual(result["state"], "versioned")
            self.assertEqual(result["version_count"], 1)

    def test_version_duplicate_label_raises(self):
        with isolated_cache():
            mod = _load()
            did = self._make(mod)
            import argparse, io, contextlib
            args = argparse.Namespace(dataset_id=did, label="v1", notes=None)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_version(args)
            with self.assertRaises(SystemExit):
                mod.cmd_version(args)

    def test_version_records_hashes_at_time(self):
        with isolated_cache():
            with tempfile.TemporaryDirectory() as td:
                f = Path(td) / "a.txt"
                f.write_text("data")
                mod = _load()
                import io, contextlib, argparse
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    mod.cmd_register(_make_register_args(paths=[str(f)]))
                did = json.loads(buf.getvalue())["dataset_id"]

                buf2 = io.StringIO()
                with contextlib.redirect_stdout(buf2):
                    mod.cmd_hash(argparse.Namespace(
                        dataset_id=did, algorithm="sha256", force_large=False
                    ))

                buf3 = io.StringIO()
                with contextlib.redirect_stdout(buf3):
                    mod.cmd_version(argparse.Namespace(
                        dataset_id=did, label="v1", notes=None
                    ))
                versions = mod._load_versions(did)
                self.assertEqual(len(versions), 1)
                self.assertIn("combined", versions[0]["hashes"])


class ListStatusTests(CoscientistTestCase):
    def test_list_empty(self):
        with isolated_cache():
            mod = _load()
            import argparse, io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_list(argparse.Namespace(project_id=None, state=None))
            self.assertEqual(json.loads(buf.getvalue())["total"], 0)

    def test_list_after_register(self):
        with isolated_cache():
            mod = _load()
            import argparse, io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_register(_make_register_args(title="Set A"))
                mod.cmd_register(_make_register_args(title="Set B"))
            buf2 = io.StringIO()
            with contextlib.redirect_stdout(buf2):
                mod.cmd_list(argparse.Namespace(project_id=None, state=None))
            self.assertEqual(json.loads(buf2.getvalue())["total"], 2)

    def test_status_basic(self):
        with isolated_cache():
            mod = _load()
            import argparse, io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_register(_make_register_args(doi="10.5281/zenodo.fake"))
            did = json.loads(buf.getvalue())["dataset_id"]

            buf2 = io.StringIO()
            with contextlib.redirect_stdout(buf2):
                mod.cmd_status(argparse.Namespace(dataset_id=did))
            status = json.loads(buf2.getvalue())
            self.assertEqual(status["state"], "registered")
            self.assertEqual(status["doi"], "10.5281/zenodo.fake")
            self.assertEqual(status["version_count"], 0)
            self.assertFalse(status["has_hashes"])

    def test_status_unknown_id_raises(self):
        with isolated_cache():
            mod = _load()
            import argparse
            with self.assertRaises(FileNotFoundError):
                mod.cmd_status(argparse.Namespace(dataset_id="nonexistent_xyz"))

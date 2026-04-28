"""Tests for the grant-draft skill."""
from __future__ import annotations

import importlib.util as _ilu
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

from tests.harness import CoscientistTestCase, isolated_cache  # noqa


def _load(name: str):
    spec = _ilu.spec_from_file_location(
        name,
        _REPO_ROOT / ".claude/skills/grant-draft/scripts" / f"{name}.py",
    )
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ──────────────────────────────────────────────
# outline.py unit tests
# ──────────────────────────────────────────────

class OutlineTests(CoscientistTestCase):
    def setUp(self):
        self.mod = _load("outline")

    def test_funders_has_four(self):
        self.assertIn("nih", self.mod.FUNDERS)
        self.assertIn("nsf", self.mod.FUNDERS)
        self.assertIn("erc", self.mod.FUNDERS)
        self.assertIn("wellcome", self.mod.FUNDERS)

    def test_get_template_default_mechanism(self):
        tmpl = self.mod.get_template("nih")
        self.assertEqual(tmpl["mechanism"], "R01")

    def test_get_template_explicit_mechanism(self):
        tmpl = self.mod.get_template("nih", "R21")
        self.assertEqual(tmpl["mechanism"], "R21")

    def test_get_template_invalid_funder(self):
        with self.assertRaises(ValueError):
            self.mod.get_template("gates")

    def test_get_template_invalid_mechanism(self):
        with self.assertRaises(ValueError):
            self.mod.get_template("nih", "K99999")

    def test_make_grant_id_stable(self):
        gid1 = self.mod.make_grant_id("Cancer Study", "nih")
        gid2 = self.mod.make_grant_id("Cancer Study", "nih")
        self.assertEqual(gid1, gid2)

    def test_make_grant_id_different_funders(self):
        gid_nih = self.mod.make_grant_id("Cancer Study", "nih")
        gid_nsf = self.mod.make_grant_id("Cancer Study", "nsf")
        self.assertFalse(gid_nih == gid_nsf)

    def test_build_outline_structure(self):
        outline = self.mod.build_outline("My Study", "nsf")
        self.assertEqual(outline["funder"], "nsf")
        self.assertEqual(outline["mechanism"], "Standard")
        self.assertIsInstance(outline["sections"], list)
        self.assertGreater(len(outline["sections"]), 0)
        for s in outline["sections"]:
            self.assertIn("id", s)
            self.assertIn("status", s)
            self.assertEqual(s["status"], "placeholder")

    def test_build_source_md_has_placeholders(self):
        outline = self.mod.build_outline("My Study", "nih")
        md = self.mod.build_source_md(outline)
        self.assertIn("[PLACEHOLDER:", md)
        self.assertIn("## Specific Aims", md)

    def test_count_words(self):
        self.assertEqual(self.mod.count_words("one two three"), 3)
        self.assertEqual(self.mod.count_words(""), 0)

    def test_nih_has_significance_section(self):
        tmpl = self.mod.get_template("nih")
        ids = [s["id"] for s in tmpl["sections"]]
        self.assertIn("significance", ids)
        self.assertIn("innovation", ids)

    def test_erc_mechanisms(self):
        tmpl = self.mod.get_template("erc", "Advanced")
        self.assertEqual(tmpl["mechanism"], "Advanced")

    def test_wellcome_has_impact_section(self):
        tmpl = self.mod.get_template("wellcome")
        ids = [s["id"] for s in tmpl["sections"]]
        self.assertIn("impact", ids)


# ──────────────────────────────────────────────
# draft.py CLI tests
# ──────────────────────────────────────────────

class DraftInitTests(CoscientistTestCase):
    def test_init_creates_files(self):
        with isolated_cache() as cache:
            mod = _load("draft")
            import argparse
            import contextlib
            import io
            args = argparse.Namespace(
                title="Neuroscience Study", funder="nih", mechanism=None, force=False
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_init(args)
            result = json.loads(buf.getvalue())
            self.assertIn("grant_id", result)
            self.assertEqual(result["funder"], "nih")
            self.assertGreater(result["n_sections"], 0)
            # Check files exist
            gdir = cache / "grants" / result["grant_id"]
            self.assertTrue((gdir / "manifest.json").exists())
            self.assertTrue((gdir / "outline.json").exists())
            self.assertTrue((gdir / "source.md").exists())

    def test_init_manifest_content(self):
        with isolated_cache() as cache:
            mod = _load("draft")
            import argparse
            import contextlib
            import io
            args = argparse.Namespace(
                title="NSF Study", funder="nsf", mechanism="CAREER", force=False
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_init(args)
            result = json.loads(buf.getvalue())
            gid = result["grant_id"]
            manifest = json.loads((cache / "grants" / gid / "manifest.json").read_text())
            self.assertEqual(manifest["funder"], "nsf")
            self.assertEqual(manifest["mechanism"], "CAREER")
            self.assertEqual(manifest["state"], "drafted")
            self.assertEqual(manifest["title"], "NSF Study")

    def test_init_duplicate_raises(self):
        with isolated_cache() as cache:
            mod = _load("draft")
            import argparse
            import contextlib
            import io
            args = argparse.Namespace(
                title="Dup Study", funder="erc", mechanism=None, force=False
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_init(args)
            # Second init without force
            with self.assertRaises(SystemExit):
                mod.cmd_init(args)

    def test_init_force_overwrites(self):
        with isolated_cache() as cache:
            mod = _load("draft")
            import argparse
            import contextlib
            import io
            args = argparse.Namespace(
                title="Force Study", funder="wellcome", mechanism=None, force=False
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_init(args)
            # Force re-init
            args.force = True
            buf2 = io.StringIO()
            with contextlib.redirect_stdout(buf2):
                mod.cmd_init(args)
            result = json.loads(buf2.getvalue())
            self.assertIn("grant_id", result)

    def test_init_invalid_funder_raises(self):
        with isolated_cache():
            mod = _load("draft")
            import argparse
            args = argparse.Namespace(
                title="Bad Funder", funder="gates", mechanism=None, force=False
            )
            with self.assertRaises((ValueError, SystemExit)):
                mod.cmd_init(args)


class DraftSectionTests(CoscientistTestCase):
    def _make_grant(self, cache, title="Bio Study", funder="nih", mechanism=None):
        mod = _load("draft")
        import argparse
        import contextlib
        import io
        args = argparse.Namespace(title=title, funder=funder, mechanism=mechanism, force=False)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            mod.cmd_init(args)
        return json.loads(buf.getvalue())["grant_id"]

    def test_section_updates_outline(self):
        with isolated_cache() as cache:
            gid = self._make_grant(cache)
            mod = _load("draft")
            import argparse
            import contextlib
            import io
            args = argparse.Namespace(
                grant_id=gid, section="specific_aims",
                content="We propose three aims to study neural plasticity."
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_section(args)
            result = json.loads(buf.getvalue())
            self.assertEqual(result["section"], "specific_aims")
            self.assertGreater(result["word_count"], 0)
            self.assertEqual(result["status"], "drafted")

    def test_section_updates_source_md(self):
        with isolated_cache() as cache:
            gid = self._make_grant(cache)
            mod = _load("draft")
            import argparse
            import contextlib
            import io
            content = "Plasticity underlies learning and memory."
            args = argparse.Namespace(grant_id=gid, section="significance", content=content)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_section(args)
            source = (cache / "grants" / gid / "source.md").read_text()
            self.assertIn(content, source)

    def test_section_invalid_section_raises(self):
        with isolated_cache() as cache:
            gid = self._make_grant(cache)
            mod = _load("draft")
            import argparse
            args = argparse.Namespace(grant_id=gid, section="nonexistent", content="text")
            with self.assertRaises(SystemExit):
                mod.cmd_section(args)

    def test_section_word_count_accurate(self):
        with isolated_cache() as cache:
            gid = self._make_grant(cache, funder="nsf")
            mod = _load("draft")
            import argparse
            import contextlib
            import io
            content = " ".join(["word"] * 42)
            args = argparse.Namespace(grant_id=gid, section="project_summary", content=content)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_section(args)
            result = json.loads(buf.getvalue())
            self.assertEqual(result["word_count"], 42)


class DraftStatusTests(CoscientistTestCase):
    def test_status_empty_grant(self):
        with isolated_cache() as cache:
            mod = _load("draft")
            import argparse
            import contextlib
            import io
            init_args = argparse.Namespace(title="Status Test", funder="erc", mechanism=None, force=False)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_init(init_args)
            gid = json.loads(buf.getvalue())["grant_id"]

            status_args = argparse.Namespace(grant_id=gid)
            buf2 = io.StringIO()
            with contextlib.redirect_stdout(buf2):
                mod.cmd_status(status_args)
            status = json.loads(buf2.getvalue())
            self.assertEqual(status["funder"], "erc")
            self.assertEqual(status["sections_drafted"], 0)
            self.assertEqual(status["total_words"], 0)

    def test_status_after_section(self):
        with isolated_cache() as cache:
            mod = _load("draft")
            import argparse
            import contextlib
            import io

            init_args = argparse.Namespace(title="After Section", funder="wellcome", mechanism=None, force=False)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_init(init_args)
            gid = json.loads(buf.getvalue())["grant_id"]

            sec_args = argparse.Namespace(
                grant_id=gid, section="scientific_abstract",
                content="A study of inflammatory markers in aging populations."
            )
            buf2 = io.StringIO()
            with contextlib.redirect_stdout(buf2):
                mod.cmd_section(sec_args)

            status_args = argparse.Namespace(grant_id=gid)
            buf3 = io.StringIO()
            with contextlib.redirect_stdout(buf3):
                mod.cmd_status(status_args)
            status = json.loads(buf3.getvalue())
            self.assertEqual(status["sections_drafted"], 1)
            self.assertGreater(status["total_words"], 0)
            self.assertGreater(status["target_words"], 0)

    def test_status_missing_grant_raises(self):
        with isolated_cache():
            mod = _load("draft")
            import argparse
            args = argparse.Namespace(grant_id="nonexistent_grant_abc")
            with self.assertRaises(FileNotFoundError):
                mod.cmd_status(args)


class FundersListTests(CoscientistTestCase):
    def test_funders_returns_four(self):
        with isolated_cache():
            mod = _load("draft")
            import argparse
            import contextlib
            import io
            args = argparse.Namespace()
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_funders(args)
            result = json.loads(buf.getvalue())
            self.assertEqual(len(result), 4)
            funder_keys = {r["funder"] for r in result}
            self.assertIn("nih", funder_keys)
            self.assertIn("nsf", funder_keys)
            self.assertIn("erc", funder_keys)
            self.assertIn("wellcome", funder_keys)

    def test_funders_have_mechanisms(self):
        with isolated_cache():
            mod = _load("draft")
            import argparse
            import contextlib
            import io
            args = argparse.Namespace()
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_funders(args)
            result = json.loads(buf.getvalue())
            for r in result:
                self.assertIsInstance(r["mechanisms"], list)
                self.assertGreater(len(r["mechanisms"]), 0)
                self.assertIn("default_mechanism", r)
                self.assertIn(r["default_mechanism"], r["mechanisms"])

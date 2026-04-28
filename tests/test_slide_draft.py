"""Tests for the slide-draft skill."""
from __future__ import annotations

import importlib.util as _ilu
import json
import shutil
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

from tests.harness import CoscientistTestCase, isolated_cache  # noqa


def _load():
    spec = _ilu.spec_from_file_location(
        "slide",
        _REPO_ROOT / ".claude/skills/slide-draft/scripts/slide.py",
    )
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_manuscript(cache: Path, mid: str = "ms_test") -> Path:
    """Create a synthetic manuscript with all standard sections."""
    md = cache / "manuscripts" / mid
    md.mkdir(parents=True, exist_ok=True)
    (md / "source.md").write_text("""---
title: "Test Paper"
---

## Introduction
This is the intro section. It explains why the work matters.
Background sentence here.

## Background
Prior work covers X, Y, and Z.

## Methods
We use approach A. Approach A consists of B and C.
Detailed step-by-step description.

## Experiments
Setup section: hardware, datasets, baselines.

## Results
Main results table. We achieve 95% on benchmark.

## Discussion
We discuss why it works. Limitations include scale.

## Conclusion
We conclude X. Future work: Y.

## References
Bibliography here.
""")
    return md


class OutlineTests(CoscientistTestCase):
    def test_outline_creates_default(self):
        with isolated_cache() as cache:
            _make_manuscript(cache)
            mod = _load()
            import argparse
            import contextlib
            import io
            args = argparse.Namespace(
                manuscript_id="ms_test", style="standard", force=False
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_outline(args)
            result = json.loads(buf.getvalue())
            self.assertEqual(result["style"], "standard")
            self.assertGreater(result["slide_count"], 5)

    def test_outline_styles(self):
        with isolated_cache() as cache:
            _make_manuscript(cache)
            mod = _load()
            for style in ("standard", "short-talk", "long-talk", "poster"):
                # Clean any existing outline
                outline_p = cache / "manuscripts" / "ms_test" / "slides" / "outline.json"
                if outline_p.exists():
                    outline_p.unlink()
                import argparse
                import contextlib
                import io
                args = argparse.Namespace(
                    manuscript_id="ms_test", style=style, force=False
                )
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    mod.cmd_outline(args)
                result = json.loads(buf.getvalue())
                self.assertEqual(result["style"], style)

    def test_outline_unknown_style_raises(self):
        with isolated_cache() as cache:
            _make_manuscript(cache)
            mod = _load()
            import argparse
            args = argparse.Namespace(
                manuscript_id="ms_test", style="bogus", force=False
            )
            with self.assertRaises(SystemExit):
                mod.cmd_outline(args)

    def test_outline_no_source_raises(self):
        with isolated_cache():
            mod = _load()
            import argparse
            args = argparse.Namespace(
                manuscript_id="nonexistent", style="standard", force=False
            )
            with self.assertRaises(SystemExit):
                mod.cmd_outline(args)

    def test_outline_duplicate_no_force_raises(self):
        with isolated_cache() as cache:
            _make_manuscript(cache)
            mod = _load()
            import argparse
            import contextlib
            import io
            args = argparse.Namespace(
                manuscript_id="ms_test", style="standard", force=False
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_outline(args)
            with self.assertRaises(SystemExit):
                mod.cmd_outline(args)

    def test_outline_force_overwrites(self):
        with isolated_cache() as cache:
            _make_manuscript(cache)
            mod = _load()
            import argparse
            import contextlib
            import io
            args = argparse.Namespace(
                manuscript_id="ms_test", style="standard", force=False
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_outline(args)
            args.force = True
            buf2 = io.StringIO()
            with contextlib.redirect_stdout(buf2):
                mod.cmd_outline(args)
            self.assertIn("slide_count", json.loads(buf2.getvalue()))


class SlideMdBuildTests(CoscientistTestCase):
    def test_split_sections(self):
        mod = _load()
        text = "## Intro\nA sentence.\n\n## Methods\nMethod text.\n"
        sections = mod._split_sections(text)
        self.assertIn("Intro", sections)
        self.assertIn("Methods", sections)
        self.assertIn("A sentence", sections["Intro"])

    def test_find_section_match_exact(self):
        mod = _load()
        sections = {"Introduction": "x", "Methods": "y"}
        self.assertEqual(mod._find_section_match(sections, "Introduction"), "Introduction")

    def test_find_section_match_case_insensitive(self):
        mod = _load()
        sections = {"Introduction": "x"}
        self.assertEqual(mod._find_section_match(sections, "introduction"), "Introduction")

    def test_find_section_match_prefix(self):
        mod = _load()
        sections = {"Introduction and Background": "x"}
        self.assertEqual(
            mod._find_section_match(sections, "Introduction"),
            "Introduction and Background",
        )

    def test_find_section_match_none_for_missing(self):
        mod = _load()
        sections = {"Introduction": "x"}
        self.assertIsNone(mod._find_section_match(sections, "Nonexistent"))

    def test_strip_placeholders(self):
        mod = _load()
        text = "Hello [PLACEHOLDER: filler] world <!-- comment --> here"
        stripped = mod._strip_placeholders(text)
        self.assertNotIn("PLACEHOLDER", stripped)
        self.assertNotIn("<!--", stripped)
        self.assertIn("Hello", stripped)


class RenderTests(CoscientistTestCase):
    def test_render_slidev_no_pandoc(self):
        with isolated_cache() as cache:
            _make_manuscript(cache)
            mod = _load()
            import argparse
            import contextlib
            import io
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_outline(argparse.Namespace(
                    manuscript_id="ms_test", style="short-talk", force=False
                ))
            buf2 = io.StringIO()
            with contextlib.redirect_stdout(buf2):
                mod.cmd_render(argparse.Namespace(
                    manuscript_id="ms_test", format="slidev", output=None
                ))
            result = json.loads(buf2.getvalue())
            self.assertEqual(result["format"], "slidev")
            self.assertFalse(result["pandoc_used"])
            output = Path(result["output"])
            self.assertTrue(output.exists())
            content = output.read_text()
            self.assertIn("---", content)
            self.assertIn("##", content)

    def test_render_no_outline_raises(self):
        with isolated_cache() as cache:
            _make_manuscript(cache)
            mod = _load()
            import argparse
            args = argparse.Namespace(
                manuscript_id="ms_test", format="slidev", output=None
            )
            with self.assertRaises(SystemExit):
                mod.cmd_render(args)

    def test_render_unknown_format_raises(self):
        with isolated_cache() as cache:
            _make_manuscript(cache)
            mod = _load()
            import argparse
            import contextlib
            import io
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_outline(argparse.Namespace(
                    manuscript_id="ms_test", style="standard", force=False
                ))
            args = argparse.Namespace(
                manuscript_id="ms_test", format="rtf", output=None
            )
            with self.assertRaises(SystemExit):
                mod.cmd_render(args)

    def test_render_pandoc_format_skipped_if_missing(self):
        if shutil.which("pandoc"):
            # pandoc installed — can't validate the missing-pandoc branch
            return
        with isolated_cache() as cache:
            _make_manuscript(cache)
            mod = _load()
            import argparse
            import contextlib
            import io
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_outline(argparse.Namespace(
                    manuscript_id="ms_test", style="short-talk", force=False
                ))
            args = argparse.Namespace(
                manuscript_id="ms_test", format="pptx", output=None
            )
            with self.assertRaises(SystemExit):
                mod.cmd_render(args)


class ListCleanTests(CoscientistTestCase):
    def test_list_empty(self):
        with isolated_cache() as cache:
            _make_manuscript(cache)
            mod = _load()
            import argparse
            import contextlib
            import io
            args = argparse.Namespace(manuscript_id="ms_test")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_list(args)
            result = json.loads(buf.getvalue())
            self.assertFalse(result["has_outline"])
            self.assertEqual(result["exports"], [])

    def test_list_after_outline_and_render(self):
        with isolated_cache() as cache:
            _make_manuscript(cache)
            mod = _load()
            import argparse
            import contextlib
            import io
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_outline(argparse.Namespace(
                    manuscript_id="ms_test", style="short-talk", force=False
                ))
                mod.cmd_render(argparse.Namespace(
                    manuscript_id="ms_test", format="slidev", output=None
                ))

            buf2 = io.StringIO()
            with contextlib.redirect_stdout(buf2):
                mod.cmd_list(argparse.Namespace(manuscript_id="ms_test"))
            result = json.loads(buf2.getvalue())
            self.assertTrue(result["has_outline"])
            self.assertEqual(len(result["exports"]), 1)

    def test_clean_removes_files(self):
        with isolated_cache() as cache:
            _make_manuscript(cache)
            mod = _load()
            import argparse
            import contextlib
            import io
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_outline(argparse.Namespace(
                    manuscript_id="ms_test", style="short-talk", force=False
                ))
                mod.cmd_render(argparse.Namespace(
                    manuscript_id="ms_test", format="slidev", output=None
                ))

            buf2 = io.StringIO()
            with contextlib.redirect_stdout(buf2):
                mod.cmd_clean(argparse.Namespace(manuscript_id="ms_test"))
            result = json.loads(buf2.getvalue())
            self.assertGreater(result["removed_count"], 0)


class FormatsListTests(CoscientistTestCase):
    def test_formats_lists_all(self):
        with isolated_cache():
            mod = _load()
            import argparse
            import contextlib
            import io
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_formats(argparse.Namespace())
            result = json.loads(buf.getvalue())
            self.assertIn("beamer", result["formats"])
            self.assertIn("pptx", result["formats"])
            self.assertIn("revealjs", result["formats"])
            self.assertIn("slidev", result["formats"])
            self.assertEqual(set(result["styles"]),
                             {"standard", "short-talk", "long-talk", "poster"})

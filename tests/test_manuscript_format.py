"""Tests for the manuscript-format skill.

Tests
-----
PandocUtilsTests    — unit tests for pandoc_utils helpers (no subprocess, no filesystem)
FormatExportTests   — integration: init a draft, then export
FormatListTests     — integration: list subcommand behavior
FormatCleanTests    — integration: clean subcommand behavior
CliEdgeTests        — CLI error handling (missing args, bad values, --help)

No LLM calls. No network. Pure filesystem + subprocess.
"""

from tests import _shim  # noqa: F401

import subprocess
import sys
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests

_ROOT = Path(__file__).resolve().parent.parent
_FORMAT = _ROOT / ".claude/skills/manuscript-format/scripts/format.py"
_DRAFT = _ROOT / ".claude/skills/manuscript-draft/scripts/draft.py"
_PANDOC_UTILS = _ROOT / ".claude/skills/manuscript-format/scripts/pandoc_utils.py"


def _run_format(*args: str, env=None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_FORMAT), *args],
        capture_output=True, text=True, env=env,
    )


def _run_draft(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_DRAFT), *args],
        capture_output=True, text=True,
    )


# ---------------------------------------------------------------------------
# Import pandoc_utils directly for unit tests
# ---------------------------------------------------------------------------

import importlib.util as _ilu

def _load_pandoc_utils():
    spec = _ilu.spec_from_file_location("pandoc_utils", str(_PANDOC_UTILS))
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_putils = _load_pandoc_utils()


# ---------------------------------------------------------------------------
# PandocUtilsTests
# ---------------------------------------------------------------------------

class PandocUtilsTests(TestCase):
    """Unit tests for pandoc_utils — no subprocess, no filesystem required."""

    def test_strip_placeholders_removes_placeholder_blocks(self):
        text = "## Introduction\n\n[PLACEHOLDER Write the intro here.]\n\n## Methods\n\nReal content.\n"
        result = _putils.strip_placeholders(text)
        self.assertNotIn("[PLACEHOLDER", result)
        self.assertIn("Real content.", result)

    def test_strip_placeholders_removes_inline_placeholder(self):
        text = "See [PLACEHOLDER insert citation] for details."
        result = _putils.strip_placeholders(text)
        self.assertNotIn("[PLACEHOLDER", result)
        self.assertIn("for details.", result)

    def test_strip_placeholders_removes_html_comment_notes(self):
        text = "## Abstract\n\n<!-- notes: keep this short -->\n\nActual abstract text.\n"
        result = _putils.strip_placeholders(text)
        self.assertNotIn("<!-- notes:", result)
        self.assertIn("Actual abstract text.", result)

    def test_strip_placeholders_removes_html_comment_target(self):
        text = "## Introduction\n\n<!-- target: 500 words -->\n\nReal intro.\n"
        result = _putils.strip_placeholders(text)
        self.assertNotIn("<!-- target:", result)
        self.assertIn("Real intro.", result)

    def test_strip_placeholders_leaves_real_content(self):
        text = "## Results\n\nWe found that accuracy improved by 3.5% over baseline.\n"
        result = _putils.strip_placeholders(text)
        self.assertIn("We found that accuracy improved by 3.5% over baseline.", result)

    def test_strip_placeholders_handles_empty_string(self):
        result = _putils.strip_placeholders("")
        self.assertEqual(result, "")

    def test_strip_placeholders_multiline_html_comment(self):
        text = "Before.\n<!-- multi\nline\ncomment -->\nAfter.\n"
        result = _putils.strip_placeholders(text)
        self.assertNotIn("multi", result)
        self.assertNotIn("line", result)
        self.assertIn("Before.", result)
        self.assertIn("After.", result)

    def test_pandoc_available_returns_bool(self):
        result = _putils.pandoc_available()
        self.assertTrue(isinstance(result, bool))

    def test_build_pandoc_args_returns_list_starting_with_pandoc(self):
        args = _putils.build_pandoc_args(
            "imrad", "tex",
            Path("/tmp/source.md"),
            Path("/tmp/output.tex"),
        )
        self.assertTrue(isinstance(args, list))
        self.assertIn("pandoc", args)
        self.assertEqual(args[0], "pandoc")

    def test_build_pandoc_args_contains_source_and_output(self):
        src = Path("/tmp/source.md")
        out = Path("/tmp/output.tex")
        args = _putils.build_pandoc_args("imrad", "tex", src, out)
        self.assertIn(str(src), args)
        self.assertIn(str(out), args)

    def test_build_pandoc_args_tex_includes_latex_flag(self):
        args = _putils.build_pandoc_args(
            "neurips", "tex",
            Path("/tmp/s.md"), Path("/tmp/o.tex"),
        )
        # Should include --to latex or latex-related flag
        args_str = " ".join(args)
        self.assertIn("latex", args_str)

    def test_build_pandoc_args_docx_includes_docx_flag(self):
        args = _putils.build_pandoc_args(
            "docx", "docx",
            Path("/tmp/s.md"), Path("/tmp/o.docx"),
        )
        args_str = " ".join(args)
        self.assertIn("docx", args_str)


# ---------------------------------------------------------------------------
# FormatExportTests
# ---------------------------------------------------------------------------

class FormatExportTests(TestCase):
    """Integration: init a draft then run export."""

    def test_export_tex_creates_file_or_errors_on_missing_pandoc(self):
        with isolated_cache():
            # Init a draft
            r = _run_draft("init", "--title", "Format Export Test", "--venue", "imrad")
            self.assertEqual(r.returncode, 0, r.stderr)
            mid = r.stdout.strip()

            r2 = _run_format("export", "--manuscript-id", mid,
                             "--venue", "imrad", "--output-format", "tex")

            if _putils.pandoc_available():
                self.assertEqual(r2.returncode, 0, r2.stderr)
                output_path = r2.stdout.strip()
                self.assertTrue(Path(output_path).exists(),
                                f"expected output file at {output_path}")
            else:
                self.assertTrue(r2.returncode != 0,
                                "should fail when pandoc is not installed")
                self.assertIn("pandoc not installed", r2.stderr)

    def test_export_error_message_contains_install_url(self):
        """If pandoc is absent, stderr must contain the install URL."""
        if _putils.pandoc_available():
            # Can't test this path without pandoc being absent
            return
        with isolated_cache():
            r = _run_draft("init", "--title", "No Pandoc Test", "--venue", "imrad")
            mid = r.stdout.strip()
            r2 = _run_format("export", "--manuscript-id", mid,
                             "--venue", "imrad", "--output-format", "tex")
            self.assertIn("https://pandoc.org/installing.html", r2.stderr)

    def test_export_creates_exports_dir(self):
        if not _putils.pandoc_available():
            return
        with isolated_cache():
            r = _run_draft("init", "--title", "Exports Dir Test", "--venue", "imrad")
            mid = r.stdout.strip()
            _run_format("export", "--manuscript-id", mid,
                        "--venue", "imrad", "--output-format", "tex")

            from lib.cache import cache_root
            exports_dir = cache_root() / "manuscripts" / mid / "exports"
            self.assertTrue(exports_dir.exists())

    def test_export_output_path_printed_to_stdout(self):
        if not _putils.pandoc_available():
            return
        with isolated_cache():
            r = _run_draft("init", "--title", "Stdout Path Test", "--venue", "neurips")
            mid = r.stdout.strip()
            r2 = _run_format("export", "--manuscript-id", mid,
                             "--venue", "neurips", "--output-format", "tex")
            self.assertEqual(r2.returncode, 0, r2.stderr)
            out = r2.stdout.strip()
            self.assertTrue(out.endswith(".tex"), f"expected .tex path, got: {out!r}")

    def test_export_unknown_manuscript_errors(self):
        with isolated_cache():
            r = _run_format("export", "--manuscript-id", "does_not_exist_000000",
                            "--venue", "imrad", "--output-format", "tex")
            self.assertTrue(r.returncode != 0,
                            "unknown manuscript_id should fail")

    def test_export_does_not_modify_source_md(self):
        if not _putils.pandoc_available():
            return
        with isolated_cache():
            r = _run_draft("init", "--title", "Source Unchanged", "--venue", "imrad")
            mid = r.stdout.strip()

            from lib.cache import cache_root
            source_path = cache_root() / "manuscripts" / mid / "source.md"
            original = source_path.read_text()

            _run_format("export", "--manuscript-id", mid,
                        "--venue", "imrad", "--output-format", "tex")

            after = source_path.read_text()
            self.assertEqual(original, after, "source.md must not be modified by export")


# ---------------------------------------------------------------------------
# FormatListTests
# ---------------------------------------------------------------------------

class FormatListTests(TestCase):
    """Integration: list subcommand behavior."""

    def test_list_on_fresh_manuscript_prints_no_exports(self):
        with isolated_cache():
            r = _run_draft("init", "--title", "List Fresh", "--venue", "imrad")
            mid = r.stdout.strip()

            r2 = _run_format("list", "--manuscript-id", mid)
            self.assertEqual(r2.returncode, 0, r2.stderr)
            self.assertIn("no exports", r2.stdout)

    def test_list_after_export_shows_file(self):
        if not _putils.pandoc_available():
            return
        with isolated_cache():
            r = _run_draft("init", "--title", "List After Export", "--venue", "imrad")
            mid = r.stdout.strip()
            _run_format("export", "--manuscript-id", mid,
                        "--venue", "imrad", "--output-format", "tex")

            r2 = _run_format("list", "--manuscript-id", mid)
            self.assertEqual(r2.returncode, 0, r2.stderr)
            self.assertIn("imrad.tex", r2.stdout)

    def test_list_exits_zero_always(self):
        with isolated_cache():
            r = _run_draft("init", "--title", "List Zero Exit", "--venue", "imrad")
            mid = r.stdout.strip()
            r2 = _run_format("list", "--manuscript-id", mid)
            self.assertEqual(r2.returncode, 0)


# ---------------------------------------------------------------------------
# FormatCleanTests
# ---------------------------------------------------------------------------

class FormatCleanTests(TestCase):
    """Integration: clean subcommand behavior."""

    def test_clean_removes_exports_dir(self):
        if not _putils.pandoc_available():
            return
        with isolated_cache():
            r = _run_draft("init", "--title", "Clean Test", "--venue", "imrad")
            mid = r.stdout.strip()
            _run_format("export", "--manuscript-id", mid,
                        "--venue", "imrad", "--output-format", "tex")

            from lib.cache import cache_root
            exports_dir = cache_root() / "manuscripts" / mid / "exports"
            self.assertTrue(exports_dir.exists(), "exports dir should exist before clean")

            r2 = _run_format("clean", "--manuscript-id", mid)
            self.assertEqual(r2.returncode, 0, r2.stderr)
            self.assertFalse(exports_dir.exists(), "exports dir should be gone after clean")

    def test_clean_on_no_exports_exits_zero(self):
        with isolated_cache():
            r = _run_draft("init", "--title", "Clean No Exports", "--venue", "imrad")
            mid = r.stdout.strip()

            r2 = _run_format("clean", "--manuscript-id", mid)
            self.assertEqual(r2.returncode, 0, r2.stderr)

    def test_clean_on_no_exports_prints_friendly_message(self):
        with isolated_cache():
            r = _run_draft("init", "--title", "Clean Friendly", "--venue", "imrad")
            mid = r.stdout.strip()

            r2 = _run_format("clean", "--manuscript-id", mid)
            # Should say something about nothing to clean or no exports
            combined = r2.stdout + r2.stderr
            self.assertTrue(
                "nothing" in combined.lower() or "no exports" in combined.lower()
                or "empty" in combined.lower(),
                f"expected friendly message, got: {combined!r}",
            )


# ---------------------------------------------------------------------------
# CliEdgeTests
# ---------------------------------------------------------------------------

class CliEdgeTests(TestCase):
    """CLI error handling."""

    def test_export_requires_manuscript_id(self):
        r = _run_format("export", "--venue", "imrad", "--output-format", "tex")
        self.assertTrue(r.returncode != 0, "export without --manuscript-id should fail")

    def test_export_rejects_unknown_venue(self):
        with isolated_cache():
            r = _run_draft("init", "--title", "Bad Venue Format", "--venue", "imrad")
            mid = r.stdout.strip()
            r2 = _run_format("export", "--manuscript-id", mid,
                             "--venue", "plos-one", "--output-format", "tex")
            self.assertTrue(r2.returncode != 0, "unknown venue should fail")

    def test_export_rejects_unknown_output_format(self):
        with isolated_cache():
            r = _run_draft("init", "--title", "Bad Format", "--venue", "imrad")
            mid = r.stdout.strip()
            r2 = _run_format("export", "--manuscript-id", mid,
                             "--venue", "imrad", "--output-format", "odt")
            self.assertTrue(r2.returncode != 0, "unknown output-format should fail")

    def test_list_requires_manuscript_id(self):
        r = _run_format("list")
        self.assertTrue(r.returncode != 0, "list without --manuscript-id should fail")

    def test_clean_requires_manuscript_id(self):
        r = _run_format("clean")
        self.assertTrue(r.returncode != 0, "clean without --manuscript-id should fail")

    def test_help_lists_all_subcommands(self):
        r = _run_format("--help")
        self.assertEqual(r.returncode, 0)
        for sub in ("export", "list", "clean"):
            self.assertIn(sub, r.stdout)

    def test_export_help_lists_all_venues(self):
        r = _run_format("export", "--help")
        self.assertEqual(r.returncode, 0)
        for venue in ("neurips", "acl", "nature", "imrad", "arxiv", "docx"):
            self.assertIn(venue, r.stdout)


if __name__ == "__main__":
    sys.exit(run_tests(
        PandocUtilsTests,
        FormatExportTests,
        FormatListTests,
        FormatCleanTests,
        CliEdgeTests,
    ))

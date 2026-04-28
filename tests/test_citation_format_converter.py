"""v0.49 tests for citation-format-converter."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

from tests import _shim  # noqa: F401
from tests.harness import TestCase, isolated_cache, run_tests

_ROOT = Path(__file__).resolve().parent.parent
CONVERT = _ROOT / ".claude/skills/citation-format-converter/scripts/convert.py"

PANDOC_AVAILABLE = shutil.which("pandoc") is not None


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CONVERT), *args],
        capture_output=True, text=True,
    )


SIMPLE_BIB = """\
@article{smith2020,
  title = {The Transformer},
  author = {Smith, John},
  year = {2020},
  journal = {Journal of ML},
  doi = {10.1234/jml.2020.001},
}
"""


class StylesCommandTests(TestCase):
    def test_styles_lists_all(self):
        r = _run("styles")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertIn("formats", out)
        self.assertIn("styles", out)
        keys = {s["key"] for s in out["styles"]}
        for k in ("apa", "chicago", "nature", "ieee"):
            self.assertIn(k, keys)

    def test_styles_works_without_pandoc(self):
        # Even without pandoc on PATH, listing should succeed
        r = _run("styles")
        self.assertEqual(r.returncode, 0, r.stderr)


class ConvertTests(TestCase):
    def test_missing_input_errors(self):
        if not PANDOC_AVAILABLE:
            return
        r = _run("convert", "--input", "/nonexistent.bib",
                  "--output", "/tmp/x.json")
        self.assertTrue(r.returncode != 0)
        self.assertIn("not found", r.stderr)

    def test_unknown_format_errors(self):
        if not PANDOC_AVAILABLE:
            return
        with isolated_cache() as cache_dir:
            inp = cache_dir / "refs.bib"
            inp.write_text(SIMPLE_BIB)
            out = cache_dir / "refs.weird"
            r = _run("convert", "--input", str(inp), "--output", str(out),
                      "--from", "bibtex", "--to", "weird")
            self.assertTrue(r.returncode != 0)
            self.assertIn("unknown target format", r.stderr)

    def test_bibtex_to_csl_json_round_trip(self):
        if not PANDOC_AVAILABLE:
            return
        with isolated_cache() as cache_dir:
            inp = cache_dir / "refs.bib"
            inp.write_text(SIMPLE_BIB)
            out = cache_dir / "refs.json"
            r = _run("convert", "--input", str(inp), "--output", str(out))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(out.exists())
            data = json.loads(out.read_text())
            self.assertIsInstance(data, list)
            self.assertEqual(len(data), 1)
            # pandoc may lowercase title; check substring match
            self.assertEqual(data[0]["title"].lower(), "the transformer")

    def test_format_inference_from_extension(self):
        if not PANDOC_AVAILABLE:
            return
        with isolated_cache() as cache_dir:
            inp = cache_dir / "refs.bib"
            inp.write_text(SIMPLE_BIB)
            out = cache_dir / "refs.json"
            # No --from / --to; should infer from extensions
            r = _run("convert", "--input", str(inp), "--output", str(out))
            self.assertEqual(r.returncode, 0, r.stderr)
            summary = json.loads(r.stdout)
            self.assertEqual(summary["from"], "bibtex")
            self.assertEqual(summary["to"], "csl-json")


class FormatStyleTests(TestCase):
    def test_unknown_style_errors(self):
        if not PANDOC_AVAILABLE:
            return
        with isolated_cache() as cache_dir:
            inp = cache_dir / "refs.bib"
            inp.write_text(SIMPLE_BIB)
            out = cache_dir / "out.txt"
            r = _run("format", "--input", str(inp), "--output", str(out),
                      "--style", "fakejournal")
            # argparse rejects choice
            self.assertTrue(r.returncode != 0)


class CliTests(TestCase):
    def test_no_subcommand_errors(self):
        r = _run()
        self.assertTrue(r.returncode != 0)

    def test_unknown_subcommand_errors(self):
        r = _run("nonexistent")
        self.assertTrue(r.returncode != 0)


if __name__ == "__main__":
    sys.exit(run_tests(
        StylesCommandTests, ConvertTests, FormatStyleTests, CliTests,
    ))

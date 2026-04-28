"""v0.73 — manuscript-mcp unit tests. All offline."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests

_REPO = Path(__file__).resolve().parents[1]
_SERVER = _REPO / "mcp" / "manuscript-mcp" / "server.py"


def _import_server():
    if "mcp" not in sys.modules:
        import types
        mcp_pkg = types.ModuleType("mcp")
        mcp_server = types.ModuleType("mcp.server")
        mcp_fastmcp = types.ModuleType("mcp.server.fastmcp")

        class _StubMCP:
            def __init__(self, name): self.name = name
            def tool(self):
                def deco(fn): return fn
                return deco
            def run(self): pass

        mcp_fastmcp.FastMCP = _StubMCP
        sys.modules["mcp"] = mcp_pkg
        sys.modules["mcp.server"] = mcp_server
        sys.modules["mcp.server.fastmcp"] = mcp_fastmcp

    spec = importlib.util.spec_from_file_location(
        "manuscript_mcp_server", _SERVER,
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FormatDetectTests(TestCase):
    def setUp(self):
        self.mod = _import_server()

    def test_md_extension(self):
        self.assertEqual(
            self.mod.detect_format_from_path("paper.md"), "markdown")

    def test_markdown_extension(self):
        self.assertEqual(
            self.mod.detect_format_from_path("paper.markdown"), "markdown")

    def test_tex_extension(self):
        self.assertEqual(
            self.mod.detect_format_from_path("paper.tex"), "latex")

    def test_docx_extension(self):
        self.assertEqual(
            self.mod.detect_format_from_path("paper.docx"), "docx")

    def test_unknown_extension_falls_back_to_markdown(self):
        self.assertEqual(
            self.mod.detect_format_from_path("paper.txt"), "markdown")

    def test_uppercase_extension(self):
        self.assertEqual(
            self.mod.detect_format_from_path("PAPER.TEX"), "latex")

    def test_detect_format_tool_returns_dict(self):
        out = self.mod.detect_format("paper.tex")
        self.assertEqual(out["format"], "latex")
        self.assertEqual(out["path"], "paper.tex")


class CitationExtractionTests(TestCase):
    def setUp(self):
        self.mod = _import_server()

    def test_latex_cite_single_key(self):
        out = self.mod._extract_citations_from_text("see \\cite{smith2020}.")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["key"], "smith2020")
        self.assertEqual(out[0]["style"], "latex")

    def test_latex_cite_multi_key(self):
        out = self.mod._extract_citations_from_text(
            "\\cite{a2020,b2021,c2022}"
        )
        keys = [c["key"] for c in out]
        self.assertEqual(set(keys), {"a2020", "b2021", "c2022"})

    def test_latex_citep_variant(self):
        out = self.mod._extract_citations_from_text("\\citep{smith2020}")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["key"], "smith2020")

    def test_pandoc_single(self):
        out = self.mod._extract_citations_from_text("see [@smith2020]")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["key"], "smith2020")
        self.assertEqual(out[0]["style"], "pandoc")

    def test_pandoc_multi(self):
        out = self.mod._extract_citations_from_text(
            "see [@smith2020; @jones2021]"
        )
        keys = sorted({c["key"] for c in out})
        self.assertEqual(keys, ["jones2021", "smith2020"])

    def test_numeric_single(self):
        out = self.mod._extract_citations_from_text("see [1]")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["style"], "numeric")

    def test_author_year(self):
        out = self.mod._extract_citations_from_text(
            "as shown by (Smith, 2020), but (Jones et al., 2021a) disagrees"
        )
        styles = {c["style"] for c in out}
        self.assertIn("author-year", styles)
        self.assertGreaterEqual(len(out), 2)

    def test_no_citations(self):
        out = self.mod._extract_citations_from_text(
            "this paper has no references at all."
        )
        self.assertEqual(out, [])

    def test_citations_sorted_by_position(self):
        text = "first \\cite{b}, then [@a], finally \\cite{c}."
        out = self.mod._extract_citations_from_text(text)
        positions = [c["span"][0] for c in out]
        self.assertEqual(positions, sorted(positions))


class SectionExtractionTests(TestCase):
    def setUp(self):
        self.mod = _import_server()

    def test_markdown_h1_h2(self):
        text = "# Intro\n\nbody\n\n## Methods\n\nmore"
        out = self.mod._extract_sections_from_text(text, "markdown")
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["title"], "Intro")
        self.assertEqual(out[0]["level"], 1)
        self.assertEqual(out[1]["title"], "Methods")
        self.assertEqual(out[1]["level"], 2)

    def test_markdown_levels(self):
        text = "# A\n\n## B\n\n### C\n\n#### D\n\n##### E\n\n###### F"
        out = self.mod._extract_sections_from_text(text, "markdown")
        self.assertEqual([s["level"] for s in out], [1, 2, 3, 4, 5, 6])

    def test_latex_sections(self):
        text = (
            "\\section{Intro}\n"
            "body\n"
            "\\subsection{Setup}\n"
            "\\subsubsection{Specifics}"
        )
        out = self.mod._extract_sections_from_text(text, "latex")
        self.assertEqual(len(out), 3)
        titles = [s["title"] for s in out]
        self.assertEqual(titles, ["Intro", "Setup", "Specifics"])
        self.assertEqual([s["level"] for s in out], [2, 3, 4])

    def test_latex_starred_sections(self):
        text = "\\section*{Unnumbered}\n\\subsection{Numbered}"
        out = self.mod._extract_sections_from_text(text, "latex")
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["title"], "Unnumbered")

    def test_no_sections(self):
        out = self.mod._extract_sections_from_text("plain text", "markdown")
        self.assertEqual(out, [])


class ResolveTextTests(TestCase):
    def setUp(self):
        self.mod = _import_server()

    def test_raw_text_treated_as_markdown(self):
        text, fmt = self.mod._resolve_text("# Hello\nbody", "auto")
        self.assertEqual(fmt, "markdown")
        self.assertIn("Hello", text)

    def test_raw_text_with_explicit_latex(self):
        text, fmt = self.mod._resolve_text("\\section{X}", "latex")
        self.assertEqual(fmt, "latex")

    def test_real_file_path(self):
        with isolated_cache() as root:
            md = root / "doc.md"
            md.write_text("# Title\n\nBody")
            text, fmt = self.mod._resolve_text(str(md), "auto")
            self.assertEqual(fmt, "markdown")
            self.assertIn("Title", text)

    def test_real_tex_file_path(self):
        with isolated_cache() as root:
            tex = root / "doc.tex"
            tex.write_text("\\section{Intro}")
            text, fmt = self.mod._resolve_text(str(tex), "auto")
            self.assertEqual(fmt, "latex")


class ParseManuscriptTests(TestCase):
    def setUp(self):
        self.mod = _import_server()

    def test_full_ast_markdown(self):
        text = (
            "# Intro\n\nThe Vaswani paper [@vaswani2017] is foundational.\n\n"
            "## Methods\n\nWe extend [@kingma2014] further.\n"
        )
        out = self.mod.parse_manuscript(text, fmt="markdown")
        self.assertEqual(out["format"], "markdown")
        self.assertEqual(out["n_sections"], 2)
        self.assertEqual(out["n_citations"], 2)
        self.assertIn("vaswani2017", out["unique_citation_keys"])
        self.assertIn("kingma2014", out["unique_citation_keys"])
        self.assertGreater(out["word_count"], 5)

    def test_full_ast_latex(self):
        text = (
            "\\section{Intro}\n"
            "Following \\cite{smith2020,jones2021}.\n"
            "\\subsection{Setup}\n"
        )
        out = self.mod.parse_manuscript(text, fmt="latex")
        self.assertEqual(out["format"], "latex")
        self.assertEqual(out["n_sections"], 2)
        self.assertGreaterEqual(out["n_citations"], 2)


class DocxFallbackTests(TestCase):
    def setUp(self):
        self.mod = _import_server()

    def test_missing_pandoc_returns_error(self):
        # Path resolves to a non-existent file; we patch shutil.which to
        # always return None so the pandoc check fires before file IO.
        from unittest.mock import patch
        with isolated_cache() as root:
            fake_docx = root / "x.docx"
            fake_docx.write_bytes(b"PK\x03\x04")  # zip magic; never read
            with patch.object(self.mod.shutil, "which", return_value=None):
                out = self.mod.parse_manuscript(str(fake_docx), fmt="auto")
        self.assertIn("error", out)
        self.assertIn("pandoc", out["error"].lower())


if __name__ == "__main__":
    raise SystemExit(run_tests(
        FormatDetectTests,
        CitationExtractionTests,
        SectionExtractionTests,
        ResolveTextTests,
        ParseManuscriptTests,
        DocxFallbackTests,
    ))

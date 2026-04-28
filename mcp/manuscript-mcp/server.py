#!/usr/bin/env python3
"""manuscript-mcp — stdio MCP server: .docx / .tex / .md → structured AST.

Tools:
  parse_manuscript(path_or_text, fmt="auto") — full AST
  extract_sections(path_or_text, fmt="auto") — section tree only
  extract_citations(path_or_text, fmt="auto") — citation keys + spans
  detect_format(path)                          — sniff format from extension

Format autodetect:
  .md / .markdown → markdown
  .tex / .latex   → latex
  .docx           → docx (pandoc-based)
  no extension + raw text → markdown fallback

The Markdown + LaTeX paths are pure stdlib (regex). DOCX path uses
pandoc shell-out to convert .docx → markdown first, then re-parses.
Pandoc is a soft dep — if absent, docx requests return an error
explaining how to install.

Pattern mirrors retraction-mcp: FastMCP + import-time stub fallback
for the test environment.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as e:
    raise SystemExit(
        "manuscript-mcp requires the `mcp` package. Run via:\n"
        "  uv run --with mcp python mcp/manuscript-mcp/server.py\n"
        f"(import error: {e})"
    )


# ---------- format sniffing ----------

_KNOWN_EXTS = {
    ".md": "markdown", ".markdown": "markdown",
    ".tex": "latex", ".latex": "latex",
    ".docx": "docx",
}


def detect_format_from_path(path: str) -> str:
    """Return format inferred from extension, or 'markdown' as fallback."""
    ext = Path(path).suffix.lower()
    return _KNOWN_EXTS.get(ext, "markdown")


def _resolve_text(path_or_text: str, fmt: str) -> tuple[str, str]:
    """Returns (text, resolved_fmt). If path_or_text is a real file
    path, reads it and (when fmt='auto') sniffs format from extension.
    Otherwise treats input as raw text."""
    p = Path(path_or_text)
    is_path = (
        len(path_or_text) < 4096
        and "\n" not in path_or_text
        and p.exists()
        and p.is_file()
    )
    if is_path:
        if fmt == "auto":
            fmt = detect_format_from_path(str(p))
        if fmt == "docx":
            return _docx_to_markdown(p), "markdown"
        return p.read_text(encoding="utf-8", errors="replace"), fmt
    # Raw text: assume markdown unless explicitly stated.
    if fmt == "auto":
        fmt = "markdown"
    return path_or_text, fmt


def _docx_to_markdown(p: Path) -> str:
    """Shell out to pandoc; raise if pandoc missing."""
    if not shutil.which("pandoc"):
        raise RuntimeError(
            "pandoc not on PATH — required for .docx parsing. "
            "Install via `brew install pandoc` or apt/dnf equivalent."
        )
    with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as out:
        out_path = Path(out.name)
    try:
        subprocess.run(
            ["pandoc", str(p), "-f", "docx", "-t", "markdown",
             "-o", str(out_path)],
            check=True, capture_output=True,
        )
        return out_path.read_text(encoding="utf-8", errors="replace")
    finally:
        out_path.unlink(missing_ok=True)


# ---------- citation extraction ----------

_CITATION_PATTERNS = [
    # \cite{key1,key2}, \citep, \citet, \citeauthor, etc.
    (re.compile(r"\\cite[a-z]*\{([^}]+)\}"), "latex"),
    # Pandoc [@key] or [@key1; @key2]
    (re.compile(r"\[@([^;\]\s]+(?:\s*;\s*@[^;\]\s]+)*)\]"), "pandoc"),
    # Numeric [1], [1,2-5]
    (re.compile(r"\[(\d+(?:\s*[,-]\s*\d+)*)\]"), "numeric"),
    # Author-year (Smith, 2020) / (Smith et al., 2020a)
    (re.compile(
        r"\(([A-Z][a-zA-Z]+(?:\s+et\s+al\.?)?,?\s+\d{4}[a-z]?)\)"
    ), "author-year"),
]


def _extract_citations_from_text(text: str) -> list[dict[str, Any]]:
    """Walk all citation patterns; emit {key, style, span: [start, end]}."""
    out: list[dict[str, Any]] = []
    for pat, style in _CITATION_PATTERNS:
        for m in pat.finditer(text):
            keys_blob = m.group(1)
            if style == "pandoc":
                keys = [k.lstrip("@").strip()
                        for k in re.split(r"\s*;\s*@?", keys_blob) if k.strip()]
            elif style == "latex":
                keys = [k.strip() for k in keys_blob.split(",") if k.strip()]
            else:
                keys = [keys_blob.strip()]
            for k in keys:
                out.append({"key": k, "style": style,
                            "span": [m.start(), m.end()]})
    # Stable order by position
    out.sort(key=lambda r: (r["span"][0], r["key"]))
    return out


# ---------- section extraction ----------

_MD_HEADER_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_LATEX_SECTION_RE = re.compile(
    r"\\(part|chapter|section|subsection|subsubsection|paragraph|"
    r"subparagraph)\*?\{([^}]+)\}"
)
_LATEX_LEVEL = {
    "part": 1, "chapter": 1, "section": 2,
    "subsection": 3, "subsubsection": 4,
    "paragraph": 5, "subparagraph": 6,
}


def _extract_sections_from_text(text: str, fmt: str) -> list[dict[str, Any]]:
    """Returns flat list of {level, title, span: [start, end]} entries
    in document order. Caller can rebuild a tree from levels."""
    out: list[dict[str, Any]] = []
    if fmt == "latex":
        for m in _LATEX_SECTION_RE.finditer(text):
            kind = m.group(1).lower()
            out.append({
                "level": _LATEX_LEVEL.get(kind, 6),
                "title": m.group(2).strip(),
                "span": [m.start(), m.end()],
                "kind": kind,
            })
    else:  # markdown / auto
        for m in _MD_HEADER_RE.finditer(text):
            out.append({
                "level": len(m.group(1)),
                "title": m.group(2).strip(),
                "span": [m.start(), m.end()],
                "kind": "atx-heading",
            })
    return out


# ---------- tools ----------

mcp = FastMCP("manuscript-mcp")


def _trace_emit(tool_name: str, args_summary: dict | None,
                result_summary: dict | None) -> None:
    """v0.93c — best-effort tool-call span emit."""
    try:
        from lib.trace import maybe_emit_tool_call
        maybe_emit_tool_call(
            tool_name,
            args_summary=args_summary,
            result_summary=result_summary,
        )
    except Exception:
        pass


@mcp.tool()
def detect_format(path: str) -> dict[str, str]:
    """Sniff manuscript format from file extension.

    Returns: {"path": <as given>, "format": "markdown"|"latex"|"docx"}.
    """
    return {"path": path, "format": detect_format_from_path(path)}


@mcp.tool()
def extract_citations(
    path_or_text: str, fmt: str = "auto",
) -> dict[str, Any]:
    """Extract every citation reference from a manuscript.

    Each entry: {key, style: latex|pandoc|numeric|author-year,
                 span: [start, end]}. Sorted by position.
    """
    try:
        text, resolved_fmt = _resolve_text(path_or_text, fmt)
    except RuntimeError as e:
        return {"error": str(e)}
    citations = _extract_citations_from_text(text)
    return {
        "format": resolved_fmt,
        "n_citations": len(citations),
        "unique_keys": sorted({c["key"] for c in citations}),
        "citations": citations,
    }


@mcp.tool()
def extract_sections(
    path_or_text: str, fmt: str = "auto",
) -> dict[str, Any]:
    """Extract the section / heading tree from a manuscript.

    Each entry: {level, title, span, kind}. Levels follow the source
    (1 = top-level), so the caller can rebuild a tree by walking
    levels.
    """
    try:
        text, resolved_fmt = _resolve_text(path_or_text, fmt)
    except RuntimeError as e:
        return {"error": str(e)}
    sections = _extract_sections_from_text(text, resolved_fmt)
    return {
        "format": resolved_fmt,
        "n_sections": len(sections),
        "sections": sections,
    }


@mcp.tool()
def parse_manuscript(
    path_or_text: str, fmt: str = "auto",
) -> dict[str, Any]:
    """Full structural AST: format + sections + citations + word count.

    For .docx, pandoc is shelled out to convert to markdown first.
    """
    try:
        text, resolved_fmt = _resolve_text(path_or_text, fmt)
    except RuntimeError as e:
        result = {"error": str(e)}
        _trace_emit("parse_manuscript",
                    {"path_or_text_len": len(path_or_text), "fmt": fmt},
                    {"error": str(e)})
        return result
    sections = _extract_sections_from_text(text, resolved_fmt)
    citations = _extract_citations_from_text(text)
    word_count = len(re.findall(r"\b\w+\b", text))
    result = {
        "format": resolved_fmt,
        "word_count": word_count,
        "char_count": len(text),
        "n_sections": len(sections),
        "n_citations": len(citations),
        "unique_citation_keys": sorted({c["key"] for c in citations}),
        "sections": sections,
        "citations": citations,
    }
    _trace_emit("parse_manuscript",
                {"format": resolved_fmt, "fmt": fmt},
                {"word_count": word_count,
                 "n_sections": len(sections),
                 "n_citations": len(citations)})
    return result


def main() -> None:
    """Console-script entry. v0.80 — pyproject scripts hook."""
    mcp.run()


if __name__ == "__main__":
    main()

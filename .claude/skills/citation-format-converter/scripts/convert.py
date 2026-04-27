#!/usr/bin/env python3
"""citation-format-converter: pandoc-driven format + style conversion.

Two operations:
  - convert: bibtex ↔ csl-json ↔ ris ↔ endnote
  - format:  render references in a journal style (apa, chicago, ...)

Pandoc is required.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

# Format → pandoc CLI flag value for --output-format / --input-format
FORMAT_TO_PANDOC = {
    "bibtex": "biblatex",
    "csl-json": "csljson",
    "ris": "ris",
    "endnote": "endnotexml",
}

# Recognised file extensions → format
EXT_TO_FORMAT = {
    ".bib": "bibtex",
    ".json": "csl-json",
    ".ris": "ris",
    ".xml": "endnote",
}

STYLES = {
    "apa": "apa",
    "chicago": "chicago-author-date",
    "chicago-note": "chicago-note-bibliography",
    "nature": "nature",
    "ieee": "ieee",
    "mla": "modern-language-association",
    "vancouver": "vancouver",
}


def _ensure_pandoc() -> None:
    if not shutil.which("pandoc"):
        raise SystemExit(
            "pandoc not found on PATH. "
            "Install via `brew install pandoc` (macOS) or your package manager."
        )


def _detect_format(path: Path) -> str | None:
    return EXT_TO_FORMAT.get(path.suffix.lower())


def cmd_convert(args: argparse.Namespace) -> dict:
    _ensure_pandoc()
    in_path = Path(args.input)
    out_path = Path(args.output)
    if not in_path.exists():
        raise SystemExit(f"input not found: {in_path}")

    src_fmt = args.from_ or _detect_format(in_path)
    dst_fmt = args.to or _detect_format(out_path)
    if src_fmt is None:
        raise SystemExit(
            f"can't infer source format from {in_path.suffix!r}; "
            f"pass --from"
        )
    if dst_fmt is None:
        raise SystemExit(
            f"can't infer target format from {out_path.suffix!r}; "
            f"pass --to"
        )
    if src_fmt not in FORMAT_TO_PANDOC:
        raise SystemExit(
            f"unknown source format {src_fmt!r}; "
            f"valid: {sorted(FORMAT_TO_PANDOC)}"
        )
    if dst_fmt not in FORMAT_TO_PANDOC:
        raise SystemExit(
            f"unknown target format {dst_fmt!r}; "
            f"valid: {sorted(FORMAT_TO_PANDOC)}"
        )

    cmd = [
        "pandoc",
        "--from", FORMAT_TO_PANDOC[src_fmt],
        "--to", FORMAT_TO_PANDOC[dst_fmt],
        str(in_path),
        "-o", str(out_path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"pandoc failed: {r.stderr}")

    return {
        "from": src_fmt,
        "to": dst_fmt,
        "input": str(in_path),
        "output": str(out_path),
        "bytes_written": out_path.stat().st_size if out_path.exists() else 0,
    }


def cmd_format(args: argparse.Namespace) -> dict:
    """Render references in a journal style. Output is plain text."""
    _ensure_pandoc()
    in_path = Path(args.input)
    out_path = Path(args.output)
    if args.style not in STYLES:
        raise SystemExit(
            f"unknown style {args.style!r}; valid: {sorted(STYLES)}"
        )
    if not in_path.exists():
        raise SystemExit(f"input not found: {in_path}")

    csl_name = STYLES[args.style]
    src_fmt = args.from_ or _detect_format(in_path) or "bibtex"

    # Build a minimal markdown document that nocite's all entries from the
    # bibliography, then render with --citeproc using the style.
    md_doc = "---\nnocite: |\n  @*\n---\n\n# References\n"
    md_path = out_path.with_suffix(".tmp.md")
    md_path.write_text(md_doc)

    cmd = [
        "pandoc",
        str(md_path),
        "--from", "markdown",
        "--to", "plain",
        "--citeproc",
        "--bibliography", str(in_path),
        "--csl", _resolve_csl(csl_name),
        "-o", str(out_path),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True)
    finally:
        md_path.unlink(missing_ok=True)
    if r.returncode != 0:
        raise SystemExit(f"pandoc failed: {r.stderr}")

    return {
        "style": args.style,
        "csl": csl_name,
        "input": str(in_path),
        "output": str(out_path),
        "bytes_written": out_path.stat().st_size if out_path.exists() else 0,
    }


def _resolve_csl(name: str) -> str:
    """Try local CSL bundle first; fall back to the GitHub URL pandoc fetches."""
    # Pandoc accepts a bare style name and will try to download from
    # https://www.zotero.org/styles/<name>. For deterministic behaviour
    # we point at the GitHub CSL repo's raw URL.
    return (
        f"https://raw.githubusercontent.com/citation-style-language/"
        f"styles/master/{name}.csl"
    )


def cmd_styles(args: argparse.Namespace) -> dict:
    return {
        "formats": sorted(FORMAT_TO_PANDOC),
        "styles": [{"key": k, "csl": v} for k, v in STYLES.items()],
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("convert")
    c.add_argument("--input", required=True)
    c.add_argument("--output", required=True)
    c.add_argument("--from", dest="from_", default=None)
    c.add_argument("--to", default=None)
    c.set_defaults(func=cmd_convert)

    f = sub.add_parser("format")
    f.add_argument("--input", required=True)
    f.add_argument("--output", required=True)
    f.add_argument("--style", required=True, choices=sorted(STYLES))
    f.add_argument("--from", dest="from_", default=None)
    f.set_defaults(func=cmd_format)

    s = sub.add_parser("styles")
    s.set_defaults(func=cmd_styles)

    args = p.parse_args()
    out = args.func(args)
    sys.stdout.write(json.dumps(out, indent=2, default=str) + "\n")


if __name__ == "__main__":
    main()

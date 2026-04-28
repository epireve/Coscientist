#!/usr/bin/env python3
"""manuscript-format: export a manuscript draft to venue-specific formats via pandoc.

Subcommands
-----------
export    Convert source.md to .tex, .docx, or .pdf for a target venue.
list      Show all exports for a manuscript (paths + timestamps).
clean     Remove all exports for a manuscript.

Typical workflow
----------------
  # Export to LaTeX for NeurIPS
  python format.py export --manuscript-id <mid> --venue neurips --output-format tex

  # Export to Word
  python format.py export --manuscript-id <mid> --venue docx --output-format docx

  # List all exports
  python format.py list --manuscript-id <mid>

  # Remove all exports
  python format.py clean --manuscript-id <mid>
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from pandoc_utils import (  # noqa: E402
    KNOWN_OUTPUT_FORMATS,
    KNOWN_VENUES,
    build_pandoc_args,
    pandoc_available,
    strip_placeholders,
)

from lib.artifact import ManuscriptArtifact  # noqa: E402

_PANDOC_ERROR = (
    "pandoc not installed — install via https://pandoc.org/installing.html"
)

# Extension map for output formats
_EXT = {"tex": ".tex", "docx": ".docx", "pdf": ".pdf"}


# --------------------------------------------------------------------------- #
# Subcommand: export                                                           #
# --------------------------------------------------------------------------- #

def cmd_export(args: argparse.Namespace) -> int:
    if not pandoc_available():
        print(_PANDOC_ERROR, file=sys.stderr)
        return 1

    venue = args.venue.lower()
    if venue not in KNOWN_VENUES:
        print(
            f"ERROR: unknown venue {venue!r}. Known: {', '.join(sorted(KNOWN_VENUES))}",
            file=sys.stderr,
        )
        return 2

    output_format = args.output_format.lower()
    if output_format not in KNOWN_OUTPUT_FORMATS:
        print(
            f"ERROR: unknown output-format {output_format!r}. "
            f"Known: {', '.join(sorted(KNOWN_OUTPUT_FORMATS))}",
            file=sys.stderr,
        )
        return 2

    art = ManuscriptArtifact(args.manuscript_id)
    source_path = art.root / "source.md"
    if not source_path.exists():
        print(
            f"ERROR: source.md not found for manuscript {args.manuscript_id!r}. "
            f"Run manuscript-draft init or manuscript-ingest first.",
            file=sys.stderr,
        )
        return 1

    # Prepare exports directory
    exports_dir = art.root / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)

    ext = _EXT[output_format]
    output_path = exports_dir / f"{venue}{ext}"

    # Read and strip placeholders from source
    source_text = source_path.read_text()
    stripped = strip_placeholders(source_text)

    # Write stripped content to a temp file for pandoc
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(stripped)
        tmp_path = Path(tmp.name)

    try:
        pandoc_args = build_pandoc_args(venue, output_format, tmp_path, output_path)
        result = subprocess.run(
            pandoc_args,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(
                f"ERROR: pandoc exited with code {result.returncode}:\n{result.stderr}",
                file=sys.stderr,
            )
            return result.returncode
    finally:
        tmp_path.unlink(missing_ok=True)

    print(str(output_path))
    return 0


# --------------------------------------------------------------------------- #
# Subcommand: list                                                             #
# --------------------------------------------------------------------------- #

def cmd_list(args: argparse.Namespace) -> int:
    art = ManuscriptArtifact(args.manuscript_id)
    exports_dir = art.root / "exports"

    if not exports_dir.exists():
        print("(no exports)")
        return 0

    files = sorted(exports_dir.iterdir())
    if not files:
        print("(no exports)")
        return 0

    for f in files:
        mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        print(f"{f}  [{mtime}]")

    return 0


# --------------------------------------------------------------------------- #
# Subcommand: clean                                                            #
# --------------------------------------------------------------------------- #

def cmd_clean(args: argparse.Namespace) -> int:
    import shutil

    art = ManuscriptArtifact(args.manuscript_id)
    exports_dir = art.root / "exports"

    if not exports_dir.exists():
        print(f"No exports directory for manuscript {args.manuscript_id!r} — nothing to clean.")
        return 0

    files = list(exports_dir.iterdir())
    if not files:
        print(f"exports/ directory is already empty for manuscript {args.manuscript_id!r}.")
        shutil.rmtree(exports_dir)
        return 0

    shutil.rmtree(exports_dir)
    print(f"Removed exports/ for manuscript {args.manuscript_id!r} ({len(files)} file(s) deleted).")
    return 0


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #

def main() -> int:
    p = argparse.ArgumentParser(
        prog="format.py",
        description="Export a manuscript draft to venue-specific formats via pandoc.",
    )
    sub = p.add_subparsers(dest="subcommand", required=True)

    # export
    pe = sub.add_parser("export", help="Convert source.md to .tex/.docx/.pdf")
    pe.add_argument("--manuscript-id", required=True, dest="manuscript_id",
                    help="Manuscript artifact ID")
    pe.add_argument(
        "--venue",
        required=True,
        choices=sorted(KNOWN_VENUES),
        help="Target venue (e.g. neurips, acl, imrad, arxiv, docx)",
    )
    pe.add_argument(
        "--output-format",
        required=True,
        dest="output_format",
        choices=sorted(KNOWN_OUTPUT_FORMATS),
        help="Output format: tex, docx, or pdf",
    )

    # list
    pl = sub.add_parser("list", help="Show all exports for a manuscript")
    pl.add_argument("--manuscript-id", required=True, dest="manuscript_id")

    # clean
    pc = sub.add_parser("clean", help="Remove all exports for a manuscript")
    pc.add_argument("--manuscript-id", required=True, dest="manuscript_id")

    args = p.parse_args()
    dispatch = {
        "export": cmd_export,
        "list": cmd_list,
        "clean": cmd_clean,
    }
    return dispatch[args.subcommand](args)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Vision-LLM fallback for pdf-extract.

Rasterizes the PDF page-by-page and writes placeholder instructions for the
calling Claude agent to read the images and produce content.md itself.

Why: this skill runs under a Claude Code session that already has multimodal
access. Instead of calling an external vision API, we save the rasterized
pages and let the invoking agent read them via the `Read` tool.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.paper_artifact import PaperArtifact  # noqa: E402


def rasterize(pdf: Path, out_dir: Path) -> list[Path]:
    try:
        import fitz  # PyMuPDF
    except ImportError as e:
        raise SystemExit(
            "PyMuPDF not installed. Add `pymupdf` to pyproject dependencies."
        ) from e
    out_dir.mkdir(parents=True, exist_ok=True)
    pages: list[Path] = []
    doc = fitz.open(pdf)
    for i, page in enumerate(doc):
        pix = page.get_pixmap(dpi=200)
        out = out_dir / f"page-{i+1:04d}.png"
        pix.save(str(out))
        pages.append(out)
    return pages


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--canonical-id", required=True)
    args = p.parse_args()

    art = PaperArtifact(args.canonical_id)
    pdf = art.primary_pdf()
    if pdf is None:
        raise SystemExit("no PDF")

    page_dir = art.root / "pages"
    pages = rasterize(pdf, page_dir)

    # Write a handoff manifest so the calling agent knows what to read.
    handoff = {
        "engine": "vision_fallback",
        "at": datetime.now(UTC).isoformat(),
        "pdf": str(pdf),
        "pages": [str(p) for p in pages],
        "instructions": (
            "Read each page image in order, transcribe into structured markdown, "
            "identify figures/tables/equations, and write to content.md. "
            "Extract figures as separate PNGs under figures/ and index them in figures.json."
        ),
    }
    (art.root / "vision_handoff.json").write_text(json.dumps(handoff, indent=2))

    # Minimal placeholder so downstream skills see content.md exists.
    if not art.content_path.exists():
        art.content_path.write_text(
            f"# Vision-fallback pending\n\n"
            f"Rasterized {len(pages)} pages under `{page_dir}`. "
            f"See `vision_handoff.json` for transcription instructions.\n"
        )
    print(args.canonical_id)


if __name__ == "__main__":
    main()

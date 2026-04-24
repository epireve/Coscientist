#!/usr/bin/env python3
"""pdf-extract: Docling-primary PDF extraction into the paper artifact.

Falls back to vision_fallback.py when Docling output is low-confidence.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.paper_artifact import PaperArtifact, State  # noqa: E402

MIN_CONFIDENCE_CHARS = 1500  # heuristic: <1500 chars ≈ extraction failed


def _run_docling(pdf: Path, art: PaperArtifact) -> dict:
    """Run Docling and persist artifact files. Returns a log dict."""
    try:
        from docling.document_converter import DocumentConverter
    except ImportError as e:
        raise SystemExit("docling not installed. Run `uv sync`.") from e

    converter = DocumentConverter()
    result = converter.convert(str(pdf))
    doc = result.document

    md = doc.export_to_markdown()
    art.content_path.write_text(md)

    # Figures
    figures_meta: list[dict] = []
    for i, pic in enumerate(getattr(doc, "pictures", []) or []):
        fig_id = f"fig-{i+1:03d}"
        img = getattr(pic, "image", None)
        if img is not None:
            out = art.figures_dir / f"{fig_id}.png"
            try:
                img.save(str(out))
            except Exception:
                continue
            figures_meta.append(
                {
                    "id": fig_id,
                    "caption": (getattr(pic, "caption_text", None) or "")[:500],
                    "page": getattr(pic, "page_no", None),
                    "bbox": getattr(pic, "bbox", None),
                    "type": "figure",
                }
            )
    art.figures_json.write_text(json.dumps(figures_meta, indent=2, default=str))

    # Tables
    tables_meta: list[dict] = []
    for i, tbl in enumerate(getattr(doc, "tables", []) or []):
        tbl_id = f"tbl-{i+1:03d}"
        md_out = art.tables_dir / f"{tbl_id}.md"
        csv_out = art.tables_dir / f"{tbl_id}.csv"
        try:
            md_out.write_text(tbl.export_to_markdown() if hasattr(tbl, "export_to_markdown") else str(tbl))
        except Exception:
            md_out.write_text(str(tbl))
        try:
            df = tbl.export_to_dataframe() if hasattr(tbl, "export_to_dataframe") else None
            if df is not None:
                df.to_csv(csv_out, index=False)
        except Exception:
            pass
        tables_meta.append({"id": tbl_id, "page": getattr(tbl, "page_no", None)})

    # Equations (best-effort — Docling exposes these through document tree)
    equations: list[dict] = []
    for i, eq in enumerate(getattr(doc, "equations", []) or []):
        equations.append(
            {
                "id": f"eq-{i+1:03d}",
                "latex": getattr(eq, "latex", None) or getattr(eq, "text", ""),
                "page": getattr(eq, "page_no", None),
            }
        )
    art.equations_json.write_text(json.dumps(equations, indent=2, default=str))

    # References: Docling doesn't structure them by default; keep placeholder
    if not art.references_json.exists():
        art.references_json.write_text("[]")

    return {
        "engine": "docling",
        "chars": len(md),
        "figures": len(figures_meta),
        "tables": len(tables_meta),
        "equations": len(equations),
    }


def _invoke_vision_fallback(cid: str) -> None:
    script = Path(__file__).with_name("vision_fallback.py")
    subprocess.run(
        [sys.executable, str(script), "--canonical-id", cid],
        check=True,
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--canonical-id", required=True)
    p.add_argument("--force", action="store_true")
    p.add_argument("--engine", choices=["docling", "vision", "auto"], default="auto")
    args = p.parse_args()

    art = PaperArtifact(args.canonical_id)
    pdf = art.primary_pdf()
    if pdf is None:
        raise SystemExit(f"no PDF in {art.raw_dir}; run paper-acquire first")

    if art.has_full_text() and not args.force:
        print(f"already extracted: {art.content_path}")
        return

    log: dict = {"at": datetime.now(UTC).isoformat(), "pdf": str(pdf)}

    if args.engine == "vision":
        _invoke_vision_fallback(args.canonical_id)
        log["engine"] = "vision"
    else:
        try:
            docling_log = _run_docling(pdf, art)
            log.update(docling_log)
            if docling_log["chars"] < MIN_CONFIDENCE_CHARS and args.engine == "auto":
                log["low_confidence"] = True
                log["fallback"] = "vision"
                _invoke_vision_fallback(args.canonical_id)
        except Exception as e:
            log["docling_error"] = str(e)
            if args.engine == "auto":
                log["fallback"] = "vision"
                _invoke_vision_fallback(args.canonical_id)
            else:
                raise

    art.extraction_log.write_text(json.dumps(log, indent=2))
    art.set_state(State.extracted)
    print(args.canonical_id)


if __name__ == "__main__":
    main()

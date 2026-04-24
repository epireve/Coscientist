---
name: pdf-extract
description: Convert a PDF (already saved to the paper artifact's raw/ dir) into structured Markdown plus figures, tables, equations, and references. Primary engine is Docling; Claude vision is the fallback for scanned or image-only PDFs.
when_to_use: A non-arXiv PDF has been acquired by `paper-acquire` (or `institutional-access`) and sits at `raw/*.pdf`. For arXiv papers, prefer `arxiv-to-markdown`.
---

# pdf-extract

Two-tier extraction:

1. **Docling** (primary) — layout-aware; handles figures, tables, equations, reading order.
2. **Claude vision fallback** — when Docling returns low-confidence or near-empty output (scanned PDFs, image-only exports).

## Inputs

- `canonical_id` of a paper whose `raw/*.pdf` exists
- Optional: `--force` to rerun even if `content.md` already exists
- Optional: `--engine docling|vision` to bypass auto-selection

## How to run

```bash
uv run python .claude/skills/pdf-extract/scripts/extract.py \
  --canonical-id <cid> \
  [--force] [--engine docling]
```

On low-confidence or failure, the script automatically calls:

```bash
uv run python .claude/skills/pdf-extract/scripts/vision_fallback.py \
  --canonical-id <cid>
```

## Outputs (per paper artifact contract)

All under `~/.cache/coscientist/papers/<canonical_id>/`:

- `content.md` — structured markdown with section headings, inline figure/table refs
- `figures/<id>.png` — extracted images
- `figures.json` — `[{id, caption, page, bbox, type}]`
- `tables/<id>.md` + `tables/<id>.csv` — one pair per table
- `equations.json` — `[{id, latex, surrounding_text}]`
- `references.json` — parsed bibliography; DOIs resolved where possible
- `extraction.log` — which engine ran, confidence score, fallbacks used
- Updates `manifest.json` state → `extracted`

## Figure handling

Figures are stored as **image files** — not described in text. Downstream agents that need to reason about a figure call `Read` on the file directly (Claude is multimodal). A `describe_figure` helper can be added later if we want pre-generated captions.

## Guarantees

- Idempotent when `content.md` exists, unless `--force`
- Low-confidence triggers vision fallback automatically — no silent bad extractions
- Never modifies `raw/` — original PDF is preserved

---
name: arxiv-to-markdown
description: Convert an arXiv paper (URL or ID) into clean structured Markdown with frontmatter. Preferred over pdf-extract whenever the source is arXiv — uses arXiv's native HTML so math (MathML → LaTeX), tables, and section hierarchy are preserved without OCR.
when_to_use: The paper has an arXiv ID or URL. Do not use this for papers hosted elsewhere — use `pdf-extract` after `paper-acquire` for those.
---

# arxiv-to-markdown

Wraps the [`arxiv2markdown`](https://pypi.org/project/arxiv2markdown/) PyPI package. Output lands in the standard paper artifact layout so downstream skills (`paper-triage`, `research-eval`, `deep-research`) can consume it unchanged.

## Inputs

- `arxiv_id` (e.g., `2501.11120` or `2501.11120v1`) **or** an arXiv URL
- Optional: `canonical_id` — if known from a prior `paper-discovery` run; otherwise it's derived from metadata
- Optional flags: `--remove-refs`, `--remove-toc`, `--remove-citations`, `--sections <csv>`

## How to run

```bash
uv run python .claude/skills/arxiv-to-markdown/scripts/fetch.py \
  --arxiv-id 2501.11120 \
  [--canonical-id <cid>] \
  [--remove-refs] [--remove-toc] [--remove-citations]
```

Without `--canonical-id`, the script derives it from the paper's metadata and prints it to stdout for the caller to pass downstream.

## Outputs (per paper artifact contract)

Written under `~/.cache/coscientist/papers/<canonical_id>/`:

- `content.md` — structured markdown
- `frontmatter.yaml` — title, authors, venue, year, arxiv_id, doi
- `metadata.json` — populated/updated via `lib.paper_artifact`
- `manifest.json` — `state` advances to `extracted`
- `references.json` — parsed bibliography if present
- `extraction.log` — records `"extractor": "arxiv2markdown"`

## When to fall back

If `arxiv2markdown` errors (withdrawn paper, no HTML version, malformed math), the script exits non-zero. The caller (`deep-research` or `paper-acquire`) should then:

1. Fetch the PDF from arXiv directly (it's always OA)
2. Hand off to `/pdf-extract` instead

## Guarantees

- Does **not** network-fetch anything except arXiv itself.
- Idempotent: re-running on the same paper overwrites `content.md` and leaves other artifact files untouched unless explicitly regenerated.
- Safe to run inside `paper-discovery` for instant markdown of arXiv hits.

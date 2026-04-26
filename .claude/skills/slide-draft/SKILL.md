---
name: slide-draft
description: Convert a manuscript into a slide deck — beamer (LaTeX) for academic talks, pptx for general use, or revealjs for HTML. Builds an outline.json mapping manuscript sections to slide groups, then renders via pandoc. Strips placeholders before export. Mirrors manuscript-format pattern.
when_to_use: User says "make slides from this paper", "draft a talk", "convert to beamer", "presentation deck". Requires a manuscript artifact already ingested.
---

# slide-draft

Manuscript → slide deck. Two-stage:

1. **Outline build** (`outline`) — section-to-slide-group mapping, written to `manuscripts/<mid>/slides/outline.json`. User reviews/edits before rendering.
2. **Render** (`render`) — pandoc-based export to `.tex` (beamer), `.pptx`, `.html` (revealjs), or `.md` (slidev-compatible).

## Scripts

| Script | CLI | Purpose |
|---|---|---|
| `slide.py` | subcommands: `outline`, `render`, `list`, `clean`, `formats` | Main entry |

## Subcommands

```
slide.py outline --manuscript-id MID [--style standard|short-talk|long-talk|poster] [--force]
slide.py render --manuscript-id MID --format beamer|pptx|revealjs|slidev [--output PATH]
slide.py list --manuscript-id MID
slide.py clean --manuscript-id MID
slide.py formats
```

## Slide styles

| Style | Slides | Purpose |
|---|---|---|
| `standard` | ~15 | 12-min conference talk |
| `short-talk` | ~8 | 5-min lightning |
| `long-talk` | ~30 | 30-min seminar |
| `poster` | ~6 | poster sections (sectioned, not slides per se) |

## Output formats

- **beamer**: pandoc `--to=beamer`, produces `.tex` + bib for compile via `latexmk`
- **pptx**: pandoc `--to=pptx`, produces standalone `.pptx`
- **revealjs**: pandoc `--to=revealjs`, produces self-contained `.html`
- **slidev**: emits frontmatter + `---` separators in markdown for the [Slidev](https://sli.dev/) tool

## Storage

```
manuscripts/<mid>/slides/
  outline.json    # slide groups + per-group source-section mapping
  exports/
    deck.tex
    deck.pptx
    deck.html
    deck.slidev.md
```

## Outline structure

```json
{
  "manuscript_id": "...",
  "style": "standard",
  "slides": [
    {"id": 1, "title": "Title", "from_section": null, "type": "title"},
    {"id": 2, "title": "Motivation", "from_section": "Introduction", "type": "content"},
    {"id": 3, "title": "Method", "from_section": "Methods", "type": "content"},
    ...
  ]
}
```

`from_section` references manuscript section heading (matching `## Heading` in `source.md`). User may edit `outline.json` to redistribute content.

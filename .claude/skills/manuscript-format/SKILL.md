---
name: manuscript-format
description: Pandoc-driven export of a manuscript draft (source.md) to venue-specific formats — LaTeX (.tex), Word (.docx), and optionally PDF. Strips placeholder sections before export, writes output under the manuscript artifact's exports/ subdirectory.
when_to_use: You have a manuscript artifact with a source.md and want to produce a submission-ready file in a venue-specific format. Use after manuscript-draft has filled the sections you want exported, or after manuscript-ingest has created the artifact. Supports neurips, acl, nature, imrad, arxiv, and docx as export targets.
---

# manuscript-format

Pandoc-driven export of `source.md` to LaTeX or Word for a target venue. The skill handles YAML frontmatter, strips `[PLACEHOLDER ...]` sections and HTML comment blocks, and calls pandoc with venue-appropriate options. Output lands in the manuscript artifact's `exports/` directory.

## Prerequisites

- [pandoc](https://pandoc.org/installing.html) must be on `PATH`. If it is not, all subcommands print a clear error and exit with code 1.
- A manuscript artifact (`manuscripts/<mid>/`) must exist and contain `source.md`.

## Subcommands

### export — convert source.md to a venue format

```bash
uv run python .claude/skills/manuscript-format/scripts/format.py export \
  --manuscript-id <mid> \
  --venue <venue> \
  --output-format <tex|docx|pdf>
```

Writes the output file to:

```
~/.cache/coscientist/manuscripts/<mid>/exports/<venue>.<ext>
```

Creates the `exports/` directory if it does not exist.

Prints the absolute output path to stdout on success.

**Supported venues**

| Venue | Description | Output class |
|---|---|---|
| `neurips` | NeurIPS submission | LaTeX `article` with NeurIPS-style options |
| `acl` | ACL / EMNLP / NAACL | LaTeX with ACL-style YAML block |
| `nature` | Nature / Nature Methods | LaTeX minimal article |
| `imrad` | Generic empirical (IMRaD) | LaTeX generic article |
| `arxiv` | arXiv preprint | LaTeX arxiv-friendly article |
| `docx` | Venue-agnostic Word | .docx (any output-format) |

**Placeholder handling**

Before calling pandoc, `format.py` strips:
- Lines/blocks matching `[PLACEHOLDER ...]` (sections not yet drafted)
- HTML comment blocks `<!-- ... -->` (notes, targets)

Real content is left untouched.

### list — show all exports for a manuscript

```bash
uv run python .claude/skills/manuscript-format/scripts/format.py list \
  --manuscript-id <mid>
```

Prints each export file path and its modification timestamp. Prints `(no exports)` if the `exports/` directory does not exist or is empty.

### clean — remove all exports for a manuscript

```bash
uv run python .claude/skills/manuscript-format/scripts/format.py clean \
  --manuscript-id <mid>
```

Removes the `exports/` directory and all its contents. Prints a friendly message if there is nothing to clean (exits 0).

## Guarantees

- If pandoc is not installed, every subcommand prints exactly:
  `pandoc not installed — install via https://pandoc.org/installing.html`
  and exits with code 1.
- `export` never modifies `source.md` — it works on an in-memory copy.
- `clean` on a manuscript with no exports exits 0 without error.
- Unknown `--venue` or `--output-format` values produce an error message and non-zero exit code.
- Missing `--manuscript-id` produces a non-zero exit code.

## Output layout

```
manuscripts/<manuscript_id>/
  source.md           # unchanged
  exports/
    imrad.tex         # example: --venue imrad --output-format tex
    neurips.tex       # example: --venue neurips --output-format tex
    docx.docx         # example: --venue docx --output-format docx
```

---
name: citation-format-converter
description: Convert citation files between formats (BibTeX ↔ CSL-JSON ↔ RIS ↔ EndNote) and format references in different journal styles (APA, Chicago, Nature, IEEE). Pandoc-driven wrapper. Pure conversion — no fetching, no de-duplication, no semantic edits.
when_to_use: User says "convert .bib to .ris", "format these refs as APA", "EndNote to BibTeX", "Chicago citation style", "switch reference format". Submission to a different journal that demands a specific format.
---

# citation-format-converter

Pandoc does the heavy lifting. This skill is a thin CLI wrapper for the two common operations: format conversion + style rendering.

## Subcommands

```bash
# Convert between formats (BibTeX ↔ CSL-JSON ↔ RIS ↔ EndNote)
uv run python .claude/skills/citation-format-converter/scripts/convert.py convert \
  --input refs.bib --output refs.json [--from bibtex] [--to csl-json]

# Render references in a specific journal style (APA/Chicago/Nature/IEEE/MLA)
uv run python .claude/skills/citation-format-converter/scripts/convert.py format \
  --input refs.bib --style apa --output refs.txt

# List all available styles + supported format conversions
uv run python .claude/skills/citation-format-converter/scripts/convert.py styles
```

## Supported formats

`--from` / `--to`:
- `bibtex` — `.bib`
- `csl-json` — Citation Style Language JSON, `.json`
- `ris` — Research Information Systems, `.ris`
- `endnote` — EndNote XML, `.xml`

Auto-detect from file extension if `--from`/`--to` omitted.

## Supported styles

| Style | Notes |
|---|---|
| `apa` | APA 7th edition |
| `chicago` | Chicago author-date |
| `chicago-note` | Chicago notes-bibliography |
| `nature` | Nature numeric |
| `ieee` | IEEE numeric |
| `mla` | MLA 9th |
| `vancouver` | Vancouver numeric (medical) |

## What it does NOT do

- No fetching from DOI / S2 / Crossref. Use `paper-discovery` for that.
- No deduplication. Use `paper-discovery merge.py` for that.
- No retraction check. Use `retraction-watch`.
- Doesn't write to project DB. Pure file I/O.

## Principles

From `RESEARCHER.md`: deterministic transforms only. Citation conversion is a syntax operation, not a semantic one — this skill keeps it that way.

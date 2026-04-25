---
name: manuscript-draft
description: Create a new manuscript from scratch using a venue template. Generates a structured outline (outline.json) and a source.md with placeholder sections, then fills sections one at a time with tracked word counts and cite-key harvesting. Markdown-first; export to LaTeX/docx via `manuscript-format` (future).
when_to_use: You are starting a new paper and want a structured scaffold. Pick a venue template (imrad, neurips, acl, nature, thesis) to get the correct section order, word targets, and venue-specific notes. Use `section` to fill each section incrementally; use `status` to monitor progress. Feed the completed source.md to `manuscript-ingest` for audit/critique/reflect.
---

# manuscript-draft

Markdown-first scaffold for new academic manuscripts. The output is a
`source.md` that follows venue conventions and is immediately readable by
`manuscript-ingest` → `manuscript-audit` → `manuscript-critique`.

## Subcommands

### init — scaffold a new draft

```bash
uv run python .claude/skills/manuscript-draft/scripts/draft.py init \
  --title "Your Paper Title" \
  --venue neurips \
  [--project-id <pid>] \
  [--force]
```

Prints `manuscript_id` to stdout. Creates under
`~/.cache/coscientist/manuscripts/<manuscript_id>/`:

| File | Contents |
|---|---|
| `manifest.json` | kind=manuscript, state=`drafted`, title, venue |
| `outline.json` | Venue template with per-section status/word_count/cite_keys |
| `source.md` | YAML frontmatter + placeholder sections for every venue section |

`manuscript_id` is deterministic: `<slug-of-title>_<6-char-blake2s(title::venue)>`.

### section — fill or update one section

```bash
uv run python .claude/skills/manuscript-draft/scripts/draft.py section \
  --manuscript-id <mid> \
  --section introduction \
  --text "Recent advances in... [@vaswani2017attention]..."
```

Or pipe content via stdin:

```bash
cat intro.md | python draft.py section --manuscript-id <mid> --section introduction
```

- Replaces the placeholder body (everything between the `## Heading` and the next `## `) with the new content.
- Counts words, extracts cite keys from the new body, updates `outline.json`.
- Default `--status drafted`; pass `--status revised` when making a second pass.

### status — print progress table

```bash
uv run python .claude/skills/manuscript-draft/scripts/draft.py status \
  --manuscript-id <mid>
```

Prints a table of section name / status / word_count / target_words / cite_keys.

### venues — list available templates

```bash
uv run python .claude/skills/manuscript-draft/scripts/draft.py venues
```

## Venue templates

| Template | Venue | Sections | Word limit |
|---|---|---|---|
| `imrad` | IMRaD (generic empirical) | 7 | 6 000 |
| `neurips` | NeurIPS | 11 | 8 000 |
| `acl` | ACL / EMNLP / NAACL | 11 | 8 000 |
| `nature` | Nature / Nature Methods | 8 | 3 000 |
| `thesis` | PhD / MPhil thesis | 10 | 80 000 |

Each template JSON lives in `.claude/skills/manuscript-draft/templates/<venue>.json`
and contains per-section `notes` with venue-specific guidance.

## Output layout

```
manuscripts/<manuscript_id>/
  manifest.json       # kind=manuscript, state=drafted
  outline.json        # section list with status/word_count/cite_keys
  source.md           # full draft (YAML frontmatter + sections)
```

After all required sections reach status `drafted`, run:

```bash
python .claude/skills/manuscript-ingest/scripts/ingest.py \
  --source ~/.cache/coscientist/manuscripts/<mid>/source.md \
  --title "Your Paper Title" [--project-id pid]
```

to register it for `manuscript-audit` / `manuscript-critique` / `manuscript-reflect`.

## Guarantees

- No LLM calls, no network — pure filesystem.
- Idempotent `init`: same title + venue → same `manuscript_id`; add `--force` to reinitialise.
- `section` never touches any section other than the named one.
- Cite keys extracted by `section` match the four styles understood by `manuscript-ingest` (LaTeX, pandoc, numeric, author-year).
- `source.md` produced by `init` is valid pandoc markdown; the YAML frontmatter is readable by `manuscript-ingest`.

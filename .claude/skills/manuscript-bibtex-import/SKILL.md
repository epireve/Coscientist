---
name: manuscript-bibtex-import
description: Import a `.bib` file into Coscientist's paper cache as paper artifacts. For each entry: parse fields, derive canonical_id, write manifest+metadata stubs, register in project's `artifact_index`, mark reading_state=`to-read`. Reverse of `reference-agent export-bibtex`. Pure stdlib bibtex parser — no external deps.
when_to_use: User says "import bib file", "ingest bibliography", "load my Zotero export", "start project from existing references", or onboarding to a new project with prior `.bib`. After import, user can run `paper-acquire` on entries with DOI/arXiv to populate full text.
---

# manuscript-bibtex-import

Reverse of reference-agent's BibTeX export. Take a `.bib` file → paper artifacts on disk → registered in a project.

## Subcommands

```bash
# Import every entry from refs.bib into project <pid>
uv run python .claude/skills/manuscript-bibtex-import/scripts/import_bib.py \
  --bib refs.bib --project-id <pid> [--reading-state to-read]

# Dry run — parse + report what would be created, write nothing
uv run python .claude/skills/manuscript-bibtex-import/scripts/import_bib.py \
  --bib refs.bib --project-id <pid> --dry-run

# Show parsed entries without touching disk
uv run python .claude/skills/manuscript-bibtex-import/scripts/import_bib.py \
  --bib refs.bib --parse-only
```

## What it does

1. **Parse** `.bib` — entry-by-entry. Recognises `@article`, `@inproceedings`, `@book`, `@misc`, etc. Field unescaping handles `\&`, `{Title}`, brace-quoted strings.
2. **Derive canonical_id** via `lib.paper_artifact.canonical_id(title, year, first_author, doi)` — same fn paper-discovery uses, so a paper imported here matches one already discovered.
3. **Write stubs**:
   - `manifest.json` — doi, arxiv_id (extracted if URL present), title slug
   - `metadata.json` — authors, year, venue, abstract (if `abstract` field), keywords (from `keywords`)
   - `state` = `discovered` (use `paper-acquire` to fetch PDF if needed)
4. **Register in project** — `artifact_index` row with `kind=paper`, `reading_state=to-read` (override via `--reading-state`).
5. **Output** JSON summary: count imported, count duplicates, count errors.

## What it does NOT do

- No PDF fetch. `paper-acquire` does that, gated by triage.
- No DOI resolution. If the `.bib` entry has no DOI, the canonical_id falls back to title-slug + author + year.
- No retraction check. Run `retraction-watch` after import.
- No concept extraction. `reference-agent populate_concepts.py` does that.

## Principles

From `RESEARCHER.md`: cite what you've read. This skill imports references — it doesn't claim you've read them. Reading state defaults to `to-read` for that reason.

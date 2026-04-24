---
name: manuscript-ingest
description: Ingest a markdown manuscript into the Coscientist cache as a `manuscript` artifact. First step before any manuscript-audit, manuscript-critique, or manuscript-reflect run.
when_to_use: You have a draft `.md` file and want to analyze it. Creates the artifact directory, copies the source, registers it in the project's artifact_index if a project_id is given.
---

# manuscript-ingest

Markdown-first by design. LaTeX and .docx will come later through `pandoc` conversion, but markdown is the canonical format for the current pipeline.

## Inputs

- `--source <path>` — path to the manuscript `.md` file
- `--title "..."` — human title (used for the manuscript_id derivation)
- `--project-id <pid>` — optional; registers the manuscript in the project's artifact_index

## How to run

```bash
uv run python .claude/skills/manuscript-ingest/scripts/ingest.py \
  --source ~/drafts/my-paper.md \
  --title "ViT for protein structure" \
  [--project-id <pid>]
```

Prints the `manuscript_id` to stdout.

## Outputs

Under `~/.cache/coscientist/manuscripts/<manuscript_id>/`:

- `source.md` — copied from `--source`
- `manifest.json` — kind=manuscript, state=`drafted`
- (no versioning yet — that's A1's `manuscript-version` skill, future iteration)

If `--project-id` is set, also inserts a row into that project's `artifact_index` with `kind='manuscript'` and `state='drafted'`.

## manuscript_id format

Deterministic: `<slug-of-title>_<6-char-blake2s>` where the hash is over the source file's content. Re-ingesting the same file with the same title gets the same ID. Changing either produces a new ID.

## Guarantees

- Original source at `--source` is never modified
- No network access; pure filesystem operation
- Fails loudly if the source isn't a readable text file (catches common mistakes like pointing at a .pdf)

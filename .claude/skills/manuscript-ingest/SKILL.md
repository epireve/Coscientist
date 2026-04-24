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

## What else happens with `--project-id` (v0.8 + v0.9)

- Inline citations are parsed (LaTeX, pandoc, numeric, author-year) and recorded in `manuscript_citations` with source-location metadata
- The bibliography section (`## References` / `## Bibliography` / `## Works Cited`) is parsed into `manuscript_references` with extracted DOIs, years, and inferred entry keys
- Graph: a `manuscript:<mid>` node is created with `cites` edges to placeholder `paper:unresolved:<key>` nodes

## Related scripts

- `scripts/resolve_citations.py` — map raw citation keys → canonical_ids; migrates graph edges from placeholder → resolved paper nodes
- `scripts/validate_citations.py` (v0.9) — cross-checks in-text citations vs bibliography. Reports `dangling-citation`, `orphan-reference`, `unresolved-citation`, `broken-reference`. Writes `validation_report.json` + populates `manuscript_audit_findings` so the author sees issues alongside other audit findings. Add `--fail-on-major` for CI gating.

## Guarantees

- Original source at `--source` is never modified
- No network access; pure filesystem operation
- Fails loudly if the source isn't a readable text file (catches common mistakes like pointing at a .pdf)

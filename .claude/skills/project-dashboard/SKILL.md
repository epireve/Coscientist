---
name: project-dashboard
description: Read-only single-screen view across all projects (or one). Shows active projects, recent activity, papers by reading state, manuscripts in flight, open audit issues, runs in progress.
when_to_use: Quick "where am I" check across your research life. Daily / weekly skim.
---

# project-dashboard

Pure aggregation over existing tables. No new data. Read-only — never mutates project DBs.

## How to run

```bash
# Across all projects
uv run python .claude/skills/project-dashboard/scripts/dashboard.py

# Single project
uv run python .claude/skills/project-dashboard/scripts/dashboard.py --project-id <pid>

# Markdown output instead of JSON
uv run python .claude/skills/project-dashboard/scripts/dashboard.py --format md
```

## What's reported

Per project:

- **Identity**: project_id, name, question, created_at
- **Activity (last 7 days)**: journal entries, audit findings, citations recorded
- **Reading state**: counts of papers by `to-read | reading | read | annotated | cited | skipped`
- **Manuscripts**: by state (`drafted | audited | critiqued | revised | submitted | published`)
- **Open audit issues**: counts by `kind` (overclaim, dangling-citation, broken-reference, ambiguous-citation, etc.) — surfaces what needs fixing before submission
- **Recent journal entries**: last 5
- **Graph stats**: paper nodes, concept nodes, edge count

## Outputs

JSON to stdout by default; markdown with `--format md` for embedding into a daily review document.

## Principles

From `RESEARCHER.md`: read-only, never editorializes. Dashboard reports counts, not "good"/"bad" judgments.

## What this does NOT do

- Doesn't write anything
- Doesn't fetch from MCPs
- Doesn't synthesize across projects (use `cross-project-memory` for that)

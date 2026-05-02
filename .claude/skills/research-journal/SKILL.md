---
name: research-journal
description: Daily lab-notebook for ideas, observations, decisions, and links to runs/papers/manuscripts. Per-project, time-stamped, searchable. The "where did I write that down?" tool.
when_to_use: Capture an idea or observation. Look back at what you noted on a date. Search across past entries by keyword or tag.
---

# research-journal

Markdown body + structured links + tags. One DB row per entry; the entry's body also lives on disk under `~/.cache/coscientist/projects/<pid>/journal/<entry_id>.md` so you can grep with normal tools.

## Three scripts

| Script | Job |
|---|---|
| `add_entry.py` | Append a journal entry (body via stdin or `--text`, tags + links optional) |
| `list_entries.py` | List entries by date range, tag, or linked artifact |
| `search.py` | Plain substring search across entry bodies |

## add-entry

```bash
# From stdin
echo "Discovered transformer scaling law in Vaswani 2017" | \
  uv run python .claude/skills/research-journal/scripts/add_entry.py \
    --project-id <pid> \
    --tags transformers,scaling \
    --link-papers vaswani_2017_attention_abc

# Or inline
uv run python .claude/skills/research-journal/scripts/add_entry.py \
  --project-id <pid> \
  --text "Brief note here" \
  --link-manuscripts ms_abc \
  --link-runs run_xyz
```

Tags and links are stored as JSON. Links accept `--link-papers`, `--link-manuscripts`, `--link-runs`, `--link-experiments` (comma-separated). The entry's `entry_date` defaults to today (UTC); override with `--date YYYY-MM-DD`.

## list-entries

```bash
uv run python .claude/skills/research-journal/scripts/list_entries.py \
  --project-id <pid> \
  [--from 2026-04-01] [--to 2026-04-30] \
  [--tag transformers] \
  [--linked-paper <cid>] \
  [--linked-manuscript <mid>]
```

JSON to stdout: list of `{entry_id, entry_date, body, tags, links, at}` newest first.

## search

```bash
uv run python .claude/skills/research-journal/scripts/search.py \
  --project-id <pid> \
  --query "scaling law"
```

Substring search (case-insensitive) over `body`. Returns matching entries with location.

## Outputs

- DB: rows in `journal_entries` (in project DB)
- Disk: one markdown file per entry at `~/.cache/coscientist/projects/<pid>/journal/<entry_id>.md` for grepping with non-Coscientist tools

## Principles

From `RESEARCHER.md`: **2 (Cite What You've Read — links to papers must be real canonical_ids)**, **5 (Register Bias — record decisions and exclusions when made)**.

## CLI flag reference (drift coverage)

- `list_entries.py`: `--limit`, `--linked-run`
- `search.py`: `--limit`

---
name: retraction-watch
description: Use when you want to check whether any papers you have cited across projects have been retracted. Run periodically or before manuscript submission. Writes structured alerts and journal entries for any newly-retracted papers found.
---

# retraction-watch

Scans every project DB for papers in `retraction_flags` or cited in `manuscript_citations`, checks retraction status via Semantic Scholar MCP, and writes alerts when newly-retracted papers are found.

## Scripts

| Script | CLI | Purpose |
|---|---|---|
| `scan.py` | `--project-id P [--canonical-id C] [--dry-run]` | Check retraction status for all cited papers in a project; updates `retraction_flags` |
| `alert.py` | `--project-id P [--output PATH]` | Write `retraction_alerts.json` + research-journal entry for papers with `retracted=1` |
| `status.py` | `--project-id P [--format json\|table]` | Show current retraction flag status across all papers in the project |

## Workflow

```
scan.py --project-id <pid>
  └── queries retraction_flags for known status
  └── for each paper with no recent check (>7d), prompts MCP lookup
  └── updates retraction_flags with result + checked_at

alert.py --project-id <pid>
  └── reads retraction_flags WHERE retracted=1
  └── writes retraction_alerts.json to project dir
  └── appends research-journal entry with paper list
```

## Guardrails

- `scan.py` never deletes existing flags — only adds/updates
- Re-checking window: 7 days (configurable via `--max-age-days`)
- MCP lookup is disabled in `--dry-run` mode; uses only cached flags
- Alert entries are idempotent — same retracted set → same alert file

## Schema used

`retraction_flags` (per-project DB, created by `reference-agent` in v0.5):
```sql
canonical_id TEXT UNIQUE, retracted INTEGER, source TEXT, detail TEXT, checked_at TEXT
```

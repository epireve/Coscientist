---
name: citation-alerts
description: Track who is citing your published papers. Two-phase like retraction-watch — `list` shows papers needing a citation refresh, caller queries Semantic Scholar for new citers, `persist` records the new citers. Stores under projects/<pid>/citation_alerts/.
when_to_use: User says "who's citing my paper", "citation alerts", "track citations of X", "new citations". Periodic check before reviews/grants.
---

# citation-alerts

Per-project alerts when new papers cite your tracked papers. Mirrors `retraction-watch` two-phase pattern — script can't make MCP calls itself, so:

1. `list` — emit canonical_ids of tracked papers needing a citation refresh (stale > N days).
2. **Caller** invokes `mcp__semantic-scholar__get_paper_citations` for each.
3. `persist --input <results.json>` — records new citers, computes deltas vs. prior snapshot.

## Scripts

| Script | CLI | Purpose |
|---|---|---|
| `track.py` | subcommands: `add`, `remove`, `list-tracked`, `list`, `persist`, `digest`, `status` | Main entry |

## Subcommands

```
track.py add --project-id P --canonical-id CID [--label "My JMLR 2023 paper"]
track.py remove --project-id P --canonical-id CID
track.py list-tracked --project-id P
track.py list --project-id P [--max-age-days 7]
track.py persist --project-id P --input results.json
track.py digest --project-id P [--since-days 30]
track.py status --project-id P
```

## Storage

```
projects/<pid>/
  citation_alerts/
    tracked.json          # [{canonical_id, label, added_at}, ...]
    snapshots/<cid>.json  # [{citer_canonical_id, citer_title, citer_year, first_seen}, ...]
    digest_<date>.json    # new citers since last digest
```

## Input format for `persist`

```json
[
  {
    "canonical_id": "smith_2023_method_abc",
    "citers": [
      {"canonical_id": "wang_2024_extension_def", "title": "Extending the Smith Method",
       "year": 2024, "venue": "NeurIPS"},
      ...
    ]
  },
  ...
]
```

## What this skill does NOT do

- Doesn't fetch citers itself — caller must invoke S2 MCP.
- Doesn't deduplicate against retraction flags (use retraction-watch separately).
- No notification email/webhook — output is files; user reads them.

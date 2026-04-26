---
name: preprint-alerts
description: Use when you want a daily filtered digest of new arXiv/bioRxiv preprints matching your topics or followed authors. Stores subscriptions and digest history under projects/<pid>/preprint_alerts/.
---

# preprint-alerts

Filtered preprint digest. Subscriptions stored per-project; digests written to disk and the research journal.

## Scripts

| Script | CLI | Purpose |
|---|---|---|
| `subscribe.py` | `--project-id P --topics "t1,t2" --authors "a1,a2" --sources "arxiv,biorxiv"` | Add/update subscription for a project |
| `digest.py` | `--project-id P --input papers.json [--date YYYY-MM-DD]` | Filter a paper list against subscriptions; write digest |
| `list_subs.py` | `--project-id P [--format json\|table]` | Show current subscriptions |
| `history.py` | `--project-id P [--limit N]` | List past digests |

## Subscription format (subscription.json)

```json
{
  "project_id": "...",
  "topics": ["transformer", "distribution shift"],
  "authors": ["Hinton", "LeCun"],
  "sources": ["arxiv", "biorxiv"],
  "updated_at": "..."
}
```

## Digest format (digest_YYYY-MM-DD.json)

```json
{
  "project_id": "...",
  "date": "YYYY-MM-DD",
  "n_candidates": 100,
  "n_matched": 5,
  "matches": [
    {"title": "...", "authors": [...], "abstract": "...", "source": "arxiv",
     "arxiv_id": "...", "matched_topics": [...], "matched_authors": [...]}
  ]
}
```

## Matching logic

A paper matches if ANY topic appears (case-insensitive) in title OR abstract,
OR ANY followed author appears in the author list.

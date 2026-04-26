---
name: credit-tracker
description: Track CRediT (Contributor Roles Taxonomy) per author per manuscript. Records who did Conceptualization, Methodology, Software, etc. Generates submission-ready CRediT statements and audits coverage (every required role assigned to ≥1 author). Per-manuscript persistence under manuscripts/<mid>/credit/.
when_to_use: When user says "track contributions", "add CRediT statement", "who did what", "audit author roles". Used before submission to journals that require CRediT.
---

# credit-tracker

CRediT (Contributor Roles Taxonomy, Brand et al. 2015 / casrai.org) per-manuscript bookkeeping.

## The 14 CRediT roles

1. `conceptualization`
2. `data-curation`
3. `formal-analysis`
4. `funding-acquisition`
5. `investigation`
6. `methodology`
7. `project-administration`
8. `resources`
9. `software`
10. `supervision`
11. `validation`
12. `visualization`
13. `writing-original-draft`
14. `writing-review-editing`

## Scripts

| Script | CLI | Purpose |
|---|---|---|
| `track.py` | subcommands: `assign`, `unassign`, `list`, `audit`, `statement`, `roles` | Main entry |

## Subcommands

```
track.py assign --manuscript-id MID --author "Name" --roles role1,role2,role3
track.py unassign --manuscript-id MID --author "Name" [--roles role1]
track.py list --manuscript-id MID
track.py audit --manuscript-id MID
track.py statement --manuscript-id MID [--style narrative|table]
track.py roles
```

## Storage

```
manuscripts/<manuscript_id>/credit/
  contributions.json    # {author: [role, role, ...]}
```

## Audit rules

- **Required roles**: `conceptualization`, `methodology`, `writing-original-draft` — at least one author per role.
- **Recommended roles**: `formal-analysis`, `investigation`, `writing-review-editing` — flagged if absent but not blocking.
- Each author must have ≥1 role assigned.

## CRediT statement output

`narrative` style produces a paragraph:
> "**Alice Smith**: Conceptualization, Methodology, Writing — original draft.
> **Bob Johnson**: Investigation, Formal analysis, Visualization."

`table` style produces a markdown table with one row per author and a column per role.

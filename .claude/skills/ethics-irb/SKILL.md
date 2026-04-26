---
name: ethics-irb
description: IRB application drafting + conflict-of-interest tracker. Templates for common IRB types (exempt/expedited/full-board) plus a per-project COI registry. Stores under irb/<application_id>/ and per-project coi.json.
when_to_use: User says "draft IRB", "IRB application", "ethics review", "track conflict of interest", "COI". Required for human/animal subjects research.
---

# ethics-irb

Two-track skill:
1. **IRB application scaffold** under `irb/<application_id>/`
2. **COI registry** under `projects/<pid>/coi.json` — list of {entity, type, value, declared_at}

## Scripts

```
ethics.py irb-init --title "T" --review-level exempt|expedited|full-board [--has-vulnerable-pop]
ethics.py irb-section --application-id A --section S --content "text"
ethics.py irb-status --application-id A
ethics.py coi-add --project-id P --entity "Acme Pharma" --type funding|consulting|stock|family|advisory --value "5000 USD"
ethics.py coi-list --project-id P
ethics.py coi-remove --project-id P --entry-id N
```

## IRB review levels

| Level | Sections |
|---|---|
| `exempt` | study description, exemption category, data security |
| `expedited` | + risk assessment, consent, recruitment, monitoring |
| `full-board` | + DSMB, vulnerable populations, equity, oversight |

## COI types

`funding | consulting | stock | family | advisory | other`

Each entry: `{id, entity, type, value, declared_at}`. Stored under `projects/<pid>/coi.json` as a list.

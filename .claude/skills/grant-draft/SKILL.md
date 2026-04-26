---
name: grant-draft
description: Use when drafting a grant application scaffold. Generates funder-specific section templates (NIH, NSF, ERC, Wellcome) with significance and impact framing distinct from academic papers. Stores under grants/<grant_id>/.
---

# grant-draft

Funder-specific grant scaffold. Each grant gets a directory under `grants/<grant_id>/` with a structured outline and source document.

## Scripts

| Script | CLI | Purpose |
|---|---|---|
| `draft.py` | subcommands: `init`, `section`, `status`, `funders` | Main entry point |
| `outline.py` | (module) | Outline data model + template loading |

## Subcommands

```
draft.py init --title "T" --funder nih|nsf|erc|wellcome [--mechanism R01|R21|...]
draft.py section --grant-id G --section S --content "text"
draft.py status --grant-id G
draft.py funders
```

## Funder templates

| Funder | Mechanism | Key sections |
|---|---|---|
| NIH | R01, R21 | Specific Aims, Significance, Innovation, Approach, Human Subjects |
| NSF | Standard | Project Summary, Project Description, Broader Impacts, References |
| ERC | Starting, Consolidator, Advanced | Extended Synopsis, State of the Art, Methodology, Resources |
| Wellcome | Discovery | Scientific Abstract, Background, Research Plan, Team, Impact |

## Storage

```
grants/<grant_id>/
  manifest.json    # grant_id, title, funder, mechanism, state, created_at
  outline.json     # sections with status, word_count, target_words
  source.md        # full draft text
```

`grant_id` = `slug(title)_slug(funder)_<6-char blake2s hash>`

---
name: dmp-generator
description: Generate funder-specific Data Management Plans (NIH DMSP, NSF DMP, Wellcome DMP, ERC DMP). Mirrors grant-draft pattern — section templates with target word counts and notes per funder. Stores under dmps/<dmp_id>/.
when_to_use: User says "draft DMP", "data management plan", "NIH DMSP", "data sharing plan". Required by most funders since 2023.
---

# dmp-generator

Funder-specific DMP scaffold. Each plan stored under `dmps/<dmp_id>/`.

## Scripts

| Script | CLI | Purpose |
|---|---|---|
| `dmp.py` | `init`, `section`, `status`, `funders` | Main entry |

## Subcommands

```
dmp.py init --title "T" --funder nih|nsf|wellcome|erc [--mechanism R01|...]
dmp.py section --dmp-id D --section S --content "text"
dmp.py status --dmp-id D
dmp.py funders
```

## Funder templates

| Funder | Sections | Source |
|---|---|---|
| NIH (DMSP) | Data Type, Tools/Standards, Preservation, Access, Oversight | NIH 2023 DMS Policy |
| NSF (DMP) | Data Description, Standards, Access, Re-use, Archiving | NSF 2-page DMP |
| Wellcome | Data Output, Sharing Strategy, Resources, Ethics | Wellcome Output Mgmt 2023 |
| ERC | Findability, Accessibility, Interoperability, Reuse | Horizon Europe DMP / FAIR |

## Storage

```
dmps/<dmp_id>/
  manifest.json
  outline.json   # sections, status, word_count, target_words
  source.md      # YAML front-matter + section bodies
```

`dmp_id` = `slug(title)_slug(funder)_<6-char hash>`.

## CLI flag reference (drift coverage)

- `dmp.py`: `--force`

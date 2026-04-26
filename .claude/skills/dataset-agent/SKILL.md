---
name: dataset-agent
description: Track datasets used in research with DOIs, licenses, versions, and content hashes. Treats datasets as first-class artifacts. State machine — registered → deposited → versioned. Zenodo deposit handled by zenodo-deposit skill (Phase 2). This skill is local-only registration + integrity tracking.
when_to_use: When user says "register this dataset", "track this data", "compute hash of dataset", "list datasets in this project", or wants reproducibility metadata for a paper.
---

# dataset-agent

Local registry for research datasets. Pairs with `zenodo-deposit` (Phase 2) for actual DOI minting.

## Scripts

| Script | CLI | Purpose |
|---|---|---|
| `register.py` | subcommands: `register`, `version`, `hash`, `list`, `status` | Main entry |

## Subcommands

```
register.py register --title "T" --description "D" --license "MIT|CC-BY-4.0|..." [--source-url URL] [--doi DOI] [--paths /path/to/data ...] [--project-id P]
register.py version --dataset-id DID --label "v2-after-cleanup" [--notes "..."]
register.py hash --dataset-id DID [--algorithm sha256|blake2s]
register.py list [--project-id P] [--state STATE]
register.py status --dataset-id DID
```

## Storage

```
datasets/<dataset_id>/
  manifest.json         # artifact_id, kind=dataset, state, created_at, updated_at
  dataset.json          # title, description, license, source_url, doi, paths, hashes
  versions.json         # [{label, registered_at, hashes, notes}, ...]
```

`dataset_id` = `slug(title)_<6-char blake2s hash>`

## State machine

- `registered` — basic metadata captured
- `deposited` — DOI minted (set by zenodo-deposit skill)
- `versioned` — at least one version label recorded

## Hash computation

Uses Python stdlib `hashlib`. Skips files larger than 100 MB unless `--force-large` given (avoids accidentally hashing 50 GB datasets in foreground). Returns per-file hashes + a combined manifest hash.

## License field

Free-text but the skill flags non-OSI / non-Creative-Commons values for review. Common values:
- `MIT`, `Apache-2.0`, `BSD-3-Clause`
- `CC0-1.0`, `CC-BY-4.0`, `CC-BY-SA-4.0`, `CC-BY-NC-4.0`
- `proprietary`, `restricted`, `embargo`

## Linking

With `--project-id`, registers in `artifact_index` (kind=`dataset`).

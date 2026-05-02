---
name: negative-results-logger
description: Use when an experiment, hypothesis test, or attempted approach failed and you want a durable record. Negative results are first-class research artifacts. Logs failed-attempt artifacts under negative_results/<id>/ with structured fields (what was tried, what was expected, what happened, why we think it failed, lessons).
when_to_use: When user says "log this failure", "this didn't work, save it", "add a negative result", "experiment X failed". Not for general bug reports — only for research-level negative findings.
---

# negative-results-logger

Captures failed experiments, dead-end approaches, and disconfirmed hypotheses as durable artifacts. State machine: `logged → analyzed → shared`.

## Why

Negative results rarely get published, so they're lost — and the next researcher repeats the same dead end. This skill makes them findable in your own knowledge base.

## Scripts

| Script | CLI | Purpose |
|---|---|---|
| `log.py` | subcommands: `init`, `analyze`, `share`, `status`, `list` | Main entry point |

## Subcommands

```
log.py init --title "T" --hypothesis "H" --approach "A" --expected "E" --observed "O" [--project-id P]
log.py analyze --result-id RID --root-cause "..." --lessons "..."
log.py share --result-id RID --shared-via "preprint|blog|talk|github|other" --url "..."
log.py status --result-id RID
log.py list [--project-id P] [--state STATE]
```

## Fields

`init` requires:
- `title` — short label
- `hypothesis` — what you predicted
- `approach` — method you tried
- `expected` — outcome you hoped for
- `observed` — what actually happened

`analyze` adds:
- `root_cause` — best guess at why it failed
- `lessons` — what to do/avoid next time

`share` records dissemination:
- `shared_via` ∈ {preprint, blog, talk, github, other}
- `url` — link if applicable

## Storage

```
negative_results/<result_id>/
  manifest.json    # artifact_id, state, created_at, updated_at
  result.json      # full structured record
```

`result_id` = `slug(title)_<6-char blake2s hash>`

## Linking

With `--project-id`, registers in `artifact_index` (kind=`negative-result`) so cross-project-memory search finds it.

## CLI flag reference (drift coverage)

- `log.py`: `--force`

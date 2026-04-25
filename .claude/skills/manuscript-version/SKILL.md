---
name: manuscript-version
description: Lightweight version history for manuscript drafts. Snapshots source.md at key moments, lists the version log, diffs two snapshots by word count and section, and restores a prior snapshot. No git required — snapshots are stored under manuscripts/<mid>/versions/.
when_to_use: You have a manuscript artifact and want to checkpoint the current source.md before a major rewrite, compare two drafts to see how much changed per section, browse the version history, or undo an edit by restoring an earlier snapshot.
---

# manuscript-version

Version history for manuscript drafts without requiring git. Each snapshot is
a copy of `source.md` paired with a small `meta.json` file. All snapshots live
under the artifact directory so they travel with the manuscript.

## Snapshot layout

```
manuscripts/<mid>/
  source.md                          # working draft (read/write)
  versions/
    v1-20260425-143000/
      source.md                      # frozen copy
      meta.json                      # snapshot metadata
    v2-20260425-160000/
      source.md
      meta.json
```

### version_id format

`v<N>-<YYYYMMDD-HHMMSS>`

The integer prefix `N` is auto-incremented (1-based). The timestamp is local
wall-clock time in `YYYYMMDD-HHMMSS` format for human readability. Together
they sort correctly as plain strings.

### meta.json fields

| Field | Type | Description |
|---|---|---|
| `version_id` | str | `v<N>-<YYYYMMDD-HHMMSS>` |
| `manuscript_id` | str | the owning manuscript's id |
| `created_at` | str | ISO-8601 timestamp |
| `note` | str | optional human note (default: "") |
| `word_count` | int | total words in the snapshot |
| `source_md_hash` | str | sha256 hex digest of source.md content |
| `state_at_snapshot` | str | manifest state when snapshot was taken |

## Subcommands

### snapshot — capture current source.md

```bash
uv run python .claude/skills/manuscript-version/scripts/version.py snapshot \
  --manuscript-id <mid> \
  [--note "before major rewrite"] \
  [--force]
```

Prints `version_id` to stdout. Refuses if source.md hasn't changed since the
last snapshot (same sha256) unless `--force` is passed.

### log — list all snapshots

```bash
uv run python .claude/skills/manuscript-version/scripts/version.py log \
  --manuscript-id <mid>
```

Prints snapshots in reverse-chronological order: version_id, date, word_count,
note.

### diff — compare two snapshots

```bash
uv run python .claude/skills/manuscript-version/scripts/version.py diff \
  --manuscript-id <mid> \
  --from v1-20260425-143000 \
  --to   v2-20260425-160000
```

Accepts `HEAD` as an alias for the current `source.md`. Shows per-section word
count delta and the total delta. Pure text — no LLM.

### restore — roll back to a prior snapshot

```bash
uv run python .claude/skills/manuscript-version/scripts/version.py restore \
  --manuscript-id <mid> \
  --version v1-20260425-143000 \
  --confirm
```

Overwrites `source.md` with the snapshot content. **Automatically snapshots
the current state** before restoring so the operation is reversible. Requires
explicit `--confirm` flag to prevent accidental overwrites.

## Guarantees

- No LLM calls, no network — pure filesystem.
- `snapshot` is idempotent: same content → same hash → refused (unless `--force`).
- `restore` always leaves a recovery snapshot; the pre-restore state is never
  silently discarded.
- All metadata lives in `meta.json` files — no new SQLite tables, no schema
  migrations.

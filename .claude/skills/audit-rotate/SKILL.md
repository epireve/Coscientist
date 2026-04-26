---
name: audit-rotate
description: Rotate Coscientist's two append-only audit logs by size or age. Renames the current log to `<name>.<UTC-timestamp>` and starts a fresh empty file in its place. Refuses to delete archives — that's a deliberate human decision. Pure stdlib, atomic rename, never loses data. Distinct from `audit-query` which is read-only.
when_to_use: Logs have grown large enough to slow down `audit-query` (or you just want a clean baseline before a forensic exercise). Use after `audit-query summary` so you know what you're freezing. Run periodically, or once before a destructive Docker batch.
---

# audit-rotate

Two logs, one rotator. Both files are JSONL/text and append-only — the
producers never reopen old archives. So a simple rename is safe: the
new write opens a fresh file at the original path; archives are
immutable from that moment on.

## Files this rotates

| File | Producer |
|---|---|
| `~/.cache/coscientist/audit.log` | `paper-acquire`, `institutional-access` |
| `~/.cache/coscientist/sandbox_audit.log` | `reproducibility-mcp/sandbox.py` |

## Subcommands

```bash
# Inspect — show size, line count, oldest + newest entries per log
uv run python .claude/skills/audit-rotate/scripts/rotate.py inspect

# Rotate by size threshold (default: 10 MiB)
uv run python .claude/skills/audit-rotate/scripts/rotate.py rotate \
  --max-bytes 10485760 \
  [--target fetches|sandbox|both]

# Rotate unconditionally (force)
uv run python .claude/skills/audit-rotate/scripts/rotate.py rotate \
  --force [--target ...]

# List archives — see what's been frozen
uv run python .claude/skills/audit-rotate/scripts/rotate.py list-archives
```

Archive naming: `audit.log.20260427T093015Z` (UTC, second precision).
Atomic via `Path.rename` on the same filesystem.

## What it does NOT do

- Doesn't delete archives. Cleanup is a separate manual decision.
- Doesn't compress. Archives stay as raw text/JSONL so `grep` + `audit-query`
  could be retrofitted to read them.
- Doesn't write to either DB or any artifact.

## Principles

From `RESEARCHER.md`: never silently lose data; rename, don't delete.

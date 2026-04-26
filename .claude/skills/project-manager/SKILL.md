---
name: project-manager
description: CLI for project lifecycle — init, list, activate, archive, status, current. Wraps lib.project. Maintains a single global "active project" marker (~/.cache/coscientist/active_project.json) so other skills can default to it when --project-id is omitted. Distinct from project-dashboard (read-only view).
when_to_use: User says "create project", "activate project", "archive project", "current project", "list projects", "what project am I on". First step before any project-bound work.
---

# project-manager

Project-lifecycle CLI. Wraps `lib.project` primitives + adds active-project marker.

## Scripts

| Script | Subcommand | Purpose |
|---|---|---|
| `manage.py` | `init` | Create new project |
| | `list` | List all projects |
| | `activate` | Set as global active project |
| | `current` | Show currently active project |
| | `deactivate` | Clear active marker |
| | `archive` | Mark project as archived (soft-delete) |
| | `unarchive` | Restore archived project |
| | `status` | Show project metadata + counts |

## Subcommands

```
manage.py init --name "T" [--question "Q"] [--description "D"]
manage.py list [--include-archived]
manage.py activate --project-id P
manage.py current
manage.py deactivate
manage.py archive --project-id P
manage.py unarchive --project-id P
manage.py status --project-id P
```

## Active project marker

```
~/.cache/coscientist/active_project.json
{
  "project_id": "my_thesis_abc123",
  "activated_at": "2026-04-27T10:00:00+00:00"
}
```

Other skills can read this when `--project-id` is omitted. Single global marker (not per-shell). Cleared by `deactivate`.

## Archive semantics

Soft-delete: writes `archived_at` to project record. `list` excludes archived by default. `unarchive` clears `archived_at`. Project DB and artifacts are *not* deleted.

## Why this exists

`lib.project` already had create/get/list. This skill exposes them as CLI + adds the active-project pattern for ergonomic cross-skill use.

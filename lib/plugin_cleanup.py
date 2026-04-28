"""v0.85 — manual cleanup helper for Coscientist plugin uninstall.

Claude Code plugin spec doesn't define a formal uninstall hook
(as of v2.0.x). When user removes a Coscientist plugin, the
plugin files are deleted but per-project DB rows seeded by the
plugin's MCP tools (e.g. citation_resolutions written by
retraction-mcp) stay. This helper offers an opt-in cleanup.

Read-only by default. Mutations require `--confirm`.

Plugins covered:
  - coscientist-retraction-mcp:
      Drops `retraction_flags` rows where source='retraction-mcp'.
  - coscientist-manuscript-mcp:
      No persistent DB state; nothing to clean.
  - coscientist-graph-query-mcp:
      Read-only MCP; nothing to clean.
  - coscientist-deep-research:
      Skill bundle; per-run DBs are user data, never auto-deleted.

CLI:
    uv run python -m lib.plugin_cleanup --plugin retraction-mcp [--confirm]
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from lib.cache import cache_root


def _project_dbs() -> list[Path]:
    root = cache_root() / "projects"
    if not root.exists():
        return []
    return [p / "project.db" for p in root.iterdir()
            if (p / "project.db").exists()]


def _retraction_cleanup(*, confirm: bool) -> dict:
    candidates: list[dict] = []
    deleted = 0
    for db in _project_dbs():
        try:
            con = sqlite3.connect(db)
        except sqlite3.Error:
            continue
        try:
            try:
                rows = con.execute(
                    "SELECT canonical_id FROM retraction_flags "
                    "WHERE source='retraction-mcp'"
                ).fetchall()
            except sqlite3.OperationalError:
                continue
            n = len(rows)
            if n == 0:
                continue
            candidates.append({"db": str(db), "rows": n})
            if confirm:
                with con:
                    con.execute(
                        "DELETE FROM retraction_flags "
                        "WHERE source='retraction-mcp'"
                    )
                deleted += n
        finally:
            con.close()
    return {
        "plugin": "coscientist-retraction-mcp",
        "n_dbs_with_rows": len(candidates),
        "n_rows_total": sum(c["rows"] for c in candidates),
        "n_deleted": deleted,
        "candidates": candidates,
        "confirmed": confirm,
    }


def _no_op(plugin: str) -> dict:
    return {
        "plugin": plugin,
        "n_dbs_with_rows": 0,
        "n_rows_total": 0,
        "n_deleted": 0,
        "candidates": [],
        "confirmed": False,
        "note": "no persistent DB state to clean for this plugin",
    }


_HANDLERS = {
    "retraction-mcp": _retraction_cleanup,
    "manuscript-mcp": lambda *, confirm: _no_op(
        "coscientist-manuscript-mcp",
    ),
    "graph-query-mcp": lambda *, confirm: _no_op(
        "coscientist-graph-query-mcp",
    ),
    "deep-research": lambda *, confirm: _no_op(
        "coscientist-deep-research",
    ),
}


def cleanup(plugin: str, *, confirm: bool = False) -> dict:
    """Dispatch to the plugin-specific handler. Plugin name is the
    suffix without the `coscientist-` prefix."""
    handler = _HANDLERS.get(plugin)
    if handler is None:
        return {
            "plugin": plugin,
            "error": f"unknown plugin {plugin!r}; expected one of "
                     f"{sorted(_HANDLERS)}",
        }
    return handler(confirm=confirm)


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(
        prog="plugin_cleanup",
        description="Manual cleanup of plugin-seeded DB rows (v0.85).",
    )
    p.add_argument("--plugin", required=True,
                   choices=sorted(_HANDLERS),
                   help="Which plugin's residue to clean")
    p.add_argument("--confirm", action="store_true",
                   help="Actually delete. Without this, dry-run only.")
    args = p.parse_args(argv)
    payload = cleanup(args.plugin, confirm=args.confirm)
    print(json.dumps(payload, indent=2))
    return 0 if "error" not in payload else 1


if __name__ == "__main__":
    raise SystemExit(main())

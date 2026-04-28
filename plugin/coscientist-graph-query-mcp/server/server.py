#!/usr/bin/env python3
"""graph-query-mcp — read-only stdio MCP over per-project citation graph.

Wraps `lib.graph` (SQLite-adjacency, planned Kuzu migration).
Read-only: never mutates `graph_nodes` or `graph_edges`.

Tools:
  neighbors(project_id, node_id, relation=None, direction="out")
  walk(project_id, start_node, relation, max_hops=2)
  in_degree(project_id, node_id, relation=None)
  hubs(project_id, kind, relation="cites", top_k=10)
  shortest_path(project_id, start_node, end_node, max_hops=4)
  node_info(project_id, node_id)

Node IDs follow the existing convention: `paper:<canonical_id>`,
`concept:<slug>`, `author:<s2_id>`, `manuscript:<mid>`.
"""
from __future__ import annotations

import sqlite3
import sys
from collections import deque
from pathlib import Path
from typing import Any

# Locate `lib/graph.py` regardless of whether we're running from the
# source tree or from a plugin install. Two valid layouts:
#   1. Source tree:  <repo>/mcp/graph-query-mcp/server.py + <repo>/lib/
#   2. Plugin:       <plugin>/server/server.py + <plugin>/lib/  (vendored)
_HERE = Path(__file__).resolve()
_CANDIDATES = (
    _HERE.parents[1],   # plugin: server/ -> plugin root has lib/
    _HERE.parents[2],   # source: mcp/<name>/ -> repo root has lib/
    _HERE.parents[3],   # source nested in plugin install
)
for cand in _CANDIDATES:
    if (cand / "lib" / "graph.py").exists():
        if str(cand) not in sys.path:
            sys.path.insert(0, str(cand))
        break

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as e:
    raise SystemExit(
        "graph-query-mcp requires the `mcp` package. Run via:\n"
        "  uv run --with mcp python mcp/graph-query-mcp/server.py\n"
        f"(import error: {e})"
    )


# Lazy import so unit tests can stub `lib.graph` without a real DB.
def _gmod():
    from lib import graph  # noqa: WPS433
    return graph


def _project_con(project_id: str) -> sqlite3.Connection:
    """Open the project DB read-only, returning a Row-factory connection.

    Uses lib.cache.connect_wal so we share the WAL settings of writers.
    """
    from lib.cache import connect_wal
    from lib.project import project_db_path
    db = project_db_path(project_id)
    if not db.exists():
        raise FileNotFoundError(f"project DB not found: {db}")
    con = connect_wal(db)
    con.row_factory = sqlite3.Row
    return con


mcp = FastMCP("graph-query-mcp")


def _trace_emit(tool_name: str, args_summary: dict | None,
                result_summary: dict | None,
                error: str | None = None) -> None:
    """v0.93c — best-effort tool-call span emit. v0.112 — error
    forwarded for status='error' marking."""
    try:
        from lib.trace import maybe_emit_tool_call
        maybe_emit_tool_call(
            tool_name,
            args_summary=args_summary,
            result_summary=result_summary,
            error=error,
        )
    except Exception:
        pass


@mcp.tool()
def neighbors(
    project_id: str,
    node_id: str,
    relation: str | None = None,
    direction: str = "out",
) -> dict[str, Any]:
    """Return neighbor nodes of `node_id`.

    direction: "out" (default), "in", or "both".
    relation: optional filter (e.g. "cites", "about").
    """
    try:
        rows = _gmod().neighbors(
            project_id, node_id, relation=relation, direction=direction,
        )
    except Exception as e:
        return {"error": str(e), "node_id": node_id}
    return {
        "project_id": project_id,
        "node_id": node_id,
        "relation": relation,
        "direction": direction,
        "n_neighbors": len(rows),
        "neighbors": rows,
    }


@mcp.tool()
def walk(
    project_id: str,
    start_node: str,
    relation: str,
    max_hops: int = 2,
) -> dict[str, Any]:
    """BFS walk along a single relation up to `max_hops`.

    Returns every node reached (excluding the start node).
    """
    try:
        rows = _gmod().walk(project_id, start_node, relation, max_hops=max_hops)
    except Exception as e:
        return {"error": str(e), "start_node": start_node}
    return {
        "project_id": project_id,
        "start_node": start_node,
        "relation": relation,
        "max_hops": max_hops,
        "n_reached": len(rows),
        "reached": rows,
    }


@mcp.tool()
def in_degree(
    project_id: str, node_id: str, relation: str | None = None,
) -> dict[str, Any]:
    """Count incoming edges. Optionally filter by relation."""
    try:
        n = _gmod().in_degree(project_id, node_id, relation=relation)
    except Exception as e:
        return {"error": str(e), "node_id": node_id}
    return {
        "project_id": project_id,
        "node_id": node_id,
        "relation": relation,
        "in_degree": int(n),
    }


@mcp.tool()
def hubs(
    project_id: str,
    kind: str,
    relation: str = "cites",
    top_k: int = 10,
) -> dict[str, Any]:
    """Top-k nodes of `kind` by in-degree on `relation`."""
    try:
        rows = _gmod().hubs(project_id, kind, relation=relation, top_k=top_k)
    except Exception as e:
        return {"error": str(e), "kind": kind}
    return {
        "project_id": project_id,
        "kind": kind,
        "relation": relation,
        "top_k": top_k,
        "n_hubs": len(rows),
        "hubs": rows,
    }


@mcp.tool()
def node_info(project_id: str, node_id: str) -> dict[str, Any]:
    """Return the row for a single node, or {found: False} if missing."""
    try:
        con = _project_con(project_id)
    except Exception as e:
        return {"error": str(e), "node_id": node_id}
    try:
        row = con.execute(
            "SELECT * FROM graph_nodes WHERE node_id=?", (node_id,),
        ).fetchone()
    finally:
        con.close()
    if row is None:
        return {"project_id": project_id, "node_id": node_id, "found": False}
    return {
        "project_id": project_id,
        "node_id": node_id,
        "found": True,
        "node": dict(row),
    }


def _bfs_shortest_path(
    project_id: str,
    start: str,
    end: str,
    max_hops: int,
    relation: str | None,
) -> list[str] | None:
    """v0.79: now a thin wrapper around `lib.graph.shortest_path`."""
    return _gmod().shortest_path(
        project_id, start, end,
        max_hops=max_hops, relation=relation,
    )


@mcp.tool()
def shortest_path(
    project_id: str,
    start_node: str,
    end_node: str,
    max_hops: int = 4,
    relation: str | None = None,
) -> dict[str, Any]:
    """Shortest path from `start_node` to `end_node` along directed
    edges (optionally filtered by `relation`).

    Returns: {found: bool, path: [node_ids], length: int} on success,
    {found: false} when no path exists within `max_hops`.
    """
    try:
        path = _bfs_shortest_path(
            project_id, start_node, end_node, max_hops, relation,
        )
    except Exception as e:
        result = {"error": str(e), "start_node": start_node,
                  "end_node": end_node}
        _trace_emit("shortest_path",
                    {"start": start_node, "end": end_node,
                     "max_hops": max_hops},
                    result,
                    error=str(e)[:200])
        return result
    if path is None:
        result = {
            "project_id": project_id,
            "start_node": start_node,
            "end_node": end_node,
            "max_hops": max_hops,
            "relation": relation,
            "found": False,
        }
        _trace_emit("shortest_path",
                    {"start": start_node, "end": end_node,
                     "max_hops": max_hops},
                    {"found": False})
        return result
    result = {
        "project_id": project_id,
        "start_node": start_node,
        "end_node": end_node,
        "max_hops": max_hops,
        "relation": relation,
        "found": True,
        "length": len(path) - 1,
        "path": path,
    }
    _trace_emit("shortest_path",
                {"start": start_node, "end": end_node,
                 "max_hops": max_hops},
                {"found": True, "length": len(path) - 1})
    return result


def main() -> None:
    """Console-script entry. v0.80 — pyproject scripts hook."""
    mcp.run()


if __name__ == "__main__":
    main()

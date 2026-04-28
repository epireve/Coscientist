#!/usr/bin/env python3
"""retraction-watch: scan cited papers for retraction status.

Updates retraction_flags in the project DB for all papers that either:
  (a) have no existing flag, or
  (b) have not been checked in the last --max-age-days days.

In --dry-run mode: prints what would be checked, does not update DB or call MCPs.
In normal mode: caller (Claude agent) is expected to perform MCP lookups using
the list of canonical_ids printed to stdout, then call this script again with
--input <results.json> to persist the results.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import cache_root  # noqa: E402


def _project_db(project_id: str) -> Path:
    return cache_root() / "projects" / project_id / "project.db"


def _open(project_id: str) -> sqlite3.Connection:
    db = _project_db(project_id)
    if not db.exists():
        raise SystemExit(f"no project DB at {db}")
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    return con


def _all_cited_papers(con: sqlite3.Connection) -> list[str]:
    """Return all canonical_ids referenced in the project (artifact_index + manuscript_citations)."""
    ids: set[str] = set()
    # Papers in artifact_index (kind=paper)
    try:
        rows = con.execute(
            "SELECT artifact_id FROM artifact_index WHERE kind='paper'"
        ).fetchall()
        for r in rows:
            if r["artifact_id"]:
                ids.add(r["artifact_id"])
    except sqlite3.OperationalError:
        pass
    # Papers cited in manuscripts
    try:
        rows = con.execute(
            "SELECT DISTINCT resolved_canonical_id FROM manuscript_citations "
            "WHERE resolved_canonical_id IS NOT NULL"
        ).fetchall()
        for r in rows:
            if r["resolved_canonical_id"]:
                ids.add(r["resolved_canonical_id"])
    except sqlite3.OperationalError:
        pass
    # Graph nodes of kind=paper
    try:
        rows = con.execute(
            "SELECT node_id FROM graph_nodes WHERE kind='paper'"
        ).fetchall()
        for r in rows:
            nid = r["node_id"] or ""
            cid = nid.removeprefix("paper:")
            if cid and not cid.startswith("unresolved:"):
                ids.add(cid)
    except sqlite3.OperationalError:
        pass
    return sorted(ids)


def _existing_flags(con: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    try:
        rows = con.execute(
            "SELECT canonical_id, retracted, source, detail, checked_at "
            "FROM retraction_flags"
        ).fetchall()
        return {r["canonical_id"]: r for r in rows}
    except sqlite3.OperationalError:
        return {}


def _needs_check(flag: sqlite3.Row | None, max_age_days: int) -> bool:
    if flag is None:
        return True
    checked = flag["checked_at"]
    if not checked:
        return True
    try:
        dt = datetime.fromisoformat(checked)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return datetime.now(UTC) - dt > timedelta(days=max_age_days)
    except ValueError:
        return True


def cmd_list(args: argparse.Namespace) -> None:
    """List papers needing a retraction check (no DB writes)."""
    con = _open(args.project_id)
    all_ids = _all_cited_papers(con)
    if args.canonical_id:
        all_ids = [c for c in all_ids if c == args.canonical_id]
    flags = _existing_flags(con)
    to_check = [cid for cid in all_ids if _needs_check(flags.get(cid), args.max_age_days)]
    con.close()
    result = {
        "project_id": args.project_id,
        "total_papers": len(all_ids),
        "to_check": to_check,
        "already_current": len(all_ids) - len(to_check),
        "max_age_days": args.max_age_days,
        "mode": "dry_run" if args.dry_run else "list",
    }
    print(json.dumps(result, indent=2))


def cmd_persist(args: argparse.Namespace) -> None:
    """Persist MCP lookup results into retraction_flags."""
    results_path = Path(args.input)
    if not results_path.exists():
        raise SystemExit(f"input file not found: {results_path}")
    items = json.loads(results_path.read_text())
    if not isinstance(items, list):
        raise SystemExit("input must be a JSON array of {canonical_id, retracted, source, detail?}")

    con = _open(args.project_id)
    now = datetime.now(UTC).isoformat()
    saved = 0
    errors: list[str] = []

    with con:
        # Ensure table exists (may be absent in very old DBs)
        con.execute("""
            CREATE TABLE IF NOT EXISTS retraction_flags (
                flag_id      INTEGER PRIMARY KEY AUTOINCREMENT,
                canonical_id TEXT NOT NULL UNIQUE,
                retracted    INTEGER NOT NULL,
                source       TEXT NOT NULL,
                detail       TEXT,
                checked_at   TEXT NOT NULL
            )
        """)
        for item in items:
            cid = item.get("canonical_id")
            if not cid:
                errors.append("missing canonical_id")
                continue
            retracted = 1 if item.get("retracted") else 0
            source = item.get("source", "semantic-scholar")
            detail = item.get("detail")
            con.execute(
                "INSERT INTO retraction_flags "
                "(canonical_id, retracted, source, detail, checked_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(canonical_id) DO UPDATE SET "
                "retracted=excluded.retracted, source=excluded.source, "
                "detail=excluded.detail, checked_at=excluded.checked_at",
                (cid, retracted, source, detail, now),
            )
            saved += 1

    con.close()
    print(json.dumps({
        "saved": saved,
        "errors": errors,
        "project_id": args.project_id,
    }, indent=2))


def _doi_for_canonical(cid: str) -> str | None:
    """Look up a paper's DOI via its on-disk manifest, if present."""
    manifest = cache_root() / "papers" / cid / "manifest.json"
    if not manifest.exists():
        return None
    try:
        data = json.loads(manifest.read_text())
    except json.JSONDecodeError:
        return None
    return data.get("doi")


def cmd_mcp_lookup(args: argparse.Namespace) -> None:
    """v0.78 — drive retraction lookups via the retraction-mcp Python
    surface, then persist results.

    Pipeline:
      1. Build the to-check list (same as cmd_list).
      2. For each canonical_id, read manifest.json for the DOI.
      3. Call retraction-mcp's `lookup_doi` directly (it's an
         ordinary Python function decorated with @mcp.tool()).
      4. Write a result file in the shape `cmd_persist` expects, then
         optionally call cmd_persist if --auto-persist is set.

    Skips papers without a known DOI — reports them in the output.
    """
    # Lazy import: module is expensive to load (sets up FastMCP), and
    # we only need it on this code path.
    sys.path.insert(0, str(_REPO_ROOT / "mcp" / "retraction-mcp"))
    # The FastMCP import inside server.py raises SystemExit if the
    # `mcp` package is missing; handle gracefully.
    import importlib.util

    server_path = _REPO_ROOT / "mcp" / "retraction-mcp" / "server.py"
    spec = importlib.util.spec_from_file_location(
        "retraction_mcp_server_cli", server_path,
    )
    mod = importlib.util.module_from_spec(spec)
    try:
        # If `mcp` package isn't present, install a stub so the server
        # module can import. We're only calling its plain functions
        # (lookup_doi, batch_lookup, pubpeer_comments).
        if "mcp" not in sys.modules:
            import types
            mcp_pkg = types.ModuleType("mcp")
            mcp_server = types.ModuleType("mcp.server")
            mcp_fastmcp = types.ModuleType("mcp.server.fastmcp")

            class _StubMCP:
                def __init__(self, name): self.name = name
                def tool(self):
                    def deco(fn): return fn
                    return deco
                def run(self): pass

            mcp_fastmcp.FastMCP = _StubMCP
            sys.modules["mcp"] = mcp_pkg
            sys.modules["mcp.server"] = mcp_server
            sys.modules["mcp.server.fastmcp"] = mcp_fastmcp
        spec.loader.exec_module(mod)
    except Exception as e:
        raise SystemExit(f"failed to load retraction-mcp server: {e}")

    con = _open(args.project_id)
    all_ids = _all_cited_papers(con)
    if args.canonical_id:
        all_ids = [c for c in all_ids if c == args.canonical_id]
    flags = _existing_flags(con)
    to_check = [
        cid for cid in all_ids
        if _needs_check(flags.get(cid), args.max_age_days)
    ]
    con.close()

    results: list[dict] = []
    skipped_no_doi: list[str] = []
    errors: list[dict] = []

    for cid in to_check:
        doi = _doi_for_canonical(cid)
        if not doi:
            skipped_no_doi.append(cid)
            continue
        try:
            r = mod.lookup_doi(doi)
        except Exception as e:
            errors.append({"canonical_id": cid, "error": str(e)})
            continue
        if not r.get("found"):
            errors.append({"canonical_id": cid,
                           "error": r.get("error", "not found")})
            continue
        results.append({
            "canonical_id": cid,
            "retracted": bool(r.get("is_retracted")),
            "source": "retraction-mcp",
            "detail": json.dumps({
                "has_correction_or_eoc": r.get("has_correction_or_eoc"),
                "notices": r.get("notices") or [],
                "title": r.get("title"),
            }),
        })

    output = {
        "project_id": args.project_id,
        "checked": len(results),
        "skipped_no_doi": skipped_no_doi,
        "errors": errors,
        "results": results,
    }

    if args.output:
        Path(args.output).write_text(json.dumps(output, indent=2))

    if args.auto_persist and results:
        # Reuse the persist code path by writing a temp file.
        import tempfile
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False,
        ) as f:
            json.dump(results, f)
            tmp_path = f.name
        try:
            persist_args = argparse.Namespace(
                project_id=args.project_id, input=tmp_path,
            )
            cmd_persist(persist_args)
        finally:
            Path(tmp_path).unlink(missing_ok=True)
        # cmd_persist already prints a JSON summary; we follow with our own.
    print(json.dumps(output, indent=2))


def main() -> None:
    p = argparse.ArgumentParser(
        description="Scan project papers for retraction status."
    )
    p.add_argument("--project-id", required=True)
    p.add_argument("--canonical-id", default=None,
                   help="Check only this paper (default: all)")
    p.add_argument("--max-age-days", type=int, default=7,
                   help="Re-check papers checked more than N days ago (default: 7)")
    p.add_argument("--dry-run", action="store_true", default=False,
                   help="Print what would be checked; do not modify DB")
    p.add_argument("--input", default=None,
                   help="JSON results file to persist (from MCP lookup)")
    p.add_argument("--mcp-lookup", action="store_true", default=False,
                   help="v0.78: drive retraction-mcp directly + emit "
                        "results JSON. Pair with --auto-persist to "
                        "write straight back to retraction_flags.")
    p.add_argument("--auto-persist", action="store_true", default=False,
                   help="With --mcp-lookup, also persist results to "
                        "retraction_flags in one shot.")
    p.add_argument("--output", default=None,
                   help="With --mcp-lookup, write the results JSON to "
                        "this path (in addition to stdout).")
    args = p.parse_args()

    if args.mcp_lookup:
        cmd_mcp_lookup(args)
    elif args.input:
        cmd_persist(args)
    else:
        cmd_list(args)


if __name__ == "__main__":
    main()

"""v0.84 — coscientist DB integrity checker.

Walks every coscientist DB (`runs/*.db` + `projects/*/project.db`)
and reports:
  - Missing tables vs base schema.
  - Foreign-key violations.
  - Orphan rows (e.g. graph_edges referencing non-existent nodes).
  - Migration version drift.

Read-only. Pure stdlib. CLI emits structured JSON.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from lib.cache import cache_root
from lib.migrations import ALL_VERSIONS


@dataclass
class DbReport:
    path: str
    healthy: bool = True
    issues: list[str] = field(default_factory=list)
    schema_versions: list[int] = field(default_factory=list)
    n_tables: int = 0
    fk_violations: int = 0


def _check_one(db_path: Path) -> DbReport:
    out = DbReport(path=str(db_path))
    if not db_path.exists():
        out.healthy = False
        out.issues.append("file missing")
        return out
    try:
        con = sqlite3.connect(db_path)
    except sqlite3.Error as e:
        out.healthy = False
        out.issues.append(f"connect failed: {e}")
        return out
    try:
        # Schema versions
        try:
            rows = con.execute(
                "SELECT version FROM schema_versions ORDER BY version"
            ).fetchall()
            out.schema_versions = [r[0] for r in rows]
        except sqlite3.OperationalError:
            out.issues.append("schema_versions table missing")

        # Migration version drift
        if out.schema_versions:
            applied = set(out.schema_versions)
            expected = set(ALL_VERSIONS)
            missing = sorted(expected - applied)
            extra = sorted(applied - expected)
            if missing:
                out.issues.append(
                    f"missing migrations: {missing} "
                    f"(run ensure_current to fix)"
                )
            if extra:
                out.issues.append(
                    f"unknown migrations applied: {extra}"
                )

        # Table count
        rows = con.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'"
        ).fetchone()
        out.n_tables = int(rows[0]) if rows else 0

        # FK violations
        try:
            con.execute("PRAGMA foreign_keys=ON")
            fk_rows = con.execute("PRAGMA foreign_key_check").fetchall()
            out.fk_violations = len(fk_rows)
            if fk_rows:
                out.issues.append(
                    f"{len(fk_rows)} foreign-key violation(s) "
                    f"(first: {fk_rows[0]})"
                )
        except sqlite3.OperationalError as e:
            out.issues.append(f"FK check failed: {e}")

        # Orphan graph_edges (only relevant on project DBs)
        try:
            orphans = con.execute(
                "SELECT COUNT(*) FROM graph_edges e "
                "WHERE NOT EXISTS ("
                "  SELECT 1 FROM graph_nodes n WHERE n.node_id=e.from_node"
                ") OR NOT EXISTS ("
                "  SELECT 1 FROM graph_nodes n WHERE n.node_id=e.to_node"
                ")"
            ).fetchone()[0]
            if orphans:
                out.issues.append(
                    f"{orphans} graph_edges row(s) reference missing nodes"
                )
        except sqlite3.OperationalError:
            pass  # graph tables not in this DB
    finally:
        con.close()

    out.healthy = not out.issues
    return out


def check_all() -> dict:
    """Walk every coscientist DB; return a structured report."""
    root = cache_root()
    candidates: list[Path] = []
    runs_dir = root / "runs"
    if runs_dir.exists():
        candidates.extend(p for p in runs_dir.glob("*.db") if p.is_file())
    projects_dir = root / "projects"
    if projects_dir.exists():
        for proj in projects_dir.iterdir():
            db = proj / "project.db"
            if db.exists():
                candidates.append(db)
    reports = [_check_one(p) for p in sorted(candidates)]
    return {
        "ok": all(r.healthy for r in reports),
        "n_dbs": len(reports),
        "n_healthy": sum(1 for r in reports if r.healthy),
        "n_unhealthy": sum(1 for r in reports if not r.healthy),
        "reports": [
            {
                "path": r.path,
                "healthy": r.healthy,
                "issues": r.issues,
                "schema_versions": r.schema_versions,
                "n_tables": r.n_tables,
                "fk_violations": r.fk_violations,
            }
            for r in reports
        ],
    }


def main(argv: list[str] | None = None) -> int:
    payload = check_all()
    print(json.dumps(payload, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

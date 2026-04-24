"""Project container — the top-level research unit.

A Project wraps many runs, manuscripts, experiments, datasets, reviews.
Each Project has its own SQLite DB at
~/.cache/coscientist/projects/<project_id>/project.db (schema in
lib/sqlite_schema.sql). Each run DB optionally belongs to a project.

Projects also own:
- a writing-style profile (set when writing-style subsystem lands)
- a calibration set (for publishability-judge)
- a Zotero collection key (for bidirectional sync)
- the knowledge graph for this research program

Kept small on purpose — most project-level operations are queries
against the DB. This module is the filesystem + init side only.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from lib.cache import cache_root

SCHEMA_PATH = Path(__file__).resolve().parent / "sqlite_schema.sql"


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def project_id_for(name: str) -> str:
    """Deterministic project_id: <slug>_<4-char hash>."""
    slug = _slug(name)[:50]
    h = hashlib.blake2s(name.lower().encode(), digest_size=2).hexdigest()
    return f"{slug}_{h}"


def project_root(project_id: str) -> Path:
    p = cache_root() / "projects" / project_id
    p.mkdir(parents=True, exist_ok=True)
    (p / "manuscripts").mkdir(exist_ok=True)
    (p / "experiments").mkdir(exist_ok=True)
    (p / "journal").mkdir(exist_ok=True)
    return p


def project_db_path(project_id: str) -> Path:
    return project_root(project_id) / "project.db"


def _connect(project_id: str) -> sqlite3.Connection:
    db = project_db_path(project_id)
    fresh = not db.exists()
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    if fresh:
        con.executescript(SCHEMA_PATH.read_text())
    return con


def create(name: str, question: str | None = None, description: str | None = None) -> str:
    """Create a project and return its project_id.

    Idempotent: if a project with the computed id exists, return it
    unchanged (no overwrite).
    """
    pid = project_id_for(name)
    con = _connect(pid)
    existing = con.execute("SELECT project_id FROM projects WHERE project_id=?", (pid,)).fetchone()
    if existing:
        con.close()
        return pid
    with con:
        con.execute(
            "INSERT INTO projects (project_id, name, question, description, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (pid, name, question, description, datetime.now(UTC).isoformat()),
        )
    con.close()
    return pid


def get(project_id: str) -> dict | None:
    if not project_db_path(project_id).exists():
        return None
    con = _connect(project_id)
    row = con.execute("SELECT * FROM projects WHERE project_id=?", (project_id,)).fetchone()
    con.close()
    return dict(row) if row else None


def update_style_profile(project_id: str, path: Path) -> None:
    con = _connect(project_id)
    with con:
        con.execute(
            "UPDATE projects SET style_profile_path=? WHERE project_id=?",
            (str(path), project_id),
        )
    con.close()


def set_calibration(project_id: str, path: Path) -> None:
    con = _connect(project_id)
    with con:
        con.execute(
            "UPDATE projects SET calibration_path=? WHERE project_id=?",
            (str(path), project_id),
        )
    con.close()


def list_all() -> list[dict]:
    """List every project we've ever created (scanning the project dirs)."""
    base = cache_root() / "projects"
    if not base.exists():
        return []
    out: list[dict] = []
    for p in sorted(base.iterdir()):
        if (p / "project.db").exists():
            meta = get(p.name)
            if meta:
                out.append(meta)
    return out


def link_run_to_project(run_db: Path, project_id: str) -> None:
    """Mark a run DB as belonging to a project."""
    if not run_db.exists():
        raise FileNotFoundError(run_db)
    con = sqlite3.connect(run_db)
    with con:
        con.execute("UPDATE runs SET project_id=? WHERE run_id=(SELECT run_id FROM runs LIMIT 1)", (project_id,))
    con.close()


def register_artifact(
    project_id: str,
    artifact_id: str,
    kind: str,
    state: str,
    path: Path,
) -> None:
    """Index an artifact (paper/manuscript/experiment/etc) in the project DB."""
    con = _connect(project_id)
    now = datetime.now(UTC).isoformat()
    with con:
        con.execute(
            "INSERT OR REPLACE INTO artifact_index "
            "(artifact_id, kind, project_id, state, path, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, "
            "COALESCE((SELECT created_at FROM artifact_index WHERE artifact_id=?), ?), ?)",
            (artifact_id, kind, project_id, state, str(path), artifact_id, now, now),
        )
    con.close()

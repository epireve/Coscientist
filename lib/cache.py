"""Filesystem layout for cached paper artifacts and runtime state.

Never hand-build paths. Import from here.
"""

from __future__ import annotations

import os
from pathlib import Path


def cache_root() -> Path:
    """Root of the cache. Override with COSCIENTIST_CACHE_DIR."""
    override = os.environ.get("COSCIENTIST_CACHE_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".cache" / "coscientist"


def paper_dir(canonical_id: str) -> Path:
    """Directory for a single paper's artifact. Created if missing."""
    p = cache_root() / "papers" / canonical_id
    p.mkdir(parents=True, exist_ok=True)
    (p / "figures").mkdir(exist_ok=True)
    (p / "tables").mkdir(exist_ok=True)
    (p / "raw").mkdir(exist_ok=True)
    return p


def audit_log_path() -> Path:
    """Append-only log of every PDF fetch. Required for library compliance."""
    p = cache_root() / "audit.log"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def run_db_path(run_id: str) -> Path:
    """SQLite run log for a deep-research run."""
    p = cache_root() / "runs" / f"run-{run_id}.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def runs_dir() -> Path:
    p = cache_root() / "runs"
    p.mkdir(parents=True, exist_ok=True)
    return p

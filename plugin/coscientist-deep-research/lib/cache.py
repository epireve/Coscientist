"""Filesystem layout for cached paper artifacts and runtime state.

Never hand-build paths. Import from here.
"""

from __future__ import annotations

import os
import re
from pathlib import Path


# audit-rotate stamps archives as <name>.<8-digit-date>T<6-digit-time>Z
# (with optional `_<size>` suffix on rare same-second collisions).
_ARCHIVE_STAMP_RE = re.compile(r"^(.+)\.\d{8}T\d{6}Z(_\d+)?$")


def archives_for(live: Path) -> list[Path]:
    """Rotated archives sitting next to a live append-only log.

    Returns a list of sibling files matching `<live.name>.<UTC-stamp>`,
    sorted oldest→newest by stamp. The live file itself is NOT included.
    Used by audit-query --include-archives and any other read-side tool
    that wants to walk the full history. Never raises on missing dirs.
    """
    if not live.parent.exists():
        return []
    out: list[Path] = []
    for sib in live.parent.iterdir():
        if not sib.is_file():
            continue
        m = _ARCHIVE_STAMP_RE.match(sib.name)
        if m and m.group(1) == live.name:
            out.append(sib)
    # Stamp is ISO-ish so name sort = chronological sort.
    out.sort(key=lambda p: p.name)
    return out


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


def run_inputs_dir(run_id: str) -> Path:
    """Per-run directory for orchestrator-harvested persona input files.

    The smoke-test resume plan (ROADMAP, item 3) pivots search-using
    personas to consume pre-harvested shortlist files instead of calling
    MCPs directly (since sub-agents in some runtimes don't inherit MCP
    access). Files land here as `<persona>-<phase>.json`.
    """
    p = cache_root() / "runs" / f"run-{run_id}" / "inputs"
    p.mkdir(parents=True, exist_ok=True)
    return p

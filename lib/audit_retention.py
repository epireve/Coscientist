"""v0.82 — audit-log archive retention.

Walks `~/.cache/coscientist/audit.log.<stamp>` + matching sandbox
archives, lists those older than N days. Deletion is opt-in via
explicit `--confirm` from the caller — mirrors the audit-rotate
doctrine ("refuses to delete archives without explicit user
intent").

Pure stdlib.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from lib.cache import archives_for, audit_log_path, cache_root


def _sandbox_log_path() -> Path:
    return cache_root() / "sandbox_audit.log"


@dataclass(frozen=True)
class ArchiveRow:
    path: Path
    age_days: int
    size_bytes: int
    label: str  # "audit" | "sandbox"


_STAMP_RE = re.compile(r"\.(\d{8})T(\d{6})Z")


def _archive_age_days(p: Path, now: datetime | None = None) -> int:
    """Parse the rotation stamp to compute age. Falls back to mtime."""
    now = now or datetime.now(UTC)
    m = _STAMP_RE.search(p.name)
    if m:
        try:
            stamp = datetime.strptime(
                f"{m.group(1)}T{m.group(2)}Z",
                "%Y%m%dT%H%M%SZ",
            ).replace(tzinfo=UTC)
            return (now - stamp).days
        except ValueError:
            pass
    # Fallback: mtime
    try:
        mtime = datetime.fromtimestamp(
            p.stat().st_mtime, tz=UTC,
        )
        return (now - mtime).days
    except OSError:
        return 0


def list_archives(*, older_than_days: int = 0) -> list[ArchiveRow]:
    """Return every audit + sandbox archive older than N days.

    `older_than_days=0` returns all archives (regardless of age).
    Sorted oldest first.
    """
    out: list[ArchiveRow] = []
    now = datetime.now(UTC)
    for live, label in (
        (audit_log_path(), "audit"),
        (_sandbox_log_path(), "sandbox"),
    ):
        for p in archives_for(live):
            age = _archive_age_days(p, now=now)
            if age < older_than_days:
                continue
            try:
                size = p.stat().st_size
            except OSError:
                size = 0
            out.append(ArchiveRow(
                path=p, age_days=age, size_bytes=size, label=label,
            ))
    out.sort(key=lambda r: (-r.age_days, r.path.name))
    return out


def purge_archives(
    *,
    older_than_days: int,
    confirm: bool = False,
) -> dict:
    """Delete audit + sandbox archives older than N days.

    Returns: {n_candidates, n_deleted, bytes_freed,
              candidates: [{path, age_days, size_bytes, label}, ...]}.

    Without `confirm=True`, this is a dry run — never deletes.
    """
    if older_than_days < 1:
        raise ValueError("older_than_days must be >= 1 to be safe")
    rows = list_archives(older_than_days=older_than_days)
    deleted = 0
    bytes_freed = 0
    deleted_paths: list[str] = []
    if confirm:
        for r in rows:
            try:
                size = r.size_bytes
                r.path.unlink()
                deleted += 1
                bytes_freed += size
                deleted_paths.append(str(r.path))
            except OSError:
                continue
        # v0.88: audit our own deletions to the live audit.log so a
        # purge is itself traceable. Doesn't recurse — only writes
        # to audit_log_path() not the sandbox log.
        if deleted_paths:
            _log_purge(deleted_paths, bytes_freed, older_than_days)
    return {
        "older_than_days": older_than_days,
        "confirm": confirm,
        "n_candidates": len(rows),
        "n_deleted": deleted,
        "bytes_freed": bytes_freed,
        "candidates": [
            {
                "path": str(r.path),
                "age_days": r.age_days,
                "size_bytes": r.size_bytes,
                "label": r.label,
            }
            for r in rows
        ],
    }


def _log_purge(deleted_paths: list[str], bytes_freed: int,
               older_than_days: int) -> None:
    """v0.88: append a JSON-line audit entry recording our purge."""
    import json
    log = audit_log_path()
    log.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "kind": "audit-purge",
        "at": datetime.now(UTC).isoformat(),
        "older_than_days": older_than_days,
        "n_deleted": len(deleted_paths),
        "bytes_freed": bytes_freed,
        "paths": [str(p) for p in deleted_paths],
    }
    try:
        with log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except OSError:
        pass  # logging failure shouldn't break the purge

#!/usr/bin/env python3
"""audit-rotate: size/age-based rotation for Coscientist audit logs.

Rotation is a rename — never a delete. Archives sit next to the live
log with a UTC timestamp suffix (`audit.log.20260427T093015Z`). The
producers (paper-acquire, sandbox.py) reopen the live path on each
write, so a fresh file gets created the next time they emit.

Subcommands: inspect | rotate | list-archives
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import archives_for, audit_log_path, cache_root  # noqa: E402

DEFAULT_MAX_BYTES = 10 * 1024 * 1024  # 10 MiB
# list-archives still wants to extract the stamp string; matches the
# canonical form (no collision suffix) since list output is for humans.
ARCHIVE_RE = re.compile(r"^(.+)\.(\d{8}T\d{6}Z)$")


def _sandbox_log_path() -> Path:
    return cache_root() / "sandbox_audit.log"


def _targets(target: str) -> list[Path]:
    if target == "fetches":
        return [audit_log_path()]
    if target == "sandbox":
        return [_sandbox_log_path()]
    return [audit_log_path(), _sandbox_log_path()]


def _utc_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _peek_first_last(path: Path) -> tuple[str | None, str | None]:
    if not path.exists() or path.stat().st_size == 0:
        return None, None
    text = path.read_text(errors="replace")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return None, None
    return lines[0], lines[-1]


def _line_count(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for ln in path.read_text(errors="replace").splitlines()
               if ln.strip())


def cmd_inspect(args: argparse.Namespace) -> dict:
    out: dict = {}
    for p in (audit_log_path(), _sandbox_log_path()):
        size = p.stat().st_size if p.exists() else 0
        first, last = _peek_first_last(p)
        out[p.name] = {
            "path": str(p),
            "exists": p.exists(),
            "size_bytes": size,
            "size_human": f"{size / 1024:.1f} KiB",
            "line_count": _line_count(p),
            "oldest_line": first,
            "newest_line": last,
        }
    return out


def _rotate_one(path: Path, max_bytes: int, force: bool) -> dict:
    if not path.exists():
        return {"path": str(path), "skipped": "no-such-file"}
    size = path.stat().st_size
    if not force and size < max_bytes:
        return {
            "path": str(path),
            "skipped": "under-threshold",
            "size_bytes": size,
            "max_bytes": max_bytes,
        }
    archive = path.with_name(f"{path.name}.{_utc_stamp()}")
    if archive.exists():
        # extreme edge case: same-second collision — append suffix
        archive = path.with_name(f"{archive.name}_{int(size)}")
    path.rename(archive)
    # Producer will reopen the original path on next write — no need to
    # touch a fresh file ourselves. But create one so audit-query can
    # always show "0 records" cleanly.
    path.touch()
    return {
        "path": str(path),
        "archived_to": str(archive),
        "size_bytes": size,
        "rotated_at": _utc_stamp(),
    }


def cmd_rotate(args: argparse.Namespace) -> dict:
    results = [_rotate_one(p, args.max_bytes, args.force)
               for p in _targets(args.target)]
    return {"rotations": results}


def cmd_list_archives(args: argparse.Namespace) -> dict:
    """All archive files sitting next to the two live logs."""
    archives: list[dict] = []
    for live in (audit_log_path(), _sandbox_log_path()):
        for sib in archives_for(live):
            m = ARCHIVE_RE.match(sib.name)
            stamp = m.group(2) if m else sib.name.rsplit(".", 1)[-1]
            archives.append({
                "archive": sib.name,
                "live_path": str(live),
                "stamp": stamp,
                "size_bytes": sib.stat().st_size,
            })
    archives.sort(key=lambda d: d["stamp"], reverse=True)
    return {"archives": archives, "count": len(archives)}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("inspect").set_defaults(func=cmd_inspect)

    r = sub.add_parser("rotate")
    r.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    r.add_argument("--target", choices=["fetches", "sandbox", "both"],
                   default="both")
    r.add_argument("--force", action="store_true",
                   help="rotate even when under threshold")
    r.set_defaults(func=cmd_rotate)

    sub.add_parser("list-archives").set_defaults(func=cmd_list_archives)

    args = p.parse_args()
    out = args.func(args)
    sys.stdout.write(json.dumps(out, indent=2, default=str) + "\n")


if __name__ == "__main__":
    main()

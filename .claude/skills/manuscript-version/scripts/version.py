#!/usr/bin/env python3
"""manuscript-version: lightweight version history for manuscript drafts.

Subcommands
-----------
snapshot   Copy current source.md into versions/<version_id>/ + write meta.json.
log        List all snapshots in reverse-chronological order.
diff       Compare two snapshots by per-section word count delta.
restore    Overwrite source.md with a snapshot's content (requires --confirm).

No LLM calls, no network. Pure filesystem.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.artifact import ManuscriptArtifact  # noqa: E402

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from version_store import (  # noqa: E402
    latest_version,
    list_versions,
    make_version_id,
    section_word_counts,
    snapshot_hash,
)

# --------------------------------------------------------------------------- #
# Internal helpers                                                             #
# --------------------------------------------------------------------------- #

def _manuscript_dir(manuscript_id: str) -> Path:
    art = ManuscriptArtifact(manuscript_id)
    return art.root


def _source_path(manuscript_dir: Path) -> Path:
    return manuscript_dir / "source.md"


def _require_source(manuscript_dir: Path, manuscript_id: str) -> str:
    sp = _source_path(manuscript_dir)
    if not sp.exists():
        print(
            f"ERROR: source.md not found for manuscript {manuscript_id!r}",
            file=sys.stderr,
        )
        sys.exit(1)
    return sp.read_text()


def _load_manifest_state(manuscript_dir: Path) -> str:
    mp = manuscript_dir / "manifest.json"
    if mp.exists():
        try:
            return json.loads(mp.read_text()).get("state", "unknown")
        except (json.JSONDecodeError, OSError):
            pass
    return "unknown"


def _do_snapshot(manuscript_dir: Path, manuscript_id: str,
                 note: str, source_text: str) -> str:
    """Create a snapshot unconditionally. Returns version_id."""
    version_id = make_version_id(manuscript_dir)
    snap_dir = manuscript_dir / "versions" / version_id
    snap_dir.mkdir(parents=True, exist_ok=True)

    # Copy source.md
    (snap_dir / "source.md").write_text(source_text)

    # Compute metadata
    wc_map = section_word_counts(source_text)
    total_wc = sum(wc_map.values())
    h = snapshot_hash(source_text)
    state = _load_manifest_state(manuscript_dir)

    meta = {
        "version_id": version_id,
        "manuscript_id": manuscript_id,
        "created_at": datetime.now(UTC).isoformat(),
        "note": note,
        "word_count": total_wc,
        "source_md_hash": h,
        "state_at_snapshot": state,
    }
    (snap_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    return version_id


def _resolve_version_id(manuscript_dir: Path, version_id: str,
                         manuscript_id: str) -> str:
    """Resolve a version_id (possibly a short prefix like 'v1') to its full id.

    If the exact directory exists, return it unchanged.
    Otherwise find any snapshot whose version_id starts with the given string.
    Exits with an error if no match or multiple matches.
    """
    vdir = manuscript_dir / "versions"
    exact = vdir / version_id
    if exact.exists():
        return version_id

    # Prefix match
    matches = [
        p.name for p in vdir.iterdir()
        if p.is_dir() and p.name.startswith(version_id)
    ] if vdir.exists() else []

    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        print(
            f"ERROR: ambiguous version prefix {version_id!r}: matches {matches}",
            file=sys.stderr,
        )
        sys.exit(1)
    print(
        f"ERROR: snapshot {version_id!r} not found for manuscript "
        f"{manuscript_id!r}",
        file=sys.stderr,
    )
    sys.exit(1)


def _resolve_version_source(manuscript_dir: Path, version_id: str,
                             manuscript_id: str) -> str:
    """Return source.md text for a version_id, or HEAD for current source.md."""
    if version_id.upper() == "HEAD":
        return _require_source(manuscript_dir, manuscript_id)

    full_vid = _resolve_version_id(manuscript_dir, version_id, manuscript_id)
    snap_src = manuscript_dir / "versions" / full_vid / "source.md"
    if not snap_src.exists():
        print(
            f"ERROR: snapshot {full_vid!r} source.md missing for manuscript "
            f"{manuscript_id!r}",
            file=sys.stderr,
        )
        sys.exit(1)
    return snap_src.read_text()


# --------------------------------------------------------------------------- #
# Subcommand: snapshot                                                         #
# --------------------------------------------------------------------------- #

def cmd_snapshot(args: argparse.Namespace) -> int:
    manuscript_dir = _manuscript_dir(args.manuscript_id)
    source_text = _require_source(manuscript_dir, args.manuscript_id)

    h = snapshot_hash(source_text)

    # Refuse if content hasn't changed since last snapshot (unless --force)
    if not args.force:
        latest = latest_version(manuscript_dir)
        if latest and latest.get("source_md_hash") == h:
            print(
                "ERROR: source.md has not changed since last snapshot "
                f"({latest['version_id']}). Use --force to snapshot anyway.",
                file=sys.stderr,
            )
            return 1

    note = args.note or ""
    version_id = _do_snapshot(manuscript_dir, args.manuscript_id, note, source_text)
    print(version_id)
    return 0


# --------------------------------------------------------------------------- #
# Subcommand: log                                                              #
# --------------------------------------------------------------------------- #

def cmd_log(args: argparse.Namespace) -> int:
    manuscript_dir = _manuscript_dir(args.manuscript_id)

    # Verify the manuscript exists (has a source.md or manifest.json)
    if not manuscript_dir.exists() or (
        not (manuscript_dir / "source.md").exists()
        and not (manuscript_dir / "manifest.json").exists()
    ):
        print(
            f"ERROR: manuscript {args.manuscript_id!r} not found.",
            file=sys.stderr,
        )
        return 1

    versions = list_versions(manuscript_dir)
    if not versions:
        print(f"No snapshots for manuscript {args.manuscript_id!r}.")
        return 0

    # Reverse-chronological
    versions = list(reversed(versions))

    col = "{:<30}  {:<20}  {:>6}  {}"
    print(col.format("version_id", "created_at", "words", "note"))
    print("-" * 72)
    for v in versions:
        created = v.get("created_at", "")[:19]  # drop sub-second + tz
        note = v.get("note") or ""
        wc = v.get("word_count", 0)
        print(col.format(v["version_id"], created, str(wc), note))
    return 0


# --------------------------------------------------------------------------- #
# Subcommand: diff                                                             #
# --------------------------------------------------------------------------- #

def cmd_diff(args: argparse.Namespace) -> int:
    manuscript_dir = _manuscript_dir(args.manuscript_id)

    from_text = _resolve_version_source(
        manuscript_dir, args.from_version, args.manuscript_id
    )
    to_text = _resolve_version_source(
        manuscript_dir, args.to_version, args.manuscript_id
    )

    from_counts = section_word_counts(from_text)
    to_counts = section_word_counts(to_text)

    # Union of all sections
    all_sections = sorted(set(from_counts) | set(to_counts))

    from_label = args.from_version
    to_label = args.to_version

    col = "{:<30}  {:>8}  {:>8}  {:>8}"
    print(col.format("section", from_label[:8], to_label[:8], "delta"))
    print("-" * 60)
    total_from = 0
    total_to = 0
    for sec in all_sections:
        f = from_counts.get(sec, 0)
        t = to_counts.get(sec, 0)
        delta = t - f
        total_from += f
        total_to += t
        sign = "+" if delta > 0 else ""
        print(col.format(sec[:30], str(f), str(t), f"{sign}{delta}"))

    print("-" * 60)
    total_delta = total_to - total_from
    sign = "+" if total_delta > 0 else ""
    print(col.format("TOTAL", str(total_from), str(total_to),
                     f"{sign}{total_delta}"))
    return 0


# --------------------------------------------------------------------------- #
# Subcommand: restore                                                          #
# --------------------------------------------------------------------------- #

def cmd_restore(args: argparse.Namespace) -> int:
    if not args.confirm:
        print(
            "ERROR: restore requires --confirm to prevent accidental overwrites.",
            file=sys.stderr,
        )
        return 1

    manuscript_dir = _manuscript_dir(args.manuscript_id)
    current_text = _require_source(manuscript_dir, args.manuscript_id)

    # Auto-snapshot current state before overwriting
    _do_snapshot(
        manuscript_dir, args.manuscript_id,
        note=f"auto-snapshot before restore to {args.version}",
        source_text=current_text,
    )

    # Load the target snapshot (support prefix matching)
    full_vid = _resolve_version_id(manuscript_dir, args.version, args.manuscript_id)
    snap_src = manuscript_dir / "versions" / full_vid / "source.md"
    if not snap_src.exists():
        print(
            f"ERROR: snapshot {full_vid!r} source.md missing for manuscript "
            f"{args.manuscript_id!r}",
            file=sys.stderr,
        )
        return 1

    restore_text = snap_src.read_text()
    _source_path(manuscript_dir).write_text(restore_text)
    print(f"Restored {args.manuscript_id} to {full_vid}")
    return 0


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #

def main() -> int:
    p = argparse.ArgumentParser(
        prog="version.py",
        description="Lightweight version history for manuscript drafts.",
    )
    sub = p.add_subparsers(dest="subcommand", required=True)

    # snapshot
    ps = sub.add_parser("snapshot", help="Snapshot current source.md")
    ps.add_argument("--manuscript-id", required=True, dest="manuscript_id")
    ps.add_argument("--note", default="", help="Human-readable note for this snapshot")
    ps.add_argument("--force", action="store_true",
                    help="Snapshot even if content hasn't changed")

    # log
    pl = sub.add_parser("log", help="List all snapshots in reverse order")
    pl.add_argument("--manuscript-id", required=True, dest="manuscript_id")

    # diff
    pd = sub.add_parser("diff", help="Compare two snapshots by section word count")
    pd.add_argument("--manuscript-id", required=True, dest="manuscript_id")
    pd.add_argument("--from", required=True, dest="from_version",
                    metavar="VERSION_ID",
                    help="Source version (or HEAD for current source.md)")
    pd.add_argument("--to", required=True, dest="to_version",
                    metavar="VERSION_ID",
                    help="Target version (or HEAD for current source.md)")

    # restore
    pr = sub.add_parser("restore", help="Restore source.md from a snapshot")
    pr.add_argument("--manuscript-id", required=True, dest="manuscript_id")
    pr.add_argument("--version", required=True, dest="version",
                    help="version_id to restore")
    pr.add_argument("--confirm", action="store_true",
                    help="Required: confirm the overwrite")

    args = p.parse_args()
    dispatch = {
        "snapshot": cmd_snapshot,
        "log": cmd_log,
        "diff": cmd_diff,
        "restore": cmd_restore,
    }
    return dispatch[args.subcommand](args)


if __name__ == "__main__":
    sys.exit(main())

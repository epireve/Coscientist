#!/usr/bin/env python3
"""citation-alerts: track who's citing your papers (two-phase like retraction-watch)."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import cache_root  # noqa: E402


def _alert_dir(project_id: str) -> Path:
    d = cache_root() / "projects" / project_id / "citation_alerts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _snapshots_dir(project_id: str) -> Path:
    d = _alert_dir(project_id) / "snapshots"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _tracked_path(project_id: str) -> Path:
    return _alert_dir(project_id) / "tracked.json"


def _load_tracked(project_id: str) -> list[dict]:
    p = _tracked_path(project_id)
    if not p.exists():
        return []
    return json.loads(p.read_text())


def _save_tracked(project_id: str, tracked: list[dict]) -> None:
    _tracked_path(project_id).write_text(json.dumps(tracked, indent=2))


def _snapshot_path(project_id: str, cid: str) -> Path:
    return _snapshots_dir(project_id) / f"{cid}.json"


def _load_snapshot(project_id: str, cid: str) -> dict:
    p = _snapshot_path(project_id, cid)
    if not p.exists():
        return {"canonical_id": cid, "citers": [], "last_checked": None}
    return json.loads(p.read_text())


def _save_snapshot(project_id: str, cid: str, snapshot: dict) -> None:
    _snapshot_path(project_id, cid).write_text(json.dumps(snapshot, indent=2))


def cmd_add(args: argparse.Namespace) -> None:
    tracked = _load_tracked(args.project_id)
    if any(t["canonical_id"] == args.canonical_id for t in tracked):
        raise SystemExit(f"already tracking {args.canonical_id!r}")
    tracked.append({
        "canonical_id": args.canonical_id,
        "label": args.label or args.canonical_id,
        "added_at": datetime.now(UTC).isoformat(),
    })
    _save_tracked(args.project_id, tracked)
    print(json.dumps({
        "project_id": args.project_id,
        "canonical_id": args.canonical_id,
        "tracked_count": len(tracked),
    }, indent=2))


def cmd_remove(args: argparse.Namespace) -> None:
    tracked = _load_tracked(args.project_id)
    new = [t for t in tracked if t["canonical_id"] != args.canonical_id]
    if len(new) == len(tracked):
        raise SystemExit(f"not tracking {args.canonical_id!r}")
    _save_tracked(args.project_id, new)
    # Optionally remove snapshot
    snap = _snapshot_path(args.project_id, args.canonical_id)
    if snap.exists():
        snap.unlink()
    print(json.dumps({
        "project_id": args.project_id,
        "canonical_id": args.canonical_id,
        "tracked_count": len(new),
        "snapshot_removed": True,
    }, indent=2))


def cmd_list_tracked(args: argparse.Namespace) -> None:
    tracked = _load_tracked(args.project_id)
    print(json.dumps({
        "project_id": args.project_id,
        "tracked": tracked,
        "total": len(tracked),
    }, indent=2))


def cmd_list(args: argparse.Namespace) -> None:
    tracked = _load_tracked(args.project_id)
    cutoff = datetime.now(UTC) - timedelta(days=args.max_age_days)
    to_check: list[dict] = []
    fresh = 0
    for t in tracked:
        snap = _load_snapshot(args.project_id, t["canonical_id"])
        last = snap.get("last_checked")
        needs = True
        if last:
            try:
                last_dt = datetime.fromisoformat(last)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=UTC)
                if last_dt >= cutoff:
                    needs = False
            except ValueError:
                pass
        if needs:
            to_check.append({
                "canonical_id": t["canonical_id"],
                "label": t.get("label"),
                "last_checked": last,
                "known_citer_count": len(snap.get("citers", [])),
            })
        else:
            fresh += 1
    print(json.dumps({
        "project_id": args.project_id,
        "to_check": to_check,
        "already_current": fresh,
        "max_age_days": args.max_age_days,
    }, indent=2))


def cmd_persist(args: argparse.Namespace) -> None:
    p = Path(args.input)
    if not p.exists():
        raise SystemExit(f"input file not found: {p}")
    items = json.loads(p.read_text())
    if not isinstance(items, list):
        raise SystemExit("input must be JSON array of {canonical_id, citers}")

    saved = 0
    new_citers_total = 0
    deltas: list[dict] = []
    now = datetime.now(UTC).isoformat()

    for item in items:
        cid = item.get("canonical_id")
        if not cid:
            continue
        new_citers = item.get("citers") or []
        snapshot = _load_snapshot(args.project_id, cid)
        old_set = {c["canonical_id"] for c in snapshot.get("citers", [])
                   if c.get("canonical_id")}
        new_only = []
        for c in new_citers:
            if c.get("canonical_id") and c["canonical_id"] not in old_set:
                c2 = dict(c)
                c2["first_seen"] = now
                new_only.append(c2)

        # Merge
        merged = list(snapshot.get("citers", []))
        merged.extend(new_only)
        snapshot["citers"] = merged
        snapshot["last_checked"] = now
        _save_snapshot(args.project_id, cid, snapshot)

        saved += 1
        new_citers_total += len(new_only)
        deltas.append({
            "canonical_id": cid,
            "new_citer_count": len(new_only),
            "total_citer_count": len(merged),
        })

    print(json.dumps({
        "project_id": args.project_id,
        "saved": saved,
        "new_citers_total": new_citers_total,
        "deltas": deltas,
    }, indent=2))


def cmd_digest(args: argparse.Namespace) -> None:
    tracked = _load_tracked(args.project_id)
    cutoff = datetime.now(UTC) - timedelta(days=args.since_days)
    digest_entries: list[dict] = []
    new_total = 0

    for t in tracked:
        snap = _load_snapshot(args.project_id, t["canonical_id"])
        recent = []
        for c in snap.get("citers", []):
            fs = c.get("first_seen")
            if not fs:
                continue
            try:
                ts = datetime.fromisoformat(fs)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                if ts >= cutoff:
                    recent.append(c)
            except ValueError:
                pass
        if recent:
            digest_entries.append({
                "canonical_id": t["canonical_id"],
                "label": t.get("label"),
                "new_citers": recent,
            })
            new_total += len(recent)

    digest = {
        "project_id": args.project_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "since_days": args.since_days,
        "entries": digest_entries,
        "new_citers_total": new_total,
    }
    out = _alert_dir(args.project_id) / f"digest_{datetime.now(UTC).date().isoformat()}.json"
    out.write_text(json.dumps(digest, indent=2))
    print(json.dumps({
        "digest_path": str(out),
        "new_citers_total": new_total,
        "papers_with_new_citers": len(digest_entries),
    }, indent=2))


def cmd_status(args: argparse.Namespace) -> None:
    tracked = _load_tracked(args.project_id)
    total_citers = 0
    last_checked = None
    for t in tracked:
        snap = _load_snapshot(args.project_id, t["canonical_id"])
        total_citers += len(snap.get("citers", []))
        lc = snap.get("last_checked")
        if lc and (last_checked is None or lc > last_checked):
            last_checked = lc
    print(json.dumps({
        "project_id": args.project_id,
        "tracked_papers": len(tracked),
        "total_citers": total_citers,
        "most_recent_check": last_checked,
    }, indent=2))


def main() -> None:
    p = argparse.ArgumentParser(description="Citation alerts (two-phase, like retraction-watch).")
    sub = p.add_subparsers(dest="cmd", required=True)

    pa = sub.add_parser("add")
    pa.add_argument("--project-id", required=True)
    pa.add_argument("--canonical-id", required=True)
    pa.add_argument("--label", default=None)
    pa.set_defaults(func=cmd_add)

    pr = sub.add_parser("remove")
    pr.add_argument("--project-id", required=True)
    pr.add_argument("--canonical-id", required=True)
    pr.set_defaults(func=cmd_remove)

    plt = sub.add_parser("list-tracked")
    plt.add_argument("--project-id", required=True)
    plt.set_defaults(func=cmd_list_tracked)

    pl = sub.add_parser("list")
    pl.add_argument("--project-id", required=True)
    pl.add_argument("--max-age-days", type=int, default=7)
    pl.set_defaults(func=cmd_list)

    pp = sub.add_parser("persist")
    pp.add_argument("--project-id", required=True)
    pp.add_argument("--input", required=True)
    pp.set_defaults(func=cmd_persist)

    pd = sub.add_parser("digest")
    pd.add_argument("--project-id", required=True)
    pd.add_argument("--since-days", type=int, default=30)
    pd.set_defaults(func=cmd_digest)

    ps = sub.add_parser("status")
    ps.add_argument("--project-id", required=True)
    ps.set_defaults(func=cmd_status)

    args = p.parse_args()
    try:
        args.func(args)
    except (FileNotFoundError, ValueError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

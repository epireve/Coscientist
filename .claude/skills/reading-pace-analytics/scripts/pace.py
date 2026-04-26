#!/usr/bin/env python3
"""reading-pace-analytics: read-only velocity metrics from reading_state."""
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

READ_STATES = {"read", "annotated", "cited"}
ALL_STATES = ["to-read", "reading", "read", "annotated", "cited", "skipped"]


def _project_dbs(project_id: str | None) -> list[Path]:
    base = cache_root() / "projects"
    if not base.exists():
        return []
    if project_id:
        p = base / project_id / "project.db"
        return [p] if p.exists() else []
    return sorted(p for p in base.glob("*/project.db") if p.is_file())


def _open_ro(db: Path) -> sqlite3.Connection:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    return con


def _all_reading_rows(project_id: str | None) -> list[dict]:
    rows: list[dict] = []
    for db in _project_dbs(project_id):
        try:
            con = _open_ro(db)
            try:
                for r in con.execute(
                    "SELECT canonical_id, project_id, state, updated_at "
                    "FROM reading_state"
                ).fetchall():
                    rows.append(dict(r))
            except sqlite3.OperationalError:
                # table may not exist yet
                pass
            finally:
                con.close()
        except sqlite3.DatabaseError:
            continue
    return rows


def _parse_iso(s: str) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except ValueError:
        return None


def cmd_velocity(args: argparse.Namespace) -> None:
    rows = _all_reading_rows(args.project_id)
    cutoff = datetime.now(UTC) - timedelta(days=args.days)
    weeks = args.days / 7.0

    read_in_window = 0
    cited_in_window = 0
    for r in rows:
        ts = _parse_iso(r["updated_at"])
        if ts is None or ts < cutoff:
            continue
        if r["state"] in READ_STATES:
            read_in_window += 1
        if r["state"] == "cited":
            cited_in_window += 1

    print(json.dumps({
        "project_id": args.project_id,
        "window_days": args.days,
        "papers_read_in_window": read_in_window,
        "papers_cited_in_window": cited_in_window,
        "papers_per_week": round(read_in_window / weeks, 2) if weeks else 0,
        "cited_per_week": round(cited_in_window / weeks, 2) if weeks else 0,
        "total_tracked_rows": len(rows),
    }, indent=2))


def cmd_backlog(args: argparse.Namespace) -> None:
    rows = _all_reading_rows(args.project_id)
    counts = {s: 0 for s in ALL_STATES}
    untouched_count = 0
    oldest_age_days = 0
    threshold = datetime.now(UTC) - timedelta(days=30)
    now = datetime.now(UTC)

    for r in rows:
        s = r["state"]
        if s in counts:
            counts[s] += 1
        if s == "to-read":
            ts = _parse_iso(r["updated_at"])
            if ts and ts < threshold:
                untouched_count += 1
            if ts:
                age = (now - ts).days
                if age > oldest_age_days:
                    oldest_age_days = age

    print(json.dumps({
        "project_id": args.project_id,
        "counts_by_state": counts,
        "untouched_to_read_count": untouched_count,
        "oldest_to_read_age_days": oldest_age_days,
        "total_tracked_rows": len(rows),
    }, indent=2))


def cmd_trend(args: argparse.Namespace) -> None:
    rows = _all_reading_rows(args.project_id)
    weeks = args.weeks
    now = datetime.now(UTC)
    # Bucket count = `weeks`; each bucket is 7 days, ending at `now`
    buckets = [0] * weeks

    for r in rows:
        if r["state"] not in READ_STATES:
            continue
        ts = _parse_iso(r["updated_at"])
        if ts is None:
            continue
        delta_days = (now - ts).days
        if delta_days < 0:
            continue
        bucket_index = delta_days // 7
        if bucket_index < weeks:
            buckets[bucket_index] += 1

    # buckets[0] = current week, buckets[1] = last week, etc.
    # Reverse so output is oldest → newest
    weekly = list(reversed(buckets))
    rolling_avg_4w = []
    for i in range(len(weekly)):
        start = max(0, i - 3)
        slice_ = weekly[start:i + 1]
        rolling_avg_4w.append(round(sum(slice_) / len(slice_), 2))

    print(json.dumps({
        "project_id": args.project_id,
        "weeks": weeks,
        "weekly_read_counts_oldest_first": weekly,
        "rolling_avg_4w": rolling_avg_4w,
        "total_in_window": sum(weekly),
    }, indent=2))


def cmd_summary(args: argparse.Namespace) -> None:
    """Combined view of velocity + backlog + trend."""
    rows = _all_reading_rows(args.project_id)
    if not rows:
        print(json.dumps({
            "project_id": args.project_id,
            "total_tracked_rows": 0,
            "note": "no reading_state rows found",
        }, indent=2))
        return

    # 28-day velocity
    cutoff_28 = datetime.now(UTC) - timedelta(days=28)
    read_28 = sum(1 for r in rows
                  if r["state"] in READ_STATES
                  and (ts := _parse_iso(r["updated_at"]))
                  and ts >= cutoff_28)

    # backlog counts
    counts = {s: 0 for s in ALL_STATES}
    for r in rows:
        if r["state"] in counts:
            counts[r["state"]] += 1

    # all-time read total
    total_read = sum(1 for r in rows if r["state"] in READ_STATES)

    print(json.dumps({
        "project_id": args.project_id,
        "total_tracked_rows": len(rows),
        "papers_per_week_28d": round(read_28 / 4.0, 2),
        "papers_read_28d": read_28,
        "total_read_all_time": total_read,
        "counts_by_state": counts,
        "to_read_backlog": counts["to-read"],
    }, indent=2))


def main() -> None:
    p = argparse.ArgumentParser(description="Reading velocity analytics.")
    sub = p.add_subparsers(dest="cmd", required=True)

    pv = sub.add_parser("velocity")
    pv.add_argument("--project-id", default=None)
    pv.add_argument("--days", type=int, default=28)
    pv.set_defaults(func=cmd_velocity)

    pb = sub.add_parser("backlog")
    pb.add_argument("--project-id", default=None)
    pb.set_defaults(func=cmd_backlog)

    pt = sub.add_parser("trend")
    pt.add_argument("--project-id", default=None)
    pt.add_argument("--weeks", type=int, default=12)
    pt.set_defaults(func=cmd_trend)

    ps = sub.add_parser("summary")
    ps.add_argument("--project-id", default=None)
    ps.set_defaults(func=cmd_summary)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

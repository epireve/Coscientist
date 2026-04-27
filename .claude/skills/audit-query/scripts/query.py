#!/usr/bin/env python3
"""audit-query: read-only summary over Coscientist's append-only audit logs.

Two logs:
  - ~/.cache/coscientist/audit.log         (paper-acquire / institutional-access)
  - ~/.cache/coscientist/sandbox_audit.log (reproducibility-mcp Docker runs)

Subcommands: fetches | sandbox | summary
Output: JSON to stdout (or markdown via --format md).
Never mutates either file.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import archives_for, audit_log_path, cache_root  # noqa: E402


def _sandbox_log_path() -> Path:
    return cache_root() / "sandbox_audit.log"


def _expand_with_archives(live: Path) -> list[Path]:
    """Archives oldest→newest, then live log last (so newest record wins)."""
    paths = archives_for(live)
    if live.exists():
        paths.append(live)
    return paths


# Legacy line: "2026-04-26T01:22:38.481316 doi=None arxiv=2010.11929 tier=arxiv status=ok"
_LEGACY_RE = re.compile(r"^(\S+)\s+(.*)$")


def _parse_legacy(line: str) -> dict | None:
    m = _LEGACY_RE.match(line.strip())
    if not m:
        return None
    ts, kvs = m.groups()
    out: dict = {"at": ts, "_legacy": True}
    for tok in kvs.split():
        if "=" in tok:
            k, v = tok.split("=", 1)
            out[k] = v
    # reject unless we got a recognisable tier or status
    if "tier" in out or "status" in out:
        return out
    return None


def _iter_fetch_records(path: Path):
    """Yield dicts from audit.log. Handles JSONL + legacy free-text."""
    if not path.exists():
        return
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        # JSON first
        if line.startswith("{"):
            try:
                yield json.loads(line)
                continue
            except json.JSONDecodeError:
                pass
        rec = _parse_legacy(line)
        if rec is not None:
            yield rec


def _iter_sandbox_records(path: Path):
    if not path.exists():
        return
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def _record_time(rec: dict) -> str | None:
    return rec.get("at") or rec.get("started_at") or rec.get("finished_at")


def _after(rec: dict, since: str | None) -> bool:
    if not since:
        return True
    t = _record_time(rec)
    if not t:
        return False
    # Compare ISO prefix lexicographically — works for YYYY-MM-DD bounds.
    return t >= since


def cmd_fetches(args: argparse.Namespace) -> dict:
    paths = (_expand_with_archives(audit_log_path())
             if getattr(args, "include_archives", False)
             else [audit_log_path()])
    records: list[dict] = []
    for p in paths:
        records.extend(
            r for r in _iter_fetch_records(p)
            if _after(r, args.since)
            and (not args.domain or args.domain in json.dumps(r))
        )
    by_tier = Counter(r.get("tier") or r.get("source") or "unknown" for r in records)
    by_status = Counter(_status_of(r) for r in records)
    failures = [r for r in records if _status_of(r) not in ("ok", "success", "200")]
    return {
        "log": str(audit_log_path()),
        "since": args.since,
        "total_records": len(records),
        "by_tier": dict(by_tier.most_common()),
        "by_status": dict(by_status.most_common()),
        "recent_failures": failures[-args.limit:],
    }


def _status_of(rec: dict) -> str:
    s = rec.get("status")
    if s is not None:
        return str(s)
    # Newer JSONL paper-acquire records use {"result": "ok"} or "tier_result"
    return str(rec.get("result") or rec.get("tier_result") or "unknown")


def cmd_sandbox(args: argparse.Namespace) -> dict:
    paths = (_expand_with_archives(_sandbox_log_path())
             if getattr(args, "include_archives", False)
             else [_sandbox_log_path()])
    records: list[dict] = []
    for p in paths:
        records.extend(
            r for r in _iter_sandbox_records(p)
            if _after(r, args.since)
            and (not args.error_class
                 or r.get("error_class") == args.error_class)
        )
    by_error_class = Counter(r.get("error_class") or "ok" for r in records)
    timeouts = [r for r in records if r.get("timed_out")]
    ooms = [r for r in records if r.get("memory_oom")]
    nonzero = [r for r in records if r.get("exit_code") not in (0, None)]
    total_wall = sum(float(r.get("wall_time_seconds", 0) or 0) for r in records)
    return {
        "log": str(_sandbox_log_path()),
        "since": args.since,
        "total_runs": len(records),
        "by_error_class": dict(by_error_class.most_common()),
        "n_timeouts": len(timeouts),
        "n_ooms": len(ooms),
        "n_nonzero_exit": len(nonzero),
        "total_wall_time_seconds": round(total_wall, 3),
        "recent_failures": nonzero[-args.limit:],
    }


def cmd_records(args: argparse.Namespace) -> dict:
    """v0.57 — per-table row counts in a coscientist DB.

    Lists every user table with row count. Optionally dumps the
    db_writes audit summary (which skill wrote how many rows when).
    Read-only.
    """
    import sqlite3 as _sq
    db_path = Path(args.db_path)
    if not db_path.exists():
        raise SystemExit(f"DB not found: {db_path}")
    con = _sq.connect(db_path)
    try:
        # Avoid hard import dep — try lib.db_notify if available
        try:
            from lib.db_notify import per_table_counts, summarize_writes
            counts = per_table_counts(con)
            payload: dict = {
                "db_path": str(db_path),
                "tables": [
                    {"name": k, "rows": v}
                    for k, v in sorted(counts.items())
                ],
                "n_tables": len(counts),
                "n_nonempty": sum(1 for v in counts.values() if v > 0),
                "n_empty": sum(1 for v in counts.values() if v == 0),
            }
            if args.writes:
                payload["db_writes_summary"] = summarize_writes(con)
        except ImportError:
            # Manual fallback
            rows = con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' AND name != 'schema_versions' "
                "ORDER BY name"
            ).fetchall()
            counts = {}
            for (name,) in rows:
                try:
                    counts[name] = con.execute(
                        f'SELECT COUNT(*) FROM "{name}"'
                    ).fetchone()[0]
                except _sq.Error:
                    counts[name] = -1
            payload = {
                "db_path": str(db_path),
                "tables": [
                    {"name": k, "rows": v}
                    for k, v in sorted(counts.items())
                ],
            }
        return payload
    finally:
        con.close()


def cmd_resolutions(args: argparse.Namespace) -> dict:
    """v0.64 — read-only summary of citation_resolutions rows.

    Reports total, matched/unmatched counts, match rate, score
    distribution, and the most-recent attempts. Optional filters by
    run_id, project_id, and matched-only.
    """
    import sqlite3 as _sq
    db_path = Path(args.db_path)
    if not db_path.exists():
        raise SystemExit(f"DB not found: {db_path}")
    con = _sq.connect(db_path)
    try:
        if not con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='citation_resolutions'"
        ).fetchone():
            return {
                "db_path": str(db_path),
                "table_present": False,
                "total": 0,
            }
        where: list[str] = []
        params: list = []
        if args.run_id:
            where.append("run_id = ?")
            params.append(args.run_id)
        if args.project_id:
            where.append("project_id = ?")
            params.append(args.project_id)
        if args.matched_only:
            where.append("matched = 1")
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""

        total = con.execute(
            f"SELECT COUNT(*) FROM citation_resolutions {where_sql}",
            params,
        ).fetchone()[0]
        matched = con.execute(
            f"SELECT COUNT(*) FROM citation_resolutions {where_sql} "
            f"{'AND' if where_sql else 'WHERE'} matched=1",
            params,
        ).fetchone()[0]
        unmatched = total - matched

        # score buckets
        buckets = {"<0.3": 0, "0.3-0.5": 0, "0.5-0.7": 0, "0.7-0.9": 0,
                   ">=0.9": 0}
        for (score,) in con.execute(
            f"SELECT score FROM citation_resolutions {where_sql}",
            params,
        ):
            s = float(score or 0.0)
            if s < 0.3:
                buckets["<0.3"] += 1
            elif s < 0.5:
                buckets["0.3-0.5"] += 1
            elif s < 0.7:
                buckets["0.5-0.7"] += 1
            elif s < 0.9:
                buckets["0.7-0.9"] += 1
            else:
                buckets[">=0.9"] += 1

        recent = []
        for row in con.execute(
            f"SELECT input_text, matched, score, canonical_id, at "
            f"FROM citation_resolutions {where_sql} ORDER BY at DESC LIMIT ?",
            (*params, max(1, args.limit)),
        ):
            recent.append({
                "input_text": row[0],
                "matched": bool(row[1]),
                "score": round(float(row[2] or 0.0), 4),
                "canonical_id": row[3],
                "at": row[4],
            })

        return {
            "db_path": str(db_path),
            "table_present": True,
            "filters": {
                "run_id": args.run_id,
                "project_id": args.project_id,
                "matched_only": args.matched_only,
            },
            "total": total,
            "matched": matched,
            "unmatched": unmatched,
            "match_rate": round(matched / total, 4) if total else 0.0,
            "score_buckets": buckets,
            "recent": recent,
        }
    finally:
        con.close()


def cmd_summary(args: argparse.Namespace) -> dict:
    incl = getattr(args, "include_archives", False)
    fa = argparse.Namespace(since=args.since, domain=None, limit=5,
                             include_archives=incl)
    sa = argparse.Namespace(since=args.since, error_class=None, limit=5,
                             include_archives=incl)
    return {
        "since": args.since,
        "include_archives": incl,
        "fetches": cmd_fetches(fa),
        "sandbox": cmd_sandbox(sa),
    }


def _to_markdown(out: dict) -> str:
    """Best-effort markdown rendering for one-screen forensic view."""
    lines = ["# audit-query"]
    if "fetches" in out:
        f = out["fetches"]
        lines += [
            "", "## Fetches",
            f"- log: `{f['log']}`",
            f"- total: **{f['total_records']}**",
            "- by tier: " + ", ".join(f"`{k}`={v}" for k, v in f["by_tier"].items()),
            "- by status: " + ", ".join(f"`{k}`={v}" for k, v in f["by_status"].items()),
        ]
    if "sandbox" in out:
        s = out["sandbox"]
        lines += [
            "", "## Sandbox",
            f"- log: `{s['log']}`",
            f"- total runs: **{s['total_runs']}**",
            f"- timeouts: {s['n_timeouts']}; OOMs: {s['n_ooms']}; "
            f"non-zero exits: {s['n_nonzero_exit']}",
            f"- total wall-time: {s['total_wall_time_seconds']}s",
            "- by error_class: " + ", ".join(
                f"`{k}`={v}" for k, v in s["by_error_class"].items()
            ),
        ]
    return "\n".join(lines) + "\n"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--format", choices=["json", "md"], default="json")
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetches", help="PDF fetch log summary")
    f.add_argument("--since", help="ISO date (YYYY-MM-DD)")
    f.add_argument("--domain", help="substring filter on record JSON")
    f.add_argument("--limit", type=int, default=20)
    f.add_argument("--include-archives", action="store_true",
                    help="also read rotated <name>.<UTC-stamp> archives")
    f.set_defaults(func=cmd_fetches)

    s = sub.add_parser("sandbox", help="Docker sandbox log summary")
    s.add_argument("--since", help="ISO date (YYYY-MM-DD)")
    s.add_argument("--error-class", dest="error_class")
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--include-archives", action="store_true")
    s.set_defaults(func=cmd_sandbox)

    a = sub.add_parser("summary", help="Combined fetch + sandbox forensic view")
    a.add_argument("--since", help="ISO date (YYYY-MM-DD)")
    a.add_argument("--include-archives", action="store_true")
    a.set_defaults(func=cmd_summary)

    r = sub.add_parser("records",
                        help="Per-table row counts in a coscientist DB (v0.57)")
    r.add_argument("--db-path", required=True,
                    help="Path to a coscientist SQLite DB (run-<rid>.db, "
                         "wide-<rid>.db, project DB, etc.)")
    r.add_argument("--writes", action="store_true",
                    help="Also dump db_writes audit summary")
    r.set_defaults(func=cmd_records)

    rs = sub.add_parser(
        "resolutions",
        help="citation_resolutions summary (match rate + score buckets) (v0.64)",
    )
    rs.add_argument("--db-path", required=True,
                    help="Path to a coscientist SQLite DB")
    rs.add_argument("--run-id", default=None, help="Filter by run_id")
    rs.add_argument("--project-id", default=None, help="Filter by project_id")
    rs.add_argument("--matched-only", action="store_true",
                    help="Show only matched resolutions")
    rs.add_argument("--limit", type=int, default=10,
                    help="How many recent rows to include (default 10)")
    rs.set_defaults(func=cmd_resolutions)

    args = p.parse_args()
    out = args.func(args)
    if args.format == "md":
        sys.stdout.write(_to_markdown(out))
    else:
        sys.stdout.write(json.dumps(out, indent=2, default=str) + "\n")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""meta-research: cross-project trajectory + concept overlap + productivity (read-only)."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import cache_root  # noqa: E402


def _project_dbs() -> list[Path]:
    base = cache_root() / "projects"
    if not base.exists():
        return []
    return sorted(p for p in base.glob("*/project.db") if p.is_file())


def _open_ro(db: Path) -> sqlite3.Connection:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    return con


def _get_project_meta(db: Path) -> dict | None:
    """Read project row from a single DB."""
    try:
        con = _open_ro(db)
        try:
            row = con.execute(
                "SELECT project_id, name, created_at, archived_at FROM projects LIMIT 1"
            ).fetchone()
            return dict(row) if row else None
        except sqlite3.OperationalError:
            return None
        finally:
            con.close()
    except sqlite3.DatabaseError:
        return None


def cmd_trajectory(args: argparse.Namespace) -> None:
    """Per-year manuscript counts by state."""
    cutoff = datetime.now(UTC) - timedelta(days=365 * args.years)
    by_year: dict[int, dict[str, int]] = defaultdict(
        lambda: {"drafted": 0, "audited": 0, "critiqued": 0, "revised": 0,
                 "submitted": 0, "published": 0, "total": 0}
    )

    for db in _project_dbs():
        try:
            con = _open_ro(db)
            try:
                rows = con.execute(
                    "SELECT state, created_at FROM artifact_index WHERE kind = 'manuscript'"
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
            finally:
                con.close()
            for r in rows:
                ts = r["created_at"]
                if not ts:
                    continue
                try:
                    dt = datetime.fromisoformat(ts)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=UTC)
                except ValueError:
                    continue
                if dt < cutoff:
                    continue
                year = dt.year
                state = r["state"]
                if state in by_year[year]:
                    by_year[year][state] += 1
                by_year[year]["total"] += 1
        except sqlite3.DatabaseError:
            continue

    years_sorted = sorted(by_year)
    print(json.dumps({
        "years_window": args.years,
        "by_year": [
            {"year": y, **by_year[y]} for y in years_sorted
        ],
        "total_manuscripts": sum(d["total"] for d in by_year.values()),
    }, indent=2))


def cmd_concepts(args: argparse.Namespace) -> None:
    """Concepts appearing in ≥N project graphs."""
    concept_to_projects: dict[str, set[str]] = defaultdict(set)
    for db in _project_dbs():
        meta = _get_project_meta(db)
        if not meta:
            continue
        try:
            con = _open_ro(db)
            try:
                rows = con.execute(
                    "SELECT label FROM graph_nodes WHERE kind = 'concept'"
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
            finally:
                con.close()
            for r in rows:
                if r["label"]:
                    concept_to_projects[r["label"]].add(meta["project_id"])
        except sqlite3.DatabaseError:
            continue

    out = []
    for concept, pids in concept_to_projects.items():
        if len(pids) >= args.min_projects:
            out.append({
                "concept": concept,
                "project_count": len(pids),
                "projects": sorted(pids),
            })
    out.sort(key=lambda x: -x["project_count"])
    print(json.dumps({
        "min_projects": args.min_projects,
        "shared_concepts": out,
        "total_shared": len(out),
    }, indent=2))


def cmd_productivity(args: argparse.Namespace) -> None:
    now = datetime.now(UTC)
    out = []
    for db in _project_dbs():
        meta = _get_project_meta(db)
        if not meta:
            continue
        if meta.get("archived_at") and not args.include_archived:
            continue

        try:
            con = _open_ro(db)
            try:
                rows = con.execute(
                    "SELECT kind, COUNT(*) AS c, MAX(updated_at) AS last_at "
                    "FROM artifact_index WHERE project_id = ? GROUP BY kind",
                    (meta["project_id"],),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
            finally:
                con.close()
        except sqlite3.DatabaseError:
            continue

        counts = {}
        latest: str | None = None
        for r in rows:
            counts[r["kind"]] = r["c"]
            la = r["last_at"]
            if la and (latest is None or la > latest):
                latest = la

        # Age + days-since-last-activity
        age_days = None
        try:
            cdt = datetime.fromisoformat(meta["created_at"])
            if cdt.tzinfo is None:
                cdt = cdt.replace(tzinfo=UTC)
            age_days = (now - cdt).days
        except (ValueError, KeyError, TypeError):
            pass

        days_since_last = None
        if latest:
            try:
                ldt = datetime.fromisoformat(latest)
                if ldt.tzinfo is None:
                    ldt = ldt.replace(tzinfo=UTC)
                days_since_last = (now - ldt).days
            except ValueError:
                pass

        out.append({
            "project_id": meta["project_id"],
            "name": meta.get("name"),
            "is_archived": bool(meta.get("archived_at")),
            "age_days": age_days,
            "days_since_last_activity": days_since_last,
            "artifact_counts": counts,
            "total_artifacts": sum(counts.values()),
        })

    out.sort(key=lambda x: -(x["total_artifacts"]))
    print(json.dumps({
        "projects": out,
        "total": len(out),
    }, indent=2))


def _read_active_project() -> str | None:
    p = cache_root() / "active_project.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text()).get("project_id")
    except (json.JSONDecodeError, OSError):
        return None


def _render_summary_md(data: dict) -> str:
    lines = ["# Meta-research Summary", ""]
    lines.append(f"**Active project:** `{data.get('active_project_id') or 'none'}`")
    lines.append("")
    lines.append("## Trajectory")
    lines.append("")
    lines.append("| Year | Total | Submitted | Published |")
    lines.append("|---|---|---|---|")
    for entry in data["trajectory"]["by_year"]:
        lines.append(
            f"| {entry['year']} | {entry['total']} | "
            f"{entry['submitted']} | {entry['published']} |"
        )
    lines.append("")
    lines.append(f"**Total manuscripts in window:** {data['trajectory']['total_manuscripts']}")
    lines.append("")
    lines.append("## Productivity")
    lines.append("")
    lines.append("| Project | Total Artifacts | Days since last |")
    lines.append("|---|---|---|")
    for p in data["productivity"]["projects"][:10]:
        ds = p["days_since_last_activity"]
        ds_str = f"{ds}" if ds is not None else "—"
        lines.append(f"| {p['name']} | {p['total_artifacts']} | {ds_str} |")
    lines.append("")
    lines.append("## Cross-project Concept Overlap")
    lines.append("")
    if data["concepts"]["total_shared"] == 0:
        lines.append("*No concepts shared across ≥2 projects.*")
    else:
        lines.append("| Concept | Project Count |")
        lines.append("|---|---|")
        for c in data["concepts"]["shared_concepts"][:20]:
            lines.append(f"| {c['concept']} | {c['project_count']} |")
    return "\n".join(lines)


def cmd_summary(args: argparse.Namespace) -> None:
    """Combined trajectory + concepts + productivity."""
    import io, contextlib
    # Trajectory
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cmd_trajectory(argparse.Namespace(years=args.years))
    trajectory = json.loads(buf.getvalue())

    # Concepts (default min 2)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cmd_concepts(argparse.Namespace(min_projects=2))
    concepts = json.loads(buf.getvalue())

    # Productivity (active only)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cmd_productivity(argparse.Namespace(include_archived=False))
    productivity = json.loads(buf.getvalue())

    summary = {
        "active_project_id": _read_active_project(),
        "trajectory": trajectory,
        "concepts": concepts,
        "productivity": productivity,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    if args.format == "md":
        print(_render_summary_md(summary))
    else:
        print(json.dumps(summary, indent=2))


def main() -> None:
    p = argparse.ArgumentParser(description="Cross-project research analytics (read-only).")
    sub = p.add_subparsers(dest="cmd", required=True)

    pt = sub.add_parser("trajectory")
    pt.add_argument("--years", type=int, default=5)
    pt.set_defaults(func=cmd_trajectory)

    pc = sub.add_parser("concepts")
    pc.add_argument("--min-projects", type=int, default=2)
    pc.set_defaults(func=cmd_concepts)

    pp = sub.add_parser("productivity")
    pp.add_argument("--include-archived", action="store_true", default=False)
    pp.set_defaults(func=cmd_productivity)

    ps = sub.add_parser("summary")
    ps.add_argument("--years", type=int, default=5)
    ps.add_argument("--format", default="json", choices=["json", "md"])
    ps.set_defaults(func=cmd_summary)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

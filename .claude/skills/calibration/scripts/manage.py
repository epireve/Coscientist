"""calibration skill CLI — per-venue reference set management.

Subcommands: init, add, remove, show, check, list.

Storage via lib.calibration; root via lib.cache.cache_root().
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Repo root on sys.path so `import lib...` works when invoked via `uv run`.
_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from lib import calibration as cal  # noqa: E402
from lib.cache import cache_root  # noqa: E402


def _root(args) -> Path:
    if getattr(args, "cache_root", None):
        return Path(args.cache_root).expanduser().resolve()
    return cache_root()


def cmd_init(args) -> int:
    root = _root(args)
    cset = cal.load(root, args.venue)
    path = cal.save(root, cset)
    print(json.dumps({
        "ok": True,
        "venue": cset.venue,
        "path": str(path),
        "n_total": cset.n_total(),
    }))
    return 0


def cmd_add(args) -> int:
    root = _root(args)
    cset = cal.load(root, args.venue)
    case = cal.CalibrationCase(
        title=args.title,
        canonical_id=args.canonical_id,
        doi=args.doi,
        year=args.year,
        reasons=list(args.reasons or []),
        notes=args.notes or "",
        outcome=args.outcome or "",
    )
    try:
        cal.add_case(cset, args.bucket, case)
    except ValueError as e:
        print(json.dumps({"ok": False, "error": str(e)}), file=sys.stderr)
        return 2
    path = cal.save(root, cset)
    print(json.dumps({
        "ok": True,
        "venue": cset.venue,
        "bucket": args.bucket,
        "path": str(path),
        "n_total": cset.n_total(),
    }))
    return 0


def cmd_remove(args) -> int:
    root = _root(args)
    cset = cal.load(root, args.venue)
    removed = cal.remove_case(
        cset, args.bucket,
        canonical_id=args.canonical_id,
        title=args.title,
    )
    if not removed:
        print(json.dumps({"ok": False, "error": "no matching case"}),
              file=sys.stderr)
        return 1
    path = cal.save(root, cset)
    print(json.dumps({
        "ok": True,
        "venue": cset.venue,
        "removed": True,
        "path": str(path),
        "n_total": cset.n_total(),
    }))
    return 0


def cmd_show(args) -> int:
    root = _root(args)
    cset = cal.load(root, args.venue)
    if args.format == "json":
        print(json.dumps(cset.to_dict(), indent=2, sort_keys=True))
    else:
        print(cal.render_summary(cset))
    return 0


def cmd_check(args) -> int:
    root = _root(args)
    cset = cal.load(root, args.venue)
    out = cal.coverage_check(cset)
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


def cmd_list(args) -> int:
    root = _root(args)
    d = cal.calibration_dir(root)
    venues = []
    for p in sorted(d.glob("*.json")):
        try:
            data = json.loads(p.read_text())
        except Exception:
            continue
        venues.append({
            "venue": data.get("venue", p.stem),
            "slug": p.stem,
            "path": str(p),
            "n_accepted": len(data.get("accepted") or []),
            "n_rejected": len(data.get("rejected") or []),
            "n_borderline": len(data.get("borderline") or []),
        })
    print(json.dumps(venues, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="manage.py")
    p.add_argument("--cache-root", help="Override cache root (testing).")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("init", help="Initialize venue (no-op if exists).")
    pi.add_argument("--venue", required=True)
    pi.set_defaults(func=cmd_init)

    pa = sub.add_parser("add", help="Add a case to a bucket.")
    pa.add_argument("--venue", required=True)
    pa.add_argument("--bucket", required=True,
                    choices=("accepted", "rejected", "borderline"))
    pa.add_argument("--title", required=True)
    pa.add_argument("--canonical-id", default=None)
    pa.add_argument("--doi", default=None)
    pa.add_argument("--year", type=int, default=None)
    pa.add_argument("--reasons", nargs="*", default=[],
                    help="Reasons (accepted/rejected only).")
    pa.add_argument("--outcome", default="",
                    help="Outcome string (borderline only).")
    pa.add_argument("--notes", default="",
                    help="Free-form notes (borderline only).")
    pa.set_defaults(func=cmd_add)

    pr = sub.add_parser("remove", help="Remove a case.")
    pr.add_argument("--venue", required=True)
    pr.add_argument("--bucket", required=True,
                    choices=("accepted", "rejected", "borderline"))
    pr.add_argument("--canonical-id", default=None)
    pr.add_argument("--title", default=None)
    pr.set_defaults(func=cmd_remove)

    ps = sub.add_parser("show", help="Render summary of a venue's set.")
    ps.add_argument("--venue", required=True)
    ps.add_argument("--format", choices=("md", "json"), default="md")
    ps.set_defaults(func=cmd_show)

    pc = sub.add_parser("check", help="Coverage health check.")
    pc.add_argument("--venue", required=True)
    pc.set_defaults(func=cmd_check)

    pl = sub.add_parser("list", help="List all venues with calibration sets.")
    pl.set_defaults(func=cmd_list)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

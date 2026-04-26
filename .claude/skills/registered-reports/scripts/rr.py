#!/usr/bin/env python3
"""registered-reports: Stage 1/Stage 2 RR pathway state tracking."""
from __future__ import annotations

import argparse, hashlib, json, re, sys
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import cache_root  # noqa: E402

STATES = [
    "stage-1-drafted", "stage-1-submitted", "in-principle-accepted",
    "data-collected", "stage-2-drafted", "stage-2-submitted", "published",
]


def _slug(t):
    t = t.lower().strip()
    t = re.sub(r"[^\w\s-]", "", t)
    t = re.sub(r"[\s_-]+", "_", t)
    return t[:40].strip("_")


def make_rr_id(title):
    h = hashlib.blake2s(title.encode(), digest_size=3).hexdigest()
    return f"{_slug(title)}_{h}"


def rr_dir(rr_id):
    return cache_root() / "registered_reports" / rr_id


def cmd_init(args):
    rr_id = make_rr_id(args.title)
    d = rr_dir(rr_id)
    if (d / "manifest.json").exists() and not args.force:
        raise SystemExit(f"RR {rr_id!r} already exists. Use --force.")
    d.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).isoformat()
    (d / "manifest.json").write_text(json.dumps({
        "rr_id": rr_id, "title": args.title, "journal": args.journal,
        "state": "stage-1-drafted", "created_at": now, "updated_at": now,
        "history": [{"state": "stage-1-drafted", "at": now}],
    }, indent=2))
    print(json.dumps({"rr_id": rr_id, "state": "stage-1-drafted", "path": str(d)}, indent=2))


def cmd_advance(args):
    if args.to_state not in STATES:
        raise SystemExit(f"--to-state must be one of {STATES}")
    d = rr_dir(args.rr_id)
    mp = d / "manifest.json"
    if not mp.exists():
        raise FileNotFoundError(f"RR {args.rr_id!r} not found")
    manifest = json.loads(mp.read_text())
    cur_idx = STATES.index(manifest["state"])
    new_idx = STATES.index(args.to_state)
    if new_idx < cur_idx and not args.force:
        raise SystemExit(
            f"backward transition {manifest['state']!r} → {args.to_state!r} blocked. Use --force."
        )
    if new_idx == cur_idx:
        raise SystemExit(f"already in state {args.to_state!r}")
    now = datetime.now(UTC).isoformat()
    manifest["state"] = args.to_state
    manifest["updated_at"] = now
    manifest["history"].append({"state": args.to_state, "at": now})
    mp.write_text(json.dumps(manifest, indent=2))
    print(json.dumps({"rr_id": args.rr_id, "state": args.to_state}, indent=2))


def cmd_status(args):
    d = rr_dir(args.rr_id)
    mp = d / "manifest.json"
    if not mp.exists():
        raise FileNotFoundError(f"RR {args.rr_id!r} not found")
    manifest = json.loads(mp.read_text())
    print(json.dumps(manifest, indent=2))


def cmd_list(args):
    base = cache_root() / "registered_reports"
    out = []
    if base.exists():
        for sub in sorted(base.iterdir()):
            mp = sub / "manifest.json"
            if mp.exists():
                m = json.loads(mp.read_text())
                out.append({"rr_id": m["rr_id"], "title": m["title"], "state": m["state"]})
    print(json.dumps({"rrs": out, "total": len(out)}, indent=2))


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    pi = sub.add_parser("init")
    pi.add_argument("--title", required=True)
    pi.add_argument("--journal", default=None)
    pi.add_argument("--force", action="store_true", default=False)
    pi.set_defaults(func=cmd_init)
    pa = sub.add_parser("advance")
    pa.add_argument("--rr-id", required=True)
    pa.add_argument("--to-state", required=True)
    pa.add_argument("--force", action="store_true", default=False)
    pa.set_defaults(func=cmd_advance)
    ps = sub.add_parser("status")
    ps.add_argument("--rr-id", required=True)
    ps.set_defaults(func=cmd_status)
    pl = sub.add_parser("list")
    pl.set_defaults(func=cmd_list)
    args = p.parse_args()
    try:
        args.func(args)
    except (FileNotFoundError, ValueError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""reference-agent: record retraction flags for papers.

Input: JSON list of {canonical_id, retracted, source, detail?}.
Writes into retraction_flags in the project DB.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import cache_root  # noqa: E402

VALID_SOURCES = {"semantic-scholar", "retraction-watch", "manual"}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--project-id", required=True)
    args = p.parse_args()

    items = json.loads(Path(args.input).read_text())
    if not isinstance(items, list):
        raise SystemExit("input must be a JSON array")

    db = cache_root() / "projects" / args.project_id / "project.db"
    if not db.exists():
        raise SystemExit(f"no project DB at {db}")
    con = sqlite3.connect(db)
    now = datetime.now(UTC).isoformat()
    new_flags = 0
    updated = 0
    errors: list[str] = []

    with con:
        for i, item in enumerate(items):
            cid = item.get("canonical_id")
            if not cid:
                errors.append(f"[{i}] missing canonical_id")
                continue
            source = item.get("source", "manual")
            if source not in VALID_SOURCES:
                errors.append(f"[{cid}] source {source!r} not in {sorted(VALID_SOURCES)}")
                continue
            retracted_val = 1 if item.get("retracted") else 0
            cur = con.execute(
                "INSERT INTO retraction_flags "
                "(canonical_id, retracted, source, detail, checked_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(canonical_id) DO UPDATE SET "
                "retracted=excluded.retracted, source=excluded.source, "
                "detail=excluded.detail, checked_at=excluded.checked_at",
                (cid, retracted_val, source, item.get("detail"), now),
            )
            if cur.rowcount == 1:
                new_flags += 1
            else:
                updated += 1
    con.close()

    if errors:
        print("[mark-retracted] errors:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(2)

    print(json.dumps({"new": new_flags, "updated": updated}))


if __name__ == "__main__":
    main()

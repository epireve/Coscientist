#!/usr/bin/env python3
"""paper-triage: record per-paper triage verdicts on the manifest.

Enforces: a paper cannot be marked `sufficient=true` without at least one of
{abstract, tldr, claims}. Prevents lazy "skip this" verdicts that would hide
missing data.
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

from lib.paper_artifact import PaperArtifact, State  # noqa: E402


def record_one(cid: str, sufficient: bool, rationale: str) -> None:
    art = PaperArtifact(cid)
    meta = art.load_metadata()
    if sufficient:
        if not meta or not (meta.abstract or meta.tldr or meta.claims):
            raise SystemExit(
                f"[{cid}] cannot mark sufficient=true: no abstract/tldr/claims in metadata. "
                "Fetch or override explicitly."
            )
    manifest = art.load_manifest()
    manifest.triage = {
        "sufficient": bool(sufficient),
        "rationale": rationale,
        "at": datetime.now(UTC).isoformat(),
    }
    manifest.state = State.triaged
    art.save_manifest(manifest)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--canonical-id")
    p.add_argument("--sufficient", choices=["true", "false"])
    p.add_argument("--rationale", default="")
    p.add_argument("--batch", help="JSON file with a list of verdicts")
    args = p.parse_args()

    if args.batch:
        items = json.loads(Path(args.batch).read_text())
        for item in items:
            record_one(
                item["canonical_id"],
                bool(item["sufficient"]),
                item.get("rationale", ""),
            )
    else:
        if not args.canonical_id or args.sufficient is None:
            raise SystemExit("--canonical-id and --sufficient required (or use --batch)")
        record_one(args.canonical_id, args.sufficient == "true", args.rationale)

    # Print insufficient papers for downstream piping
    # (only meaningful for --batch; for single, print this cid if insufficient)
    if args.batch:
        for item in json.loads(Path(args.batch).read_text()):
            if not item["sufficient"]:
                print(item["canonical_id"])
    elif args.sufficient == "false":
        print(args.canonical_id)


if __name__ == "__main__":
    main()

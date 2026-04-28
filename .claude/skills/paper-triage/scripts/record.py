#!/usr/bin/env python3
"""paper-triage: record per-paper triage verdicts on the manifest.

Enforces:
- A paper cannot be marked `sufficient=true` without at least one of
  {abstract, tldr, claims}. Prevents lazy "skip this" verdicts that would
  hide missing data.
- v0.17: state monotonicity. Re-triaging a paper that has already moved
  past `triaged` (acquired / extracted / read / cited) refuses by
  default — silently demoting state was a real bug surfaced by the
  per-paper state-machine harness. Pass `--force` if you really mean to
  reset (e.g. corrupted PDF needs a re-fetch decision).
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

from lib.lockfile import artifact_lock  # noqa: E402  v0.14
from lib.paper_artifact import PaperArtifact, State  # noqa: E402

_DOWNSTREAM_STATES = {
    State.acquired, State.extracted, State.read, State.cited,
}


def record_one(cid: str, sufficient: bool, rationale: str,
               force: bool = False) -> None:
    art = PaperArtifact(cid)
    # v0.14: serialize against concurrent paper-acquire / paper-discovery
    # writes on the same paper artifact.
    with artifact_lock(art.root, timeout=30.0):
        meta = art.load_metadata()
        if sufficient:
            if not meta or not (meta.abstract or meta.tldr or meta.claims):
                raise SystemExit(
                    f"[{cid}] cannot mark sufficient=true: no abstract/tldr/claims in metadata. "
                    "Fetch or override explicitly."
                )
        manifest = art.load_manifest()
        # v0.17: refuse to silently demote state from acquired/extracted/...
        # back to triaged. Re-running triage on a paper that's already
        # downstream is almost always an orchestrator bug.
        if manifest.state in _DOWNSTREAM_STATES and not force:
            raise SystemExit(
                f"[{cid}] refusing to re-triage: state is "
                f"{manifest.state.value!r}. Re-triaging would silently "
                "demote progress. Pass --force if you really mean to reset."
            )
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
    p.add_argument("--force", action="store_true",
                   help="Allow re-triage even when state is past triaged")
    args = p.parse_args()

    if args.batch:
        items = json.loads(Path(args.batch).read_text())
        for item in items:
            record_one(
                item["canonical_id"],
                bool(item["sufficient"]),
                item.get("rationale", ""),
                force=bool(item.get("force", args.force)),
            )
    else:
        if not args.canonical_id or args.sufficient is None:
            raise SystemExit("--canonical-id and --sufficient required (or use --batch)")
        record_one(args.canonical_id, args.sufficient == "true",
                   args.rationale, force=args.force)

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

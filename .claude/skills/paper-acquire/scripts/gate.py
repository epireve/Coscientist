#!/usr/bin/env python3
"""paper-acquire gate: enforce triage verdict before any fetch.

Non-negotiable. Callers run this first; on exit 0, acquisition may proceed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.paper_artifact import PaperArtifact  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--canonical-id", required=True)
    args = p.parse_args()

    art = PaperArtifact(args.canonical_id)
    manifest = art.load_manifest()
    triage = manifest.triage or {}

    if triage.get("sufficient") is None:
        print(f"[gate] {args.canonical_id}: no triage verdict — run paper-triage first", file=sys.stderr)
        sys.exit(2)
    if triage.get("sufficient") is True:
        print(
            f"[gate] {args.canonical_id}: triage marked sufficient=true — fetch forbidden",
            file=sys.stderr,
        )
        sys.exit(3)

    # approved
    sys.exit(0)


if __name__ == "__main__":
    main()

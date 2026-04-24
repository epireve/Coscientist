#!/usr/bin/env python3
"""writing-style: paragraph-level style critique for drafting-time feedback.

Reads a paragraph from stdin, emits JSON deviations against the project
profile. Designed to be called inline while drafting.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import cache_root  # noqa: E402

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
from audit import analyze  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--project-id", required=True)
    p.add_argument("--text", default=None,
                   help="Inline text (else read stdin)")
    args = p.parse_args()

    profile_path = cache_root() / "projects" / args.project_id / "style_profile.json"
    if not profile_path.exists():
        raise SystemExit(f"no style profile at {profile_path}")

    text = args.text if args.text is not None else sys.stdin.read()
    if not text.strip():
        raise SystemExit("empty input")

    profile = json.loads(profile_path.read_text())
    findings = analyze(text, profile)
    print(json.dumps({"findings": findings}, indent=2))


if __name__ == "__main__":
    main()

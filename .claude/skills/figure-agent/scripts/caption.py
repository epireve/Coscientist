#!/usr/bin/env python3
"""Update or set a figure caption."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import cache_root  # noqa


def update_caption(mid: str, fig_id: str, caption: str) -> dict:
    fig_dir = cache_root() / "manuscripts" / mid / "figures" / fig_id
    mp = fig_dir / "manifest.json"
    if not mp.exists():
        raise FileNotFoundError(f"Figure {fig_id} not found under manuscript {mid}")
    manifest = json.loads(mp.read_text())
    manifest["caption"] = caption
    mp.write_text(json.dumps(manifest, indent=2))
    return {"fig_id": fig_id, "mid": mid, "caption": caption, "updated": True}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--mid", required=True)
    p.add_argument("--fig-id", required=True)
    p.add_argument("--caption", required=True)
    args = p.parse_args()
    try:
        result = update_caption(args.mid, args.fig_id, args.caption)
        print(json.dumps(result, indent=2))
    except FileNotFoundError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()

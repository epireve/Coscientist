#!/usr/bin/env python3
"""Register a figure with a manuscript."""
from __future__ import annotations
import argparse, json, sys
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import cache_root  # noqa


def figure_dir(mid: str, fig_id: str) -> Path:
    return cache_root() / "manuscripts" / mid / "figures" / fig_id


def register(mid: str, fig_id: str, path: str | None, caption: str,
             label: str | None, overwrite: bool = False) -> dict:
    fig_dir = figure_dir(mid, fig_id)
    manifest_path = fig_dir / "manifest.json"
    if manifest_path.exists() and not overwrite:
        raise FileExistsError(
            f"Figure {fig_id} already registered under {mid}. Use --overwrite to replace."
        )
    fig_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "fig_id": fig_id,
        "mid": mid,
        "path": path,
        "caption": caption,
        "label": label,
        "registered_at": datetime.now(UTC).isoformat(),
        "state": "registered",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return manifest


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--mid", required=True)
    p.add_argument("--fig-id", required=True)
    p.add_argument("--path", default=None)
    p.add_argument("--caption", required=True)
    p.add_argument("--label", default=None)
    p.add_argument("--overwrite", action="store_true", default=False)
    args = p.parse_args()
    try:
        result = register(args.mid, args.fig_id, args.path, args.caption,
                          args.label, args.overwrite)
        print(json.dumps(result, indent=2))
    except FileExistsError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""List all figures for a manuscript."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import cache_root  # noqa


def list_figures(mid: str) -> list[dict]:
    base = cache_root() / "manuscripts" / mid / "figures"
    if not base.exists():
        return []
    results = []
    for fig_dir in sorted(base.iterdir()):
        if not fig_dir.is_dir():
            continue
        mp = fig_dir / "manifest.json"
        if mp.exists():
            results.append(json.loads(mp.read_text()))
    return results


def _render_table(figures: list[dict]) -> str:
    if not figures:
        return "No figures registered."
    header = f"{'fig_id':<20} {'label':<15} {'caption (preview)':<40}"
    rows = [header, "-" * len(header)]
    for f in figures:
        cap = (f.get("caption") or "")[:38]
        rows.append(f"{f.get('fig_id',''):<20} {f.get('label',''):<15} {cap:<40}")
    return "\n".join(rows)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--mid", required=True)
    p.add_argument("--format", default="json", choices=["json", "table"])
    args = p.parse_args()
    figures = list_figures(args.mid)
    if args.format == "table":
        print(_render_table(figures))
    else:
        print(json.dumps(figures, indent=2))

if __name__ == "__main__":
    main()

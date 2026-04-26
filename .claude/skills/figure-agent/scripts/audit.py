#!/usr/bin/env python3
"""Audit all figures in a manuscript."""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import cache_root  # noqa

RESULT_WORDS = {"show", "shows", "depict", "depicts", "illustrate", "illustrates",
                "compare", "compares", "display", "displays", "present", "presents",
                "demonstrate", "demonstrates", "plot", "plots", "highlight", "highlights"}

MIN_CAPTION_WORDS = 10


def _fig_dirs(mid: str) -> list[Path]:
    base = cache_root() / "manuscripts" / mid / "figures"
    if not base.exists():
        return []
    return sorted(p for p in base.iterdir() if p.is_dir())


def _load_manifest(fig_dir: Path) -> dict:
    mp = fig_dir / "manifest.json"
    if not mp.exists():
        return {}
    return json.loads(mp.read_text())


def _check_caption(caption: str | None) -> list[str]:
    issues = []
    if not caption:
        issues.append("missing_caption")
        return issues
    words = caption.lower().split()
    if len(words) < MIN_CAPTION_WORDS:
        issues.append(f"caption_too_short ({len(words)} words, min {MIN_CAPTION_WORDS})")
    if not RESULT_WORDS.intersection(set(words)):
        issues.append("caption_lacks_result_verb")
    return issues


def _check_crossref(mid: str, fig_id: str, label: str | None) -> list[str]:
    """Check if figure is cross-referenced in manuscript body."""
    issues = []
    if label is None:
        issues.append("no_label_set")
        return issues
    ms_dir = cache_root() / "manuscripts" / mid
    # Look for content.md or draft.md
    body_files = list(ms_dir.glob("*.md")) + list(ms_dir.glob("*.tex"))
    if not body_files:
        return []  # No body to check — skip
    found = False
    pattern_latex = re.compile(r"\\ref\{fig:" + re.escape(label) + r"\}")
    pattern_word = re.compile(r"\b" + re.escape(label) + r"\b")
    for bf in body_files:
        text = bf.read_text(errors="replace")
        if pattern_latex.search(text) or pattern_word.search(text):
            found = True
            break
    if not found:
        issues.append(f"not_cross_referenced (label={label!r} not found in manuscript body)")
    return issues


def audit(mid: str) -> dict:
    fig_dirs = _fig_dirs(mid)
    if not fig_dirs:
        return {"mid": mid, "figures": [], "total": 0, "issues": 0}
    results = []
    for fd in fig_dirs:
        m = _load_manifest(fd)
        if not m:
            continue
        fid = m.get("fig_id", fd.name)
        caption_issues = _check_caption(m.get("caption"))
        crossref_issues = _check_crossref(mid, fid, m.get("label"))
        all_issues = caption_issues + crossref_issues
        results.append({
            "fig_id": fid,
            "label": m.get("label"),
            "caption_preview": (m.get("caption") or "")[:60],
            "issues": all_issues,
            "status": "fail" if all_issues else "pass",
        })
    total_issues = sum(len(r["issues"]) for r in results)
    return {
        "mid": mid,
        "figures": results,
        "total": len(results),
        "issues": total_issues,
        "status": "fail" if total_issues else "pass",
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--mid", required=True)
    args = p.parse_args()
    print(json.dumps(audit(args.mid), indent=2))

if __name__ == "__main__":
    main()

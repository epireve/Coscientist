#!/usr/bin/env python3
"""peer-review: show round history and current state."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import cache_root  # noqa


def review_dir(mid: str) -> Path:
    return cache_root() / "manuscripts" / mid / "peer_review"

def round_dir(mid: str, round_num: int) -> Path:
    return review_dir(mid) / f"round_{round_num}"

def _state_path(mid: str) -> Path:
    return review_dir(mid) / "state.json"


def get_status(mid: str) -> dict:
    sp = _state_path(mid)
    if not sp.exists():
        return {"mid": mid, "state": "pending", "current_round": 0, "rounds": [], "history": []}
    state = json.loads(sp.read_text())
    history = []
    for r in state.get("rounds", []):
        rd = round_dir(mid, r)
        entry = {"round": r, "has_review": (rd / "review.json").exists(),
                 "has_response": (rd / "response.json").exists()}
        if entry["has_review"]:
            rev = json.loads((rd / "review.json").read_text())
            entry["decision"] = rev.get("decision")
            entry["venue"] = rev.get("venue")
        history.append(entry)
    decision_path = review_dir(mid) / "decision.json"
    state["history"] = history
    state["final_decision_written"] = decision_path.exists()
    return state


def _render_table(status: dict) -> str:
    lines = [
        f"Manuscript: {status['mid']}",
        f"State: {status['state']}  |  Round: {status['current_round']}",
        "",
    ]
    if status["history"]:
        lines.append(f"{'Round':<8} {'Venue':<12} {'Decision':<18} {'Review':<8} {'Response'}")
        lines.append("-" * 60)
        for h in status["history"]:
            lines.append(
                f"{h['round']:<8} {h.get('venue',''):<12} {h.get('decision',''):<18} "
                f"{'yes':<8} {'yes' if h['has_response'] else 'no'}"
            )
    else:
        lines.append("No rounds recorded.")
    if status.get("final_decision_written"):
        lines.append(f"\nFinal decision: {status.get('final_decision', 'see decision.json')}")
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--mid", required=True)
    p.add_argument("--format", default="json", choices=["json", "table"])
    args = p.parse_args()
    status = get_status(args.mid)
    if args.format == "table":
        print(_render_table(status))
    else:
        print(json.dumps(status, indent=2))


if __name__ == "__main__":
    main()

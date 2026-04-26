#!/usr/bin/env python3
"""peer-review: generate final editorial decision."""
from __future__ import annotations
import argparse, json, sys
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import cache_root  # noqa

DECISIONS = {"accept", "reject", "major_revision", "minor_revision"}


def review_dir(mid: str) -> Path:
    return cache_root() / "manuscripts" / mid / "peer_review"

def round_dir(mid: str, round_num: int) -> Path:
    return review_dir(mid) / f"round_{round_num}"

def _state_path(mid: str) -> Path:
    return review_dir(mid) / "state.json"

def load_state(mid: str) -> dict:
    sp = _state_path(mid)
    if not sp.exists():
        return {"mid": mid, "state": "pending", "current_round": 0, "rounds": []}
    return json.loads(sp.read_text())

def save_state(mid: str, state: dict) -> None:
    _state_path(mid).parent.mkdir(parents=True, exist_ok=True)
    _state_path(mid).write_text(json.dumps(state, indent=2))


def _load_all_rounds(mid: str, rounds: list[int]) -> list[dict]:
    history = []
    for r in rounds:
        rd = round_dir(mid, r)
        review_path = rd / "review.json"
        response_path = rd / "response.json"
        entry = {"round": r}
        if review_path.exists():
            entry["review"] = json.loads(review_path.read_text())
        if response_path.exists():
            entry["response"] = json.loads(response_path.read_text())
        history.append(entry)
    return history


def make_decision(mid: str, final_decision: str, rationale: str) -> dict:
    if final_decision not in DECISIONS:
        raise ValueError(f"decision must be one of {sorted(DECISIONS)}")

    state = load_state(mid)
    if state["state"] == "pending":
        raise ValueError("No reviews recorded yet. Run review.py first.")

    history = _load_all_rounds(mid, state.get("rounds", []))
    decision = {
        "mid": mid,
        "decided_at": datetime.now(UTC).isoformat(),
        "final_decision": final_decision,
        "rationale": rationale,
        "n_rounds": len(state.get("rounds", [])),
        "round_history": history,
    }
    decision_path = review_dir(mid) / "decision.json"
    decision_path.write_text(json.dumps(decision, indent=2))

    state["state"] = "decided"
    state["final_decision"] = final_decision
    save_state(mid, state)
    return decision


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--mid", required=True)
    p.add_argument("--decision", required=True, choices=sorted(DECISIONS))
    p.add_argument("--rationale", required=True)
    args = p.parse_args()

    try:
        result = make_decision(args.mid, args.decision, args.rationale)
        print(json.dumps(result, indent=2))
    except (ValueError, FileNotFoundError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

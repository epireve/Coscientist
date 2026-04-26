#!/usr/bin/env python3
"""peer-review: record author response to reviewer comments."""
from __future__ import annotations
import argparse, json, sys
from datetime import UTC, datetime
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

def load_state(mid: str) -> dict:
    sp = _state_path(mid)
    if not sp.exists():
        return {"mid": mid, "state": "pending", "current_round": 0, "rounds": []}
    return json.loads(sp.read_text())

def save_state(mid: str, state: dict) -> None:
    _state_path(mid).parent.mkdir(parents=True, exist_ok=True)
    _state_path(mid).write_text(json.dumps(state, indent=2))


def record_response(mid: str, round_num: int, response_data: dict) -> dict:
    rd = round_dir(mid, round_num)
    review_path = rd / "review.json"
    if not review_path.exists():
        raise FileNotFoundError(
            f"No review found for round {round_num}. Run review.py first."
        )
    response_path = rd / "response.json"
    response = {
        "mid": mid,
        "round": round_num,
        "responded_at": datetime.now(UTC).isoformat(),
        "responses": response_data.get("responses", []),
        "cover_letter": response_data.get("cover_letter", ""),
        "changes_summary": response_data.get("changes_summary", ""),
    }
    response_path.write_text(json.dumps(response, indent=2))

    state = load_state(mid)
    state["state"] = "responded"
    save_state(mid, state)
    return response


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--mid", required=True)
    p.add_argument("--round", type=int, required=True)
    p.add_argument("--response-file", required=True,
                   help="JSON file with {responses: [], cover_letter: str, changes_summary: str}")
    args = p.parse_args()

    resp_path = Path(args.response_file)
    if not resp_path.exists():
        print(json.dumps({"error": f"response file not found: {resp_path}"}), file=sys.stderr)
        sys.exit(1)

    response_data = json.loads(resp_path.read_text())
    try:
        result = record_response(args.mid, args.round, response_data)
        print(json.dumps(result, indent=2))
    except FileNotFoundError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""peer-review: generate a structured reviewer report."""
from __future__ import annotations
import argparse, json, sys
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import cache_root  # noqa

VALID_RECOMMENDATIONS = {"major_revision", "minor_revision", "accept", "reject"}
VALID_VENUES = {"neurips", "acl", "nature", "science", "plos_one", "arxiv", "generic"}


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


def generate_review(mid: str, venue: str, round_num: int,
                    manuscript_text: str | None = None) -> dict:
    rd = round_dir(mid, round_num)
    review_path = rd / "review.json"
    if review_path.exists():
        raise FileExistsError(
            f"Review for round {round_num} already exists. Use a higher round number."
        )
    rd.mkdir(parents=True, exist_ok=True)

    # Venue-specific reviewer count and stringency
    n_reviewers = 3 if venue in {"neurips", "acl", "nature", "science"} else 2
    venue_label = venue.replace("_", " ").title()

    reviewers = []
    for i in range(1, n_reviewers + 1):
        reviewers.append({
            "id": f"R{i}",
            "recommendation": "major_revision",
            "summary": f"[Reviewer {i} summary — to be filled by manuscript-critique sub-agent]",
            "strengths": ["[strength 1]", "[strength 2]"],
            "weaknesses": ["[weakness 1]", "[weakness 2]"],
            "required_changes": ["[required change 1]"],
            "optional_changes": ["[optional change 1]"],
        })

    report = {
        "mid": mid,
        "venue": venue,
        "venue_label": venue_label,
        "round": round_num,
        "generated_at": datetime.now(UTC).isoformat(),
        "reviewers": reviewers,
        "meta_review": f"[Area chair meta-review for {venue_label} round {round_num}]",
        "decision": "major_revision",
        "n_reviewers": n_reviewers,
    }
    review_path.write_text(json.dumps(report, indent=2))

    state = load_state(mid)
    state["state"] = "reviewed"
    state["current_round"] = round_num
    if round_num not in state.get("rounds", []):
        state.setdefault("rounds", []).append(round_num)
    save_state(mid, state)
    return report


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--mid", required=True)
    p.add_argument("--venue", required=True, choices=sorted(VALID_VENUES))
    p.add_argument("--round", type=int, default=None)
    args = p.parse_args()

    state = load_state(args.mid)
    round_num = args.round if args.round is not None else state["current_round"] + 1

    try:
        report = generate_review(args.mid, args.venue, round_num)
        print(json.dumps(report, indent=2))
    except FileExistsError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

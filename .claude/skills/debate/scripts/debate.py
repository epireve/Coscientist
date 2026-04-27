#!/usr/bin/env python3
"""debate CLI — init + finalize a self-play debate."""
from __future__ import annotations

import argparse
import json
import secrets
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_PLUGIN_ROOT = _HERE.parents[3]
_REPO_ROOT = (
    _HERE.parents[4] if (_HERE.parents[4] / "lib").exists()
    else _PLUGIN_ROOT
)
for _p in (_REPO_ROOT, _PLUGIN_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from lib.cache import cache_root  # noqa: E402
from lib.debate import (  # noqa: E402
    DebateSpec, JudgeRuling, Position, Scores,
    decide_verdict, render_brief, render_con_prompt,
    render_judge_prompt, render_pro_prompt, score_position,
)


def _debate_dir(run_id: str | None, debate_id: str) -> Path:
    if run_id:
        d = cache_root() / "runs" / f"run-{run_id}" / "debates" / debate_id
    else:
        d = cache_root() / "debates" / debate_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def cmd_init(args: argparse.Namespace) -> dict:
    debate_id = args.debate_id or f"deb-{secrets.token_hex(4)}"
    spec = DebateSpec(
        topic=args.topic,
        target_id=args.target_id,
        target_claim=args.target_claim,
        min_anchors_per_side=args.min_anchors,
        n_rounds=args.n_rounds,
    )
    d = _debate_dir(args.run_id, debate_id)
    (d / "spec.json").write_text(
        json.dumps(spec.to_dict(), indent=2, sort_keys=True)
    )
    (d / "pro_prompt.md").write_text(render_pro_prompt(spec))
    (d / "con_prompt.md").write_text(render_con_prompt(spec))
    return {
        "debate_id": debate_id,
        "topic": spec.topic,
        "spec_path": str(d / "spec.json"),
        "pro_prompt_path": str(d / "pro_prompt.md"),
        "con_prompt_path": str(d / "con_prompt.md"),
        "next_step": (
            "Dispatch debate-pro and debate-con sub-agents in a single "
            "parallel message. Each returns JSON; save to pro.json / "
            "con.json under the debate dir, then dispatch debate-judge."
        ),
    }


def cmd_judge_prompt(args: argparse.Namespace) -> dict:
    """Render the judge prompt now that pro+con are in."""
    d = _debate_dir(args.run_id, args.debate_id)
    spec = DebateSpec(**json.loads((d / "spec.json").read_text()))
    pro = Position.from_dict(json.loads((d / "pro.json").read_text()))
    con = Position.from_dict(json.loads((d / "con.json").read_text()))
    out = render_judge_prompt(spec, pro, con)
    (d / "judge_prompt.md").write_text(out)
    return {
        "debate_id": args.debate_id,
        "judge_prompt_path": str(d / "judge_prompt.md"),
    }


def cmd_finalize(args: argparse.Namespace) -> dict:
    """Compute mechanical scores, validate judge ruling, write transcript."""
    d = _debate_dir(args.run_id, args.debate_id)
    spec = DebateSpec(**json.loads((d / "spec.json").read_text()))
    pro = Position.from_dict(json.loads((d / "pro.json").read_text()))
    con = Position.from_dict(json.loads((d / "con.json").read_text()))
    judge_raw = json.loads((d / "judge.json").read_text())

    # Validate canonical_ids if given
    valid_cids: set[str] | None = None
    if args.valid_cids:
        valid_cids = set(json.loads(Path(args.valid_cids).read_text()))

    # Mechanical scoring (cross-check)
    pro_mech = score_position(
        pro, other_statement=con.statement,
        valid_canonical_ids=valid_cids,
        min_anchors=spec.min_anchors_per_side,
    )
    con_mech = score_position(
        con, other_statement=pro.statement,
        valid_canonical_ids=valid_cids,
        min_anchors=spec.min_anchors_per_side,
    )

    judge_pro = Scores(**{
        k: float(v) for k, v in judge_raw.get("pro_scores", {}).items()
        if k in ("evidence_groundedness", "argument_specificity",
                  "rebuttal_responsiveness", "falsifiability")
    })
    judge_con = Scores(**{
        k: float(v) for k, v in judge_raw.get("con_scores", {}).items()
        if k in ("evidence_groundedness", "argument_specificity",
                  "rebuttal_responsiveness", "falsifiability")
    })

    # Mechanical-judge sanity check
    drift_pro = abs(judge_pro.mean() - pro_mech.mean())
    drift_con = abs(judge_con.mean() - con_mech.mean())
    sanity_warning = None
    if drift_pro > args.drift_threshold or drift_con > args.drift_threshold:
        sanity_warning = (
            f"judge scores drift from mechanical by "
            f"pro={drift_pro:.2f}, con={drift_con:.2f} "
            f"(>{args.drift_threshold:.2f})"
        )

    declared_verdict = judge_raw.get("verdict", "draw")
    derived_verdict, delta = decide_verdict(judge_pro, judge_con)
    # If declared verdict disagrees with derived, prefer derived but flag
    if declared_verdict != derived_verdict:
        sanity_warning = (
            (sanity_warning + "; " if sanity_warning else "")
            + f"declared verdict {declared_verdict!r} != derived "
            f"{derived_verdict!r}"
        )

    ruling = JudgeRuling(
        verdict=derived_verdict,
        reasoning=judge_raw.get("reasoning", ""),
        kill_criterion=judge_raw.get("kill_criterion", ""),
        pro_scores=judge_pro,
        con_scores=judge_con,
        delta=delta,
    )

    transcript = render_brief(spec, pro, con, ruling)
    (d / "transcript.md").write_text(transcript)

    payload = {
        "debate_id": args.debate_id,
        "verdict": ruling.verdict,
        "delta": round(delta, 3),
        "kill_criterion": ruling.kill_criterion,
        "transcript_path": str(d / "transcript.md"),
        "mechanical_pro_mean": round(pro_mech.mean(), 3),
        "mechanical_con_mean": round(con_mech.mean(), 3),
        "judge_pro_mean": round(judge_pro.mean(), 3),
        "judge_con_mean": round(judge_con.mean(), 3),
    }
    if sanity_warning:
        payload["sanity_warning"] = sanity_warning
    return payload


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("init")
    pi.add_argument("--topic", required=True,
                     choices=["novelty", "publishability", "red-team"])
    pi.add_argument("--target-id", required=True)
    pi.add_argument("--target-claim", required=True)
    pi.add_argument("--min-anchors", type=int, default=3)
    pi.add_argument("--n-rounds", type=int, default=2)
    pi.add_argument("--debate-id", default=None)
    pi.add_argument("--run-id", default=None,
                     help="If set, persist under runs/run-<rid>/debates/")
    pi.set_defaults(func=cmd_init)

    pj = sub.add_parser("judge-prompt")
    pj.add_argument("--debate-id", required=True)
    pj.add_argument("--run-id", default=None)
    pj.set_defaults(func=cmd_judge_prompt)

    pf = sub.add_parser("finalize")
    pf.add_argument("--debate-id", required=True)
    pf.add_argument("--run-id", default=None)
    pf.add_argument("--valid-cids", default=None,
                     help="Path to JSON list of valid canonical_ids")
    pf.add_argument("--drift-threshold", type=float, default=0.2,
                     help="Max acceptable drift between judge scores "
                          "and mechanical scores")
    pf.set_defaults(func=cmd_finalize)

    args = p.parse_args()
    out = args.func(args)
    sys.stdout.write(json.dumps(out, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()

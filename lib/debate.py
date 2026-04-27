"""Self-play debate (v0.56, A5 capstone).

Two instances argue opposing sides of a verdict. A judge scores
argument quality + evidence grounding and picks a winner. Used to
sharpen high-stakes verdicts where a single-pass model is prone to
sycophancy or status-quo bias.

This module is the contract + scoring + orchestration template. The
actual LLM calls happen in the calling agent (orchestrator dispatches
PRO + CON + JUDGE as separate sub-agents). Lib here is pure stdlib —
the deterministic spine.

Three verdict topics supported:
  - novelty           (PRO: "this is novel"; CON: "already known")
  - publishability    (PRO: "publishable at tier X"; CON: "below bar")
  - red-team          (PRO: "no fatal flaw"; CON: "fatal flaw exists")

Each side must produce:
  - position           one-paragraph statement
  - evidence_anchors   list of {canonical_id, claim_quote, why_relevant}
                       — minimum N anchors per side (default 3)
  - rebuttal_to_other  one-paragraph response to the other side's
                       opening position (empty in round 1)

Judge scores both sides on 4 axes (each 0..1):
  - evidence_groundedness  proportion of anchors that resolve to
                           real canonical_ids in the run/manuscript
  - argument_specificity   penalty for vague phrases; reward for
                           concrete experiments / numbers / cites
  - rebuttal_responsiveness  did rebuttal address the other's claim?
  - falsifiability         did side declare what would change verdict?

Final verdict = side with higher mean score, OR 'draw' if delta <
0.05. Judge also writes a short reasoning paragraph + a kill_criterion
(specific observation that would flip the verdict).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Literal


Topic = Literal["novelty", "publishability", "red-team"]
Side = Literal["pro", "con"]
Verdict = Literal["pro", "con", "draw"]


# Hedge / vagueness phrases penalized in argument_specificity
_HEDGE_PHRASES = (
    "may", "might", "could potentially", "seems to", "appears to",
    "broadly", "generally", "interestingly", "in some sense",
    "arguably", "it is possible", "perhaps", "somewhat",
)
# Specificity-positive signals
_CONCRETE_SIGNALS = (
    r"\b\d+\s*%", r"\bp\s*[<>=]\s*0?\.\d+", r"\bn\s*=\s*\d+",
    r"\bfig(?:ure)?\.\s*\d+", r"\btable\s*\d+", r"\b(?:cited|see)\s+\[",
    r"\bexperiment(s)?\b", r"\bablation\b", r"\bsample size\b",
)


@dataclass
class EvidenceAnchor:
    canonical_id: str
    claim_quote: str
    why_relevant: str

    def to_dict(self) -> dict:
        return {
            "canonical_id": self.canonical_id,
            "claim_quote": self.claim_quote,
            "why_relevant": self.why_relevant,
        }


@dataclass
class Position:
    side: Side
    statement: str
    evidence_anchors: list[EvidenceAnchor] = field(default_factory=list)
    rebuttal_to_other: str = ""

    def to_dict(self) -> dict:
        return {
            "side": self.side,
            "statement": self.statement,
            "evidence_anchors": [a.to_dict() for a in self.evidence_anchors],
            "rebuttal_to_other": self.rebuttal_to_other,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Position":
        return cls(
            side=d["side"],
            statement=d.get("statement", ""),
            evidence_anchors=[
                EvidenceAnchor(**a) for a in d.get("evidence_anchors", []) or []
            ],
            rebuttal_to_other=d.get("rebuttal_to_other", ""),
        )


@dataclass
class Scores:
    evidence_groundedness: float
    argument_specificity: float
    rebuttal_responsiveness: float
    falsifiability: float

    def mean(self) -> float:
        return (
            self.evidence_groundedness + self.argument_specificity
            + self.rebuttal_responsiveness + self.falsifiability
        ) / 4.0

    def to_dict(self) -> dict:
        return {
            "evidence_groundedness": round(self.evidence_groundedness, 3),
            "argument_specificity": round(self.argument_specificity, 3),
            "rebuttal_responsiveness": round(self.rebuttal_responsiveness, 3),
            "falsifiability": round(self.falsifiability, 3),
            "mean": round(self.mean(), 3),
        }


@dataclass
class JudgeRuling:
    verdict: Verdict
    reasoning: str
    kill_criterion: str
    pro_scores: Scores
    con_scores: Scores
    delta: float

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "reasoning": self.reasoning,
            "kill_criterion": self.kill_criterion,
            "pro_scores": self.pro_scores.to_dict(),
            "con_scores": self.con_scores.to_dict(),
            "delta": round(self.delta, 3),
        }


@dataclass
class DebateSpec:
    """Contract handed to PRO/CON/JUDGE sub-agents."""
    topic: Topic
    target_id: str           # paper canonical_id or manuscript_id
    target_claim: str        # the verdict-statement under debate
    min_anchors_per_side: int = 3
    n_rounds: int = 2        # opening + rebuttal

    def to_dict(self) -> dict:
        return {
            "topic": self.topic,
            "target_id": self.target_id,
            "target_claim": self.target_claim,
            "min_anchors_per_side": self.min_anchors_per_side,
            "n_rounds": self.n_rounds,
        }


# ---------- prompt templates ----------

def render_pro_prompt(spec: DebateSpec) -> str:
    """Prompt for the PRO instance."""
    side_text = {
        "novelty": "the contribution IS novel and not already known",
        "publishability": (
            "this work IS publishable at the declared target tier"
        ),
        "red-team": "this work has NO fatal methodological flaw",
    }[spec.topic]
    return _render_template(spec, "PRO", side_text)


def render_con_prompt(spec: DebateSpec) -> str:
    """Prompt for the CON instance."""
    side_text = {
        "novelty": "the contribution is NOT novel — close prior work exists",
        "publishability": (
            "this work is NOT yet at the declared target tier"
        ),
        "red-team": "this work HAS a fatal methodological flaw",
    }[spec.topic]
    return _render_template(spec, "CON", side_text)


def render_judge_prompt(
    spec: DebateSpec, pro: Position, con: Position,
) -> str:
    """Prompt for the JUDGE instance."""
    return f"""You are the JUDGE in a self-play debate on {spec.topic}.

## Target
{spec.target_claim}
(target_id: {spec.target_id})

## PRO position (argues FOR the target claim)
{pro.statement}

### PRO evidence
{_format_anchors(pro.evidence_anchors)}

### PRO rebuttal to CON
{pro.rebuttal_to_other or "(none)"}

## CON position (argues AGAINST)
{con.statement}

### CON evidence
{_format_anchors(con.evidence_anchors)}

### CON rebuttal to PRO
{con.rebuttal_to_other or "(none)"}

## Your job

Score both sides on four axes (each 0..1):
1. evidence_groundedness — anchors resolve to real canonical_ids?
2. argument_specificity — concrete experiments / numbers / cites,
   not hedge words?
3. rebuttal_responsiveness — did the rebuttal address the other's
   strongest point?
4. falsifiability — did the side declare what would change its
   verdict?

Then declare the verdict:
- "pro" if PRO mean > CON mean by >= 0.05
- "con" if CON mean > PRO mean by >= 0.05
- "draw" otherwise

Write a short reasoning paragraph (no hedge words). Declare a
kill_criterion: a specific observation that would flip the verdict.

Return JSON:
{{
  "verdict": "pro|con|draw",
  "reasoning": "...",
  "kill_criterion": "...",
  "pro_scores": {{"evidence_groundedness": 0..1, ...}},
  "con_scores": {{"evidence_groundedness": 0..1, ...}}
}}
"""


def _render_template(
    spec: DebateSpec, side_label: str, side_text: str,
) -> str:
    return f"""You are arguing the {side_label} side of a self-play
debate on {spec.topic}.

## Target
{spec.target_claim}
(target_id: {spec.target_id})

## Your position
You must argue: **{side_text}**.

## What you must produce

1. **statement** — one paragraph, your strongest case for {side_label}.
   No hedge words. Concrete: numbers, experiments, citation IDs.
2. **evidence_anchors** — at least {spec.min_anchors_per_side}.
   Each is {{canonical_id, claim_quote, why_relevant}}. Use real
   canonical_ids from the run / manuscript corpus. Quote, don't
   paraphrase.
3. **rebuttal_to_other** — empty in opening round. In round ≥2,
   address the strongest point made by the other side; do not just
   restate your own position.

You lose points for: hedge phrases, anchors without canonical_ids,
rebuttals that don't engage with the other side's actual claim.

Return JSON matching this exact shape:
{{
  "side": "{side_label.lower()}",
  "statement": "...",
  "evidence_anchors": [
    {{"canonical_id": "...", "claim_quote": "...", "why_relevant": "..."}}
  ],
  "rebuttal_to_other": "..."
}}
"""


def _format_anchors(anchors: list[EvidenceAnchor]) -> str:
    if not anchors:
        return "  _(none)_"
    out = []
    for i, a in enumerate(anchors, 1):
        out.append(
            f"  {i}. `{a.canonical_id}` — \"{a.claim_quote}\" — {a.why_relevant}"
        )
    return "\n".join(out)


# ---------- mechanical scoring helpers ----------
# Used by the JUDGE prompt for guidance, AND used directly in tests
# to validate that a given Position would score well/poorly.

def score_specificity(text: str) -> float:
    """Heuristic specificity score in [0, 1].

    Penalties: hedge phrases. Rewards: concrete signals (numbers,
    experiments, figure refs, citations).
    """
    if not text:
        return 0.0
    t = text.lower()
    n_hedges = sum(t.count(h) for h in _HEDGE_PHRASES)
    n_concrete = sum(
        len(re.findall(p, t)) for p in _CONCRETE_SIGNALS
    )
    # Map: 0 hedges + 4+ concrete signals → 1.0
    # Many hedges + 0 concrete → ~0.0
    raw = (n_concrete / 4.0) - (n_hedges / 8.0)
    return max(0.0, min(1.0, raw))


def score_groundedness(
    anchors: Iterable[EvidenceAnchor],
    valid_canonical_ids: set[str] | None,
    *, min_anchors: int = 3,
) -> float:
    """Fraction of anchors that resolve to known canonical_ids,
    capped at 1.0. Sub-min count linearly penalized.
    """
    anchors_list = list(anchors)
    if not anchors_list:
        return 0.0
    if valid_canonical_ids is None:
        # Caller cannot validate — return 0.5 as neutral
        return 0.5
    n_valid = sum(
        1 for a in anchors_list if a.canonical_id in valid_canonical_ids
    )
    fraction = n_valid / len(anchors_list)
    # Penalize if total anchors < min_anchors
    count_penalty = max(0.0, (min_anchors - len(anchors_list)) / min_anchors)
    return max(0.0, min(1.0, fraction - count_penalty * 0.5))


def score_responsiveness(
    rebuttal: str, other_statement: str,
) -> float:
    """How much of the other side's content is mentioned in rebuttal?

    Token-overlap proxy: shared content tokens (>3 chars, no stops).
    """
    if not rebuttal or not other_statement:
        return 0.0
    stop = {
        "the", "a", "an", "and", "or", "but", "is", "are", "was",
        "were", "this", "that", "with", "by", "for", "to", "of", "in",
        "on", "as", "at", "from", "we", "they", "their", "its", "it",
        "be", "been", "have", "has", "had", "do", "does", "did",
    }
    def toks(s: str) -> set[str]:
        return {
            w.lower() for w in re.findall(r"[A-Za-z][A-Za-z\-]+", s)
            if len(w) > 3 and w.lower() not in stop
        }
    other_toks = toks(other_statement)
    rebut_toks = toks(rebuttal)
    if not other_toks:
        return 0.0
    overlap = len(other_toks & rebut_toks) / len(other_toks)
    return min(1.0, overlap * 2.0)  # scale; 50% overlap → 1.0


def score_falsifiability(text: str) -> float:
    """Did the side declare what would change its verdict?"""
    if not text:
        return 0.0
    t = text.lower()
    triggers = (
        "would change", "would flip", "would falsify", "would refute",
        "if we observed", "kill criterion", "would invalidate",
        "would overturn", "if the data showed", "evidence against",
    )
    hits = sum(t.count(tr) for tr in triggers)
    return min(1.0, hits / 2.0)


def score_position(
    pos: Position,
    *,
    other_statement: str = "",
    valid_canonical_ids: set[str] | None = None,
    min_anchors: int = 3,
) -> Scores:
    """Compute mechanical scores for a position.

    Useful for unit tests; production judges may override with their
    own LLM-derived scores.
    """
    return Scores(
        evidence_groundedness=score_groundedness(
            pos.evidence_anchors,
            valid_canonical_ids,
            min_anchors=min_anchors,
        ),
        argument_specificity=score_specificity(pos.statement),
        rebuttal_responsiveness=score_responsiveness(
            pos.rebuttal_to_other, other_statement,
        ),
        falsifiability=score_falsifiability(pos.statement),
    )


def decide_verdict(
    pro_scores: Scores, con_scores: Scores, *, draw_threshold: float = 0.05,
) -> tuple[Verdict, float]:
    """Return (verdict, delta). Delta = pro_mean - con_mean."""
    delta = pro_scores.mean() - con_scores.mean()
    if abs(delta) < draw_threshold:
        return "draw", delta
    return ("pro" if delta > 0 else "con"), delta


def render_brief(
    spec: DebateSpec,
    pro: Position, con: Position,
    ruling: JudgeRuling,
) -> str:
    """Markdown debate transcript for archive."""
    lines = [
        f"# Debate — {spec.topic} on `{spec.target_id}`",
        "",
        f"**Claim under debate**: {spec.target_claim}",
        "",
        f"**Verdict**: `{ruling.verdict}` (delta {ruling.delta:+.3f})",
        "",
        f"**Kill criterion**: {ruling.kill_criterion}",
        "",
        "## PRO",
        "",
        pro.statement,
        "",
        "### PRO anchors",
        _format_anchors(pro.evidence_anchors),
        "",
        f"**PRO scores**: {pro.to_dict() if False else ''}".rstrip(),
        f"  - evidence_groundedness: {ruling.pro_scores.evidence_groundedness:.2f}",
        f"  - argument_specificity:  {ruling.pro_scores.argument_specificity:.2f}",
        f"  - rebuttal_responsiveness: {ruling.pro_scores.rebuttal_responsiveness:.2f}",
        f"  - falsifiability:        {ruling.pro_scores.falsifiability:.2f}",
        f"  - **mean**: {ruling.pro_scores.mean():.2f}",
        "",
        "## CON",
        "",
        con.statement,
        "",
        "### CON anchors",
        _format_anchors(con.evidence_anchors),
        "",
        f"  - evidence_groundedness: {ruling.con_scores.evidence_groundedness:.2f}",
        f"  - argument_specificity:  {ruling.con_scores.argument_specificity:.2f}",
        f"  - rebuttal_responsiveness: {ruling.con_scores.rebuttal_responsiveness:.2f}",
        f"  - falsifiability:        {ruling.con_scores.falsifiability:.2f}",
        f"  - **mean**: {ruling.con_scores.mean():.2f}",
        "",
        "## Judge reasoning",
        "",
        ruling.reasoning,
    ]
    return "\n".join(lines)

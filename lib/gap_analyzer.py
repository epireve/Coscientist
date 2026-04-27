"""Gap analyzer (v0.55, A5 Tier A).

Operationalizes Surveyor's gap output. For each gap, produces a
structured analysis:

  - real_or_artifact: is this a genuine gap or an artifact of
    incomplete search? Heuristic: cross_check_query exists +
    supporting_ids count >= 2 + at least one supporting paper from
    the run with high confidence (>= 0.7).
  - addressable: would a single research project plausibly fill this?
    Driven by kind: evidential -> usually yes (run an experiment);
    measurement -> sometimes (build instrument); conceptual ->
    sometimes (theory work).
  - publishability_tier: A | B | C | none. Based on the union of
    {kind, n_supporting_ids, supporting paper avg confidence}.
  - adjacent_field_analogues: list of cross-domain analogues if the
    gap text mentions methods/concepts known in adjacent fields. Pure
    keyword scan against a small registry; LLM-free.
  - expected_difficulty: low | medium | high. Heuristic:
    evidential = low/medium; measurement = medium/high; conceptual =
    high.

Pure stdlib; consumed by `gap-analyzer` skill.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Literal


GapKind = Literal["evidential", "measurement", "conceptual"]
Tier = Literal["A", "B", "C", "none"]
Difficulty = Literal["low", "medium", "high"]


# Adjacent-field registry: maps a domain hint -> field analogues.
# Conservative: only fire when the hint appears verbatim in the gap.
_ADJACENT_FIELD_HINTS: dict[str, list[str]] = {
    "memory consolidation": ["sleep neuroscience", "hippocampal replay"],
    "forgetting": ["spaced repetition", "ecological-memory psychology"],
    "attention": ["cognitive psychology", "anesthesiology"],
    "scaling": ["statistical physics", "machine learning"],
    "active learning": ["bandits", "reinforcement learning"],
    "calibration": ["psychometrics", "weather forecasting"],
    "uncertainty": ["bayesian inference", "robust optimization"],
    "robustness": ["adversarial ML", "control theory"],
    "transformer": ["dynamical systems", "associative memory"],
    "graph": ["combinatorial optimization", "network science"],
    "causal": ["epidemiology", "econometrics"],
}


@dataclass
class GapAnalysis:
    gap_id: str
    kind: GapKind
    claim: str
    real_or_artifact: Literal["real", "artifact", "uncertain"]
    addressable: bool
    publishability_tier: Tier
    adjacent_field_analogues: list[str] = field(default_factory=list)
    expected_difficulty: Difficulty = "medium"
    reasoning: str = ""

    def to_dict(self) -> dict:
        return {
            "gap_id": self.gap_id,
            "kind": self.kind,
            "claim": self.claim,
            "real_or_artifact": self.real_or_artifact,
            "addressable": self.addressable,
            "publishability_tier": self.publishability_tier,
            "adjacent_field_analogues": list(self.adjacent_field_analogues),
            "expected_difficulty": self.expected_difficulty,
            "reasoning": self.reasoning,
        }


def analyze_gap(
    gap: dict,
    *,
    supporting_paper_confidences: dict[str, float] | None = None,
) -> GapAnalysis:
    """Analyze one gap dict from Surveyor output.

    `gap` shape: {gap_id, kind, claim, supporting_ids, cross_check_query}
    `supporting_paper_confidences`: optional cid -> confidence map.
    """
    gap_id = gap.get("gap_id", "g?")
    kind = gap.get("kind", "evidential")
    claim = gap.get("claim", "")
    supporting_ids = gap.get("supporting_ids", []) or []
    cross_check = (gap.get("cross_check_query") or "").strip()

    n_supporting = len(supporting_ids)
    confs = supporting_paper_confidences or {}
    supp_confs = [
        confs[c] for c in supporting_ids if c in confs and confs[c] is not None
    ]
    avg_conf = sum(supp_confs) / len(supp_confs) if supp_confs else None

    # real_or_artifact
    if not cross_check:
        roa = "uncertain"
    elif n_supporting >= 2 and (avg_conf is None or avg_conf >= 0.7):
        roa = "real"
    elif n_supporting < 2:
        roa = "artifact"
    else:
        roa = "uncertain"

    # addressable
    if kind == "evidential":
        addressable = True
    elif kind == "measurement":
        addressable = n_supporting >= 2
    else:  # conceptual
        addressable = avg_conf is not None and avg_conf >= 0.6

    # publishability_tier
    tier = _tier(kind, n_supporting, avg_conf, roa)

    # adjacent_field_analogues
    analogues = _find_analogues(claim)

    # expected_difficulty
    diff = _difficulty(kind, addressable, roa)

    reasoning = (
        f"kind={kind}; n_supporting={n_supporting}; "
        f"avg_conf={avg_conf if avg_conf is not None else 'n/a'}; "
        f"cross_check={'yes' if cross_check else 'no'}"
    )

    return GapAnalysis(
        gap_id=gap_id,
        kind=kind,
        claim=claim,
        real_or_artifact=roa,
        addressable=addressable,
        publishability_tier=tier,
        adjacent_field_analogues=analogues,
        expected_difficulty=diff,
        reasoning=reasoning,
    )


def analyze_gaps(
    gaps: Iterable[dict],
    *,
    supporting_paper_confidences: dict[str, float] | None = None,
) -> list[GapAnalysis]:
    return [
        analyze_gap(g, supporting_paper_confidences=supporting_paper_confidences)
        for g in gaps
    ]


def _tier(
    kind: GapKind, n_supporting: int, avg_conf: float | None,
    roa: str,
) -> Tier:
    if roa == "artifact":
        return "none"
    if kind == "evidential" and n_supporting >= 4 and (
        avg_conf is None or avg_conf >= 0.8
    ):
        return "A"
    if kind == "measurement" and n_supporting >= 3:
        return "A" if (avg_conf or 0) >= 0.75 else "B"
    if kind == "conceptual" and (avg_conf or 0) >= 0.75:
        return "A"
    if n_supporting >= 2:
        return "B"
    if n_supporting >= 1:
        return "C"
    return "none"


def _find_analogues(claim: str) -> list[str]:
    if not claim:
        return []
    text = claim.lower()
    found: list[str] = []
    seen: set[str] = set()
    for hint, analogues in _ADJACENT_FIELD_HINTS.items():
        if hint in text:
            for a in analogues:
                if a not in seen:
                    seen.add(a)
                    found.append(a)
    return found


def _difficulty(
    kind: GapKind, addressable: bool, roa: str,
) -> Difficulty:
    if roa == "artifact":
        return "low"
    if kind == "evidential":
        return "medium" if addressable else "high"
    if kind == "measurement":
        return "high" if not addressable else "medium"
    return "high"  # conceptual


def render_brief(analyses: Iterable[GapAnalysis]) -> str:
    """Markdown brief over gap analyses."""
    rows = list(analyses)
    if not rows:
        return "_(no gaps to analyze)_"
    lines = [
        "# Gap analysis",
        "",
        "| gap_id | kind | real? | addressable | tier | difficulty | analogues |",
        "|---|---|---|---|---|---|---|",
    ]
    for a in rows:
        analogues = ", ".join(a.adjacent_field_analogues) or "—"
        lines.append(
            f"| `{a.gap_id}` | {a.kind} | {a.real_or_artifact} | "
            f"{'yes' if a.addressable else 'no'} | "
            f"{a.publishability_tier} | {a.expected_difficulty} | "
            f"{analogues} |"
        )
    lines += ["", "## Per-gap reasoning", ""]
    for a in rows:
        lines += [
            f"### `{a.gap_id}` — {a.kind}",
            "",
            f"**Claim**: {a.claim}",
            "",
            f"**Reasoning**: {a.reasoning}",
            "",
        ]
    return "\n".join(lines)

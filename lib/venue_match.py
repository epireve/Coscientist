"""Venue match (v0.55, A5 Tier A).

Data-backed venue recommendation. Pure stdlib + a built-in registry
of common research venues with their characteristics. No external
network calls — we surface the registry, score against a manuscript's
characteristics, return top-K with explained tradeoffs.

Public API:
  recommend(manuscript_chars, top_k=5) -> list of Recommendation
  list_venues() -> list of Venue
  score_venue(venue, chars) -> float in [0, 1]
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


# Venue tier classification
Tier = Literal["A", "B", "C"]
# Submission characteristics
DomainTag = Literal[
    "ml", "nlp", "cv", "robotics", "biology", "neuroscience",
    "physics", "chemistry", "social-science", "policy", "general",
    "interdisciplinary",
]
TypeTag = Literal[
    "conference", "journal", "workshop", "preprint", "registered-report",
]
PaperKind = Literal[
    "empirical", "theoretical", "review", "systematic-review",
    "position", "method", "tool", "dataset",
]


@dataclass
class Venue:
    name: str
    type: TypeTag
    tier: Tier
    domains: tuple[DomainTag, ...]
    accepts_kinds: tuple[PaperKind, ...]
    impact_factor: float | None      # approximate, may be None
    open_access: bool
    typical_acceptance_rate: float   # in [0, 1]
    review_turnaround_days: int      # approximate
    notes: str = ""


@dataclass
class ManuscriptChars:
    """What the user knows / claims about the manuscript."""
    domains: tuple[DomainTag, ...]
    kind: PaperKind
    novelty_score: float = 0.5       # in [0, 1]
    rigor_score: float = 0.5         # methodology rigor in [0, 1]
    open_science_intent: bool = True  # OA preferred?
    deadline_days: int | None = None  # max review turnaround acceptable
    require_tier: Tier | None = None  # gate by minimum tier
    target_audience: Literal["specialist", "broad"] = "specialist"


@dataclass
class Recommendation:
    venue: Venue
    score: float
    reasons_for: list[str] = field(default_factory=list)
    reasons_against: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "venue": self.venue.name,
            "type": self.venue.type,
            "tier": self.venue.tier,
            "score": round(self.score, 3),
            "reasons_for": list(self.reasons_for),
            "reasons_against": list(self.reasons_against),
        }


# Registry — small but spans common research venues.
# Numbers are conservative approximations (acceptance rate / IF).
_VENUES: list[Venue] = [
    # ML
    Venue("NeurIPS", "conference", "A",
          ("ml",), ("empirical", "theoretical", "method"),
          impact_factor=None, open_access=True,
          typical_acceptance_rate=0.26, review_turnaround_days=120,
          notes="Dec deadline; large but selective"),
    Venue("ICLR", "conference", "A",
          ("ml",), ("empirical", "theoretical", "method"),
          impact_factor=None, open_access=True,
          typical_acceptance_rate=0.32, review_turnaround_days=120,
          notes="OpenReview public reviews"),
    Venue("ICML", "conference", "A",
          ("ml",), ("empirical", "theoretical", "method"),
          impact_factor=None, open_access=True,
          typical_acceptance_rate=0.27, review_turnaround_days=120),
    # NLP / CV
    Venue("ACL", "conference", "A",
          ("nlp",), ("empirical", "method", "review"),
          impact_factor=None, open_access=True,
          typical_acceptance_rate=0.23, review_turnaround_days=110),
    Venue("EMNLP", "conference", "A",
          ("nlp",), ("empirical", "method"),
          impact_factor=None, open_access=True,
          typical_acceptance_rate=0.24, review_turnaround_days=110),
    Venue("CVPR", "conference", "A",
          ("cv",), ("empirical", "method"),
          impact_factor=None, open_access=True,
          typical_acceptance_rate=0.23, review_turnaround_days=110),
    # Bio / interdisciplinary
    Venue("Nature", "journal", "A",
          ("biology", "general", "interdisciplinary"),
          ("empirical", "review"),
          impact_factor=64.8, open_access=False,
          typical_acceptance_rate=0.08, review_turnaround_days=90,
          notes="Broad-impact only"),
    Venue("Nature Methods", "journal", "A",
          ("biology", "neuroscience", "ml"),
          ("method", "tool"),
          impact_factor=47.0, open_access=False,
          typical_acceptance_rate=0.10, review_turnaround_days=90),
    Venue("eLife", "journal", "A",
          ("biology", "neuroscience"),
          ("empirical", "review", "method"),
          impact_factor=8.7, open_access=True,
          typical_acceptance_rate=0.18, review_turnaround_days=80,
          notes="Open peer review; supports registered reports"),
    Venue("PLOS ONE", "journal", "B",
          ("biology", "neuroscience", "general"),
          ("empirical", "review", "method", "dataset"),
          impact_factor=3.4, open_access=True,
          typical_acceptance_rate=0.50, review_turnaround_days=120,
          notes="Sound-science criterion, broad scope"),
    # Reviews + meta
    Venue("Annual Review of <field>", "journal", "A",
          ("general",), ("review",),
          impact_factor=20.0, open_access=False,
          typical_acceptance_rate=0.05, review_turnaround_days=180,
          notes="Invited-only typically"),
    # Workshops & preprint
    Venue("arXiv", "preprint", "C",
          ("ml", "nlp", "cv", "physics", "general"),
          ("empirical", "theoretical", "method", "tool",
           "dataset", "position", "review"),
          impact_factor=None, open_access=True,
          typical_acceptance_rate=1.0, review_turnaround_days=0,
          notes="Not peer-reviewed; for early dissemination"),
    Venue("bioRxiv", "preprint", "C",
          ("biology", "neuroscience"),
          ("empirical", "method", "review", "dataset"),
          impact_factor=None, open_access=True,
          typical_acceptance_rate=1.0, review_turnaround_days=0),
    Venue("NeurIPS Workshop", "workshop", "B",
          ("ml",), ("empirical", "position", "tool"),
          impact_factor=None, open_access=True,
          typical_acceptance_rate=0.55, review_turnaround_days=60),
    # Registered reports pathway
    Venue("Royal Society Open Science", "registered-report", "B",
          ("biology", "physics", "general"),
          ("empirical",),
          impact_factor=2.9, open_access=True,
          typical_acceptance_rate=0.45, review_turnaround_days=90,
          notes="Stage-1 in-principle accept then Stage-2"),
]


def list_venues() -> list[Venue]:
    return list(_VENUES)


def score_venue(venue: Venue, chars: ManuscriptChars) -> float:
    """Score in [0, 1]. Higher = better fit."""
    score = 0.0

    # Domain match (weight 0.30)
    domain_overlap = set(chars.domains) & set(venue.domains)
    if domain_overlap:
        score += 0.30
    elif "general" in venue.domains or "interdisciplinary" in venue.domains:
        score += 0.15

    # Kind match (0.20)
    if chars.kind in venue.accepts_kinds:
        score += 0.20

    # Novelty alignment (0.15) — A-tier venues need higher novelty
    needed_novelty = {"A": 0.7, "B": 0.4, "C": 0.0}[venue.tier]
    if chars.novelty_score >= needed_novelty:
        score += 0.15
    elif chars.novelty_score >= needed_novelty - 0.2:
        score += 0.075

    # Rigor alignment (0.15) — A-tier needs higher rigor
    needed_rigor = {"A": 0.7, "B": 0.5, "C": 0.0}[venue.tier]
    if chars.rigor_score >= needed_rigor:
        score += 0.15
    elif chars.rigor_score >= needed_rigor - 0.2:
        score += 0.075

    # Open access (0.10)
    if chars.open_science_intent and venue.open_access:
        score += 0.10
    elif not chars.open_science_intent:
        score += 0.05  # neutral

    # Deadline (0.05)
    if chars.deadline_days is None:
        score += 0.05
    elif venue.review_turnaround_days <= chars.deadline_days:
        score += 0.05

    # Hard tier filter
    if chars.require_tier:
        tier_rank = {"A": 3, "B": 2, "C": 1}
        if tier_rank[venue.tier] < tier_rank[chars.require_tier]:
            return 0.0

    return min(score, 1.0)


def _explain(venue: Venue, chars: ManuscriptChars) -> tuple[list[str], list[str]]:
    fors: list[str] = []
    againsts: list[str] = []

    domain_overlap = set(chars.domains) & set(venue.domains)
    if domain_overlap:
        fors.append(f"domain match: {', '.join(sorted(domain_overlap))}")
    elif "general" not in venue.domains:
        againsts.append(
            f"domains {sorted(chars.domains)} not in venue scope "
            f"{sorted(venue.domains)}"
        )

    if chars.kind in venue.accepts_kinds:
        fors.append(f"accepts {chars.kind} papers")
    else:
        againsts.append(
            f"venue prefers {sorted(venue.accepts_kinds)}; "
            f"manuscript is {chars.kind}"
        )

    needed_novelty = {"A": 0.7, "B": 0.4, "C": 0.0}[venue.tier]
    if chars.novelty_score < needed_novelty - 0.2:
        againsts.append(
            f"novelty {chars.novelty_score:.2f} < tier-{venue.tier} "
            f"floor (~{needed_novelty:.2f})"
        )

    if chars.open_science_intent and venue.open_access:
        fors.append("open access aligns with stated intent")
    if chars.open_science_intent and not venue.open_access:
        againsts.append("not open access; user prefers OA")

    if chars.deadline_days is not None:
        if venue.review_turnaround_days <= chars.deadline_days:
            fors.append(
                f"review turnaround {venue.review_turnaround_days}d "
                f"fits {chars.deadline_days}d deadline"
            )
        else:
            againsts.append(
                f"review turnaround {venue.review_turnaround_days}d "
                f"exceeds {chars.deadline_days}d deadline"
            )

    if venue.typical_acceptance_rate < 0.15:
        againsts.append(
            f"low acceptance rate {venue.typical_acceptance_rate:.0%}"
        )
    elif venue.typical_acceptance_rate > 0.40:
        fors.append(
            f"acceptance rate {venue.typical_acceptance_rate:.0%}"
        )

    if venue.notes:
        fors.append(f"note: {venue.notes}")

    return fors, againsts


def recommend(
    chars: ManuscriptChars, top_k: int = 5,
) -> list[Recommendation]:
    """Top-K venues for the manuscript characteristics."""
    scored = []
    for v in _VENUES:
        s = score_venue(v, chars)
        if s <= 0:
            continue
        fors, againsts = _explain(v, chars)
        scored.append(Recommendation(
            venue=v, score=s,
            reasons_for=fors, reasons_against=againsts,
        ))
    scored.sort(key=lambda r: r.score, reverse=True)
    return scored[:top_k]


def render_brief(recommendations: list[Recommendation]) -> str:
    """Markdown brief over recommendations."""
    if not recommendations:
        return "_(no venue matches; relax constraints?)_"
    lines = [
        "# Venue recommendations",
        "",
        "| rank | venue | type | tier | score | acc% | OA | notes |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(recommendations, 1):
        v = r.venue
        oa = "yes" if v.open_access else "no"
        lines.append(
            f"| {i} | {v.name} | {v.type} | {v.tier} | "
            f"{r.score:.2f} | {v.typical_acceptance_rate:.0%} | "
            f"{oa} | {v.notes or '—'} |"
        )
    lines += ["", "## Per-venue tradeoffs", ""]
    for r in recommendations:
        lines.append(f"### {r.venue.name}")
        lines.append("")
        if r.reasons_for:
            lines.append("**For**:")
            for s in r.reasons_for:
                lines.append(f"- {s}")
        if r.reasons_against:
            lines.append("")
            lines.append("**Against**:")
            for s in r.reasons_against:
                lines.append(f"- {s}")
        lines.append("")
    return "\n".join(lines)

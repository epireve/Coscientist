"""Search-strategy framework selection for deep-research Break 0.

Imports the framework-selection pattern from Consensus's official
literature-review-helper skill (April 2026). Three frameworks:

- **PICO** — Population × Intervention × Comparison × Outcome. Default
  for health, clinical, behavioral, educational, social science.
- **SPIDER** — Sample × Phenomenon × Design × Evaluation × Research.
  Fallback for qualitative / no-intervention questions.
- **Decomposition** — Mechanism × Applications × Limitations × Comparisons.
  Fallback for technology / applied-science questions.

Hybrid framing allowed — pick primary, note which components borrow from
others. Goal is clarity, not orthodoxy.

Once a framework is selected and sub-areas decomposed, the persona
harvests are gated on sub-area assignment so cartographer, chronicler,
surveyor each cover a declared sub-area rather than drifting on implicit
angles.

Pure stdlib. No LLM calls. Deterministic.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal


FrameworkKind = Literal["pico", "spider", "decomposition", "hybrid"]


# Framework component templates. Empty fields filled in by the
# orchestrator (with user confirmation) at Break 0.
FRAMEWORK_TEMPLATES: dict[FrameworkKind, list[dict]] = {
    "pico": [
        {"component": "P", "name": "Population", "prompt": "Who or what is being studied?"},
        {"component": "I", "name": "Intervention", "prompt": "What treatment, exposure, or factor is examined?"},
        {"component": "C", "name": "Comparison", "prompt": "What is it being compared to?"},
        {"component": "O", "name": "Outcome", "prompt": "What results or effects matter?"},
    ],
    "spider": [
        {"component": "S", "name": "Sample", "prompt": "Who or what is the sample?"},
        {"component": "PI", "name": "Phenomenon of Interest", "prompt": "What experience, process, or behavior?"},
        {"component": "D", "name": "Design", "prompt": "Study design (interview / ethnography / case study)?"},
        {"component": "E", "name": "Evaluation", "prompt": "What outcomes / measures of evaluation?"},
        {"component": "R", "name": "Research type", "prompt": "Qualitative, mixed-methods, etc.?"},
    ],
    "decomposition": [
        {"component": "M", "name": "Core mechanism", "prompt": "What technique / system / mechanism?"},
        {"component": "A", "name": "Applications", "prompt": "Where is it deployed / used?"},
        {"component": "L", "name": "Limitations", "prompt": "What are the known weaknesses?"},
        {"component": "C", "name": "Comparisons", "prompt": "What alternatives does it compete with?"},
    ],
}


@dataclass
class SubArea:
    """One sub-area derived from a framework component.

    Bound to a specific persona once the orchestrator assigns harvest
    targets at Break 0 — that persona's harvest then queries this
    sub-area's `query_seed` rather than drifting on implicit angles.
    """
    component: str  # e.g., "P", "I", "M"
    label: str       # human-readable, e.g., "Population: adults with depression"
    query_seed: str  # search-string seed, e.g., "depression cognitive therapy"
    assigned_persona: str | None = None  # filled in at sub-area decomposition

    def to_dict(self) -> dict:
        return {
            "component": self.component,
            "label": self.label,
            "query_seed": self.query_seed,
            "assigned_persona": self.assigned_persona,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SubArea":
        return cls(
            component=d["component"],
            label=d["label"],
            query_seed=d["query_seed"],
            assigned_persona=d.get("assigned_persona"),
        )


@dataclass
class SearchStrategy:
    """Per-run search strategy. Persisted in `runs.search_strategy_json`.

    The orchestrator emits a draft at Break 0, user confirms or adjusts,
    then the strategy is locked for the rest of the run.
    """
    framework: FrameworkKind
    rationale: str   # one-sentence: why this framework over alternatives
    sub_areas: list[SubArea] = field(default_factory=list)
    cross_cutting: str | None = None  # 5th row in lit-review-helper pattern

    def to_dict(self) -> dict:
        return {
            "framework": self.framework,
            "rationale": self.rationale,
            "sub_areas": [s.to_dict() for s in self.sub_areas],
            "cross_cutting": self.cross_cutting,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SearchStrategy":
        return cls(
            framework=d["framework"],
            rationale=d.get("rationale", ""),
            sub_areas=[SubArea.from_dict(s) for s in d.get("sub_areas", [])],
            cross_cutting=d.get("cross_cutting"),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    def render_table(self) -> str:
        """Render as markdown table for Break 0 user prompt."""
        lines = [
            f"## Search strategy — {self.framework.upper()}",
            "",
            f"_{self.rationale}_",
            "",
            "| Component | Sub-area | Query seed | Assigned to |",
            "|---|---|---|---|",
        ]
        for sa in self.sub_areas:
            persona = sa.assigned_persona or "_unassigned_"
            lines.append(
                f"| {sa.component} | {sa.label} | `{sa.query_seed}` | {persona} |"
            )
        if self.cross_cutting:
            lines.append(
                f"| ✦ | _Cross-cutting_: {self.cross_cutting} | — | — |"
            )
        return "\n".join(lines)


def template_for(framework: FrameworkKind) -> list[dict]:
    """Return the component template for a framework.

    Hybrid framing: caller picks primary framework, then notes borrowed
    components from others in `cross_cutting`.
    """
    if framework == "hybrid":
        # Hybrid uses no canonical template — caller defines components
        # by hand. Return empty list to signal that.
        return []
    return FRAMEWORK_TEMPLATES[framework]


def suggest_framework(question: str) -> tuple[FrameworkKind, str]:
    """Heuristic framework suggestion based on question text.

    Pure-keyword heuristic. The orchestrator can override this — and
    the user always has final say at Break 0. Returns (framework,
    rationale).

    PICO keywords → clinical/behavioral/educational
    SPIDER keywords → qualitative / lived-experience / phenomenology
    Decomposition keywords → technology / system / algorithm / mechanics

    Default: hybrid if multiple match strongly; PICO if none match (per
    lit-review-helper's "default to PICO unless it clearly doesn't fit").
    """
    q = question.lower()
    pico_hits = sum(
        1 for kw in (
            "patient", "intervention", "treatment", "outcome", "rct",
            "therapy", "clinical", "drug", "trial", "diagnosis",
            "population", "epidemiolog", "behavior", "education",
            "intervention vs", "compared to", "control group",
        ) if kw in q
    )
    spider_hits = sum(
        1 for kw in (
            "experience", "perception", "qualitative", "lived",
            "phenomenology", "interview", "ethnograph", "narrative",
            "attitude", "perspective", "meaning", "subjective",
        ) if kw in q
    )
    deco_hits = sum(
        1 for kw in (
            "algorithm", "mechanic", "system", "architecture",
            "framework", "model", "technique", "method", "platform",
            "tool", "infrastructure", "machine learning", "neural",
            "digital", "software", "protocol", "compute",
        ) if kw in q
    )

    # If two or more frameworks tied at >= 2 hits, signal hybrid.
    high = [(name, h) for name, h in
            [("pico", pico_hits), ("spider", spider_hits),
             ("decomposition", deco_hits)] if h >= 2]
    if len(high) >= 2:
        names = ", ".join(n for n, _ in high)
        return "hybrid", (
            f"Question spans {names}. Pick primary framework + note "
            f"borrowed components."
        )

    # Top single framework
    top = max(
        ("pico", pico_hits), ("spider", spider_hits),
        ("decomposition", deco_hits), key=lambda x: x[1]
    )
    if top[1] == 0:
        # No keyword hit — default to PICO (lit-review-helper convention)
        return "pico", "No strong framework signal; defaulting to PICO."

    rationale_map = {
        "pico": "Question has clinical/behavioral/intervention signal — PICO fits.",
        "spider": "Question has qualitative/experiential signal — SPIDER fits.",
        "decomposition": "Question has technology/system/mechanics signal — Decomposition fits.",
    }
    return top[0], rationale_map[top[0]]

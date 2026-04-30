"""v0.147 — phase-aware source picker.

Decides which paper-discovery source to call given the research phase,
mode, and budget. Codifies the rule:

  Discovery  → Consensus (high-signal triage; TLDR + claims + study quality)
  Ingestion  → OpenAlex   (graph backbone; refs/citations/topics/OA URLs)
  Enrichment → S2         (TLDR + embeddings + influentialCitationCount)
  Graph walk → OpenAlex   (structural; refs + cited_by)

Per-phase rules with mode + seed + budget overrides. Pure stdlib —
no I/O, no LLM. Heuristic only.

CLI:
    uv run python -m lib.source_selector \\
        --phase discovery --mode deep
    # → consensus

Inputs:
    phase: 'discovery' | 'ingestion' | 'enrichment' | 'graph-walk'
    mode:  'quick' | 'deep' | 'wide' | None
    has_seed: bool — user provided a DOI/arXiv/openalex_id
    budget_tier: 'free' | 'paid' | None — free forces S2/OpenAlex only
    open_question: bool — open-ended ('how/why/what') vs concrete

Output: SourceRecommendation with primary + fallbacks + reasoning.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Phase = Literal["discovery", "ingestion", "enrichment", "graph-walk"]
Mode = Literal["quick", "deep", "wide"]
BudgetTier = Literal["free", "paid"]
Source = Literal["consensus", "openalex", "s2", "paper-search"]


VALID_PHASES = {"discovery", "ingestion", "enrichment", "graph-walk"}
VALID_MODES = {"quick", "deep", "wide"}
VALID_BUDGETS = {"free", "paid"}
VALID_SOURCES = {"consensus", "openalex", "s2", "paper-search"}


@dataclass
class SourceRecommendation:
    primary: Source
    fallbacks: list[Source] = field(default_factory=list)
    reasoning: str = ""
    phase: Phase | None = None
    mode: Mode | None = None
    budget_tier: BudgetTier | None = None


def is_source_degraded(source_name: str) -> bool:
    """v0.188 — consult `lib.health.mcp_error_rates`.

    Returns True iff the named source has error_rate > 0.5 with
    n_calls >= 5 in the rolling window. Fail-open: any exception
    or missing data → False so the picker still works when the
    health stack is unreachable.
    """
    try:
        from lib import health
        rates = health.mcp_error_rates()
    except Exception:
        return False
    d = rates.get(source_name)
    if not d:
        return False
    return (
        d.get("n_calls", 0) >= 5
        and d.get("error_rate", 0.0) > 0.5
    )


def _source_to_mcp_key(src: Source) -> str:
    """Map source-selector source name to lib.health MCP key."""
    if src == "s2":
        return "semantic-scholar"
    return src


def _select_source_pure(
    *,
    phase: Phase,
    mode: Mode | None = None,
    has_seed: bool = False,
    budget_tier: BudgetTier | None = None,
    open_question: bool = True,
) -> SourceRecommendation:
    """Pick the optimal source for a phase.

    Decision order (first match wins):
      1. has_seed → openalex (skip discovery entirely)
      2. phase=ingestion → openalex (graph backbone)
      3. phase=graph-walk → openalex
      4. phase=enrichment → s2 (TLDR + embeddings, free w/ key)
      5. phase=discovery + mode=quick → s2 (cheap TLDR)
      6. phase=discovery + budget=free → s2
      7. phase=discovery + mode=wide → openalex (batch metadata)
      8. phase=discovery + open_question + mode=deep → consensus (best triage)
      9. phase=discovery + concrete → openalex (metadata sufficient)
     10. fallback → openalex (safe default)
    """
    if phase not in VALID_PHASES:
        raise ValueError(f"unknown phase: {phase}")
    if mode is not None and mode not in VALID_MODES:
        raise ValueError(f"unknown mode: {mode}")
    if budget_tier is not None and budget_tier not in VALID_BUDGETS:
        raise ValueError(f"unknown budget_tier: {budget_tier}")

    if has_seed:
        return SourceRecommendation(
            primary="openalex",
            fallbacks=["s2", "paper-search"],
            reasoning="seed provided — skip discovery, hit OpenAlex directly",
            phase=phase, mode=mode, budget_tier=budget_tier,
        )

    if phase == "ingestion":
        return SourceRecommendation(
            primary="openalex",
            fallbacks=["s2"],
            reasoning="ingestion needs graph backbone (refs, citations, OA URL, topics)",
            phase=phase, mode=mode, budget_tier=budget_tier,
        )

    if phase == "graph-walk":
        return SourceRecommendation(
            primary="openalex",
            fallbacks=["s2"],
            reasoning="graph-walk is structural — OpenAlex refs + cited_by",
            phase=phase, mode=mode, budget_tier=budget_tier,
        )

    if phase == "enrichment":
        return SourceRecommendation(
            primary="s2",
            fallbacks=["openalex"],
            reasoning="enrichment needs TLDR + embeddings + influence (S2 free w/ key)",
            phase=phase, mode=mode, budget_tier=budget_tier,
        )

    # phase == "discovery"
    if mode == "quick":
        return SourceRecommendation(
            primary="s2",
            fallbacks=["openalex"],
            reasoning="quick mode — S2 TLDR sufficient, skip Consensus",
            phase=phase, mode=mode, budget_tier=budget_tier,
        )

    if budget_tier == "free":
        return SourceRecommendation(
            primary="s2",
            fallbacks=["openalex"],
            reasoning="free budget — Consensus excluded",
            phase=phase, mode=mode, budget_tier=budget_tier,
        )

    if mode == "wide":
        return SourceRecommendation(
            primary="openalex",
            fallbacks=["s2"],
            reasoning="wide mode — batch metadata via OpenAlex, triage already implicit",
            phase=phase, mode=mode, budget_tier=budget_tier,
        )

    if mode == "deep" and open_question:
        return SourceRecommendation(
            primary="consensus",
            fallbacks=["s2", "openalex"],
            reasoning="deep open-ended discovery — Consensus TLDR+claims best triage signal",
            phase=phase, mode=mode, budget_tier=budget_tier,
        )

    if not open_question:
        return SourceRecommendation(
            primary="openalex",
            fallbacks=["s2"],
            reasoning="concrete query — metadata sufficient, skip paid signal",
            phase=phase, mode=mode, budget_tier=budget_tier,
        )

    return SourceRecommendation(
        primary="openalex",
        fallbacks=["s2", "consensus"],
        reasoning="default — OpenAlex safe baseline",
        phase=phase, mode=mode, budget_tier=budget_tier,
    )


def select_source(
    *,
    phase: Phase,
    mode: Mode | None = None,
    has_seed: bool = False,
    budget_tier: BudgetTier | None = None,
    open_question: bool = True,
    skip_degraded: bool = False,
) -> SourceRecommendation:
    """Pick the optimal source for a phase.

    v0.188 — `skip_degraded=True` consults `lib.health.mcp_error_rates`
    and falls through to the first healthy fallback if the primary
    is degraded. Default False preserves v0.147 behaviour exactly.
    """
    rec = _select_source_pure(
        phase=phase, mode=mode, has_seed=has_seed,
        budget_tier=budget_tier, open_question=open_question,
    )
    if not skip_degraded:
        return rec
    chain: list[Source] = [rec.primary, *rec.fallbacks]
    healthy: list[Source] = [
        s for s in chain
        if not is_source_degraded(_source_to_mcp_key(s))
    ]
    if not healthy or healthy[0] == rec.primary:
        return rec
    new_primary = healthy[0]
    new_fallbacks = [s for s in chain if s != new_primary]
    return SourceRecommendation(
        primary=new_primary,
        fallbacks=new_fallbacks,
        reasoning=(
            f"{rec.reasoning} [v0.188: primary {rec.primary!r} "
            f"degraded, falling through to {new_primary!r}]"
        ),
        phase=rec.phase, mode=rec.mode, budget_tier=rec.budget_tier,
    )


def call_budget(*, mode: Mode, n_candidates: int = 0) -> dict:
    """Recommended call budget per mode for a discovery+ingestion cycle.

    Returns target counts per source. Used by orchestrators to cap calls.
    """
    if mode == "quick":
        return {
            "consensus": 0,
            "s2": 1,           # one batch search
            "openalex": 1,     # ingestion of selected
            "total_paid": 0,
        }
    if mode == "wide":
        # N items processed identically; metadata-only fan-out
        return {
            "consensus": 0,
            "s2": max(1, (n_candidates + 499) // 500),
            "openalex": max(1, (n_candidates + 49) // 50),
            "total_paid": 0,
        }
    # deep
    return {
        "consensus": 2,        # discovery + 1 deep-claim follow-up
        "s2": 2,               # batch enrichment of triaged set
        "openalex": 5,         # ingestion + graph walks
        "total_paid": 2,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json
    p = argparse.ArgumentParser(prog="source_selector")
    p.add_argument("--phase", choices=sorted(VALID_PHASES))
    p.add_argument("--mode", choices=sorted(VALID_MODES))
    p.add_argument("--has-seed", action="store_true")
    p.add_argument("--budget-tier", choices=sorted(VALID_BUDGETS))
    p.add_argument("--concrete", action="store_true",
                   help="concrete query (not open-ended)")
    p.add_argument("--format", choices=("text", "json"), default="text")
    p.add_argument("--budget", action="store_true",
                   help="emit call budget instead of source pick")
    p.add_argument("--n-candidates", type=int, default=0)
    a = p.parse_args(argv)

    if a.budget:
        if not a.mode:
            print("--budget requires --mode", flush=True)
            return 2
        b = call_budget(mode=a.mode, n_candidates=a.n_candidates)
        if a.format == "json":
            print(json.dumps(b, indent=2))
        else:
            for k, v in b.items():
                print(f"{k}: {v}")
        return 0

    if not a.phase:
        print("--phase required (or use --budget --mode)", flush=True)
        return 2
    rec = select_source(
        phase=a.phase, mode=a.mode, has_seed=a.has_seed,
        budget_tier=a.budget_tier, open_question=not a.concrete,
    )
    if a.format == "json":
        print(json.dumps({
            "primary": rec.primary,
            "fallbacks": rec.fallbacks,
            "reasoning": rec.reasoning,
            "phase": rec.phase,
            "mode": rec.mode,
            "budget_tier": rec.budget_tier,
        }, indent=2))
    else:
        print(rec.primary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

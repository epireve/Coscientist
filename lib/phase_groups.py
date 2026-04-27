"""Phase concurrency groups for the deep-research pipeline.

v0.51 — parallelization. Three of the ten Expedition phases are
mechanically independent of each other within their group:

  - cartographer (Phase 1a — seminal works via citation graph)
  - chronicler   (Phase 1b — chronological arc)
  - surveyor     (Phase 1c — gap mapping)

All three read Phase 0 scout output + their own MCP harvest. None
reads another Phase 1 persona's output. Steward and Weaver consume
all three later. Safe to dispatch concurrently.

What this module does:

  - Declares phase groups (sets of phases that can run in parallel).
  - Provides `batchable(phases_remaining)` — given the remaining
    incomplete phases of a run in ordinal order, returns the largest
    prefix that forms a single concurrency group (or just the next
    phase if it has no group).

Engineering principles:

  - Pure logic. No I/O, no DB. Operates on phase-name lists.
  - Ordinal preservation: groups are subsets of contiguous ordinals,
    so steward's `ORDER BY ordinal` still produces deterministic
    output regardless of completion timing.
  - Conservative: only the phases explicitly named in PHASE_GROUPS
    parallelize. Synthesist + Architect + Inquisitor + Weaver are
    sequential because each consumes the previous.
"""
from __future__ import annotations


# Each group: a set of phase names that may run concurrently.
# A phase NOT in any group runs alone (sequential).
PHASE_GROUPS: list[frozenset[str]] = [
    # Phase 1 personas — independent harvests + analyses
    frozenset({"cartographer", "chronicler", "surveyor"}),
]


def group_for(phase: str) -> frozenset[str] | None:
    """Return the concurrency group containing `phase`, or None."""
    for g in PHASE_GROUPS:
        if phase in g:
            return g
    return None


def batchable(phases_remaining: list[str]) -> list[str]:
    """Given remaining phases in ordinal order, return the largest
    prefix that forms a single concurrency group.

    Rules:
      - If `phases_remaining` is empty, returns [].
      - If the first phase is not in any group, returns [first].
      - Otherwise returns the contiguous prefix of phases that all
        belong to the *same* group as the first phase.

    Examples:
      ["scout"]                              -> ["scout"]
      ["cartographer","chronicler","surveyor","synthesist"]
        -> ["cartographer","chronicler","surveyor"]
      ["chronicler","surveyor","synthesist"]
        -> ["chronicler","surveyor"]
      ["synthesist","architect"]             -> ["synthesist"]
    """
    if not phases_remaining:
        return []
    first = phases_remaining[0]
    g = group_for(first)
    if g is None:
        return [first]
    out = [first]
    for p in phases_remaining[1:]:
        if p in g:
            out.append(p)
        else:
            break
    return out

"""Mode auto-selector — Quick / Deep / Wide picker.

v0.53.6. Pure stdlib decision logic. No I/O, no LLM calls.

Three modes:
  - Quick : single agent, one question, no per-item iteration
  - Deep  : 10-phase Expedition pipeline on one research question
  - Wide  : N-item parallel fan-out (10 ≤ N ≤ 250)

Selector inputs:
  - question: text the user typed
  - items: list[dict] | None
  - task_shape: 'per-item' | 'one-question' | None (auto-inferred)
  - explicit_mode: 'quick'|'deep'|'wide' override (always wins)

Output: ModeRecommendation with mode + reasoning + confidence + warnings.

Decision tree (in order — first match wins):
  1. explicit_mode set → honor it (validate item-count against limits)
  2. items list present + len ≥ WIDE_THRESHOLD_ITEMS → Wide
  3. items list present + len > WIDE_MAX_ITEMS → systematic-review
       (selector returns mode=systematic-review with redirect note)
  4. items list present + len < WIDE_THRESHOLD_ITEMS → Quick (small)
       or Deep if question text is open-ended
  5. no items + open-ended question (heuristic: ≥6 words, '?' or
     keywords 'how/why/what/explain/synthesize') → Deep
  6. no items + concrete one-shot ('summarize this', 'extract X') → Quick
  7. ambiguous → Deep (safe default for "serious research" tool)

Heuristics live in this module, not in skills, so they can be tested.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from lib.wide_research import WIDE_MAX_ITEMS, WIDE_THRESHOLD_ITEMS


Mode = Literal["quick", "deep", "wide", "systematic-review"]
TaskShape = Literal["per-item", "one-question"]


# Heuristic vocabulary for one-question detection
_OPEN_ENDED_KEYWORDS = {
    "how", "why", "what", "explain", "synthesize", "synthesise",
    "investigate", "compare", "review", "survey", "analyze",
    "analyse", "understand", "research",
}

# Concrete one-shot signals — bias toward Quick
_QUICK_KEYWORDS = {
    "summarize", "summarise", "extract", "list", "format",
    "translate", "convert", "fix", "rewrite",
}


@dataclass
class ModeRecommendation:
    mode: Mode
    confidence: float                # 0..1
    reasoning: str
    warnings: list[str] = field(default_factory=list)
    n_items: int = 0
    detected_shape: TaskShape | None = None

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "confidence": round(self.confidence, 2),
            "reasoning": self.reasoning,
            "warnings": list(self.warnings),
            "n_items": self.n_items,
            "detected_shape": self.detected_shape,
        }


def select_mode(
    question: str,
    *,
    items: list[dict] | None = None,
    explicit_mode: Mode | None = None,
    task_shape: TaskShape | None = None,
) -> ModeRecommendation:
    """Pick the right mode for the user's task.

    See module docstring for decision tree.
    """
    n_items = len(items) if items is not None else 0
    warnings: list[str] = []

    # Validate empty items list distinctly from "no items list"
    if items is not None and n_items == 0:
        warnings.append(
            "items list provided but empty — items=[] is not the same "
            "as items=None; treating as 'no items'"
        )
        items = None

    # Detect task shape if not specified
    if task_shape is None:
        task_shape = _infer_shape(question, items)

    # 1) Explicit override always wins, with validation
    if explicit_mode is not None:
        return _validate_explicit(explicit_mode, n_items, question)

    # 2-3) Item-driven branches
    if items:
        if n_items > WIDE_MAX_ITEMS:
            return ModeRecommendation(
                mode="systematic-review",
                confidence=0.95,
                reasoning=(
                    f"{n_items} items exceeds Wide cap "
                    f"({WIDE_MAX_ITEMS}). Use the systematic-review "
                    f"skill for larger corpora."
                ),
                warnings=warnings,
                n_items=n_items,
                detected_shape=task_shape,
            )
        if n_items >= WIDE_THRESHOLD_ITEMS:
            return ModeRecommendation(
                mode="wide",
                confidence=0.95,
                reasoning=(
                    f"{n_items} items + per-item task → Wide "
                    f"(orchestrator-worker fan-out)."
                ),
                warnings=warnings,
                n_items=n_items,
                detected_shape=task_shape,
            )
        # Below Wide threshold — Quick if obviously concrete, else Deep
        if _looks_concrete(question):
            return ModeRecommendation(
                mode="quick",
                confidence=0.7,
                reasoning=(
                    f"Only {n_items} items (< {WIDE_THRESHOLD_ITEMS}) "
                    f"+ concrete request → Quick. Wide would over-scale."
                ),
                warnings=warnings + [
                    f"items count {n_items} below Wide threshold "
                    f"{WIDE_THRESHOLD_ITEMS}"
                ],
                n_items=n_items,
                detected_shape=task_shape,
            )
        return ModeRecommendation(
            mode="deep",
            confidence=0.6,
            reasoning=(
                f"{n_items} items + open-ended question → Deep "
                f"(small for Wide; question warrants pipeline)."
            ),
            warnings=warnings + [
                f"items count {n_items} below Wide threshold "
                f"{WIDE_THRESHOLD_ITEMS}; defaulting to Deep"
            ],
            n_items=n_items,
            detected_shape=task_shape,
        )

    # 5-7) No items list
    if _looks_concrete(question):
        return ModeRecommendation(
            mode="quick",
            confidence=0.8,
            reasoning="Concrete one-shot request, no per-item list → Quick.",
            warnings=warnings,
            n_items=0,
            detected_shape=task_shape,
        )

    # Default: Deep (this is a serious-research tool)
    return ModeRecommendation(
        mode="deep",
        confidence=0.7,
        reasoning=(
            "Open-ended research question, no per-item list → Deep "
            "(10-phase Expedition pipeline)."
        ),
        warnings=warnings,
        n_items=0,
        detected_shape=task_shape,
    )


def _validate_explicit(
    mode: Mode, n_items: int, question: str
) -> ModeRecommendation:
    """Honor the user's explicit mode but warn on obvious mismatches."""
    warnings: list[str] = []
    if mode == "wide":
        if n_items < WIDE_THRESHOLD_ITEMS:
            warnings.append(
                f"--mode wide forced but only {n_items} items (< "
                f"{WIDE_THRESHOLD_ITEMS}). Wide will refuse at decompose; "
                f"use Quick or Deep instead."
            )
        elif n_items > WIDE_MAX_ITEMS:
            warnings.append(
                f"--mode wide forced but {n_items} items > "
                f"{WIDE_MAX_ITEMS} cap. Wide will refuse at decompose; "
                f"use systematic-review."
            )
    if mode == "quick" and n_items >= WIDE_THRESHOLD_ITEMS:
        warnings.append(
            f"--mode quick forced but {n_items} items would benefit "
            f"from Wide parallel fan-out."
        )
    if mode == "deep" and n_items > WIDE_MAX_ITEMS:
        warnings.append(
            f"--mode deep forced with {n_items} items — Deep loads "
            f"all items sequentially; consider Wide or systematic-review."
        )
    return ModeRecommendation(
        mode=mode,
        confidence=1.0,
        reasoning=f"--mode {mode} explicitly set; honoring user choice.",
        warnings=warnings,
        n_items=n_items,
    )


def _infer_shape(
    question: str, items: list[dict] | None
) -> TaskShape:
    """Infer 'per-item' (every item processed identically) vs
    'one-question' (single inquiry, possibly with supporting items).
    """
    if items and len(items) >= WIDE_THRESHOLD_ITEMS:
        return "per-item"
    return "one-question"


def _looks_concrete(question: str) -> bool:
    """True if the question reads as a concrete one-shot, not research.

    Heuristics:
      - Contains a Quick-keyword (summarize/extract/translate/...) → True
      - Very short (< 4 words) → True
      - Contains an open-ended keyword (how/why/explain/...) → False
      - Has '?' → False (questions tend to be open-ended)
    """
    q = question.lower().strip()
    if not q:
        return False  # empty question → treat as ambiguous, fall to Deep
    words = q.split()
    if len(words) < 4:
        return True
    if any(kw in q for kw in _QUICK_KEYWORDS):
        return True
    if "?" in q:
        return False
    if any(w in _OPEN_ENDED_KEYWORDS for w in words):
        return False
    return False

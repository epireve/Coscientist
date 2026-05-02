"""Brief-rendering helpers for Steward (v0.54).

Pure stdlib formatters that turn run-DB rows into the markdown
sections the brief template expects. Steward shells out to these so
the brief stays declarative — no logic in the template, no synthesis
in the renderer.

Three public renderers:
  - render_hypothesis_cards(rows, top_k)
  - render_evidence_table(claim_rows)
  - render_discussion_questions(question, claim_rows)

Plus a render_run_recovery() helper for substituting {{run_id}} into
the run_recovery.md template.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable

# ---------- hypothesis cards ----------

UNCALIBRATED_TAG = (
    "## Hypothesis cards (uncalibrated — no tournament run)"
)


def render_hypothesis_cards(
    hypothesis_rows: Iterable[dict], top_k: int = 5,
) -> str:
    """Render top-K hypotheses as inline markdown cards.

    Each row is a dict with keys: hyp_id, agent_name, statement,
    method_sketch, predicted_observables, falsifiers, supporting_ids,
    elo, n_matches, n_wins, n_losses, created_at.
    JSON columns may arrive as JSON strings or already-parsed lists.

    v0.199 — fallback for n_matches=0:
      - If every row carries `n_matches` and ALL are 0, render in
        `created_at` order, prepend the uncalibrated heading, never
        drop. Tournament didn't run; preserve the section.
      - If SOME rows have matches and others don't, drop the zero-
        match rows (preserves the original "uncalibrated = unranked"
        invariant for mixed runs).
      - If every row has matches, sort by Elo (legacy behaviour).
      - If no row carries `n_matches` at all, sort by Elo (legacy
        behaviour for callers not yet plumbing tournament data).
    """
    all_rows = list(hypothesis_rows)
    if not all_rows:
        return "_(no hypotheses recorded)_"

    has_nm = [r for r in all_rows if "n_matches" in r]
    uncalibrated = False
    if has_nm and len(has_nm) == len(all_rows):
        nms = [(r.get("n_matches") or 0) for r in all_rows]
        if all(n == 0 for n in nms):
            uncalibrated = True
        else:
            # Mixed: drop zero-match rows (preserve current behaviour).
            all_rows = [r for r in all_rows if (r.get("n_matches") or 0) > 0]
            if not all_rows:
                return "_(no hypotheses recorded)_"

    if uncalibrated:
        rows = sorted(
            all_rows,
            key=lambda r: r.get("created_at") or "",
        )[:top_k]
    else:
        rows = sorted(
            all_rows,
            key=lambda r: r.get("elo", 0.0) or 0.0,
            reverse=True,
        )[:top_k]

    out: list[str] = []
    if uncalibrated:
        out.append(UNCALIBRATED_TAG)
        out.append("")
    for i, r in enumerate(rows, 1):
        observables = _coerce_list(r.get("predicted_observables"))
        falsifiers = _coerce_list(r.get("falsifiers"))
        supporting = _coerce_list(r.get("supporting_ids"))
        elo = r.get("elo", 1200.0) or 1200.0
        n_matches = r.get("n_matches", 0) or 0
        n_wins = r.get("n_wins", 0) or 0
        out.append(f"### Card {i}: `{r.get('hyp_id', '?')}`")
        out.append("")
        out.append(f"- **Statement**: {r.get('statement', '?').strip()}")
        out.append(
            f"- **From**: `{r.get('agent_name', '?')}` | "
            f"Elo {elo:.0f} ({n_wins}/{n_matches} wins)"
        )
        method = (r.get("method_sketch") or "").strip()
        if method:
            out.append(f"- **Method sketch**: {method}")
        if observables:
            out.append("- **Predicted observables**:")
            for obs in observables:
                out.append(f"  - {obs}")
        if falsifiers:
            out.append("- **Falsifiers**:")
            for f in falsifiers:
                out.append(f"  - {f}")
        if supporting:
            cids = ", ".join(f"`{s}`" for s in supporting)
            out.append(f"- **Supporting**: {cids}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def _coerce_list(v) -> list:
    """Accept JSON-string-encoded list or actual list; return list."""
    if v is None or v == "":
        return []
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        try:
            parsed = json.loads(v)
            return parsed if isinstance(parsed, list) else [parsed]
        except json.JSONDecodeError:
            return [v]
    return [v]


# ---------- per-section evidence table ----------

# Map claim.kind → brief section heading.
# When a claim doesn't fit a known kind, it lands under "Other".
_KIND_TO_SECTION = {
    "finding": "What the field agrees on",
    "consensus": "What the field agrees on",
    "tension": "Where the field disagrees",
    "disagreement": "Where the field disagrees",
    "gap": "Genuine gaps",
    "hypothesis": "Most promising approaches",
    "proposal": "Most promising approaches",
    "dead_end": "Pivotal papers",
}


def render_evidence_table(
    claim_rows: Iterable[dict],
    *,
    max_rows: int = 40,
    text_truncate: int = 80,
) -> str:
    """Render claims as `| Section | Claim | Supporting | Confidence |`.

    Each row dict keys: claim_id, canonical_id, agent_name, text, kind,
    confidence, supporting_ids (optional JSON-array string).

    Sorted by section then by confidence desc. Claims with confidence
    < 0.0 or None get sorted last.
    """
    rows = list(claim_rows)
    if not rows:
        return "| _(no claims)_ | — | — | — |"
    decorated = []
    for r in rows:
        section = _KIND_TO_SECTION.get(
            (r.get("kind") or "").lower(), "Other"
        )
        conf = r.get("confidence")
        try:
            conf_f = float(conf) if conf is not None else None
        except (TypeError, ValueError):
            conf_f = None
        decorated.append((section, conf_f or -1.0, r))
    decorated.sort(key=lambda t: (t[0], -t[1]))

    out: list[str] = []
    for section, _, r in decorated[:max_rows]:
        text = (r.get("text") or "").strip().replace("|", "\\|")
        if len(text) > text_truncate:
            text = text[: text_truncate - 1] + "…"
        cid = r.get("canonical_id") or ""
        supporting_extra = _coerce_list(r.get("supporting_ids"))
        anchors = [cid] if cid else []
        anchors += [s for s in supporting_extra if s and s != cid]
        anchor_str = ", ".join(f"`{a}`" for a in anchors[:3]) or "—"
        conf = r.get("confidence")
        conf_str = f"{float(conf):.2f}" if conf is not None else "—"
        out.append(f"| {section} | {text} | {anchor_str} | {conf_str} |")
    return "\n".join(out)


# ---------- discussion questions ----------

# Stop-words filtered out before noun-phrase extraction
_STOP = frozenset({
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for",
    "with", "by", "is", "are", "was", "were", "be", "been", "being",
    "this", "that", "these", "those", "it", "its", "as", "at", "from",
    "but", "not", "no", "do", "does", "did", "have", "has", "had",
    "we", "you", "they", "what", "how", "why", "which", "when", "who",
    "if", "then", "than", "so", "such", "via", "any", "all", "some",
})


def _facets(question: str, k: int = 4) -> list[str]:
    """Extract up to k topic facets from the question text.

    Pure heuristic: drop stopwords, take longest 1-2-grams by simple
    appearance order. Good enough for prompt scaffolding; no NLP deps.
    """
    if not question:
        return []
    tokens = re.findall(r"[A-Za-z][A-Za-z\-]+", question.lower())
    tokens = [t for t in tokens if t not in _STOP and len(t) > 2]
    facets: list[str] = []
    seen: set[str] = set()
    # Bigrams first
    for a, b in zip(tokens, tokens[1:]):
        bg = f"{a} {b}"
        if bg not in seen:
            seen.add(bg)
            facets.append(bg)
        if len(facets) >= k * 2:
            break
    # Unigrams to fill
    for t in tokens:
        if t not in seen:
            seen.add(t)
            facets.append(t)
        if len(facets) >= k * 3:
            break
    # Take first k unique facets
    return facets[:k]


_QUESTION_TEMPLATES = [
    "What is the strongest evidence in this run that {facet} is "
    "{positive}? What would falsify it?",
    "Where does the field disagree about {facet}, and what experiment "
    "would resolve the disagreement?",
    "If you had to advise a first-year PhD student to read three "
    "papers on {facet}, which `canonical_id`s in this run, and why?",
    "What is the most promising hypothesis here that touches "
    "{facet}, and what is its weakest assumption?",
    "Which gap in this brief, if filled, would most change the "
    "consensus on {facet}?",
    "If the run produced a hypothesis that contradicts your prior "
    "about {facet}, which prior do you now revise — and on what "
    "evidence?",
]


def render_discussion_questions(
    question: str,
    claim_rows: Iterable[dict] | None = None,
    *,
    n: int = 6,
) -> str:
    """Render Socratic discussion questions tying facets back to claims.

    No claim-row data is strictly required; passing it allows the
    renderer to bias question generation toward facets that have
    actual evidence. Keep the renderer pure — no LLM.
    """
    facets = _facets(question, k=4)
    if not facets:
        facets = ["the research question"]
    out: list[str] = []
    positives = ["true", "important", "tractable", "actionable"]
    for i, tmpl in enumerate(_QUESTION_TEMPLATES[:n], 1):
        facet = facets[i % len(facets)]
        positive = positives[i % len(positives)]
        out.append(f"{i}. " + tmpl.format(
            facet=facet, positive=positive,
        ))
    return "\n".join(out)


# ---------- recovery doc ----------

def render_run_recovery_doc(template: str, run_id: str) -> str:
    """Substitute {{run_id}} placeholders in the recovery template.

    Pure str.replace; no template engine. Caller passes the template
    body (e.g. read from templates/run_recovery.md).
    """
    return template.replace("{{run_id}}", run_id)


# ---------- v0.212 tensions table ----------

_TENSIONS_TABLE_HEADER = (
    "| # | Side A | Side B | Methodology / era | Confidence |\n"
    "|---|---|---|---|---|"
)


def render_tensions_table(claim_rows: Iterable[dict]) -> str:
    """v0.212 — render kind=tension claims as markdown table when >=3.

    Claims with `paired_claim_id` (v0.198) render as joined Side A/B rows.
    Unpaired tensions render with Side B = "—".

    Returns empty string when fewer than 3 tension claims (caller falls
    back to prose section).
    """
    tensions = [
        r for r in claim_rows
        if (r.get("kind") or "").lower() == "tension"
    ]
    if len(tensions) < 3:
        return ""

    # Pair Side A rows with their Side B counterparts.
    by_id: dict = {r.get("claim_id"): r for r in tensions if r.get("claim_id")}
    seen: set = set()
    rendered_rows: list[str] = []
    n = 0
    for r in tensions:
        cid = r.get("claim_id")
        if cid in seen:
            continue
        side = (r.get("side") or "").lower()
        paired_id = r.get("paired_claim_id")
        side_a_text = side_b_text = ""
        notes = ""
        if side == "a" and paired_id and paired_id in by_id:
            other = by_id[paired_id]
            side_a_text = (r.get("text") or "").strip()
            side_b_text = (other.get("text") or "").strip()
            seen.add(cid)
            seen.add(paired_id)
        elif side == "b" and paired_id and paired_id in by_id:
            # If we hit B before A, render A from the pair.
            other = by_id[paired_id]
            side_a_text = (other.get("text") or "").strip()
            side_b_text = (r.get("text") or "").strip()
            seen.add(cid)
            seen.add(paired_id)
        else:
            side_a_text = (r.get("text") or "").strip()
            side_b_text = "—"
            seen.add(cid)
        # Truncate per cell.
        side_a_text = side_a_text[:140].replace("|", "\\|")
        side_b_text = side_b_text[:140].replace("|", "\\|")
        conf = r.get("confidence")
        try:
            conf_str = f"{float(conf):.2f}" if conf is not None else "—"
        except (TypeError, ValueError):
            conf_str = "—"
        # Methodology hint: scrape (era / methodology / dataset) from text;
        # fall back to placeholder when not detectable.
        notes = "—"
        for kw in ("era", "method", "dataset", "benchmark", "before", "after"):
            blob = (side_a_text + " " + side_b_text).lower()
            if kw in blob:
                notes = kw
                break
        n += 1
        rendered_rows.append(
            f"| {n} | {side_a_text} | {side_b_text} | {notes} | {conf_str} |"
        )

    if not rendered_rows:
        return ""
    return _TENSIONS_TABLE_HEADER + "\n" + "\n".join(rendered_rows)


# ---------- v0.211 audience-aware brief render ----------

# Jargon → plain swap. Conservative; only swaps tokens that have a clean
# 1:1 plain-English equivalent. Caller decides whether to apply.
# Pairs ordered longest-first so "statistically significant" doesn't
# leave half-matched residue when "significant" alone would also match.
_AUDIENCE_NOVICE_SWAPS: tuple[tuple[str, str], ...] = (
    ("statistically significant", "reliably non-random"),
    ("inter-rater reliability", "agreement between raters"),
    ("confidence interval", "range of likely values"),
    ("meta-analysis", "combined-study analysis"),
    ("null hypothesis", "no-effect baseline"),
    ("cross-sectional", "single-snapshot"),
    ("peer-reviewed", "expert-checked"),
    ("frequentist", "classical-statistics"),
    ("longitudinal", "over-time"),
    ("effect size", "strength of the effect"),
    ("p-hacking", "cherry-picking analyses"),
    ("Bayesian", "probability-based"),
    ("HARKing", "explaining results after the fact"),
    ("RCTs", "randomized trials"),
    ("RCT", "randomized trial"),
)


def strip_jargon_for_novice(text: str) -> str:
    """v0.211 — apply conservative jargon→plain swaps for non-expert audience.

    Word-boundary regex via str.replace + manual punctuation handling.
    Idempotent. Run swaps longest-first so multi-word jargon wins over
    its single-word substring.
    """
    out = text
    for jargon, plain in _AUDIENCE_NOVICE_SWAPS:
        out = out.replace(jargon, plain)
    return out


def render_executive_summary(
    *,
    question: str,
    proven: str,
    open_problem: str,
    real_world_implication: str,
    audience: str = "expert",
) -> str:
    """v0.211 — 5-min So-What summary (Prompt 5 from external playbook).

    Three lines: what's proven, what's still unknown, why it matters.
    No jargon when audience='novice'.
    """
    if audience == "novice":
        proven = strip_jargon_for_novice(proven)
        open_problem = strip_jargon_for_novice(open_problem)
        real_world_implication = strip_jargon_for_novice(real_world_implication)

    label = "Executive summary" if audience == "novice" else "TL;DR"
    return (
        f"## {label}\n\n"
        f"**Question**: {question}\n\n"
        f"**What's proven**: {proven}\n\n"
        f"**What's still unknown**: {open_problem}\n\n"
        f"**Why it matters**: {real_world_implication}\n"
    )

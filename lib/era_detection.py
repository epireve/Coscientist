"""Empirical era detection via vocabulary-shift analysis.

v0.52.3 — replaces arbitrary year_min/year_max splits with empirically-
detected inflection points. Walks a corpus of papers (with year +
abstract) and finds years where the abstract n-gram distribution
shifts most sharply (Jensen-Shannon divergence). Those years are
candidate paradigm-shift markers.

Pure stdlib — no scipy, no numpy. Sliding-window comparison of n-gram
distributions across consecutive year bins. Returns ranked inflections;
caller (chronicler) picks which to use as era boundaries.

Method:
1. Group papers by year. Drop years with <N papers (default 3).
2. Compute n-gram (default unigram) frequency distribution per year.
3. For each adjacent year-pair, compute Jensen-Shannon divergence of
   their distributions.
4. Rank pairs by divergence. Top K = inflection candidates.

Why this beats arbitrary year cutoffs (lit-review-helper's pre-2015 +
post-2021 buckets): arbitrary buckets miss the actual paradigm shift
if it happened in 2018 or 2006. Empirical inflection detection finds
the shift wherever it is, mechanically.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

_TOKEN_RE = re.compile(r"[a-z][a-z0-9'-]+")
_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "but", "of", "in", "to", "for",
    "with", "on", "at", "by", "from", "as", "is", "are", "was", "were",
    "be", "been", "being", "this", "that", "these", "those", "it", "its",
    "we", "our", "such", "have", "has", "had", "can", "may",
    "will", "would", "should", "could", "use", "using", "used", "study",
    "studies", "paper", "papers", "research", "results", "method",
    "methods", "however", "thus", "therefore", "also", "more", "most",
    "than", "into", "between", "across", "through", "while", "their",
    "they", "which", "who", "what", "where", "when", "how",
})


@dataclass
class Inflection:
    """One detected era boundary candidate."""
    year_before: int
    year_after: int
    divergence: float       # Jensen-Shannon divergence, 0..1
    n_papers_before: int
    n_papers_after: int
    rising_terms: list[str]   # terms whose freq increased most across boundary
    falling_terms: list[str]  # terms whose freq decreased most

    def to_dict(self) -> dict:
        return {
            "year_before": self.year_before,
            "year_after": self.year_after,
            "divergence": round(self.divergence, 4),
            "n_papers_before": self.n_papers_before,
            "n_papers_after": self.n_papers_after,
            "rising_terms": self.rising_terms,
            "falling_terms": self.falling_terms,
        }


def _tokenize(text: str) -> list[str]:
    """Lowercase, strip stopwords, return unigram tokens."""
    return [
        t for t in _TOKEN_RE.findall(text.lower())
        if t not in _STOPWORDS and len(t) > 2
    ]


def _normalize(counts: Counter) -> dict[str, float]:
    total = sum(counts.values())
    if total == 0:
        return {}
    return {k: v / total for k, v in counts.items()}


def _js_divergence(p: dict[str, float], q: dict[str, float]) -> float:
    """Jensen-Shannon divergence in [0, 1] over union vocabulary.

    JS = 0.5 * KL(p || m) + 0.5 * KL(q || m), where m = 0.5*(p+q).
    Symmetric, bounded [0, 1] when using log base 2.
    """
    vocab = set(p) | set(q)
    if not vocab:
        return 0.0

    # Build full vectors over union vocab
    p_vec = {k: p.get(k, 0.0) for k in vocab}
    q_vec = {k: q.get(k, 0.0) for k in vocab}
    m_vec = {k: 0.5 * (p_vec[k] + q_vec[k]) for k in vocab}

    def _kl(a: dict[str, float], b: dict[str, float]) -> float:
        s = 0.0
        for k in a:
            if a[k] > 0 and b[k] > 0:
                s += a[k] * math.log2(a[k] / b[k])
        return s

    return 0.5 * _kl(p_vec, m_vec) + 0.5 * _kl(q_vec, m_vec)


def _top_movers(
    before: dict[str, float], after: dict[str, float], k: int = 5
) -> tuple[list[str], list[str]]:
    """Top-k rising + falling terms across the boundary.

    Rising: in `after` but rare/absent in `before` (delta > 0).
    Falling: in `before` but rare/absent in `after` (delta < 0).
    """
    vocab = set(before) | set(after)
    deltas = [
        (term, after.get(term, 0.0) - before.get(term, 0.0))
        for term in vocab
    ]
    deltas.sort(key=lambda x: x[1])
    falling = [t for t, _ in deltas[:k] if deltas[0][1] < 0]
    rising = [t for t, _ in reversed(deltas[-k:]) if deltas[-1][1] > 0]
    return rising, falling


def detect_inflections(
    papers: list[dict],
    *,
    min_papers_per_year: int = 3,
    top_k_inflections: int = 5,
    top_k_movers: int = 5,
) -> list[Inflection]:
    """Find paradigm-shift candidate years from paper abstracts.

    Args:
        papers: list of dicts with 'year' (int) + 'abstract' (str) keys.
            Missing year or empty abstract → paper skipped.
        min_papers_per_year: years with fewer papers than this are dropped
            (low-N years produce noisy distributions).
        top_k_inflections: return top-K year-boundary candidates ranked
            by JS divergence.
        top_k_movers: per-inflection, surface this many rising/falling
            terms.

    Returns ranked list of Inflection objects (highest divergence first).
    Empty list if too few years have enough papers to compare.
    """
    by_year: dict[int, list[str]] = {}
    for p in papers:
        y = p.get("year")
        a = p.get("abstract") or ""
        if not isinstance(y, int) or not a:
            continue
        by_year.setdefault(y, []).append(a)

    eligible_years = sorted(
        y for y, abs_list in by_year.items()
        if len(abs_list) >= min_papers_per_year
    )
    if len(eligible_years) < 2:
        return []

    # Per-year normalized distribution
    year_dist: dict[int, dict[str, float]] = {}
    for y in eligible_years:
        c: Counter = Counter()
        for abstract in by_year[y]:
            c.update(_tokenize(abstract))
        year_dist[y] = _normalize(c)

    # Compute JS for each adjacent pair in the ELIGIBLE-year list
    # (not strictly consecutive years — we walk eligible-year sequence)
    inflections: list[Inflection] = []
    for i in range(len(eligible_years) - 1):
        y_before = eligible_years[i]
        y_after = eligible_years[i + 1]
        d = _js_divergence(year_dist[y_before], year_dist[y_after])
        rising, falling = _top_movers(
            year_dist[y_before], year_dist[y_after], k=top_k_movers
        )
        inflections.append(Inflection(
            year_before=y_before,
            year_after=y_after,
            divergence=d,
            n_papers_before=len(by_year[y_before]),
            n_papers_after=len(by_year[y_after]),
            rising_terms=rising,
            falling_terms=falling,
        ))

    inflections.sort(key=lambda x: -x.divergence)
    return inflections[:top_k_inflections]


def render_summary(inflections: list[Inflection]) -> str:
    """Markdown summary of detected inflections for chronicler harvest."""
    if not inflections:
        return "_No inflection points detected (insufficient data)._"
    lines = [
        "## Detected paradigm-shift candidates",
        "",
        "| Boundary | JS divergence | Papers (before/after) | Rising | Falling |",
        "|---|---|---|---|---|",
    ]
    for inf in inflections:
        lines.append(
            f"| {inf.year_before} → {inf.year_after} "
            f"| {inf.divergence:.3f} "
            f"| {inf.n_papers_before} / {inf.n_papers_after} "
            f"| {', '.join(inf.rising_terms[:3])} "
            f"| {', '.join(inf.falling_terms[:3])} |"
        )
    return "\n".join(lines)

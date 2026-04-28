"""Concept-velocity metric over abstract n-grams.

v0.52.6 — per-term citation-pool growth/decline trajectory. Mechanically
surfaces emerging vs deprecated vocabulary in the run's corpus.

Method:
1. Tokenize abstracts → unigrams + bigrams (skip stopwords).
2. Per term, build a per-year frequency series (papers-containing-term).
3. Fit a simple trend per term: linear regression slope of frequency
   over years (normalized to 0..1). Positive slope = emerging,
   negative = deprecated.
4. Filter: terms appearing in <N papers total or <M distinct years
   are dropped (low signal).
5. Rank by absolute slope. Top emerging + top deprecated returned.

Pure stdlib. No scipy/numpy. Linear regression is OLS via simple
sums (1D).

Why this beats lit-review-helper's "note terminology shift" prose:
mechanical detection scales to corpora the user hasn't read. Surfaces
trends invisible to manual review.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass

_TOKEN_RE = re.compile(r"[a-z][a-z0-9'-]+")
_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "but", "of", "in", "to", "for",
    "with", "on", "at", "by", "from", "as", "is", "are", "was", "were",
    "be", "been", "being", "this", "that", "these", "those", "it", "its",
    "we", "our", "such", "have", "has", "had", "can", "may", "will",
    "would", "should", "could", "use", "using", "used", "study",
    "studies", "paper", "papers", "research", "results", "method",
    "methods", "however", "thus", "therefore", "also", "more", "most",
    "than", "into", "between", "across", "through", "while", "their",
    "they", "which", "who", "what", "where", "when", "how",
})


@dataclass
class ConceptTrend:
    """One term's velocity profile over the run's year range."""
    term: str
    slope: float            # OLS slope of normalized frequency vs year
    intercept: float
    total_papers: int       # papers containing term
    n_years: int            # distinct years term appears in
    first_year: int
    last_year: int
    direction: str          # "emerging" | "stable" | "deprecated"

    def to_dict(self) -> dict:
        return {
            "term": self.term,
            "slope": round(self.slope, 5),
            "total_papers": self.total_papers,
            "n_years": self.n_years,
            "first_year": self.first_year,
            "last_year": self.last_year,
            "direction": self.direction,
        }


def _tokenize_with_bigrams(text: str) -> list[str]:
    """Unigrams + bigrams, stopwords filtered."""
    unigrams = [
        t for t in _TOKEN_RE.findall(text.lower())
        if t not in _STOPWORDS and len(t) > 2
    ]
    bigrams = [
        f"{a} {b}" for a, b in zip(unigrams, unigrams[1:])
    ]
    return unigrams + bigrams


def _ols_slope(xs: list[int], ys: list[float]) -> tuple[float, float]:
    """Simple OLS for y = slope * x + intercept. Returns (slope, intercept).

    Pure stdlib. Returns (0.0, mean(ys)) if all xs identical.
    """
    n = len(xs)
    if n < 2:
        return 0.0, ys[0] if ys else 0.0
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den = sum((x - mean_x) ** 2 for x in xs)
    if den == 0:
        return 0.0, mean_y
    slope = num / den
    intercept = mean_y - slope * mean_x
    return slope, intercept


def compute_velocities(
    papers: list[dict],
    *,
    min_papers_per_term: int = 3,
    min_years_per_term: int = 2,
    top_k: int = 15,
    emerging_threshold: float = 0.01,
    deprecated_threshold: float = -0.01,
) -> list[ConceptTrend]:
    """Compute velocity per term across a corpus.

    Args:
        papers: list of {year: int, abstract: str} dicts.
        min_papers_per_term: term must appear in ≥N papers total.
        min_years_per_term: term must span ≥N distinct years (else
            slope is degenerate).
        top_k: return top K emerging + top K deprecated by |slope|.
        emerging_threshold / deprecated_threshold: slope cutoffs for
            direction labeling. Stable in [deprecated, emerging].

    Returns trend list sorted by direction then slope. Empty if too
    few papers / no eligible terms.
    """
    # Build year × term presence map. Each term counted at most once
    # per paper, so frequency = papers-containing-term per year.
    by_year_term: dict[int, Counter] = defaultdict(Counter)
    by_year_total: dict[int, int] = defaultdict(int)
    term_total_papers: Counter = Counter()
    term_years: dict[str, set[int]] = defaultdict(set)
    paper_years: list[int] = []

    for p in papers:
        y = p.get("year")
        a = p.get("abstract") or ""
        if not isinstance(y, int) or not a:
            continue
        paper_years.append(y)
        by_year_total[y] += 1
        seen_in_paper = set(_tokenize_with_bigrams(a))
        for term in seen_in_paper:
            by_year_term[y][term] += 1
            term_total_papers[term] += 1
            term_years[term].add(y)

    if not paper_years:
        return []

    eligible_terms = [
        t for t, n in term_total_papers.items()
        if n >= min_papers_per_term
        and len(term_years[t]) >= min_years_per_term
    ]
    if not eligible_terms:
        return []

    sorted_years = sorted(set(paper_years))
    trends: list[ConceptTrend] = []
    for term in eligible_terms:
        # Build (year, normalized_freq) series for years where term appears.
        # Normalize by paper count that year (term might appear in 3 of 10
        # papers in 2020 vs 8 of 10 in 2025; we want the share, not raw count).
        xs = []
        ys = []
        for y in sorted_years:
            total = by_year_total[y]
            if total == 0:
                continue
            cnt = by_year_term[y].get(term, 0)
            xs.append(y)
            ys.append(cnt / total)

        if len(xs) < min_years_per_term:
            continue

        slope, intercept = _ols_slope(xs, ys)
        if slope > emerging_threshold:
            direction = "emerging"
        elif slope < deprecated_threshold:
            direction = "deprecated"
        else:
            direction = "stable"

        years_with = sorted(term_years[term])
        trends.append(ConceptTrend(
            term=term,
            slope=slope,
            intercept=intercept,
            total_papers=term_total_papers[term],
            n_years=len(term_years[term]),
            first_year=years_with[0],
            last_year=years_with[-1],
            direction=direction,
        ))

    # Top-K emerging (slope desc), top-K deprecated (slope asc)
    emerging = sorted(
        [t for t in trends if t.direction == "emerging"],
        key=lambda t: -t.slope,
    )[:top_k]
    deprecated = sorted(
        [t for t in trends if t.direction == "deprecated"],
        key=lambda t: t.slope,
    )[:top_k]

    return emerging + deprecated


def render_summary(trends: list[ConceptTrend], top_k: int = 10) -> str:
    """Markdown summary for steward / chronicler / weaver."""
    if not trends:
        return "_No concept-velocity trends detected (corpus too sparse)._"

    emerging = [t for t in trends if t.direction == "emerging"][:top_k]
    deprecated = [t for t in trends if t.direction == "deprecated"][:top_k]

    lines = ["## Concept velocity (vocabulary trends)", ""]
    if emerging:
        lines += [
            "### Emerging terms",
            "",
            "| Term | Slope | Papers | Years |",
            "|---|---|---|---|",
        ]
        for t in emerging:
            lines.append(
                f"| `{t.term}` | +{t.slope:.4f} | {t.total_papers} "
                f"| {t.first_year}–{t.last_year} ({t.n_years}) |"
            )
        lines.append("")

    if deprecated:
        lines += [
            "### Deprecated terms",
            "",
            "| Term | Slope | Papers | Years |",
            "|---|---|---|---|",
        ]
        for t in deprecated:
            lines.append(
                f"| `{t.term}` | {t.slope:.4f} | {t.total_papers} "
                f"| {t.first_year}–{t.last_year} ({t.n_years}) |"
            )
    return "\n".join(lines)

"""Citation resolver (v0.58).

Heuristic, pure-stdlib resolver for incomplete citation references.
Given an informal reference like "Smith 2020", "Vaswani et al., 2017
— Attention", or a free-form mix of keywords + year, parse it into a
structured `PartialCitation`, then score Semantic Scholar candidates
to pick the best canonical match.

Designed for the orchestrator-harvest pattern: this module never
calls an MCP. The orchestrator harvests S2 candidates with a focused
query, dumps to JSON, and the resolve.py CLI scores them against a
parsed partial.

Public API:
  parse_partial(text) -> PartialCitation
  score_match(partial, candidate) -> float in [0, 1]
  pick_best(partial, candidates) -> (best_dict|None, score)
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# ---- tokens ---------------------------------------------------------

_STOP = frozenset({
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "for",
    "with", "by", "is", "are", "was", "were", "as", "at", "from",
    "but", "not", "et", "al", "etal", "vs", "via",
})

# Common venue hints we may want to lift out of free-form text.
_VENUE_HINTS = (
    "neurips", "nips", "icml", "iclr", "acl", "emnlp", "naacl",
    "cvpr", "iccv", "eccv", "aaai", "ijcai", "kdd", "www",
    "nature", "science", "cell", "plos", "jama", "bmj", "lancet",
    "arxiv", "biorxiv", "medrxiv",
)


def _strip_diacritics(s: str) -> str:
    # Cheap fold: only handle the common-enough ASCII variants we'd see
    # in author lastnames. No `unicodedata` to keep it simple.
    table = str.maketrans({
        "á": "a", "à": "a", "ä": "a", "â": "a", "ã": "a", "å": "a",
        "é": "e", "è": "e", "ë": "e", "ê": "e",
        "í": "i", "ì": "i", "ï": "i", "î": "i",
        "ó": "o", "ò": "o", "ö": "o", "ô": "o", "õ": "o", "ø": "o",
        "ú": "u", "ù": "u", "ü": "u", "û": "u",
        "ñ": "n", "ç": "c", "ß": "ss",
    })
    return s.translate(table)


def _tokenize(text: str) -> list[str]:
    """Lowercase, drop stopwords, keep tokens of length ≥ 3."""
    folded = _strip_diacritics((text or "").lower())
    raw = re.findall(r"[a-z][a-z\-']+", folded)
    return [t for t in raw if t not in _STOP and len(t) >= 3]


def _norm_lastname(name: str) -> str:
    """Normalize an author lastname for comparison."""
    return _strip_diacritics((name or "").lower()).strip().strip(".,;")


# ---- partial citation -----------------------------------------------

@dataclass(frozen=True)
class PartialCitation:
    """Heuristic parse of a free-form citation reference."""
    raw: str
    authors: tuple[str, ...]      # lowercased lastnames
    year: int | None
    title_tokens: frozenset[str]
    venue_hint: str | None

    def to_dict(self) -> dict:
        return {
            "raw": self.raw,
            "authors": list(self.authors),
            "year": self.year,
            "title_tokens": sorted(self.title_tokens),
            "venue_hint": self.venue_hint,
        }


# Year detector: 4 digits, 1900-2099, anchored on word boundaries.
_YEAR_RE = re.compile(r"\b(19[0-9]{2}|20[0-9]{2})\b")

# A "name-y" token: starts capitalized in the original, made of letters,
# possibly with apostrophe or hyphen. We resolve case from the raw input
# rather than the lowercased copy.
_NAMEISH_RE = re.compile(r"[A-Z][a-zA-Z'’\-]+")


def _extract_year(text: str) -> tuple[int | None, str]:
    """Return (year, text-with-year-removed)."""
    m = _YEAR_RE.search(text or "")
    if not m:
        return None, text or ""
    y = int(m.group(1))
    cleaned = (text[: m.start()] + text[m.end() :]).strip()
    return y, cleaned


def _extract_authors(raw: str, year: int | None) -> tuple[str, ...]:
    """Pull lastnames from the prefix of `raw`. Cope with several styles:
       - "Smith"
       - "Vaswani et al."
       - "He, Zhang, Ren, Sun"
       - "Smith and Jones"
       - "Vaswani 2017 Attention is all you need"
    """
    raw = raw or ""

    # Take only text before the year (when present) — title typically
    # follows the year in informal references.
    if year is not None:
        m = _YEAR_RE.search(raw)
        if m:
            head = raw[: m.start()]
        else:
            head = raw
    else:
        head = raw

    # Cut at em-dash / colon / parenthesis — title or venue follows.
    head = re.split(r"[—–:()\[\]]", head, maxsplit=1)[0]
    # Strip a trailing comma+title pattern: "Smith, Title Words" — but we
    # only want to do this when there's a *single* author followed by a
    # comma + many words. Heuristic: if there's exactly one comma and the
    # text after it has 3+ words, drop the tail.
    if head.count(",") == 1:
        before, after = head.split(",", 1)
        if len(after.strip().split()) >= 3:
            head = before

    # Drop "et al" markers.
    head = re.sub(r"\bet\.?\s*al\.?", "", head, flags=re.IGNORECASE)
    # Replace " and " with comma so split works uniformly.
    head = re.sub(r"\s+and\s+", ",", head, flags=re.IGNORECASE)

    out: list[str] = []
    if "," in head:
        # Comma-separated author list. Each part is one author.
        parts = [p.strip() for p in head.split(",") if p.strip()]
        for p in parts:
            words = re.findall(r"[A-Za-z'’\-]+", p)
            words = [w for w in words if not re.fullmatch(r"[A-Za-z]\.?", w or "")]
            if not words:
                continue
            # Lastname is conventionally the last token (Western
            # ordering); tolerate "van der Berg" via longest fallback.
            candidate = words[-1] if len(words[-1]) >= 3 else max(words, key=len)
            norm = _norm_lastname(candidate)
            if norm and norm not in _STOP and len(norm) >= 2:
                out.append(norm)
    else:
        # No commas: only the leading capitalized word(s) are authors —
        # "Vaswani 2017 Attention" → just "Vaswani". Walk tokens left to
        # right and stop as soon as we hit a non-capitalized word OR
        # we've collected one (since without a separator there's no way
        # to tell where author ends and title begins).
        for tok in re.findall(r"[A-Za-z'’\-]+", head):
            if re.fullmatch(r"[A-Za-z]\.?", tok):
                continue  # initial
            if tok[0].isupper():
                norm = _norm_lastname(tok)
                if norm and norm not in _STOP and len(norm) >= 2:
                    out.append(norm)
                    break  # only the leading capitalized name
            else:
                break

    # Dedupe in order.
    seen = set()
    uniq: list[str] = []
    for a in out:
        if a not in seen:
            seen.add(a)
            uniq.append(a)
    return tuple(uniq)


def _extract_venue_hint(text: str) -> str | None:
    low = (text or "").lower()
    for v in _VENUE_HINTS:
        if re.search(rf"\b{re.escape(v)}\b", low):
            return v
    return None


def parse_partial(text: str) -> PartialCitation:
    """Heuristic parse of a free-form citation reference."""
    raw = text or ""
    year, _without_year = _extract_year(raw)
    authors = _extract_authors(raw, year)

    # Title tokens: everything that isn't an author lastname or the year,
    # tokenized + stopworded. We also drop tokens equal to extracted authors.
    title_text = raw
    # Strip the leading "<authors><sep>" portion if any author was found —
    # the title generally lives after a comma, em-dash, parenthesis, or year.
    if year is not None:
        # title is usually after the year, but not always. Try both halves
        # and union them — title_tokens is a set anyway.
        pass

    tokens = set(_tokenize(title_text))
    for a in authors:
        tokens.discard(a)
    # Drop venue hints from title tokens.
    venue = _extract_venue_hint(raw)
    if venue:
        tokens.discard(venue)

    return PartialCitation(
        raw=raw,
        authors=authors,
        year=year,
        title_tokens=frozenset(tokens),
        venue_hint=venue,
    )


# ---- scoring --------------------------------------------------------

def _candidate_authors(c: dict) -> list[str]:
    """Pull lastnames from a candidate dict. Tolerate several shapes:
       - {"authors": ["Smith, J.", "Jones, A."]}
       - {"authors": [{"name": "Jane Smith"}, {"name": "..."}]}
    """
    out: list[str] = []
    for a in c.get("authors", []) or []:
        if isinstance(a, dict):
            name = a.get("name") or ""
        else:
            name = str(a)
        if not name:
            continue
        # Comma form: "Smith, John" -> lastname before comma
        if "," in name:
            ln = name.split(",", 1)[0]
        else:
            # Space form: take last whitespace-separated word
            parts = name.strip().split()
            ln = parts[-1] if parts else ""
        norm = _norm_lastname(ln)
        if norm:
            out.append(norm)
    return out


def _candidate_title_tokens(c: dict) -> frozenset[str]:
    return frozenset(_tokenize(c.get("title") or ""))


def _candidate_year(c: dict) -> int | None:
    y = c.get("year")
    if isinstance(y, int):
        return y
    if isinstance(y, str) and y.isdigit():
        return int(y)
    return None


def score_match(partial: PartialCitation, candidate: dict) -> float:
    """Score a candidate against a parsed partial.

    Components, weighted into [0, 1]:
      - author lastname overlap (0.45)
      - year exact match (0.25)
      - title token Jaccard (0.30)

    If neither side has any signal on a component, that component
    contributes 0 (we don't reward absence of information).
    """
    cand_authors = _candidate_authors(candidate)
    cand_year = _candidate_year(candidate)
    cand_tokens = _candidate_title_tokens(candidate)

    # Author overlap — fraction of the partial's authors that appear
    # in the candidate's author list. If the partial has no authors,
    # this component is neutral (0).
    a_score = 0.0
    if partial.authors:
        cand_set = set(cand_authors)
        hits = sum(1 for a in partial.authors if a in cand_set)
        a_score = hits / len(partial.authors)

    # Year — strict equality, otherwise 0.
    y_score = 0.0
    if partial.year is not None and cand_year is not None:
        y_score = 1.0 if partial.year == cand_year else 0.0

    # Title token Jaccard.
    t_score = 0.0
    if partial.title_tokens and cand_tokens:
        inter = partial.title_tokens & cand_tokens
        union = partial.title_tokens | cand_tokens
        t_score = len(inter) / len(union) if union else 0.0

    score = 0.45 * a_score + 0.25 * y_score + 0.30 * t_score
    # Clamp for floating-point safety.
    if score < 0.0:
        return 0.0
    if score > 1.0:
        return 1.0
    return score


# Default acceptance threshold — below this, pick_best returns (None, 0).
ACCEPT_THRESHOLD = 0.5


def pick_best(
    partial: PartialCitation,
    candidates: list[dict],
    threshold: float = ACCEPT_THRESHOLD,
) -> tuple[dict | None, float]:
    """Return the highest-scoring candidate above `threshold`, else (None, 0)."""
    if not candidates:
        return None, 0.0
    best: dict | None = None
    best_score = -1.0
    for c in candidates:
        s = score_match(partial, c)
        if s > best_score:
            best_score = s
            best = c
    if best is None or best_score < threshold:
        return None, 0.0
    return best, round(best_score, 4)

"""Shared text-analysis primitives for writing-style scripts.

Deterministic, stdlib-only. No LLM, no external deps.
"""

from __future__ import annotations

import re
from collections import Counter

HEDGES = re.compile(
    r"\b(may|might|could|perhaps|possibly|potentially|seem(s|ed)?|appear(s|ed)?|"
    r"suggest(s|ed)?|somewhat|relatively|arguably|likely|probably|apparent(ly)?|"
    r"tend(s|ed)? to|in a sense)\b",
    re.IGNORECASE,
)

FIRST_PERSON = re.compile(r"\b(we|our|ours|us|ourselves|I|my|mine|myself)\b", re.IGNORECASE)

PASSIVE_VOICE = re.compile(
    r"\b(is|are|was|were|be|been|being)\s+\w+(ed|en)\b", re.IGNORECASE
)

BRITISH_MARKERS = re.compile(
    r"\b(colour|behaviour|centre|analyse|organis(e|ed|ation)|modelled|learnt|"
    r"labour|favour|neighbour)\b",
    re.IGNORECASE,
)
AMERICAN_MARKERS = re.compile(
    r"\b(color|behavior|center|analyze|organiz(e|ed|ation)|modeled|learned|"
    r"labor|favor|neighbor)\b",
    re.IGNORECASE,
)

# Common English stop words (small list — we care about content words)
STOPWORDS = set(
    "a an and are as at be but by for from has have he her his i in is it its "
    "of on or our she that the their them then there they this to was we were "
    "what when where which who will with you your not no nor also only just "
    "so than too very can could may might must shall should will would".split()
)

SIGNPOST_PATTERNS = re.compile(
    r"^(First|Second|Third|Next|Then|Finally|Moreover|Furthermore|However|"
    r"In particular|Note that|Specifically|Importantly|Crucially|Nonetheless|"
    r"Consequently|Therefore|Thus|For instance|For example|In contrast|"
    r"On the other hand|In summary|To summarize)[\s,]",
    re.IGNORECASE,
)

SENTENCE_SPLITTER = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
PARAGRAPH_SPLITTER = re.compile(r"\n\s*\n")
WORD_TOKEN = re.compile(r"\b[a-zA-Z][a-zA-Z'-]*\b")


def strip_markdown(text: str) -> str:
    """Remove common markdown features that pollute text stats."""
    text = re.sub(r"```[\s\S]*?```", " ", text)       # fenced code
    text = re.sub(r"`[^`]*`", " ", text)               # inline code
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)  # images
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)  # keep link text
    text = re.sub(r"[#*_~>|]+", " ", text)             # md punctuation
    text = re.sub(r"\$[^$]*\$", " ", text)             # inline math
    text = re.sub(r"\\cite\{[^}]*\}", " ", text)       # bibtex cites
    text = re.sub(r"\[@[^\]]*\]", " ", text)           # pandoc cites
    return text


def sentences(text: str) -> list[str]:
    """Split into sentences. Rough but good enough for stats."""
    stripped = strip_markdown(text)
    raw = SENTENCE_SPLITTER.split(stripped)
    return [s.strip() for s in raw if len(s.strip().split()) >= 3]


def paragraphs(text: str) -> list[str]:
    return [p.strip() for p in PARAGRAPH_SPLITTER.split(text) if p.strip()]


def words(text: str) -> list[str]:
    return WORD_TOKEN.findall(strip_markdown(text))


def hedge_density(sents: list[str]) -> float:
    if not sents:
        return 0.0
    return sum(1 for s in sents if HEDGES.search(s)) / len(sents)


def first_person_rate(sents: list[str]) -> float:
    if not sents:
        return 0.0
    return sum(1 for s in sents if FIRST_PERSON.search(s)) / len(sents)


def passive_voice_rate(sents: list[str]) -> float:
    if not sents:
        return 0.0
    return sum(1 for s in sents if PASSIVE_VOICE.search(s)) / len(sents)


def british_or_american(text: str) -> str:
    b = len(BRITISH_MARKERS.findall(text))
    a = len(AMERICAN_MARKERS.findall(text))
    if a == b == 0:
        return "unknown"
    return "uk" if b > a else "us"


def sentence_length_stats(sents: list[str]) -> tuple[float, float]:
    lengths = [len(s.split()) for s in sents]
    if not lengths:
        return (0.0, 0.0)
    mean = sum(lengths) / len(lengths)
    var = sum((n - mean) ** 2 for n in lengths) / len(lengths)
    return (mean, var ** 0.5)


def signpost_phrases(sents: list[str], top_k: int = 10) -> list[str]:
    matches: list[str] = []
    for s in sents:
        m = SIGNPOST_PATTERNS.match(s)
        if m:
            matches.append(m.group(0).rstrip(",; "))
    counts = Counter(matches)
    return [phrase for phrase, _ in counts.most_common(top_k)]


def sentence_starters(sents: list[str], top_k: int = 10) -> list[str]:
    """Most common first-word or two-word openings."""
    starts: list[str] = []
    for s in sents:
        toks = s.split()
        if toks:
            starts.append(" ".join(toks[:2]))
    return [w for w, _ in Counter(starts).most_common(top_k)]


def top_terms(words_list: list[str], top_k: int = 30) -> dict[str, int]:
    filtered = [w.lower() for w in words_list
                if w.lower() not in STOPWORDS and len(w) > 2]
    return dict(Counter(filtered).most_common(top_k))


def paragraph_length_stats(paras: list[str]) -> tuple[float, float]:
    if not paras:
        return (0.0, 0.0)
    counts = [len(sentences(p)) for p in paras]
    mean = sum(counts) / len(counts)
    var = sum((n - mean) ** 2 for n in counts) / len(counts)
    return (mean, var ** 0.5)

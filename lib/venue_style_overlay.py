"""Venue style overlays (v0.60).

Per-venue stylistic norms (voice, tense, first-person convention, hedge
tolerance) layered on top of `lib/venue_match.py`'s domain/tier registry.

`writing-style/audit.py` measures *consistency with the author's prior
voice*. This module measures *fit to a target venue's house style* —
e.g. NeurIPS expects "we show", clinical journals tolerate passive voice,
Nature dislikes excessive hedging.

Pure stdlib. No LLM. Heuristic regex + counting; same primitives as
`_textstats.py` but rebuilt here so the lib doesn't depend on a script.

Public API:
    OVERLAYS                                    # dict[str, VenueStyleOverlay]
    VenueStyleOverlay                           # dataclass
    StyleFinding                                # dataclass
    list_overlays() -> list[str]
    get_overlay(name: str) -> VenueStyleOverlay
    audit_text_against_overlay(text, overlay) -> list[StyleFinding]
    render_audit_brief(findings, overlay) -> str
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

VoicePref = Literal["active", "passive", "mixed"]
TensePref = Literal["present", "past", "mixed"]
PronounPref = Literal["we", "the authors", "either"]
HedgeTolerance = Literal["low", "medium", "high"]


@dataclass
class VenueStyleOverlay:
    venue_name: str
    voice_preference: VoicePref
    tense_preference: TensePref
    we_vs_authors_preference: PronounPref
    hedge_tolerance: HedgeTolerance
    notes: list[str] = field(default_factory=list)


@dataclass
class StyleFinding:
    kind: str               # "voice" | "tense" | "pronoun" | "hedge"
    severity: str           # "info" | "minor" | "major"
    line_or_pos: int        # 0 = whole-text finding; otherwise 1-indexed sentence
    evidence: str
    suggestion: str

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "severity": self.severity,
            "line_or_pos": self.line_or_pos,
            "evidence": self.evidence,
            "suggestion": self.suggestion,
        }


# Registry. Names match `lib/venue_match.py` where overlap exists.
OVERLAYS: dict[str, VenueStyleOverlay] = {
    "NeurIPS": VenueStyleOverlay(
        venue_name="NeurIPS", voice_preference="active",
        tense_preference="present", we_vs_authors_preference="we",
        hedge_tolerance="low",
        notes=["Standard 'we show / we propose / we find' voice.",
               "Strong claims preferred; reviewers penalize over-hedging."],
    ),
    "ICLR": VenueStyleOverlay(
        venue_name="ICLR", voice_preference="active",
        tense_preference="present", we_vs_authors_preference="we",
        hedge_tolerance="low",
        notes=["Direct, claim-forward; OpenReview reviewers prefer specifics."],
    ),
    "ICML": VenueStyleOverlay(
        venue_name="ICML", voice_preference="active",
        tense_preference="present", we_vs_authors_preference="we",
        hedge_tolerance="low",
        notes=["Active 'we' voice; quantified claims, low hedge density."],
    ),
    "Nature": VenueStyleOverlay(
        venue_name="Nature", voice_preference="mixed",
        tense_preference="mixed", we_vs_authors_preference="either",
        hedge_tolerance="low",
        notes=["Formal but accessible; methods often passive, results active.",
               "Excessive hedging weakens broad-impact framing."],
    ),
    "Science": VenueStyleOverlay(
        venue_name="Science", voice_preference="mixed",
        tense_preference="mixed", we_vs_authors_preference="either",
        hedge_tolerance="low",
        notes=["Tight, declarative; mixed voice across sections."],
    ),
    "eLife": VenueStyleOverlay(
        venue_name="eLife", voice_preference="active",
        tense_preference="mixed", we_vs_authors_preference="we",
        hedge_tolerance="medium",
        notes=["Methods in past tense; results in present.",
               "Open peer review tolerates honest hedging on uncertainty."],
    ),
    "NEJM": VenueStyleOverlay(
        venue_name="NEJM", voice_preference="passive",
        tense_preference="past", we_vs_authors_preference="the authors",
        hedge_tolerance="medium",
        notes=["Clinical convention: passive voice, past tense for methods.",
               "'The authors' / impersonal phrasing common."],
    ),
    "JAMA": VenueStyleOverlay(
        venue_name="JAMA", voice_preference="passive",
        tense_preference="past", we_vs_authors_preference="the authors",
        hedge_tolerance="medium",
        notes=["Clinical convention: passive, past tense, impersonal."],
    ),
    "PLOS ONE": VenueStyleOverlay(
        venue_name="PLOS ONE", voice_preference="mixed",
        tense_preference="mixed", we_vs_authors_preference="either",
        hedge_tolerance="medium",
        notes=["Flexible; sound-science criterion, no strong house style."],
    ),
    "arXiv": VenueStyleOverlay(
        venue_name="arXiv", voice_preference="mixed",
        tense_preference="mixed", we_vs_authors_preference="either",
        hedge_tolerance="high",
        notes=["No house style; preprint server."],
    ),
    "Annual Reviews": VenueStyleOverlay(
        venue_name="Annual Reviews", voice_preference="mixed",
        tense_preference="present", we_vs_authors_preference="either",
        hedge_tolerance="medium",
        notes=["Review style; present tense to describe field consensus.",
               "Some sections use passive when summarizing prior work."],
    ),
    "Royal Society Open Science": VenueStyleOverlay(
        venue_name="Royal Society Open Science",
        voice_preference="active", tense_preference="mixed",
        we_vs_authors_preference="we", hedge_tolerance="medium",
        notes=["Registered-report friendly; explicit, falsifiable hypotheses.",
               "Active voice for hypotheses; methods may be past tense."],
    ),
}


def list_overlays() -> list[str]:
    return sorted(OVERLAYS.keys())


def get_overlay(name: str) -> VenueStyleOverlay:
    if name in OVERLAYS:
        return OVERLAYS[name]
    # Case-insensitive fallback
    lookup = {k.lower(): k for k in OVERLAYS}
    if name.lower() in lookup:
        return OVERLAYS[lookup[name.lower()]]
    raise KeyError(
        f"unknown venue overlay: {name!r}. "
        f"Known: {', '.join(list_overlays())}"
    )


# --- Heuristic detectors (regex; no NLP libs) -------------------------

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
_WORD = re.compile(r"\b[a-zA-Z][a-zA-Z'-]*\b")

# Active voice: first-person + past/present-tense verb (rough proxy)
_ACTIVE_PATTERN = re.compile(
    r"\b(we|our|ours|us|i|my)\s+[a-z]+", re.IGNORECASE,
)
# Passive: be-form + past participle
_PASSIVE_PATTERN = re.compile(
    r"\b(is|are|was|were|be|been|being)\s+\w+(ed|en)\b", re.IGNORECASE,
)
_PRESENT_MARKERS = re.compile(
    r"\b(show|shows|find|finds|demonstrate|demonstrates|present|presents|"
    r"propose|proposes|argue|argues|observe|observes|report|reports|"
    r"is|are|provides|provide)\b",
    re.IGNORECASE,
)
_PAST_MARKERS = re.compile(
    r"\b(showed|found|demonstrated|presented|proposed|argued|observed|"
    r"reported|was|were|provided|studied|analyzed|analysed|measured|"
    r"used|tested|examined|investigated|conducted|performed|developed|"
    r"compared|computed|calculated|trained|evaluated)\b",
    re.IGNORECASE,
)
_FIRST_PERSON = re.compile(
    r"\b(we|our|ours|us|ourselves|I|my|mine|myself)\b", re.IGNORECASE,
)
_THE_AUTHORS = re.compile(
    r"\bthe\s+authors?\b", re.IGNORECASE,
)
_HEDGES = re.compile(
    r"\b(may|might|could|perhaps|possibly|potentially|broadly|somewhat|"
    r"relatively|arguably|likely|probably|apparently|seems?|appears?|"
    r"suggest(s|ed)?|tend(s|ed)? to|in a sense|to some extent)\b",
    re.IGNORECASE,
)


def _sentences(text: str) -> list[str]:
    raw = _SENT_SPLIT.split(text.strip())
    return [s.strip() for s in raw if len(s.strip().split()) >= 3]


# Hedges per 100 words, by tolerance level.
_HEDGE_THRESHOLDS = {
    "low": 1.5,
    "medium": 3.0,
    "high": 6.0,
}


def _classify_voice(sents: list[str]) -> tuple[int, int]:
    """Return (active_count, passive_count) over the sentence list."""
    a = sum(1 for s in sents if _ACTIVE_PATTERN.search(s))
    p = sum(1 for s in sents if _PASSIVE_PATTERN.search(s))
    return a, p


def _classify_tense(sents: list[str]) -> tuple[int, int]:
    """Return (present_count, past_count). Both counted independently;
    a sentence may match both (mixed-tense)."""
    pres = sum(1 for s in sents if _PRESENT_MARKERS.search(s))
    past = sum(1 for s in sents if _PAST_MARKERS.search(s))
    return pres, past


def _hedge_density_per_100w(text: str) -> float:
    words = _WORD.findall(text)
    if not words:
        return 0.0
    hedges = len(_HEDGES.findall(text))
    return hedges * 100.0 / len(words)


def audit_text_against_overlay(
    text: str, overlay: VenueStyleOverlay,
) -> list[StyleFinding]:
    """Heuristic audit. Empty text → no findings."""
    findings: list[StyleFinding] = []
    text = text.strip()
    if not text:
        return findings

    sents = _sentences(text)
    if not sents:
        return findings

    # --- voice -------------------------------------------------------
    active, passive = _classify_voice(sents)
    total_voiced = active + passive
    if total_voiced > 0 and overlay.voice_preference != "mixed":
        active_share = active / total_voiced
        if overlay.voice_preference == "active" and active_share < 0.4:
            sev = "major" if active_share < 0.2 else "minor"
            findings.append(StyleFinding(
                kind="voice", severity=sev, line_or_pos=0,
                evidence=(
                    f"{passive} passive vs {active} active sentences "
                    f"({active_share:.0%} active)"
                ),
                suggestion=(
                    f"{overlay.venue_name} prefers active voice ('we show', "
                    f"'we find'). Rewrite passive constructions in first person."
                ),
            ))
        elif overlay.voice_preference == "passive" and active_share > 0.6:
            sev = "major" if active_share > 0.8 else "minor"
            findings.append(StyleFinding(
                kind="voice", severity=sev, line_or_pos=0,
                evidence=(
                    f"{active} active vs {passive} passive sentences "
                    f"({active_share:.0%} active)"
                ),
                suggestion=(
                    f"{overlay.venue_name} convention favors passive voice / "
                    f"impersonal phrasing in methods and results."
                ),
            ))

    # --- tense -------------------------------------------------------
    pres, past = _classify_tense(sents)
    total_tensed = pres + past
    if total_tensed > 0 and overlay.tense_preference != "mixed":
        present_share = pres / total_tensed
        if overlay.tense_preference == "present" and present_share < 0.4:
            sev = "major" if present_share < 0.2 else "minor"
            findings.append(StyleFinding(
                kind="tense", severity=sev, line_or_pos=0,
                evidence=(
                    f"{past} past-tense vs {pres} present-tense markers "
                    f"({present_share:.0%} present)"
                ),
                suggestion=(
                    f"{overlay.venue_name} prefers present-tense framing "
                    f"('we show', not 'we showed') for results and claims."
                ),
            ))
        elif overlay.tense_preference == "past" and present_share > 0.6:
            sev = "major" if present_share > 0.8 else "minor"
            findings.append(StyleFinding(
                kind="tense", severity=sev, line_or_pos=0,
                evidence=(
                    f"{pres} present-tense vs {past} past-tense markers "
                    f"({present_share:.0%} present)"
                ),
                suggestion=(
                    f"{overlay.venue_name} convention is past tense for "
                    f"methods and results ('we measured', 'we observed')."
                ),
            ))

    # --- pronoun (we vs the authors) --------------------------------
    fp_count = len(_FIRST_PERSON.findall(text))
    auth_count = len(_THE_AUTHORS.findall(text))
    if overlay.we_vs_authors_preference == "the authors" and fp_count > 0:
        sev = "minor" if fp_count <= 5 else "major"
        findings.append(StyleFinding(
            kind="pronoun", severity=sev, line_or_pos=0,
            evidence=(
                f"{fp_count} first-person pronouns ('we'/'our'/'I') found"
            ),
            suggestion=(
                f"{overlay.venue_name} prefers 'the authors' / impersonal "
                f"phrasing over first-person."
            ),
        ))
    elif overlay.we_vs_authors_preference == "we" and auth_count > 2 and fp_count == 0:
        findings.append(StyleFinding(
            kind="pronoun", severity="minor", line_or_pos=0,
            evidence=f"{auth_count} 'the authors' references, no first-person",
            suggestion=(
                f"{overlay.venue_name} prefers 'we' over 'the authors'."
            ),
        ))

    # --- hedge density ----------------------------------------------
    density = _hedge_density_per_100w(text)
    threshold = _HEDGE_THRESHOLDS[overlay.hedge_tolerance]
    if density > threshold:
        ratio = density / threshold
        sev = "major" if ratio >= 2.0 else ("minor" if ratio >= 1.5 else "info")
        findings.append(StyleFinding(
            kind="hedge", severity=sev, line_or_pos=0,
            evidence=(
                f"{density:.2f} hedges per 100 words "
                f"(threshold {threshold:.1f} for {overlay.hedge_tolerance} tolerance)"
            ),
            suggestion=(
                f"{overlay.venue_name} has {overlay.hedge_tolerance} hedge "
                f"tolerance. Trim 'may'/'might'/'could'/'possibly' where "
                f"the evidence supports a stronger claim."
            ),
        ))

    return findings


def render_audit_brief(
    findings: list[StyleFinding], overlay: VenueStyleOverlay,
) -> str:
    """Markdown brief over the findings. Always names venue + count."""
    lines = [
        f"# Venue style audit — {overlay.venue_name}",
        "",
        f"- voice preference: **{overlay.voice_preference}**",
        f"- tense preference: **{overlay.tense_preference}**",
        f"- pronoun convention: **{overlay.we_vs_authors_preference}**",
        f"- hedge tolerance: **{overlay.hedge_tolerance}**",
        "",
        f"**Findings: {len(findings)}**",
        "",
    ]
    if not findings:
        lines.append("_(no overlay-level deviations detected)_")
        if overlay.notes:
            lines.append("")
            lines.append("## Venue notes")
            for n in overlay.notes:
                lines.append(f"- {n}")
        return "\n".join(lines)

    by_sev = {"major": [], "minor": [], "info": []}
    for f in findings:
        by_sev.setdefault(f.severity, []).append(f)

    lines.append("| kind | severity | evidence | suggestion |")
    lines.append("|---|---|---|---|")
    for sev in ("major", "minor", "info"):
        for f in by_sev.get(sev, []):
            lines.append(
                f"| {f.kind} | {f.severity} | {f.evidence} | {f.suggestion} |"
            )

    if overlay.notes:
        lines.append("")
        lines.append("## Venue notes")
        for n in overlay.notes:
            lines.append(f"- {n}")
    return "\n".join(lines)

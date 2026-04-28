"""Contribution mapper (v0.55, A5 Tier A).

Positions a manuscript in the research landscape. Extracts
contributions, maps each to closest prior work via citation overlap +
concept distance, computes method/domain/finding distances, emits a
2D landscape projection.

Pure stdlib. Distances are simple Jaccard over token sets — good
enough for a coarse landscape view without ML dependencies.

Public API:
  decompose_contribution(text) -> Contribution tuple
  jaccard(a, b) -> float in [0, 1]
  contribution_distance(c1, c2) -> tuple of method/domain/finding floats
  project_2d(contributions, anchors) -> list of (x, y) per contribution
  render_landscape(projections, contributions, anchors) -> markdown
"""
from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass
class Contribution:
    """One claimed contribution from a manuscript."""
    label: str           # short tag, e.g. "C1"
    raw: str             # original sentence
    method: frozenset[str]
    domain: frozenset[str]
    finding: frozenset[str]

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "raw": self.raw,
            "method": sorted(self.method),
            "domain": sorted(self.domain),
            "finding": sorted(self.finding),
        }


@dataclass
class Anchor:
    """A prior-work anchor: a paper with extracted method/domain/finding."""
    canonical_id: str
    method: frozenset[str]
    domain: frozenset[str]
    finding: frozenset[str]

    @classmethod
    def from_dict(cls, d: dict) -> Anchor:
        return cls(
            canonical_id=d["canonical_id"],
            method=frozenset(d.get("method", []) or []),
            domain=frozenset(d.get("domain", []) or []),
            finding=frozenset(d.get("finding", []) or []),
        )


# Keyword registry — words that signal each axis. Anything matched
# becomes part of that axis token set. Stopwords stripped.
_METHOD_TOKENS = {
    "transformer", "attention", "convolution", "rnn", "lstm",
    "diffusion", "vae", "gan", "rl", "supervised", "unsupervised",
    "fine-tune", "distillation", "embedding", "kernel", "graph-neural",
    "regression", "classification", "clustering", "active-learning",
    "experiment", "rct", "longitudinal", "cross-sectional",
    "mri", "fmri", "eeg", "single-cell", "rna-seq",
    "sandboxed", "benchmark", "ablation",
}
_DOMAIN_TOKENS = {
    "memory", "vision", "language", "audio", "multimodal",
    "molecular", "protein", "genomic", "clinical", "robotics",
    "education", "finance", "physics", "chemistry", "biology",
    "neuroscience", "psychology", "economics", "policy",
    "code", "search", "recommender", "speech",
}
_FINDING_TOKENS = {
    "improvement", "scaling", "saturate", "saturation", "tradeoff",
    "robust", "robustness", "generalization", "overfit", "fail",
    "fails", "succeed", "succeeds", "outperform", "outperforms",
    "match", "matches", "exceed", "exceeds", "decrease", "decreases",
    "increase", "increases", "linear", "exponential", "power-law",
    "asymptote", "convergence", "divergence",
}
_STOP = frozenset({
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "for",
    "with", "by", "is", "are", "was", "were", "we", "show", "shows",
    "demonstrate", "demonstrates", "this", "that", "these", "those",
    "it", "its", "as", "at", "from", "but", "not",
})


def _tokenize(text: str) -> list[str]:
    return [
        t.lower() for t in re.findall(r"[A-Za-z][A-Za-z\-]+", text or "")
        if t.lower() not in _STOP and len(t) > 2
    ]


def decompose_contribution(label: str, text: str) -> Contribution:
    """Decompose a contribution sentence into method/domain/finding sets."""
    tokens = set(_tokenize(text))
    method = tokens & _METHOD_TOKENS
    domain = tokens & _DOMAIN_TOKENS
    finding = tokens & _FINDING_TOKENS
    return Contribution(
        label=label, raw=text,
        method=frozenset(method),
        domain=frozenset(domain),
        finding=frozenset(finding),
    )


def jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    """Jaccard similarity in [0, 1]; both empty -> 0.0."""
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def contribution_distance(
    c: Contribution, a: Anchor,
) -> tuple[float, float, float]:
    """Per-axis distance (1 - jaccard)."""
    return (
        1.0 - jaccard(c.method, a.method),
        1.0 - jaccard(c.domain, a.domain),
        1.0 - jaccard(c.finding, a.finding),
    )


def closest_anchor(
    c: Contribution, anchors: list[Anchor],
) -> tuple[Anchor | None, tuple[float, float, float]]:
    """Find the anchor with smallest total distance."""
    if not anchors:
        return None, (1.0, 1.0, 1.0)
    best, best_d = None, (1.0, 1.0, 1.0)
    best_total = math.inf
    for a in anchors:
        d = contribution_distance(c, a)
        total = sum(d)
        if total < best_total:
            best_total = total
            best, best_d = a, d
    return best, best_d


def project_2d(
    contributions: list[Contribution],
    anchors: list[Anchor],
) -> list[tuple[float, float]]:
    """Project each contribution to 2D using method-distance (x) +
    domain-distance (y) from its closest anchor.

    Higher x = method further from prior work; higher y = domain
    further. Origin = a contribution that perfectly overlaps the
    closest anchor on both axes.
    """
    out: list[tuple[float, float]] = []
    for c in contributions:
        _, (dm, dd, _df) = closest_anchor(c, anchors)
        out.append((round(dm, 3), round(dd, 3)))
    return out


def render_landscape(
    contributions: list[Contribution],
    anchors: list[Anchor],
) -> str:
    """Markdown landscape report."""
    lines = [
        "# Contribution landscape",
        "",
        f"**Contributions**: {len(contributions)}",
        f"**Anchors**: {len(anchors)}",
        "",
        "## Per-contribution position",
        "",
        "| label | method-d | domain-d | finding-d | closest anchor |",
        "|---|---|---|---|---|",
    ]
    for c in contributions:
        a, (dm, dd, df) = closest_anchor(c, anchors)
        anchor_str = f"`{a.canonical_id}`" if a else "_(no anchors)_"
        lines.append(
            f"| {c.label} | {dm:.2f} | {dd:.2f} | {df:.2f} | {anchor_str} |"
        )

    # ASCII landscape — coarse 5x5 grid based on method-d (x) + domain-d (y)
    lines += ["", "## ASCII landscape (method-distance × domain-distance)", ""]
    grid = [["·"] * 5 for _ in range(5)]
    for c in contributions:
        _, (dm, dd, _df) = closest_anchor(c, anchors)
        x = min(int(dm * 5), 4)
        y = min(int(dd * 5), 4)
        cell = grid[4 - y][x]
        grid[4 - y][x] = c.label[0] if cell == "·" else "*"
    lines.append("```")
    lines.append("domain")
    lines.append("  far →")
    for row in grid:
        lines.append("  " + " ".join(row))
    lines.append("        method far →")
    lines.append("```")

    return "\n".join(lines)

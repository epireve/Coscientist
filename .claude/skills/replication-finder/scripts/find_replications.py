#!/usr/bin/env python3
"""replication-finder — heuristic replication / refutation / follow-up scorer.

Read-only over the project graph. Pure stdlib.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_PLUGIN_ROOT = _HERE.parents[3]
_REPO_ROOT = (
    _HERE.parents[4] if (_HERE.parents[4] / "lib").exists()
    else _PLUGIN_ROOT
)
for _p in (_REPO_ROOT, _PLUGIN_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from lib.cache import connect_wal, paper_dir  # noqa: E402
from lib.project import project_db_path  # noqa: E402

# stem → (signal, weight). Order matters: refute stems checked before
# replicate so "fail to replicate" wins over "replicate".
REFUTE_STEMS = (
    "fail to replicate",
    "failed to replicate",
    "did not replicate",
    "does not replicate",
    "could not replicate",
    "contradict",
    "refute",
    "disconfirm",
    "inconsistent with",
)
REPLICATE_STEMS = (
    "replicate",
    "reproduce",
    "confirm",
    "corroborate",
    "successfully replicat",
)
FOLLOWUP_STEMS = (
    "extend",
    "build on",
    "builds on",
    "follow-up",
    "follow up",
    "building on",
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    if not text:
        return set()
    return {t for t in _TOKEN_RE.findall(text.lower()) if len(t) > 2}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _claims_text(meta: dict) -> str:
    """Concatenate claims[].text from a metadata dict."""
    parts: list[str] = []
    for c in meta.get("claims") or []:
        if isinstance(c, dict):
            t = c.get("text") or ""
        else:
            t = str(c)
        if t:
            parts.append(t)
    return " ".join(parts)


def _load_metadata(cid: str) -> dict | None:
    """Best-effort metadata.json read. Returns None if missing/bad."""
    try:
        p = paper_dir(cid) / "metadata.json"
        if not p.exists():
            return None
        return json.loads(p.read_text())
    except Exception:
        return None


def _load_content(cid: str) -> str:
    """Best-effort content.md read."""
    try:
        p = paper_dir(cid) / "content.md"
        if p.exists():
            return p.read_text(errors="ignore")
    except Exception:
        pass
    return ""


def _citers(project_id: str, target_cid: str) -> list[str]:
    """Find papers citing target_cid via graph_edges (relation=cites).

    Returns a list of citer canonical_ids.
    """
    db = project_db_path(project_id)
    if not db.exists():
        return []
    target_nid = f"paper:{target_cid}"
    con = connect_wal(db)
    try:
        rows = con.execute(
            "SELECT from_node FROM graph_edges "
            "WHERE to_node=? AND relation=?",
            (target_nid, "cites"),
        ).fetchall()
    finally:
        con.close()
    out: list[str] = []
    for r in rows:
        nid = r[0]
        if nid.startswith("paper:"):
            out.append(nid.split(":", 1)[1])
    return out


def _score_text(text: str) -> dict:
    """Stem-based scoring on lowercased text.

    Returns {refute: int, replicate: int, followup: int, hits: [str]}.
    Refute stems are checked first; any refute hit suppresses naive
    replicate hits arising from substrings like "fail to replicate"
    (which contains "replicate").
    """
    tl = (text or "").lower()
    hits: list[str] = []
    refute_n = 0
    replicate_n = 0
    followup_n = 0

    refute_spans: list[tuple[int, int]] = []
    for stem in REFUTE_STEMS:
        start = 0
        while True:
            i = tl.find(stem, start)
            if i < 0:
                break
            refute_n += 1
            hits.append(f"refute:{stem}")
            refute_spans.append((i, i + len(stem)))
            start = i + len(stem)

    def _in_refute_span(pos: int, ln: int) -> bool:
        for s, e in refute_spans:
            if pos >= s and pos + ln <= e:
                return True
        return False

    for stem in REPLICATE_STEMS:
        start = 0
        while True:
            i = tl.find(stem, start)
            if i < 0:
                break
            if not _in_refute_span(i, len(stem)):
                replicate_n += 1
                hits.append(f"replicate:{stem}")
            start = i + len(stem)

    for stem in FOLLOWUP_STEMS:
        start = 0
        while True:
            i = tl.find(stem, start)
            if i < 0:
                break
            followup_n += 1
            hits.append(f"followup:{stem}")
            start = i + len(stem)

    return {
        "refute": refute_n,
        "replicate": replicate_n,
        "followup": followup_n,
        "hits": hits,
    }


def _score_citer(
    citer_cid: str,
    target_tokens: set[str],
) -> dict | None:
    """Score one citer. Returns row dict or None if metadata missing."""
    meta = _load_metadata(citer_cid)
    if meta is None:
        return None
    claims_text = _claims_text(meta)
    body = _load_content(citer_cid)
    full = f"{claims_text}\n{body}"

    s = _score_text(full)

    citer_tokens = _tokens(claims_text)
    overlap = _jaccard(target_tokens, citer_tokens)

    reasons: list[str] = []
    score = 0.0

    if s["refute"] > 0:
        score += 2.0 * s["refute"]
        reasons.append(f"refute_stems={s['refute']}")
    if s["replicate"] > 0:
        score += 1.0 * s["replicate"]
        reasons.append(f"replicate_stems={s['replicate']}")
    if s["followup"] > 0:
        score += 0.5 * s["followup"]
        reasons.append(f"followup_stems={s['followup']}")

    overlap_boost = 0.0
    if overlap > 0.4:
        overlap_boost = 1.5 * overlap
        reasons.append(f"jaccard={overlap:.2f}_boost")
    elif overlap > 0.2:
        overlap_boost = 0.5 * overlap
        reasons.append(f"jaccard={overlap:.2f}")
    score += overlap_boost

    # Decide signal label.
    if s["refute"] > 0:
        if overlap > 0.4:
            signal = "refutes"
        else:
            signal = "refutes"
    elif s["replicate"] > 0:
        if overlap > 0.4:
            signal = "replicates"
        else:
            signal = "replicates"
    elif s["followup"] > 0:
        signal = "follow-up"
    else:
        signal = "weak"

    return {
        "cid": citer_cid,
        "signal": signal,
        "score": round(score, 4),
        "jaccard": round(overlap, 4),
        "reasons": reasons,
    }


def find_replications(
    project_id: str,
    canonical_id: str,
    top_n: int | None = None,
) -> list[dict] | dict:
    """Main entry. Returns list of scored citers, or {error: ...}."""
    db = project_db_path(project_id)
    if not db.exists():
        return {"error": f"no project DB at {db}"}

    target_meta = _load_metadata(canonical_id)
    if target_meta is None:
        return {"error": f"no metadata for target {canonical_id}"}

    target_tokens = _tokens(_claims_text(target_meta))

    citers = _citers(project_id, canonical_id)
    rows: list[dict] = []
    for cid in citers:
        row = _score_citer(cid, target_tokens)
        if row is not None:
            rows.append(row)

    rows.sort(key=lambda r: r["score"], reverse=True)
    if top_n is not None and top_n > 0:
        rows = rows[:top_n]
    return rows


def _format_text(rows: list[dict]) -> str:
    if not rows:
        return "(no citers found)"
    lines = []
    for r in rows:
        lines.append(
            f"{r['signal']:>11s}  score={r['score']:.2f}  "
            f"jaccard={r['jaccard']:.2f}  {r['cid']}"
        )
        if r["reasons"]:
            lines.append(f"             reasons: {', '.join(r['reasons'])}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project-id", required=True)
    p.add_argument("--canonical-id", required=True)
    p.add_argument("--top-n", type=int, default=None)
    p.add_argument("--format", choices=("json", "text"), default="json")
    args = p.parse_args(argv)

    try:
        result = find_replications(
            args.project_id, args.canonical_id, top_n=args.top_n,
        )
    except Exception as e:  # best-effort: never crash
        result = {"error": f"{type(e).__name__}: {e}"}

    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        if isinstance(result, dict) and "error" in result:
            print(f"ERROR: {result['error']}")
        else:
            print(_format_text(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())

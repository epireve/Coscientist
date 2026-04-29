#!/usr/bin/env python3
"""claim-cluster — token-Jaccard clustering of claims across project papers.

Read-only over the project artifact_index. Pure stdlib heuristic.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
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

MAX_PAPERS = 200

STOPWORDS = set(
    "a an and are as at be but by for from has have he her his i in is it "
    "its of on or our she that the their them then there they this to was "
    "we were what when where which who will with you your not no nor also "
    "only just so than too very can could may might must shall should "
    "would do does did done has had been being am if while because between "
    "into through during before after above below up down out off over "
    "under again further once here all any both each few more most other "
    "some such own same s t now".split()
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    if not text:
        return set()
    return {
        t for t in _TOKEN_RE.findall(text.lower())
        if len(t) > 2 and t not in STOPWORDS
    }


def _claim_texts(meta: dict) -> list[str]:
    out: list[str] = []
    for c in meta.get("claims") or []:
        if isinstance(c, dict):
            t = c.get("text") or ""
        else:
            t = str(c)
        if t:
            out.append(t)
    return out


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _load_metadata(cid: str) -> dict | None:
    try:
        p = paper_dir(cid) / "metadata.json"
        if not p.exists():
            return None
        return json.loads(p.read_text())
    except Exception:
        return None


def _project_paper_ids(project_id: str) -> list[str]:
    db = project_db_path(project_id)
    if not db.exists():
        return []
    con = connect_wal(db)
    try:
        rows = con.execute(
            "SELECT artifact_id FROM artifact_index "
            "WHERE project_id=? AND kind=? "
            "ORDER BY artifact_id",
            (project_id, "paper"),
        ).fetchall()
    finally:
        con.close()
    return [r[0] for r in rows]


# ---- union-find ----------------------------------------------------

class _UF:
    def __init__(self, n: int) -> None:
        self.p = list(range(n))

    def find(self, x: int) -> int:
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


def cluster_claims(
    project_id: str,
    min_jaccard: float = 0.4,
    min_cluster_size: int = 2,
    top_n: int | None = None,
) -> dict:
    """Main entry. Returns {clusters, outliers} or {error}."""
    db = project_db_path(project_id)
    if not db.exists():
        return {"error": f"no project DB at {db}"}

    cids = _project_paper_ids(project_id)
    if len(cids) > MAX_PAPERS:
        return {
            "error": (
                f"{len(cids)} papers exceeds cap {MAX_PAPERS} — "
                "all-pairs Jaccard is O(n^2); pass a representative "
                "subset instead."
            ),
        }

    if not cids:
        return {"clusters": [], "outliers": []}

    # Load each paper's claim texts + token bag.
    bags: list[set[str]] = []
    claims: list[list[str]] = []
    kept: list[str] = []
    for cid in cids:
        meta = _load_metadata(cid)
        if meta is None:
            continue
        ctexts = _claim_texts(meta)
        bag: set[str] = set()
        for t in ctexts:
            bag |= _tokens(t)
        if not bag:
            # No claim tokens — keep as outlier candidate (size 1).
            kept.append(cid)
            claims.append(ctexts)
            bags.append(bag)
            continue
        kept.append(cid)
        claims.append(ctexts)
        bags.append(bag)

    n = len(kept)
    uf = _UF(n)
    for i in range(n):
        for j in range(i + 1, n):
            if not bags[i] or not bags[j]:
                continue
            if _jaccard(bags[i], bags[j]) >= min_jaccard:
                uf.union(i, j)

    # Group by root.
    groups: dict[int, list[int]] = {}
    for i in range(n):
        r = uf.find(i)
        groups.setdefault(r, []).append(i)

    clusters: list[dict] = []
    outliers: list[str] = []
    next_id = 0
    for _root, idxs in groups.items():
        size = len(idxs)
        if size < min_cluster_size:
            for i in idxs:
                outliers.append(kept[i])
            continue
        # Aggregate tokens for heat + pick rep claim.
        all_tokens: list[str] = []
        all_claims: list[str] = []
        for i in idxs:
            all_tokens.extend(bags[i])
            all_claims.extend(claims[i])
        counts = Counter(all_tokens)
        top_tokens = [
            {"token": tok, "count": c}
            for tok, c in counts.most_common(10)
        ]
        rep = max(all_claims, key=len) if all_claims else ""
        clusters.append({
            "cluster_id": next_id,
            "papers": sorted(kept[i] for i in idxs),
            "size": size,
            "top_tokens": top_tokens,
            "representative_claim": rep,
        })
        next_id += 1

    # Largest clusters first.
    clusters.sort(key=lambda c: c["size"], reverse=True)
    if top_n is not None and top_n > 0:
        clusters = clusters[:top_n]

    return {"clusters": clusters, "outliers": sorted(outliers)}


# ---- CLI ------------------------------------------------------------

def _format_text(result: dict) -> str:
    if "error" in result:
        return f"ERROR: {result['error']}"
    clusters = result.get("clusters", [])
    outliers = result.get("outliers", [])
    lines: list[str] = []
    if not clusters and not outliers:
        return "(no papers in project)"
    for c in clusters:
        toks = ", ".join(
            f"{t['token']}({t['count']})" for t in c["top_tokens"][:5]
        )
        lines.append(
            f"cluster {c['cluster_id']}  size={c['size']}  "
            f"papers={','.join(c['papers'])}"
        )
        lines.append(f"  top: {toks}")
        rep = c["representative_claim"]
        if rep:
            lines.append(f"  rep: {rep[:120]}")
    if outliers:
        lines.append(f"outliers ({len(outliers)}): {', '.join(outliers)}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project-id", required=True)
    p.add_argument("--min-jaccard", type=float, default=0.4)
    p.add_argument("--min-cluster-size", type=int, default=2)
    p.add_argument("--top-n", type=int, default=50)
    p.add_argument("--format", choices=("json", "text"), default="json")
    args = p.parse_args(argv)

    try:
        result = cluster_claims(
            args.project_id,
            min_jaccard=args.min_jaccard,
            min_cluster_size=args.min_cluster_size,
            top_n=args.top_n,
        )
    except Exception as e:  # best-effort: never crash
        result = {"error": f"{type(e).__name__}: {e}"}

    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        print(_format_text(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())

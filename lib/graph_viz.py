"""Mermaid graph visualization for the citation/concept/author graph.

Pure-stdlib renderer. Produces a fenced ```mermaid``` markdown block
from the (`graph_nodes`, `graph_edges`)-style adjacency lists exposed
by `lib.graph`. Read-only — never writes any DB rows.

Node IDs in the project DB are typed strings like `paper:<cid>`,
`concept:<slug>`, `author:<s2_id>`, `manuscript:<mid>`. Mermaid is
fussy about identifiers — only `[A-Za-z0-9_]` survive cleanly — so
we sanitize each ID to a stable `n<hash>` token and emit the original
`<kind>:<ref>` as the node label.

Different kinds get different mermaid shapes:
  - paper       `[label]`      rectangle
  - concept     `((label))`    circle
  - author      `>label]`      asymmetric (flag)
  - manuscript  `{{label}}`    hexagon
  - other       `[label]`      rectangle (fallback)

Public API:
  render_mermaid(nodes, edges, *, max_nodes, hide_labels_above) -> str
  render_concept_subgraph(nodes, edges, root_concept_id, depth) -> str
  render_paper_lineage(nodes, edges, paper_cid, direction, depth) -> str
"""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict

# ----- ID sanitization ------------------------------------------------------

_SAFE_ID = re.compile(r"[^A-Za-z0-9_]")


def _safe_id(node_id: str) -> str:
    """Map any node_id string to a mermaid-safe identifier.

    We hash the original to avoid collisions when sanitization would
    otherwise collapse two distinct IDs to the same string.
    """
    h = hashlib.blake2s(node_id.encode("utf-8"), digest_size=4).hexdigest()
    base = _SAFE_ID.sub("_", node_id)[:24].strip("_") or "n"
    return f"n_{base}_{h}"


def _escape_label(text: str) -> str:
    """Escape a label so it survives mermaid syntax.

    Mermaid breaks on quotes, brackets, parens and pipes inside node
    text. Use HTML entities / safe substitutions where possible.
    """
    if not text:
        return ""
    # Replace characters mermaid treats as syntax inside node labels.
    repl = {
        '"': "&quot;",
        "'": "&#39;",
        "(": "&#40;",
        ")": "&#41;",
        "[": "&#91;",
        "]": "&#93;",
        "{": "&#123;",
        "}": "&#125;",
        "|": "&#124;",
        "<": "&lt;",
        ">": "&gt;",
        "\n": " ",
        "\r": " ",
        "`": "&#96;",
    }
    out = []
    for ch in text:
        out.append(repl.get(ch, ch))
    return "".join(out)


def _shape_for(kind: str, label: str) -> str:
    """Return the mermaid node-decl fragment for a kind+label."""
    safe = _escape_label(label)
    if kind == "paper":
        return f'["{safe}"]'
    if kind == "concept":
        return f'(("{safe}"))'
    if kind == "author":
        return f'>"{safe}"]'
    if kind == "manuscript":
        return f'{{{{"{safe}"}}}}'
    return f'["{safe}"]'


# ----- main renderer --------------------------------------------------------


def render_mermaid(
    nodes: list[dict],
    edges: list[dict],
    *,
    max_nodes: int = 50,
    hide_labels_above: int = 20,
) -> str:
    """Render a mermaid `graph TD` block.

    Args:
      nodes: each dict has `node_id`, `kind`, optional `label`,
             optional `degree` / `in_degree` (used for ranking).
      edges: each dict has `from_node`, `to_node`, `relation`,
             optional `weight`.
      max_nodes: hard cap on how many nodes to emit. If `nodes` has
                 a `degree` / `in_degree` field, top-N by that is
                 used; otherwise input order is preserved.
      hide_labels_above: when total emitted nodes exceeds this,
                         drop labels (mermaid still shows the safe
                         id, which is short and unique).

    Returns:
      A fenced mermaid markdown block, with a trailing newline.
    """
    # Always emit a valid (possibly empty) block.
    if not nodes:
        return "```mermaid\ngraph TD\n```\n"

    # Rank + truncate.
    def _rank(n: dict) -> int:
        return int(n.get("in_degree") or n.get("degree") or 0)

    if any(("in_degree" in n or "degree" in n) for n in nodes):
        ranked = sorted(nodes, key=_rank, reverse=True)
    else:
        ranked = list(nodes)
    ranked = ranked[: max(0, int(max_nodes))]
    keep_ids = {n["node_id"] for n in ranked}

    hide_labels = len(ranked) > int(hide_labels_above)

    lines: list[str] = ["```mermaid", "graph TD"]

    # Emit node declarations.
    for n in ranked:
        nid = n["node_id"]
        kind = n.get("kind") or _kind_of(nid)
        label = "" if hide_labels else (n.get("label") or nid)
        lines.append(f"  {_safe_id(nid)}{_shape_for(kind, label)}")

    # Collapse parallel edges between same (a,b) pair: show count if >1.
    edge_groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for e in edges:
        a, b = e.get("from_node"), e.get("to_node")
        if a in keep_ids and b in keep_ids:
            edge_groups[(a, b)].append(e)

    for (a, b), grp in edge_groups.items():
        sa, sb = _safe_id(a), _safe_id(b)
        if len(grp) == 1:
            rel = _escape_label(grp[0].get("relation") or "")
            if rel:
                lines.append(f"  {sa} -->|{rel}| {sb}")
            else:
                lines.append(f"  {sa} --> {sb}")
        else:
            rel = _escape_label(grp[0].get("relation") or "")
            tag = f"{rel} ×{len(grp)}" if rel else f"×{len(grp)}"
            lines.append(f"  {sa} -->|{tag}| {sb}")

    lines.append("```")
    return "\n".join(lines) + "\n"


def _kind_of(node_id: str) -> str:
    """Extract `<kind>` prefix from a typed node_id string."""
    if ":" in node_id:
        return node_id.split(":", 1)[0]
    return ""


# ----- BFS subgraph helpers -------------------------------------------------


def _bfs_subgraph(
    nodes: list[dict],
    edges: list[dict],
    root: str,
    depth: int,
    *,
    relation: str | None = None,
    direction: str = "both",
) -> tuple[list[dict], list[dict]]:
    """Return (kept_nodes, kept_edges) reachable from root within depth.

    `direction` ∈ {out, in, both}.
    """
    by_id = {n["node_id"]: n for n in nodes}
    if root not in by_id:
        return ([], [])

    # Build adjacency for the requested direction.
    adj: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for e in edges:
        if relation and e.get("relation") != relation:
            continue
        a, b = e.get("from_node"), e.get("to_node")
        if direction in ("out", "both"):
            adj[a].append((b, e))
        if direction in ("in", "both"):
            adj[b].append((a, e))

    seen: set[str] = {root}
    kept_edges: list[dict] = []
    frontier = [root]
    for _ in range(max(0, int(depth))):
        next_frontier: list[str] = []
        for nid in frontier:
            for other, edge in adj.get(nid, []):
                kept_edges.append(edge)
                if other not in seen and other in by_id:
                    seen.add(other)
                    next_frontier.append(other)
        frontier = next_frontier
        if not frontier:
            break

    kept_nodes = [by_id[i] for i in seen if i in by_id]
    # Deduplicate edges by identity (same dict appearing twice via both-direction adj).
    uniq_edges: list[dict] = []
    seen_edges: set[int] = set()
    for e in kept_edges:
        key = id(e)
        if key in seen_edges:
            continue
        seen_edges.add(key)
        # Only keep edges whose endpoints are both in seen.
        if e.get("from_node") in seen and e.get("to_node") in seen:
            uniq_edges.append(e)
    return (kept_nodes, uniq_edges)


def render_concept_subgraph(
    nodes: list[dict],
    edges: list[dict],
    root_concept_id: str,
    depth: int = 2,
    *,
    max_nodes: int = 50,
    hide_labels_above: int = 20,
) -> str:
    """BFS subgraph centered on a concept node, rendered as mermaid."""
    kn, ke = _bfs_subgraph(nodes, edges, root_concept_id, depth, direction="both")
    return render_mermaid(
        kn, ke, max_nodes=max_nodes, hide_labels_above=hide_labels_above
    )


def render_paper_lineage(
    nodes: list[dict],
    edges: list[dict],
    paper_cid: str,
    direction: str = "cited-by",
    depth: int = 2,
    *,
    max_nodes: int = 50,
    hide_labels_above: int = 20,
) -> str:
    """Trace forward (cited-by) or backward (cites) lineage from a paper.

    `paper_cid` is a bare canonical_id; this wraps it as `paper:<cid>`.
    """
    if ":" in paper_cid:
        root = paper_cid
    else:
        root = f"paper:{paper_cid}"

    if direction == "cited-by":
        rel, dir_ = "cited-by", "out"
        # Some pipelines only persist `cites` edges; fall back by
        # walking `cites` edges INTO the root (i.e. who cites it).
        kn, ke = _bfs_subgraph(
            nodes, edges, root, depth, relation=rel, direction=dir_
        )
        if not ke:
            kn, ke = _bfs_subgraph(
                nodes, edges, root, depth, relation="cites", direction="in"
            )
    elif direction == "cites":
        kn, ke = _bfs_subgraph(
            nodes, edges, root, depth, relation="cites", direction="out"
        )
    else:
        raise ValueError(f"direction must be 'cites' or 'cited-by', got {direction!r}")

    return render_mermaid(
        kn, ke, max_nodes=max_nodes, hide_labels_above=hide_labels_above
    )

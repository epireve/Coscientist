"""v0.171 — mermaid renderer for hypothesis trees.

Read-only. Surfaces `lib.idea_tree.get_tree` over a run DB and
emits a `graph TD` mermaid block with parent→child edges. Each
node is labeled with hyp_id + rounded Elo. Nodes are styled via
mermaid `class`:
  - green if elo >= 1300
  - red   if elo <  1100
  - default otherwise

Pure stdlib. Pairs with `lib.graph_viz` (citation graph renderer).

CLI:
    uv run python -m lib.tree_viz --run-db <path> --tree-id <id>
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

from lib.idea_tree import get_tree

_SAFE = re.compile(r"[^A-Za-z0-9_]")
DEFAULT_ELO = 1200.0
GREEN_THRESHOLD = 1300.0
RED_THRESHOLD = 1100.0


def _safe_id(hyp_id: str) -> str:
    h = hashlib.blake2s(hyp_id.encode("utf-8"), digest_size=4).hexdigest()
    base = _SAFE.sub("_", hyp_id)[:20].strip("_") or "n"
    return f"h_{base}_{h}"


def _class_for(elo: float) -> str:
    if elo >= GREEN_THRESHOLD:
        return "elo_high"
    if elo < RED_THRESHOLD:
        return "elo_low"
    return "elo_mid"


def render_tree(run_db: Path | str, tree_id: str) -> str:
    """Render hypothesis tree as mermaid markdown block.

    Empty tree (or missing) → ``error: …`` if tree_id absent, or
    a stub ``graph TD`` block when the tree has no nodes.
    """
    db = Path(run_db)
    if not db.exists():
        return f"error: run-db not found: {db}"
    try:
        nodes = get_tree(db, tree_id)
    except Exception as e:
        return f"error: {type(e).__name__}: {e}"
    if not nodes:
        # Distinguish "tree not present" from "valid empty render".
        return f"error: tree {tree_id!r} not found"

    lines: list[str] = ["```mermaid", "graph TD"]
    classes_used: set[str] = set()

    for n in nodes:
        hid = n["hyp_id"]
        elo = float(n.get("elo") or DEFAULT_ELO)
        cls = _class_for(elo)
        classes_used.add(cls)
        label = f"{hid}<br/>Elo {round(elo)}"
        lines.append(f'  {_safe_id(hid)}["{label}"]:::{cls}')

    # Edges: parent -> child
    by_id = {n["hyp_id"] for n in nodes}
    for n in nodes:
        parent = n.get("parent_hyp_id")
        if parent and parent in by_id:
            lines.append(
                f"  {_safe_id(parent)} --> {_safe_id(n['hyp_id'])}"
            )

    # Class definitions (only those used).
    if "elo_high" in classes_used:
        lines.append(
            "  classDef elo_high fill:#c6f6d5,stroke:#2f855a,color:#22543d"
        )
    if "elo_low" in classes_used:
        lines.append(
            "  classDef elo_low fill:#fed7d7,stroke:#c53030,color:#742a2a"
        )
    if "elo_mid" in classes_used:
        lines.append(
            "  classDef elo_mid fill:#edf2f7,stroke:#4a5568,color:#1a202c"
        )

    lines.append("```")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="tree_viz",
        description="Mermaid renderer for hypothesis trees (v0.171).",
    )
    p.add_argument("--run-db", required=True)
    p.add_argument("--tree-id", required=True)
    args = p.parse_args(argv)
    sys.stdout.write(render_tree(Path(args.run_db), args.tree_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

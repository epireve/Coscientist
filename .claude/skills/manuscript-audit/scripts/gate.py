#!/usr/bin/env python3
"""manuscript-audit gate: enforce structure on an audit report.

Writes claims + findings to:
- Run DB when --run-id given (for deep-research integration)
- Project DB when --project-id given (for cross-session auditability)

When --project-id given, also adds `about` edges from a concept node
for each claim to every canonical_id in cited_sources (project graph).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import cache_root, run_db_path  # noqa: E402

HEDGE_WORDS = re.compile(
    r"\b(maybe|perhaps|potentially|could\s+be|might\s+be|possibly|seems?\s+to|appears?\s+to)\b",
    re.IGNORECASE,
)
VALID_KINDS = {
    "overclaim", "uncited", "unsupported", "outdated", "retracted",
    # v0.9 citation-validator findings
    "dangling-citation", "orphan-reference",
    "unresolved-citation", "broken-reference",
    # v0.10 collision disambiguation
    "ambiguous-citation",
}
VALID_SEVERITY = {"info", "minor", "major"}
INLINE_CITATION = re.compile(r"(\\cite\{|\[@|\[\d+\]|\(\w+\s+\d{4}\))")


def validate(report: dict) -> list[str]:
    errors: list[str] = []
    claims = report.get("claims")
    if not isinstance(claims, list) or not claims:
        return ["no claims extracted — audit did not analyze the manuscript"]

    seen_ids: set[str] = set()
    for c in claims:
        cid = c.get("claim_id", "?")
        if not cid or cid in seen_ids:
            errors.append(f"claim_id duplicate or missing: {cid!r}")
        seen_ids.add(cid)
        for field in ("text", "location"):
            if not (c.get(field) or "").strip():
                errors.append(f"[{cid}] missing {field}")

        text_has_inline = bool(INLINE_CITATION.search(c.get("text", "")))
        cited = c.get("cited_sources", [])
        if text_has_inline and not cited:
            errors.append(
                f"[{cid}] text contains an inline citation but cited_sources is empty — "
                "you skipped resolution"
            )

        for f in c.get("findings") or []:
            if f.get("kind") not in VALID_KINDS:
                errors.append(f"[{cid}] finding kind {f.get('kind')!r} not in {VALID_KINDS}")
            if f.get("severity") not in VALID_SEVERITY:
                errors.append(f"[{cid}] severity {f.get('severity')!r} not in {VALID_SEVERITY}")
            evidence = (f.get("evidence") or "").strip()
            if not evidence:
                errors.append(f"[{cid}] finding missing evidence")
            elif HEDGE_WORDS.search(evidence):
                errors.append(f"[{cid}] evidence contains hedge word")

    return errors


def _concept_node_id(claim_id: str, text: str) -> str:
    """Stable concept node ID for a claim. Matches populate_concepts style."""
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:40] or f"c-{claim_id}"
    h = hashlib.blake2s(f"{claim_id}|{text}".encode(), digest_size=2).hexdigest()
    return f"concept:{slug}-{h}"


def _write_claims_and_findings(con: sqlite3.Connection, manuscript_id: str,
                                claims: list[dict], now: str) -> None:
    """Write claim + finding rows to an open connection. Schema is shared."""
    with con:
        for c in claims:
            con.execute(
                "INSERT OR IGNORE INTO manuscript_claims "
                "(manuscript_id, claim_id, text, location, cited_sources, at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    manuscript_id,
                    c["claim_id"],
                    c["text"],
                    c["location"],
                    json.dumps(c.get("cited_sources", [])),
                    now,
                ),
            )
            for f in c.get("findings") or []:
                con.execute(
                    "INSERT INTO manuscript_audit_findings "
                    "(manuscript_id, claim_id, kind, severity, evidence, at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        manuscript_id,
                        c["claim_id"],
                        f["kind"],
                        f["severity"],
                        f["evidence"],
                        now,
                    ),
                )


def _add_graph_edges(con: sqlite3.Connection, manuscript_id: str,
                      claims: list[dict], now: str) -> dict:
    """Add concept nodes + about edges to supporting papers.

    Only run on the project DB (not run DB) since the graph tables live there.
    Returns counts.
    """
    ms_node = f"manuscript:{manuscript_id}"
    concepts_added = 0
    about_edges = 0

    with con:
        # Ensure manuscript node exists
        con.execute(
            "INSERT OR IGNORE INTO graph_nodes "
            "(node_id, kind, label, data_json, created_at) "
            "VALUES (?, 'manuscript', ?, NULL, ?)",
            (ms_node, manuscript_id, now),
        )

        for c in claims:
            concept_id = _concept_node_id(c["claim_id"], c["text"])
            cur = con.execute(
                "INSERT OR IGNORE INTO graph_nodes "
                "(node_id, kind, label, data_json, created_at) "
                "VALUES (?, 'concept', ?, ?, ?)",
                (concept_id, c["text"][:120],
                 json.dumps({"source": "manuscript-audit", "manuscript_id": manuscript_id}),
                 now),
            )
            if cur.rowcount:
                concepts_added += 1

            # manuscript "contains" concept (via in-project relation reused)
            exists = con.execute(
                "SELECT 1 FROM graph_edges WHERE from_node=? AND to_node=? AND relation=?",
                (ms_node, concept_id, "about"),
            ).fetchone()
            if not exists:
                con.execute(
                    "INSERT INTO graph_edges "
                    "(from_node, to_node, relation, weight, data_json, created_at) "
                    "VALUES (?, ?, 'about', 1.0, ?, ?)",
                    (ms_node, concept_id,
                     json.dumps({"claim_id": c["claim_id"]}), now),
                )
                about_edges += 1

            # concept → each cited paper via about
            for cit_cid in c.get("cited_sources") or []:
                paper_node = f"paper:{cit_cid}"
                con.execute(
                    "INSERT OR IGNORE INTO graph_nodes "
                    "(node_id, kind, label, data_json, created_at) "
                    "VALUES (?, 'paper', ?, NULL, ?)",
                    (paper_node, cit_cid, now),
                )
                exists = con.execute(
                    "SELECT 1 FROM graph_edges WHERE from_node=? AND to_node=? AND relation=?",
                    (concept_id, paper_node, "about"),
                ).fetchone()
                if not exists:
                    con.execute(
                        "INSERT INTO graph_edges "
                        "(from_node, to_node, relation, weight, data_json, created_at) "
                        "VALUES (?, ?, 'about', 1.0, ?, ?)",
                        (concept_id, paper_node,
                         json.dumps({"claim_id": c["claim_id"]}), now),
                    )
                    about_edges += 1

    return {"concepts_added": concepts_added, "about_edges": about_edges}


def persist(report: dict, manuscript_id: str,
            run_id: str | None, project_id: str | None) -> dict:
    """Write report to disk + (optional) run DB + (optional) project DB."""
    out_dir = cache_root() / "manuscripts" / manuscript_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "audit_report.json"
    out.write_text(json.dumps(report, indent=2))

    now = datetime.now(UTC).isoformat()
    summary = {"report_path": str(out)}

    if run_id:
        db = run_db_path(run_id)
        if db.exists():
            con = sqlite3.connect(db)
            _write_claims_and_findings(con, manuscript_id, report["claims"], now)
            con.close()
            summary["run_db_written"] = True

    if project_id:
        proj_db = cache_root() / "projects" / project_id / "project.db"
        if proj_db.exists():
            con = sqlite3.connect(proj_db)
            _write_claims_and_findings(con, manuscript_id, report["claims"], now)
            graph_stats = _add_graph_edges(con, manuscript_id, report["claims"], now)
            con.close()
            summary["project_db_written"] = True
            summary.update(graph_stats)

    return summary


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--manuscript-id", required=True)
    p.add_argument("--run-id", default=None)
    p.add_argument("--project-id", default=None)
    args = p.parse_args()

    report = json.loads(Path(args.input).read_text())
    errors = validate(report)
    if errors:
        print("[manuscript-audit] REJECTED", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(2)

    summary = persist(report, args.manuscript_id, args.run_id, args.project_id)
    n_major = sum(
        1 for c in report["claims"] for f in (c.get("findings") or [])
        if f.get("severity") == "major"
    )
    print(
        f"[manuscript-audit] OK → {summary['report_path']} "
        f"({len(report['claims'])} claims, {n_major} major findings)"
    )
    if args.project_id:
        print(json.dumps(summary, indent=2), file=sys.stderr)


if __name__ == "__main__":
    main()

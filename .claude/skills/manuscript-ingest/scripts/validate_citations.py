#!/usr/bin/env python3
"""validate_citations: cross-check in-text citations against the bibliography.

Runs four validation modes and produces a report the author can act on:

- dangling-citation  — in-text [@key] has no matching bibliography entry
- orphan-reference   — bibliography entry never cited in text
- unresolved-citation — key parsed but no canonical_id ever mapped
- broken-reference   — mapped canonical_id has no paper artifact on disk

Writes `validation_report.json` to the manuscript artifact and
populates `manuscript_audit_findings` rows with the matching kinds,
so the author sees everything alongside other audit findings.

Exit codes:
  0 — clean run, report written
  2 — ran successfully but found major-severity issues (so CI can gate)
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import cache_root  # noqa: E402

NUMERIC_KEY = re.compile(r"^\[(\d+)\]$")


def _project_db(project_id: str) -> Path:
    p = cache_root() / "projects" / project_id / "project.db"
    if not p.exists():
        raise SystemExit(f"no project DB at {p}")
    return p


def _fuzzy_match_bib(citation_key: str, bib_rows: list[dict]) -> dict | None:
    """Try to find a bibliography entry for a given in-text citation key.

    Matching rules, in order:
    - Exact entry_key match
    - Numeric [N] → entry with ordinal N
    - Key substring (author slug) matches last-name + year in the raw entry
    """
    # Exact entry_key
    for row in bib_rows:
        if row["entry_key"] and row["entry_key"].lower() == citation_key.lower():
            return row

    # Numeric [N] → ordinal N
    m = NUMERIC_KEY.match(citation_key)
    if m:
        n = int(m.group(1))
        for row in bib_rows:
            if row["ordinal"] == n:
                return row

    # Author-year heuristic: "smith2020" → look for "smith" and "2020" in raw_text
    inline = citation_key.lower()
    year_match = re.search(r"(19|20)\d{2}", inline)
    if year_match:
        year = year_match.group(0)
        author_part = inline[:year_match.start()].rstrip("_-")
        if len(author_part) >= 3:
            for row in bib_rows:
                raw_low = (row["raw_text"] or "").lower()
                if author_part in raw_low and year in raw_low:
                    return row

    # (Author et al., Year) form
    # e.g. citation_key="Vaswani et al., 2017" → look for "vaswani" + "2017"
    parts = re.split(r"[\s,]+", citation_key.strip())
    if parts and len(parts) >= 2:
        author = parts[0].lower()
        year_part = next((p for p in parts if re.fullmatch(r"(19|20)\d{2}[a-z]?", p)), None)
        if year_part and len(author) >= 3:
            for row in bib_rows:
                raw_low = (row["raw_text"] or "").lower()
                if author in raw_low and year_part[:4] in raw_low:
                    return row

    return None


def _paper_artifact_exists(canonical_id: str) -> bool:
    p = cache_root() / "papers" / canonical_id / "manifest.json"
    return p.exists()


def validate(manuscript_id: str, project_id: str) -> dict:
    con = sqlite3.connect(_project_db(project_id))
    con.row_factory = sqlite3.Row

    citations = [dict(r) for r in con.execute(
        "SELECT citation_key, location, resolved_canonical_id FROM manuscript_citations "
        "WHERE manuscript_id=?", (manuscript_id,),
    )]
    bib = [dict(r) for r in con.execute(
        "SELECT entry_key, raw_text, ordinal, resolved_canonical_id FROM manuscript_references "
        "WHERE manuscript_id=? ORDER BY ordinal", (manuscript_id,),
    )]

    findings: list[dict] = []
    dangling: list[dict] = []
    unresolved: list[dict] = []
    broken: list[dict] = []

    # Track which bib entries are referenced at least once
    bib_ordinals_seen: set[int] = set()

    # Check each in-text citation
    for cit in citations:
        key = cit["citation_key"]
        match = _fuzzy_match_bib(key, bib)
        if match is None and bib:
            dangling.append({"citation_key": key, "location": cit["location"]})
            findings.append({
                "kind": "dangling-citation",
                "severity": "major",
                "citation_key": key,
                "location": cit["location"],
                "evidence": (
                    f"Inline citation '{key}' at {cit['location']} has no matching "
                    "entry in the bibliography section."
                ),
            })
        elif match is not None:
            bib_ordinals_seen.add(match["ordinal"])

        if cit["resolved_canonical_id"] is None:
            unresolved.append({"citation_key": key, "location": cit["location"]})
            findings.append({
                "kind": "unresolved-citation",
                "severity": "minor",
                "citation_key": key,
                "location": cit["location"],
                "evidence": (
                    f"Citation '{key}' has not been resolved to a canonical paper. "
                    "Run resolve_citations or the reference-agent sync."
                ),
            })
        elif not _paper_artifact_exists(cit["resolved_canonical_id"]):
            broken.append({
                "citation_key": key,
                "canonical_id": cit["resolved_canonical_id"],
                "location": cit["location"],
            })
            findings.append({
                "kind": "broken-reference",
                "severity": "major",
                "citation_key": key,
                "location": cit["location"],
                "evidence": (
                    f"Citation '{key}' resolves to canonical_id "
                    f"'{cit['resolved_canonical_id']}' but no paper artifact exists at that ID."
                ),
            })

    # Orphan bibliography entries
    orphans: list[dict] = []
    for entry in bib:
        if entry["ordinal"] in bib_ordinals_seen:
            continue
        # Also check whether the entry_key matches any citation_key (defensive)
        if entry["entry_key"] and any(
            c["citation_key"].lower() == entry["entry_key"].lower()
            for c in citations
        ):
            continue
        orphans.append({
            "ordinal": entry["ordinal"],
            "entry_key": entry["entry_key"],
            "preview": (entry["raw_text"] or "")[:120],
        })
        findings.append({
            "kind": "orphan-reference",
            "severity": "minor",
            "ordinal": entry["ordinal"],
            "entry_key": entry["entry_key"],
            "evidence": (
                f"Bibliography entry #{entry['ordinal']} "
                f"('{(entry['raw_text'] or '')[:80]}...') is never cited in the text."
            ),
        })

    now = datetime.now(UTC).isoformat()
    report = {
        "manuscript_id": manuscript_id,
        "project_id": project_id,
        "at": now,
        "summary": {
            "citations_in_text": len(citations),
            "bibliography_entries": len(bib),
            "dangling_citations": len(dangling),
            "orphan_references": len(orphans),
            "unresolved_citations": len(unresolved),
            "broken_references": len(broken),
        },
        "dangling_citations": dangling,
        "orphan_references": orphans,
        "unresolved_citations": unresolved,
        "broken_references": broken,
        "findings": findings,
    }

    # Persist report to disk
    ms_dir = cache_root() / "manuscripts" / manuscript_id
    ms_dir.mkdir(parents=True, exist_ok=True)
    out_path = ms_dir / "validation_report.json"
    out_path.write_text(json.dumps(report, indent=2))

    # Persist findings to manuscript_audit_findings in project DB
    # (synthetic claim_id "citation-validator" so they don't collide with audit)
    with con:
        for f in findings:
            ident = (
                f.get("citation_key")
                or f.get("entry_key")
                or f"ord-{f.get('ordinal')}"
            )
            con.execute(
                "INSERT INTO manuscript_audit_findings "
                "(manuscript_id, claim_id, kind, severity, evidence, at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    manuscript_id,
                    f"citation-validator:{ident}",
                    f["kind"], f["severity"], f["evidence"], now,
                ),
            )
    con.close()

    report["report_path"] = str(out_path)
    return report


def _print_author_summary(report: dict) -> None:
    s = report["summary"]
    print(
        f"[validate-citations] {s['citations_in_text']} in-text / "
        f"{s['bibliography_entries']} bib entries | "
        f"{s['dangling_citations']} dangling, "
        f"{s['orphan_references']} orphans, "
        f"{s['unresolved_citations']} unresolved, "
        f"{s['broken_references']} broken → {report['report_path']}"
    )
    if s["dangling_citations"]:
        print(
            "  ⚠ Dangling in-text citations (cited but not in ref list):",
            file=sys.stderr,
        )
        for d in report["dangling_citations"][:10]:
            print(f"    - {d['citation_key']!r} at {d['location']}", file=sys.stderr)
    if s["broken_references"]:
        print(
            "  ⚠ Broken references (mapped but paper artifact missing):",
            file=sys.stderr,
        )
        for b in report["broken_references"][:10]:
            print(
                f"    - {b['citation_key']!r} → {b['canonical_id']}",
                file=sys.stderr,
            )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--manuscript-id", required=True)
    p.add_argument("--project-id", required=True)
    p.add_argument("--fail-on-major", action="store_true",
                   help="Exit 2 if any major-severity issue found (for CI)")
    args = p.parse_args()

    report = validate(args.manuscript_id, args.project_id)
    _print_author_summary(report)

    if args.fail_on_major:
        s = report["summary"]
        if s["dangling_citations"] or s["broken_references"]:
            sys.exit(2)


if __name__ == "__main__":
    main()

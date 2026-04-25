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


def _match_bib_candidates(citation_key: str, bib_rows: list[dict]) -> list[dict]:
    """Return every bibliography entry that could match the given citation key.

    v0.10: returns a list (not a single match) so we can detect collisions.
    Callers interpret: 0 = dangling, 1 = resolved, ≥2 = ambiguous.

    Matching rules, tried in order; the first rule that yields any hits wins.
    Within a rule all matches are returned (a 2-hit match is what `ambiguous`
    is built from).

    - Exact `disambiguated_key` match (strongest — author deliberately typed
      wang2020a)
    - Exact `entry_key` match (common case)
    - Numeric [N] → entry with ordinal N
    - Key substring (author slug) matches last-name + year in the raw entry
    - (Author et al., Year) form
    """
    ck_low = citation_key.lower()

    # Strongest: disambiguated_key exact hit (single entry only by construction)
    for row in bib_rows:
        dk = (row.get("disambiguated_key") or "").lower()
        if dk and dk == ck_low:
            return [row]

    # entry_key exact — may be ambiguous
    by_entry_key = [
        row for row in bib_rows
        if row.get("entry_key") and row["entry_key"].lower() == ck_low
    ]
    if by_entry_key:
        return by_entry_key

    # Numeric [N] → ordinal N
    m = NUMERIC_KEY.match(citation_key)
    if m:
        n = int(m.group(1))
        hits = [row for row in bib_rows if row["ordinal"] == n]
        if hits:
            return hits

    # Author-year substring heuristic
    year_match = re.search(r"(19|20)\d{2}", ck_low)
    if year_match:
        year = year_match.group(0)
        author_part = ck_low[:year_match.start()].rstrip("_-")
        if len(author_part) >= 3:
            hits = [
                row for row in bib_rows
                if author_part in (row.get("raw_text") or "").lower()
                and year in (row.get("raw_text") or "").lower()
            ]
            if hits:
                return hits

    # (Author et al., Year) form
    parts = re.split(r"[\s,]+", citation_key.strip())
    if parts and len(parts) >= 2:
        author = parts[0].lower()
        year_part = next(
            (p for p in parts if re.fullmatch(r"(19|20)\d{2}[a-z]?", p)),
            None,
        )
        if year_part and len(author) >= 3:
            hits = [
                row for row in bib_rows
                if author in (row.get("raw_text") or "").lower()
                and year_part[:4] in (row.get("raw_text") or "").lower()
            ]
            if hits:
                return hits

    return []


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
        "SELECT entry_key, disambiguated_key, raw_text, ordinal, resolved_canonical_id "
        "FROM manuscript_references WHERE manuscript_id=? ORDER BY ordinal",
        (manuscript_id,),
    )]

    findings: list[dict] = []
    dangling: list[dict] = []
    unresolved: list[dict] = []
    broken: list[dict] = []
    ambiguous: list[dict] = []

    # Track which bib entries are referenced at least once
    bib_ordinals_seen: set[int] = set()

    # v0.10: pre-compute the set of entry_keys that are themselves in a
    # collision group in the bib. Used to surface the collision set in report.
    from collections import Counter
    key_counts = Counter(
        row["entry_key"] for row in bib if row.get("entry_key")
    )
    collision_keys = {k for k, n in key_counts.items() if n > 1}

    # Check each in-text citation
    for cit in citations:
        key = cit["citation_key"]
        matches = _match_bib_candidates(key, bib)

        if not matches and bib:
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
        elif len(matches) > 1:
            # v0.10: same citation key matches multiple bib entries
            candidates = [
                {
                    "ordinal": m["ordinal"],
                    "disambiguated_key": m.get("disambiguated_key"),
                    "preview": (m.get("raw_text") or "")[:100],
                }
                for m in matches
            ]
            ambiguous.append({
                "citation_key": key,
                "location": cit["location"],
                "candidates": candidates,
            })
            def _label(m: dict) -> str:
                return m.get("disambiguated_key") or f"ord-{m['ordinal']}"
            suggestion = ", ".join(f"'{_label(m)}'" for m in matches)
            findings.append({
                "kind": "ambiguous-citation",
                "severity": "major",
                "citation_key": key,
                "location": cit["location"],
                "evidence": (
                    f"Inline citation '{key}' at {cit['location']} matches "
                    f"{len(matches)} bibliography entries. Rewrite as one of: "
                    f"{suggestion}."
                ),
            })
            for m in matches:
                bib_ordinals_seen.add(m["ordinal"])
        else:
            # Exactly one match
            bib_ordinals_seen.add(matches[0]["ordinal"])

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

    # v0.10: surface the collision groups themselves, even if no in-text
    # citation was ambiguous (the author still benefits from knowing)
    collision_report: list[dict] = []
    for k in sorted(collision_keys):
        members = [
            {"ordinal": row["ordinal"],
             "disambiguated_key": row.get("disambiguated_key"),
             "preview": (row.get("raw_text") or "")[:100]}
            for row in bib if (row.get("entry_key") or "").lower() == k.lower()
        ]
        collision_report.append({"entry_key": k, "members": members})

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
            "ambiguous_citations": len(ambiguous),
            "collision_groups": len(collision_report),
        },
        "dangling_citations": dangling,
        "orphan_references": orphans,
        "unresolved_citations": unresolved,
        "broken_references": broken,
        "ambiguous_citations": ambiguous,
        "collision_groups": collision_report,
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
        f"{s['broken_references']} broken, "
        f"{s['ambiguous_citations']} ambiguous, "
        f"{s['collision_groups']} collision groups → {report['report_path']}"
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
    if s["ambiguous_citations"]:
        print(
            "  ⚠ Ambiguous citations (one key matches multiple bib entries):",
            file=sys.stderr,
        )
        for a in report["ambiguous_citations"][:10]:
            def _cand_label(c: dict) -> str:
                return c.get("disambiguated_key") or f"ord-{c['ordinal']}"
            cand = ", ".join(_cand_label(c) for c in a["candidates"])
            print(
                f"    - {a['citation_key']!r} at {a['location']} → rewrite as one of: {cand}",
                file=sys.stderr,
            )
    if s["collision_groups"]:
        print(
            "  ℹ Bibliography contains colliding keys (auto-suffixed a/b/c):",
            file=sys.stderr,
        )
        for g in report["collision_groups"][:10]:
            suffixes = ", ".join(
                m.get("disambiguated_key") or f"ord-{m['ordinal']}"
                for m in g["members"]
            )
            print(f"    - {g['entry_key']!r}: {suffixes}", file=sys.stderr)


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
        if (s["dangling_citations"] or s["broken_references"]
                or s["ambiguous_citations"]):
            sys.exit(2)


if __name__ == "__main__":
    main()

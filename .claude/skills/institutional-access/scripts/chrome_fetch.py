#!/usr/bin/env python3
"""v0.205 — Chrome Claude (claude-in-chrome MCP) institutional fetch.

Replaces Tier-1 Playwright as preferred path. User's authenticated
Chrome browser handles OpenAthens SSO + paywalls + anti-bot natively
because it's a real browser session with real credentials.

This script does NOT call MCP tools directly — those live in the
calling Claude session's tool surface. Instead, it emits a structured
**plan** (JSON) describing the steps the calling agent should drive:

  1. navigate(doi.org/<doi>) — publisher resolves DOI
  2. wait for redirect chain to settle
  3. find_pdf_link or read_page → locate download button
  4. click + wait for download to land
  5. report saved path back via record-fetch CLI

The calling agent (e.g., paper-acquire orchestrator) reads the plan,
executes via mcp__Claude_in_Chrome__* tools, then calls
`chrome_fetch.py record --canonical-id <cid> --pdf <path> --tier chrome`
to mark the artifact acquired and audit-log the fetch.

Why a plan-emitter instead of direct MCP calls:
- Sub-agents may not inherit MCP access (per v0.186). Orchestrator
  drives Chrome MCP, persona reads the plan from disk.
- Same harvest-plan pattern used everywhere else in coscientist.
- Decouples planning (cheap) from execution (expensive, interactive).

CLI:
    plan --canonical-id <cid> [--doi DOI]
        emit JSON plan to stdout

    record --canonical-id <cid> --pdf <path>
        post-execution: persist PDF + audit log

Best-effort. Errors return dicts with "error" key.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import paper_dir  # noqa: E402


def _load_manifest(cid: str) -> dict:
    pdir = paper_dir(cid)
    mp = pdir / "manifest.json"
    if not mp.exists():
        return {"error": f"no manifest at {mp}"}
    try:
        return json.loads(mp.read_text())
    except json.JSONDecodeError as e:
        return {"error": f"manifest invalid: {e}"}


def _resolve_doi(cid: str, override_doi: str | None) -> tuple[str | None, dict]:
    if override_doi:
        return override_doi, {}
    m = _load_manifest(cid)
    if "error" in m:
        return None, m
    doi = m.get("doi")
    if not doi:
        return None, {"error": f"no DOI in manifest for {cid}"}
    return doi, {}


def emit_plan(canonical_id: str, doi: str | None = None) -> dict:
    """Return JSON plan describing Chrome MCP steps for the orchestrator."""
    resolved_doi, err = _resolve_doi(canonical_id, doi)
    if err:
        return err
    return {
        "canonical_id": canonical_id,
        "doi": resolved_doi,
        "tier": "chrome",
        "steps": [
            {
                "tool": "mcp__Claude_in_Chrome__tabs_context_mcp",
                "args": {"createIfEmpty": True},
                "purpose": "ensure tab group exists",
            },
            {
                "tool": "mcp__Claude_in_Chrome__navigate",
                "args": {"url": f"https://doi.org/{resolved_doi}"},
                "purpose": "resolve DOI; publisher handles auth via existing session",
            },
            {
                "tool": "mcp__Claude_in_Chrome__find",
                "args": {"query": "download PDF button or full text PDF link"},
                "purpose": "locate publisher's PDF download element",
            },
            {
                "tool": "mcp__Claude_in_Chrome__computer",
                "args": {"action": "left_click", "ref": "<from_find>"},
                "purpose": "click PDF link; browser downloads to default dir",
            },
            {
                "tool": "shell",
                "command": "wait_and_locate_pdf",
                "purpose": "wait ~10s for download, find newest PDF in ~/Downloads",
            },
            {
                "tool": "shell",
                "command": (
                    "uv run python "
                    ".claude/skills/institutional-access/scripts/chrome_fetch.py "
                    f"record --canonical-id {canonical_id} "
                    "--pdf <downloaded_path>"
                ),
                "purpose": "persist + audit",
            },
        ],
        "notes": [
            "Auth handled by user's Chrome profile (OpenAthens / cookies).",
            "No anti-bot management needed — real browser, real user.",
            "If publisher rate-limits, fallback = Tier 2 Playwright.",
            "If find() returns multiple candidates, prefer ones whose label "
            "matches /pdf|full text|download/i.",
        ],
    }


def record_fetch(canonical_id: str, pdf_path: Path) -> dict:
    """Persist downloaded PDF into paper artifact + audit-log it."""
    if not pdf_path.exists():
        return {"error": f"PDF not found at {pdf_path}"}
    pdir = paper_dir(canonical_id)
    raw = pdir / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    target = raw / "paper.pdf"
    shutil.copy2(pdf_path, target)

    # Update manifest
    m = _load_manifest(canonical_id)
    if "error" in m:
        return m
    m.setdefault("sources_tried", [])
    m["sources_tried"].append("chrome-claude")
    m["state"] = "acquired"
    m["acquired_at"] = datetime.now(UTC).isoformat()
    m["acquired_via"] = "chrome-claude"
    (pdir / "manifest.json").write_text(json.dumps(m, indent=2))

    # Audit log
    from lib.cache import cache_root
    audit = cache_root() / "audit.log"
    audit.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({
        "at": datetime.now(UTC).isoformat(),
        "action": "fetch",
        "canonical_id": canonical_id,
        "tier": "chrome-claude",
        "pdf_size": target.stat().st_size,
        "doi": m.get("doi"),
    })
    with audit.open("a") as f:
        f.write(line + "\n")

    return {
        "ok": True,
        "canonical_id": canonical_id,
        "pdf_path": str(target),
        "pdf_size": target.stat().st_size,
        "tier": "chrome-claude",
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="chrome_fetch")
    sub = p.add_subparsers(dest="cmd", required=True)

    pp = sub.add_parser("plan", help="emit Chrome-MCP fetch plan")
    pp.add_argument("--canonical-id", required=True)
    pp.add_argument("--doi", default=None,
                     help="override DOI (default: read from manifest)")
    pp.add_argument("--format", choices=("json", "text"), default="json")

    pr = sub.add_parser("record", help="persist downloaded PDF")
    pr.add_argument("--canonical-id", required=True)
    pr.add_argument("--pdf", required=True, help="path to downloaded PDF")

    args = p.parse_args(argv)

    if args.cmd == "plan":
        plan = emit_plan(args.canonical_id, args.doi)
        if args.format == "json":
            sys.stdout.write(json.dumps(plan, indent=2) + "\n")
        else:
            if "error" in plan:
                sys.stderr.write(f"error: {plan['error']}\n")
            else:
                for i, step in enumerate(plan.get("steps", []), 1):
                    sys.stdout.write(f"{i}. {step['tool']} — {step['purpose']}\n")
        return 0 if "error" not in plan else 1

    if args.cmd == "record":
        result = record_fetch(args.canonical_id, Path(args.pdf))
        sys.stdout.write(json.dumps(result, indent=2) + "\n")
        return 0 if result.get("ok") else 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main())

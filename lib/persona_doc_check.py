"""v0.134 — static check: persona .md JSON example matches SCHEMAS.

Each `.claude/agents/<name>.md` for a persona with a registered
schema in `lib.persona_schema.SCHEMAS` should contain a JSON
example block that satisfies the schema. This catches docs drift
when SCHEMAS or persona spec changes independently.

Extracts the FIRST ```json ... ``` fenced block from the .md.
Validates against the persona's schema. Reports mismatches.

CLI:
    uv run python -m lib.persona_doc_check
        # → exit 0 clean, exit 1 if any persona drifts
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent
_AGENTS = _REPO / ".claude" / "agents"
_JSON_BLOCK = re.compile(
    r"```json\s*\n(.*?)\n```", re.DOTALL,
)


def extract_json_example(md_text: str) -> dict[str, Any] | list | None:
    """Pull the first ```json fenced block from a markdown string.
    Returns parsed JSON or None if missing/invalid."""
    m = _JSON_BLOCK.search(md_text)
    if not m:
        return None
    try:
        # JSON examples use <placeholder> tokens (`<int>`, `<cid>`).
        # Substitute with `null` — always valid JSON, won't break
        # surrounding strings. Schema validation only checks
        # presence/type at top level + required fields, so null
        # for value positions is fine.
        body = m.group(1)
        # Only substitute UNQUOTED <...>; leave embedded mentions
        # inside strings alone. Cheap heuristic: substitute when
        # not preceded by quote-content.
        body = re.sub(r"(?<![\w\"])<[^>]*>(?![\w\"])", "null", body)
        # Strip JSON comments (// + /* */) which sometimes appear
        # in human-readable docs.
        body = re.sub(r"//[^\n]*", "", body)
        body = re.sub(r"/\*.*?\*/", "", body, flags=re.DOTALL)
        return json.loads(body)
    except json.JSONDecodeError:
        return None


def check_persona(agent_name: str) -> dict[str, Any]:
    """Validate one persona's doc against its schema.

    Returns: {agent, ok, error|None, has_schema, has_example}.
    """
    from lib.persona_schema import SCHEMAS, validate
    md_path = _AGENTS / f"{agent_name}.md"
    out: dict[str, Any] = {
        "agent": agent_name,
        "ok": False,
        "has_schema": agent_name in SCHEMAS,
        "has_example": False,
        "error": None,
    }
    if not md_path.exists():
        out["error"] = f"missing {md_path}"
        return out
    if not out["has_schema"]:
        # No schema registered → skip (still "ok" per gate semantics).
        out["ok"] = True
        out["error"] = "no schema registered (skipped)"
        return out
    payload = extract_json_example(md_path.read_text())
    if payload is None:
        out["error"] = "no parseable ```json block found"
        return out
    out["has_example"] = True
    # Write to tmp file + validate (validate() takes Path).
    import tempfile
    tf = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False,
    )
    json.dump(payload, tf); tf.close()
    try:
        res = validate(agent_name, Path(tf.name))
    finally:
        Path(tf.name).unlink()
    out["ok"] = res.ok
    if not res.ok:
        out["error"] = res.error
    return out


def check_all() -> list[dict[str, Any]]:
    """Walk every persona in SCHEMAS, return per-persona results."""
    from lib.persona_schema import SCHEMAS
    out = []
    for agent in sorted(SCHEMAS.keys()):
        out.append(check_persona(agent))
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="persona_doc_check",
        description="v0.134 — static check that persona .md JSON "
                    "examples satisfy lib.persona_schema.SCHEMAS.",
    )
    p.add_argument("--agent", default=None,
                    help="Check one agent (default: all in SCHEMAS).")
    p.add_argument("--format", choices=("md", "json"), default="md")
    args = p.parse_args(argv)

    if args.agent:
        results = [check_persona(args.agent)]
    else:
        results = check_all()

    failed = [r for r in results if not r["ok"]]

    if args.format == "json":
        sys.stdout.write(json.dumps({
            "n_checked": len(results),
            "n_failed": len(failed),
            "results": results,
        }, indent=2) + "\n")
    else:
        for r in results:
            mark = "✅" if r["ok"] else "❌"
            note = f" — {r['error']}" if r["error"] else ""
            sys.stdout.write(f"{mark} {r['agent']}{note}\n")
        sys.stdout.write(
            f"\n{len(results) - len(failed)}/{len(results)} ok\n"
        )

    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())

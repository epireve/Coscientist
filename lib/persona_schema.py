"""v0.102 — persona output JSON shape validator.

Auto-rubric (v0.92) checks semantic content of persona artifacts
(>=N items, every item has field X). It does NOT check structural
shape — caller could pass anything as long as criteria pass on
defaults.

This module adds a strict-shape gate. Each persona declares an
expected top-level structure (list / dict + required keys). Loader
reads JSON, validates shape, rejects mismatches with a precise
error string.

Pure stdlib. No jsonschema. Designed to fit in pre-rubric path.

Usage:

    from lib.persona_schema import validate

    res = validate("scout", artifact_path)
    if not res.ok:
        print(f"shape error: {res.error}")
    else:
        # res.payload is the parsed JSON, ready for rubric.
        ...
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    payload: Any | None  # parsed JSON if ok else None
    error: str | None    # human-readable reason if not ok


@dataclass(frozen=True)
class Schema:
    """Minimal schema definition.

    `top_kind` = "list" | "dict"
    `item_required_fields` = required keys when top is list-of-objects
    `dict_required_fields` = required keys when top is dict
    `min_items` = minimum length for lists (advisory; rubric also
                  enforces, but this catches empty-by-mistake).
    """
    top_kind: str
    item_required_fields: tuple[str, ...] = ()
    dict_required_fields: tuple[str, ...] = ()
    min_items: int = 0


# Per-persona schemas. Mirrors RUBRICS keys in lib.agent_quality
# but kept independent — schemas can exist without rubrics and
# vice-versa.
SCHEMAS: dict[str, Schema] = {
    # v0.103 — scout/surveyor/architect/synthesist also dict-top
    # per persona output spec ({phase, summary, ...} or
    # {papers_seeded, shortlist_size, ...}). Initial v0.102 list-top
    # entries were wrong — corrected here.
    "scout": Schema(
        top_kind="dict",
        dict_required_fields=(
            "papers_seeded", "shortlist_size",
            "duplicates_dropped", "stopped_because",
        ),
    ),
    "surveyor": Schema(
        top_kind="dict",
        dict_required_fields=("phase", "summary", "gaps"),
    ),
    "architect": Schema(
        top_kind="dict",
        dict_required_fields=("phase", "summary", "hypotheses"),
    ),
    "synthesist": Schema(
        top_kind="dict",
        dict_required_fields=("phase", "summary", "implications"),
    ),
    "weaver": Schema(
        top_kind="dict",
        dict_required_fields=(
            "phase", "summary", "sharpened_question",
            "consensus", "tensions",
        ),
    ),
    # v0.103 — Phase 1 + 2c + 3 personas
    "cartographer": Schema(
        top_kind="dict",
        dict_required_fields=("phase", "summary", "seminals"),
    ),
    "chronicler": Schema(
        top_kind="dict",
        dict_required_fields=("phase", "summary", "timeline"),
    ),
    "inquisitor": Schema(
        top_kind="dict",
        dict_required_fields=("phase", "summary", "evaluations"),
    ),
    "visionary": Schema(
        top_kind="dict",
        dict_required_fields=("phase", "summary", "directions"),
    ),
    "steward": Schema(
        top_kind="dict",
        dict_required_fields=(
            "phase", "brief_path", "map_path",
            "claims_cited", "papers_cited", "eval_passed",
        ),
    ),
}


def _load_json(path: Path) -> tuple[Any | None, str | None]:
    if not path.exists():
        return None, f"file not found: {path}"
    try:
        return json.loads(path.read_text()), None
    except json.JSONDecodeError as e:
        return None, f"JSON parse error: {e}"
    except OSError as e:
        return None, f"read error: {e}"


def validate(agent_name: str, artifact_path: Path) -> ValidationResult:
    """Validate an artifact against `SCHEMAS[agent_name]`.

    If no schema exists for this agent, returns ok=True with the
    parsed payload (permissive default — schema is opt-in).
    """
    payload, err = _load_json(artifact_path)
    if err is not None:
        return ValidationResult(ok=False, payload=None, error=err)
    schema = SCHEMAS.get(agent_name)
    if schema is None:
        return ValidationResult(ok=True, payload=payload, error=None)

    if schema.top_kind == "list":
        if not isinstance(payload, list):
            return ValidationResult(
                ok=False, payload=None,
                error=f"expected list, got {type(payload).__name__}",
            )
        if len(payload) < schema.min_items:
            return ValidationResult(
                ok=False, payload=None,
                error=(
                    f"expected >={schema.min_items} items, "
                    f"got {len(payload)}"
                ),
            )
        for i, item in enumerate(payload):
            if not isinstance(item, dict):
                return ValidationResult(
                    ok=False, payload=None,
                    error=(
                        f"item[{i}] expected dict, "
                        f"got {type(item).__name__}"
                    ),
                )
            missing = [
                f for f in schema.item_required_fields
                if f not in item
            ]
            if missing:
                return ValidationResult(
                    ok=False, payload=None,
                    error=(
                        f"item[{i}] missing required fields: "
                        f"{missing}"
                    ),
                )
        return ValidationResult(ok=True, payload=payload, error=None)

    elif schema.top_kind == "dict":
        if not isinstance(payload, dict):
            return ValidationResult(
                ok=False, payload=None,
                error=f"expected dict, got {type(payload).__name__}",
            )
        missing = [
            f for f in schema.dict_required_fields
            if f not in payload
        ]
        if missing:
            return ValidationResult(
                ok=False, payload=None,
                error=f"missing required keys: {missing}",
            )
        return ValidationResult(ok=True, payload=payload, error=None)

    return ValidationResult(
        ok=False, payload=None,
        error=f"unknown schema top_kind: {schema.top_kind}",
    )


def main(argv: list[str] | None = None) -> int:
    """CLI: validate <agent> <path> → exit 0/1, or `list` schemas."""
    import argparse
    import sys
    p = argparse.ArgumentParser(prog="persona_schema")
    sub = p.add_subparsers(dest="cmd")

    pv = sub.add_parser("validate", help="Validate artifact shape")
    pv.add_argument("--agent", required=True)
    pv.add_argument("--artifact-path", required=True)

    sub.add_parser("list", help="List registered schemas (v0.103)")

    # Backward-compat: bare flags trigger validate.
    p.add_argument("--agent", default=None, help=argparse.SUPPRESS)
    p.add_argument("--artifact-path", default=None,
                    help=argparse.SUPPRESS)
    args = p.parse_args(argv)

    if args.cmd == "list":
        out = {
            agent: {
                "top_kind": s.top_kind,
                "item_required_fields": list(s.item_required_fields),
                "dict_required_fields": list(s.dict_required_fields),
                "min_items": s.min_items,
            }
            for agent, s in sorted(SCHEMAS.items())
        }
        sys.stdout.write(json.dumps(out, indent=2) + "\n")
        return 0

    agent = (
        getattr(args, "agent", None)
        if args.cmd == "validate"
        else None
    ) or args.agent
    artifact = (
        getattr(args, "artifact_path", None)
        if args.cmd == "validate"
        else None
    ) or args.artifact_path
    if not agent or not artifact:
        p.print_help(sys.stderr)
        return 2
    res = validate(agent, Path(artifact))
    out = {"ok": res.ok, "agent": agent,
           "artifact_path": artifact}
    if res.error:
        out["error"] = res.error
    sys.stdout.write(json.dumps(out, indent=2) + "\n")
    return 0 if res.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

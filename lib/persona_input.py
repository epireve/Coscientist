"""v0.46 — Per-persona input shortlist files.

In runtimes where sub-agents don't inherit MCP tool access, the
orchestrator harvests MCP results into a shortlist file on disk and
spawns the persona pointing at that file. This module is the read/write
contract.

Layout:
    ~/.cache/coscientist/runs/run-<run_id>/inputs/<persona>-<phase>.json

Schema (v1):
    {
      "schema_version": 1,
      "run_id":   "<run_id>",
      "persona":  "social|grounder|...",
      "phase":    "phase0|phase1|...",
      "query":    "<the original question>",
      "harvested_at": "<ISO 8601 UTC>",
      "harvested_by": "<orchestrator | mcp-name>",
      "budget":   {"max_papers": 200, "max_mcp_calls": 30},
      "results":  [
        {
          "source":      "consensus|paper-search|academic|semantic-scholar",
          "title":       "...",
          "authors":     ["..."],
          "year":        2024,
          "abstract":    "...",
          "tldr":        "...",
          "doi":         "10.xxx/...",
          "arxiv_id":    "2401.xxxxx",
          "s2_id":       "...",
          "venue":       "...",
          "citation_count": 42,
          "claims":      [{"text": "...", "section": "..."}]
        }, ...
      ],
      "notes":    "<free-form orchestrator log line(s)>"
    }

Personas read this with `load(run_id, persona, phase)` and treat the
results list as their candidate pool. They do not call MCPs themselves.

Round-trip is JSON; no external schema library — kept stdlib so the
helper survives even if pyproject changes.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from lib.cache import run_inputs_dir

SCHEMA_VERSION = 1


class PersonaInputError(Exception):
    """Raised when an input file is missing, malformed, or schema-mismatched."""


@dataclass
class PersonaInput:
    run_id: str
    persona: str
    phase: str
    query: str
    results: list[dict] = field(default_factory=list)
    budget: dict | None = None
    harvested_at: str = ""
    harvested_by: str = "orchestrator"
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "run_id": self.run_id,
            "persona": self.persona,
            "phase": self.phase,
            "query": self.query,
            "harvested_at": self.harvested_at or _utcnow(),
            "harvested_by": self.harvested_by,
            "budget": self.budget or {},
            "results": self.results,
            "notes": self.notes,
        }


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def input_path(run_id: str, persona: str, phase: str) -> Path:
    if not run_id or not persona or not phase:
        raise PersonaInputError(
            f"run_id, persona, phase all required; got "
            f"{run_id!r}, {persona!r}, {phase!r}"
        )
    return run_inputs_dir(run_id) / f"{persona}-{phase}.json"


def save(inp: PersonaInput) -> Path:
    """Write the shortlist atomically (write tmp + rename)."""
    path = input_path(inp.run_id, inp.persona, inp.phase)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(inp.to_dict(), indent=2))
    tmp.rename(path)
    return path


def load(run_id: str, persona: str, phase: str) -> PersonaInput:
    """Load and validate a shortlist file. Raises PersonaInputError on
    missing file, parse error, or schema-version mismatch."""
    path = input_path(run_id, persona, phase)
    if not path.exists():
        raise PersonaInputError(
            f"no shortlist for {persona}/{phase} (expected {path})"
        )
    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise PersonaInputError(f"corrupt shortlist {path}: {e}") from e
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise PersonaInputError(
            f"shortlist {path} has schema_version "
            f"{raw.get('schema_version')!r}; this lib expects "
            f"{SCHEMA_VERSION}. Re-harvest with current orchestrator."
        )
    for required in ("run_id", "persona", "phase", "query", "results"):
        if required not in raw:
            raise PersonaInputError(
                f"shortlist {path} missing required field {required!r}"
            )
    if not isinstance(raw["results"], list):
        raise PersonaInputError(
            f"shortlist {path} 'results' must be a list, got "
            f"{type(raw['results']).__name__}"
        )
    return PersonaInput(
        run_id=raw["run_id"],
        persona=raw["persona"],
        phase=raw["phase"],
        query=raw["query"],
        results=raw["results"],
        budget=raw.get("budget") or {},
        harvested_at=raw.get("harvested_at", ""),
        harvested_by=raw.get("harvested_by", ""),
        notes=raw.get("notes", ""),
    )


def list_for_run(run_id: str) -> list[Path]:
    """All shortlist files for a run, sorted by name (persona-phase)."""
    d = run_inputs_dir(run_id)
    return sorted(d.glob("*.json"))


def exists(run_id: str, persona: str, phase: str) -> bool:
    return input_path(run_id, persona, phase).exists()

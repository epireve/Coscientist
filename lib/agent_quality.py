"""v0.92 — agent quality scoring.

Three judging modes, all persist to `agent_quality`:

  - **auto-rubric**: pure-stdlib structural checks (count items,
    presence of fields). Cheap baseline; runs on every persona.
  - **llm-judge**: emits a structured prompt the `quality-judge`
    sub-agent consumes; the orchestrator dispatches the sub-agent
    and persists its JSON verdict. Sub-agent runs inside Claude
    Code's Task tool — no extra API plumbing.
  - **ranker**: existing `tournament/ranker` over agent outputs
    (deferred to v0.93).

Per-persona rubrics live in `RUBRICS` below. Each criterion has:
  - name (str)
  - weight (float; sum across criteria can be ≠ 1.0, gets normalized)
  - check (callable accepting parsed artifact, returns 0.0–1.0)
  - description (str)

Pure stdlib. No LLM in this module — `llm-judge` mode is a
two-step protocol (`emit_judge_prompt` + `persist_judge_result`)
where the LLM call happens in the orchestrator/sub-agent.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable


# ---------- rubric model ----------

@dataclass(frozen=True)
class Criterion:
    name: str
    weight: float
    check: Callable[[Any], float]  # input is whatever the rubric loads
    description: str


@dataclass(frozen=True)
class Rubric:
    agent_name: str
    version: str
    description: str
    criteria: tuple[Criterion, ...]
    loader: Callable[[Path], Any]  # path → parsed input for `check`


# ---------- pure-stdlib check helpers ----------

def count_at_least(items: list, n: int) -> float:
    """1.0 if len(items) >= n; ramp from 0 to 1 across [0, n]."""
    if not items:
        return 0.0
    return min(1.0, len(items) / max(1, n))


def every_item_has_fields(items: list[dict], fields: list[str]) -> float:
    """Fraction of items where ALL `fields` present + truthy."""
    if not items:
        return 0.0
    ok = sum(
        1 for it in items
        if all(it.get(f) for f in fields)
    )
    return ok / len(items)


def fraction_with_field(items: list[dict], field: str) -> float:
    """Fraction of items where `field` present + truthy."""
    if not items:
        return 0.0
    return sum(1 for it in items if it.get(field)) / len(items)


def unique_kind_count(
    items: list[dict], key: str, min_unique: int = 3,
) -> float:
    """Reward distinct values of `key`. 1.0 at >= min_unique."""
    if not items:
        return 0.0
    return min(1.0, len({it.get(key) for it in items if it.get(key)})
               / max(1, min_unique))


def has_field(d: dict, field: str) -> float:
    """1.0 if d[field] is truthy."""
    return 1.0 if d.get(field) else 0.0


# ---------- artifact loaders ----------

def _load_json_path(p: Path) -> Any:
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return None


def _load_text_path(p: Path) -> str:
    if not p.exists():
        return ""
    return p.read_text()


# ---------- per-persona rubrics ----------

# Each rubric ships criteria that are (a) cheap to compute (b) catch
# the most common low-quality output mode for that persona.
# Add new ones over time.

RUBRICS: dict[str, Rubric] = {
    "scout": Rubric(
        agent_name="scout",
        version="0.1",
        description="Paper-discovery breadth + dedup",
        loader=_load_json_path,
        criteria=(
            Criterion(
                name="enough_candidates",
                weight=2.0,
                check=lambda items: count_at_least(items or [], 30),
                description=">=30 candidate papers",
            ),
            Criterion(
                name="canonical_id_present",
                weight=1.0,
                check=lambda items: fraction_with_field(
                    items or [], "canonical_id",
                ),
                description="every paper has canonical_id",
            ),
            Criterion(
                name="title_present",
                weight=1.0,
                check=lambda items: fraction_with_field(
                    items or [], "title",
                ),
                description="every paper has title",
            ),
            Criterion(
                name="source_diversity",
                weight=1.0,
                check=lambda items: unique_kind_count(
                    items or [], "source", min_unique=3,
                ),
                description=">=3 distinct sources",
            ),
        ),
    ),
    "surveyor": Rubric(
        agent_name="surveyor",
        version="0.1",
        description="Gap identification specificity",
        loader=_load_json_path,
        criteria=(
            Criterion(
                name="enough_gaps",
                weight=2.0,
                check=lambda items: count_at_least(items or [], 5),
                description=">=5 gaps",
            ),
            Criterion(
                name="why_present",
                weight=1.5,
                check=lambda items: fraction_with_field(
                    items or [], "why_matters",
                ),
                description="every gap has why-this-matters",
            ),
            Criterion(
                name="kind_present",
                weight=1.0,
                check=lambda items: fraction_with_field(
                    items or [], "kind",
                ),
                description="every gap has kind label",
            ),
        ),
    ),
    "architect": Rubric(
        agent_name="architect",
        version="0.1",
        description="Candidate-approach completeness",
        loader=_load_json_path,
        criteria=(
            Criterion(
                name="enough_candidates",
                weight=2.0,
                check=lambda items: count_at_least(items or [], 3),
                description=">=3 candidate approaches",
            ),
            Criterion(
                name="all_three_fields",
                weight=2.0,
                check=lambda items: every_item_has_fields(
                    items or [], ["method", "falsifier", "observable"],
                ),
                description="every approach has method+falsifier+observable",
            ),
        ),
    ),
    "synthesist": Rubric(
        agent_name="synthesist",
        version="0.1",
        description="Cross-paper implications",
        loader=_load_json_path,
        criteria=(
            Criterion(
                name="enough_implications",
                weight=2.0,
                check=lambda items: count_at_least(items or [], 3),
                description=">=3 implications",
            ),
            Criterion(
                name="all_have_supporting_ids",
                weight=2.0,
                check=lambda items: every_item_has_fields(
                    items or [], ["supporting_ids"],
                ),
                description="every implication cites supporting papers",
            ),
        ),
    ),
    "weaver": Rubric(
        agent_name="weaver",
        version="0.1",
        description="Narrative coherence (text path)",
        loader=_load_text_path,
        criteria=(
            Criterion(
                name="length_floor",
                weight=1.0,
                check=lambda text: 1.0 if (text or "").strip().split() and
                                     len((text or "").split()) >= 200 else 0.0,
                description=">=200 words",
            ),
            Criterion(
                name="cite_density",
                weight=1.0,
                check=lambda text: min(
                    1.0,
                    (text or "").count("[@") / max(1, len((text or "").split()) // 50),
                ),
                description="~1 citation per 50 words",
            ),
        ),
    ),
}


# ---------- scoring ----------

def _normalize_total(criteria: tuple[Criterion, ...],
                     scores: dict[str, float]) -> float:
    total_weight = sum(c.weight for c in criteria) or 1.0
    weighted = sum(c.weight * scores.get(c.name, 0.0) for c in criteria)
    return weighted / total_weight


def score_auto(
    db_path: Path,
    *,
    run_id: str | None,
    span_id: str | None,
    agent_name: str,
    artifact_path: Path,
    rubric_name: str | None = None,
) -> dict[str, Any]:
    """Auto-rubric scoring for a persona.

    Loads the artifact via the rubric's loader, runs each check,
    persists a row to `agent_quality` with judge='auto-rubric'.
    Returns the persisted payload.

    `rubric_name` defaults to `agent_name`.
    """
    rubric = RUBRICS.get(rubric_name or agent_name)
    if rubric is None:
        return {
            "ok": False,
            "error": f"no rubric for agent {agent_name!r}",
        }
    artifact = rubric.loader(Path(artifact_path))
    per_criterion: dict[str, float] = {}
    for c in rubric.criteria:
        try:
            per_criterion[c.name] = float(c.check(artifact))
        except Exception as e:  # noqa: BLE001 — record + zero
            per_criterion[c.name] = 0.0
            per_criterion[f"{c.name}__error"] = -1.0  # signal
    score_total = _normalize_total(rubric.criteria, per_criterion)
    persisted = _persist(
        db_path=db_path,
        run_id=run_id, span_id=span_id, agent_name=agent_name,
        rubric_version=rubric.version,
        score_total=score_total,
        criteria_json=json.dumps(per_criterion, sort_keys=True),
        judge="auto-rubric",
        artifact_path=str(artifact_path),
        reasoning=None,
        notes=None,
    )
    return {
        "ok": True,
        "agent_name": agent_name,
        "rubric_version": rubric.version,
        "score_total": score_total,
        "criteria": per_criterion,
        "judge": "auto-rubric",
        "quality_id": persisted,
    }


def emit_judge_prompt(
    agent_name: str,
    artifact_path: Path,
    *,
    rubric_name: str | None = None,
) -> dict[str, Any]:
    """v0.92b — produce the structured prompt the `quality-judge`
    sub-agent consumes.

    The orchestrator dispatches `quality-judge` with this payload as
    the sub-agent's prompt, then calls `persist_judge_result(...)`
    with the sub-agent's JSON output.
    """
    rubric = RUBRICS.get(rubric_name or agent_name)
    if rubric is None:
        return {"ok": False, "error": f"no rubric for {agent_name!r}"}
    artifact_text = ""
    p = Path(artifact_path)
    if p.exists():
        try:
            artifact_text = p.read_text()
        except OSError as e:
            artifact_text = f"<read error: {e}>"
    return {
        "ok": True,
        "agent_name": agent_name,
        "rubric_version": rubric.version,
        "rubric_description": rubric.description,
        "artifact_path": str(p),
        "artifact_text": artifact_text[:16000],  # cap context
        "criteria": [
            {
                "name": c.name,
                "weight": c.weight,
                "description": c.description,
            }
            for c in rubric.criteria
        ],
        "instructions": (
            "Score each criterion on a 0.0–1.0 scale. Return a JSON "
            "object: {\"scores\": {<criterion>: float}, "
            "\"reasoning\": <one paragraph>}. Be honest — low "
            "scores when warranted are more useful than inflated "
            "praise."
        ),
    }


def persist_judge_result(
    db_path: Path,
    *,
    run_id: str | None,
    span_id: str | None,
    agent_name: str,
    artifact_path: Path,
    judge_json: dict,
    rubric_name: str | None = None,
) -> dict[str, Any]:
    """Validate + persist the `quality-judge` sub-agent's output."""
    rubric = RUBRICS.get(rubric_name or agent_name)
    if rubric is None:
        return {"ok": False, "error": f"no rubric for {agent_name!r}"}
    scores = (judge_json or {}).get("scores") or {}
    per_criterion = {
        c.name: float(scores.get(c.name, 0.0))
        for c in rubric.criteria
    }
    score_total = _normalize_total(rubric.criteria, per_criterion)
    qid = _persist(
        db_path=db_path,
        run_id=run_id, span_id=span_id, agent_name=agent_name,
        rubric_version=rubric.version,
        score_total=score_total,
        criteria_json=json.dumps(per_criterion, sort_keys=True),
        judge="llm-judge",
        artifact_path=str(artifact_path),
        reasoning=str(judge_json.get("reasoning") or "")[:8000],
        notes=None,
    )
    return {
        "ok": True,
        "agent_name": agent_name,
        "score_total": score_total,
        "criteria": per_criterion,
        "judge": "llm-judge",
        "quality_id": qid,
    }


def _persist(
    *,
    db_path: Path,
    run_id: str | None,
    span_id: str | None,
    agent_name: str,
    rubric_version: str,
    score_total: float,
    criteria_json: str,
    judge: str,
    artifact_path: str | None,
    reasoning: str | None,
    notes: str | None,
) -> int:
    from lib.cache import connect_wal
    from lib.migrations import ensure_current
    ensure_current(Path(db_path))
    con = connect_wal(Path(db_path))
    try:
        with con:
            cur = con.execute(
                "INSERT INTO agent_quality "
                "(run_id, span_id, agent_name, rubric_version, "
                "score_total, criteria_json, judge, artifact_path, "
                "reasoning, notes, at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, span_id, agent_name, rubric_version,
                 float(score_total), criteria_json, judge,
                 artifact_path, reasoning, notes,
                 datetime.now(UTC).isoformat()),
            )
            return int(cur.lastrowid or 0)
    finally:
        con.close()


def list_for_run(db_path: Path, run_id: str) -> list[dict]:
    """Return every quality row for `run_id`, newest first."""
    from lib.cache import connect_wal
    con = connect_wal(Path(db_path))
    try:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT * FROM agent_quality WHERE run_id=? "
            "ORDER BY at DESC",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def summary(db_path: Path, *, run_id: str | None = None) -> dict:
    """Per-agent summary across runs (or one run if `run_id` set).

    Returns: {n_rows, by_agent: {agent_name: {n, mean, min, max,
                                              latest_score}}}.
    """
    from lib.cache import connect_wal
    con = connect_wal(Path(db_path))
    try:
        con.row_factory = sqlite3.Row
        if run_id:
            rows = con.execute(
                "SELECT agent_name, score_total, at FROM agent_quality "
                "WHERE run_id=?", (run_id,),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT agent_name, score_total, at FROM agent_quality"
            ).fetchall()
        by_agent: dict[str, dict] = {}
        for r in rows:
            d = by_agent.setdefault(
                r["agent_name"],
                {"n": 0, "scores": [], "latest_at": None,
                 "latest_score": None},
            )
            d["n"] += 1
            d["scores"].append(float(r["score_total"]))
            if d["latest_at"] is None or r["at"] > d["latest_at"]:
                d["latest_at"] = r["at"]
                d["latest_score"] = float(r["score_total"])
        for agent_name, d in by_agent.items():
            scores = d.pop("scores")
            d["mean"] = sum(scores) / len(scores) if scores else 0.0
            d["min"] = min(scores) if scores else 0.0
            d["max"] = max(scores) if scores else 0.0
        return {"n_rows": len(rows), "by_agent": by_agent}
    finally:
        con.close()


def main(argv: list[str] | None = None) -> int:
    """CLI: `summary` reports per-agent quality."""
    import argparse
    p = argparse.ArgumentParser(
        prog="agent_quality",
        description="Agent quality scoring (v0.92).",
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("summary", help="Per-agent quality summary")
    s.add_argument("--db", required=True)
    s.add_argument("--run-id", default=None)
    args = p.parse_args(argv)
    out = summary(Path(args.db), run_id=args.run_id)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

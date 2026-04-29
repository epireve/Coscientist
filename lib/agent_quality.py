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
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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

def _items_from(payload: Any, list_field: str) -> list:
    """v0.105 — accept either a raw list or a dict with `list_field`.

    Rubrics built for legacy `--quality-artifact` (list-top) now
    also accept dict-top record-phase output_json by extracting the
    canonical list field.
    """
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        v = payload.get(list_field)
        if isinstance(v, list):
            return v
    return []


RUBRICS: dict[str, Rubric] = {
    "scout": Rubric(
        agent_name="scout",
        version="0.2",
        description="Paper-discovery breadth + dedup",
        loader=_load_json_path,
        criteria=(
            Criterion(
                name="enough_candidates",
                weight=2.0,
                check=lambda d: count_at_least(
                    _items_from(d, "shortlist"), 30,
                ),
                description=">=30 candidate papers",
            ),
            Criterion(
                name="canonical_id_present",
                weight=1.0,
                check=lambda d: fraction_with_field(
                    _items_from(d, "shortlist"), "canonical_id",
                ),
                description="every paper has canonical_id",
            ),
            Criterion(
                name="title_present",
                weight=1.0,
                check=lambda d: fraction_with_field(
                    _items_from(d, "shortlist"), "title",
                ),
                description="every paper has title",
            ),
            Criterion(
                name="source_diversity",
                weight=1.0,
                check=lambda d: unique_kind_count(
                    _items_from(d, "shortlist"), "source",
                    min_unique=3,
                ),
                description=">=3 distinct sources",
            ),
        ),
    ),
    "surveyor": Rubric(
        agent_name="surveyor",
        version="0.2",
        description="Gap identification specificity",
        loader=_load_json_path,
        criteria=(
            Criterion(
                name="enough_gaps",
                weight=2.0,
                check=lambda d: count_at_least(
                    _items_from(d, "gaps"), 5,
                ),
                description=">=5 gaps",
            ),
            Criterion(
                name="why_present",
                weight=1.5,
                check=lambda d: fraction_with_field(
                    _items_from(d, "gaps"), "why_matters",
                ),
                description="every gap has why-this-matters",
            ),
            Criterion(
                name="kind_present",
                weight=1.0,
                check=lambda d: fraction_with_field(
                    _items_from(d, "gaps"), "kind",
                ),
                description="every gap has kind label",
            ),
        ),
    ),
    "architect": Rubric(
        agent_name="architect",
        version="0.2",
        description="Candidate-approach completeness",
        loader=_load_json_path,
        criteria=(
            Criterion(
                name="enough_candidates",
                weight=2.0,
                check=lambda d: count_at_least(
                    _items_from(d, "hypotheses"), 1,
                ),
                description=">=1 hypothesis (max 3 per spec)",
            ),
            Criterion(
                name="all_have_falsifiers",
                weight=2.0,
                check=lambda d: fraction_with_field(
                    _items_from(d, "hypotheses"), "falsifiers",
                ),
                description="every hypothesis has falsifiers",
            ),
            Criterion(
                name="all_have_method_sketch",
                weight=1.5,
                check=lambda d: fraction_with_field(
                    _items_from(d, "hypotheses"), "method_sketch",
                ),
                description="every hypothesis has method_sketch",
            ),
        ),
    ),
    "synthesist": Rubric(
        agent_name="synthesist",
        version="0.2",
        description="Cross-paper implications",
        loader=_load_json_path,
        criteria=(
            Criterion(
                name="enough_implications",
                weight=2.0,
                check=lambda d: count_at_least(
                    _items_from(d, "implications"), 3,
                ),
                description=">=3 implications",
            ),
            Criterion(
                name="all_have_supporting_ids",
                weight=2.0,
                check=lambda d: every_item_has_fields(
                    _items_from(d, "implications"), ["supporting_ids"],
                ),
                description="every implication cites supporting papers",
            ),
        ),
    ),
    "weaver": Rubric(
        agent_name="weaver",
        version="0.2",
        description="Coherence map (dict JSON per v0.103 spec)",
        loader=_load_json_path,
        criteria=(
            Criterion(
                name="has_sharpened_question",
                weight=1.5,
                check=lambda d: 1.0 if isinstance(d, dict)
                                  and (d.get("sharpened_question") or "").strip()
                                  else 0.0,
                description="non-empty sharpened_question",
            ),
            Criterion(
                name="enough_consensus_or_tensions",
                weight=2.0,
                check=lambda d: 1.0 if (
                    len(_items_from(d, "consensus")) +
                    len(_items_from(d, "tensions"))
                ) >= 3 else 0.0,
                description=">=3 consensus or tension entries",
            ),
            Criterion(
                name="consensus_have_supporting_ids",
                weight=1.0,
                check=lambda d: fraction_with_field(
                    _items_from(d, "consensus"), "supporting_ids",
                ),
                description="every consensus entry cites papers",
            ),
        ),
    ),
    # v0.104 — rubrics for the v0.103-added personas. These score
    # the record-phase output_json directly (dict-top with phase +
    # items) so callers don't need to pass --quality-artifact.
    "cartographer": Rubric(
        agent_name="cartographer",
        version="0.1",
        description="Seminal-paper coverage",
        loader=_load_json_path,
        criteria=(
            Criterion(
                name="has_summary",
                weight=1.0,
                check=lambda d: 1.0 if isinstance(d, dict)
                                  and (d.get("summary") or "").strip()
                                  else 0.0,
                description="non-empty summary",
            ),
            Criterion(
                name="enough_seminals",
                weight=2.0,
                check=lambda d: count_at_least(
                    (d or {}).get("seminals") or [], 3,
                ),
                description=">=3 seminal papers",
            ),
            Criterion(
                name="seminals_have_why",
                weight=1.5,
                check=lambda d: fraction_with_field(
                    (d or {}).get("seminals") or [], "why_seminal",
                ),
                description="every seminal has why_seminal",
            ),
        ),
    ),
    "chronicler": Rubric(
        agent_name="chronicler",
        version="0.1",
        description="Timeline coverage + dead-end tracking",
        loader=_load_json_path,
        criteria=(
            Criterion(
                name="has_summary",
                weight=1.0,
                check=lambda d: 1.0 if isinstance(d, dict)
                                  and (d.get("summary") or "").strip()
                                  else 0.0,
                description="non-empty summary",
            ),
            Criterion(
                name="enough_timeline",
                weight=2.0,
                check=lambda d: count_at_least(
                    (d or {}).get("timeline") or [], 3,
                ),
                description=">=3 timeline events",
            ),
            Criterion(
                name="timeline_event_present",
                weight=1.0,
                check=lambda d: fraction_with_field(
                    (d or {}).get("timeline") or [], "event",
                ),
                description="every timeline entry has event",
            ),
        ),
    ),
    "inquisitor": Rubric(
        agent_name="inquisitor",
        version="0.1",
        description="Per-hypothesis adversarial coverage",
        loader=_load_json_path,
        criteria=(
            Criterion(
                name="enough_evaluations",
                weight=2.0,
                check=lambda d: count_at_least(
                    (d or {}).get("evaluations") or [], 1,
                ),
                description=">=1 evaluation per architect hypothesis",
            ),
            Criterion(
                name="all_have_steelman",
                weight=2.0,
                check=lambda d: fraction_with_field(
                    (d or {}).get("evaluations") or [], "steelman",
                ),
                description="every evaluation has steelman",
            ),
            Criterion(
                name="all_have_killer",
                weight=2.0,
                check=lambda d: fraction_with_field(
                    (d or {}).get("evaluations") or [],
                    "killer_experiment",
                ),
                description="every evaluation has killer_experiment",
            ),
            Criterion(
                name="all_have_survival",
                weight=1.5,
                check=lambda d: fraction_with_field(
                    (d or {}).get("evaluations") or [], "survival",
                ),
                description="every evaluation has survival score",
            ),
        ),
    ),
    "visionary": Rubric(
        agent_name="visionary",
        version="0.1",
        description="New-direction depth",
        loader=_load_json_path,
        criteria=(
            Criterion(
                name="enough_directions",
                weight=2.0,
                check=lambda d: count_at_least(
                    (d or {}).get("directions") or [], 2,
                ),
                description=">=2 directions",
            ),
            Criterion(
                name="all_have_first_step",
                weight=1.5,
                check=lambda d: fraction_with_field(
                    (d or {}).get("directions") or [], "first_step",
                ),
                description="every direction has first_step",
            ),
            Criterion(
                name="all_have_why_underexplored",
                weight=1.5,
                check=lambda d: fraction_with_field(
                    (d or {}).get("directions") or [],
                    "why_underexplored",
                ),
                description="every direction has why_underexplored",
            ),
        ),
    ),
    "steward": Rubric(
        agent_name="steward",
        version="0.1",
        description="Final-artifact integrity check",
        loader=_load_json_path,
        criteria=(
            Criterion(
                name="eval_passed",
                weight=2.0,
                check=lambda d: 1.0 if isinstance(d, dict)
                                  and d.get("eval_passed") is True
                                  else 0.0,
                description="research-eval passed",
            ),
            Criterion(
                name="zero_hedge_words",
                weight=1.5,
                check=lambda d: 1.0 if isinstance(d, dict)
                                  and d.get("hedge_word_hits", -1) == 0
                                  else 0.0,
                description="hedge_word_hits == 0",
            ),
            Criterion(
                name="claims_cited",
                weight=1.0,
                check=lambda d: 1.0 if isinstance(d, dict)
                                  and (d.get("claims_cited") or 0) >= 5
                                  else 0.0,
                description=">=5 claims cited",
            ),
            Criterion(
                name="papers_cited",
                weight=1.0,
                check=lambda d: 1.0 if isinstance(d, dict)
                                  and (d.get("papers_cited") or 0) >= 10
                                  else 0.0,
                description=">=10 papers cited",
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
        except Exception:  # noqa: BLE001 — record + zero
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


def leaderboard(roots: list[Path] | None = None) -> dict:
    """v0.96 — per-agent quality summary across every run DB.

    Walks `~/.cache/coscientist/runs/run-*.db` (or supplied roots[0])
    and aggregates `agent_quality` rows. Same shape as `summary`,
    plus `n_runs` (distinct run_ids per agent) and `n_dbs` scanned.
    """
    from lib.cache import runs_dir
    root = roots[0] if roots else runs_dir()
    by_agent: dict[str, dict] = {}
    n_dbs = 0
    if not root.exists():
        return {"n_rows": 0, "n_dbs": 0, "by_agent": {}}
    for db in sorted(root.glob("run-*.db")):
        try:
            con = sqlite3.connect(db)
            con.row_factory = sqlite3.Row
            try:
                rows = con.execute(
                    "SELECT agent_name, score_total, at, run_id "
                    "FROM agent_quality"
                ).fetchall()
            except sqlite3.OperationalError:
                con.close()
                continue
            con.close()
            n_dbs += 1
            for r in rows:
                d = by_agent.setdefault(
                    r["agent_name"],
                    {"n": 0, "scores": [], "run_ids": set(),
                     "latest_at": None, "latest_score": None},
                )
                d["n"] += 1
                d["scores"].append(float(r["score_total"]))
                if r["run_id"]:
                    d["run_ids"].add(r["run_id"])
                if d["latest_at"] is None or r["at"] > d["latest_at"]:
                    d["latest_at"] = r["at"]
                    d["latest_score"] = float(r["score_total"])
        except Exception:
            continue
    n_rows = 0
    for agent_name, d in by_agent.items():
        scores = d.pop("scores")
        run_ids = d.pop("run_ids")
        d["n_runs"] = len(run_ids)
        d["mean"] = sum(scores) / len(scores) if scores else 0.0
        d["min"] = min(scores) if scores else 0.0
        d["max"] = max(scores) if scores else 0.0
        n_rows += d["n"]
    return {"n_rows": n_rows, "n_dbs": n_dbs, "by_agent": by_agent}


def quality_drift(
    *,
    window: int = 5,
    roots: list[Path] | None = None,
    threshold: float = 0.05,
) -> dict:
    """v0.127 — per-agent score drift over time.

    Walks every run DB, sorts each agent's scores by `at`,
    splits into latest `window` vs prior `window`, computes
    delta. Surfaces "scout was 0.85 mean over last 5 runs but
    0.55 over prior 5 — investigate".

    Returns: {n_rows, n_dbs, window, by_agent: {name: {
      n_total, latest_window: {n, mean, scores},
      prior_window: {n, mean, scores}, delta_mean,
      direction: 'improving|declining|stable|insufficient'
    }}}.

    Direction:
      - 'insufficient' if either window has n < window
      - 'improving' if delta_mean > 0.05
      - 'declining' if delta_mean < -0.05
      - 'stable' otherwise
    """
    from lib.cache import runs_dir
    root = roots[0] if roots else runs_dir()
    if window < 1:
        window = 1
    series: dict[str, list[tuple[str, float]]] = {}
    n_dbs = 0
    if not root.exists():
        return {"n_rows": 0, "n_dbs": 0,
                "window": window, "by_agent": {}}
    for db in sorted(root.glob("run-*.db")):
        try:
            con = sqlite3.connect(db)
            con.row_factory = sqlite3.Row
            try:
                rows = con.execute(
                    "SELECT agent_name, score_total, at "
                    "FROM agent_quality"
                ).fetchall()
            except sqlite3.OperationalError:
                con.close()
                continue
            con.close()
            n_dbs += 1
            for r in rows:
                series.setdefault(r["agent_name"], []).append(
                    (r["at"], float(r["score_total"])),
                )
        except Exception:
            continue

    by_agent: dict[str, dict] = {}
    n_rows = 0
    for agent, points in series.items():
        points.sort(key=lambda p: p[0])
        n_total = len(points)
        n_rows += n_total
        latest = points[-window:]
        prior = points[-(2 * window):-window] if n_total >= 2 else []
        latest_scores = [p[1] for p in latest]
        prior_scores = [p[1] for p in prior]
        latest_mean = (
            sum(latest_scores) / len(latest_scores)
            if latest_scores else 0.0
        )
        prior_mean = (
            sum(prior_scores) / len(prior_scores)
            if prior_scores else 0.0
        )
        delta = latest_mean - prior_mean if prior_scores else 0.0
        if (len(latest_scores) < window
                or len(prior_scores) < window):
            direction = "insufficient"
        elif delta > threshold:
            direction = "improving"
        elif delta < -threshold:
            direction = "declining"
        else:
            direction = "stable"
        by_agent[agent] = {
            "n_total": n_total,
            "latest_window": {
                "n": len(latest_scores),
                "mean": round(latest_mean, 3),
                "scores": [round(s, 3) for s in latest_scores],
            },
            "prior_window": {
                "n": len(prior_scores),
                "mean": round(prior_mean, 3),
                "scores": [round(s, 3) for s in prior_scores],
            },
            "delta_mean": round(delta, 3),
            "direction": direction,
        }
    return {
        "n_rows": n_rows, "n_dbs": n_dbs,
        "window": window, "by_agent": by_agent,
    }


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
    lb = sub.add_parser(
        "leaderboard",
        help="Cross-run leaderboard (scans all run DBs)",
    )
    lb.add_argument("--root", default=None,
                     help="Override runs root (default ~/.cache/coscientist/runs)")
    dr = sub.add_parser(
        "drift",
        help="v0.127: per-agent quality drift over time. "
             "Latest --window scores vs prior --window.",
    )
    dr.add_argument("--root", default=None)
    dr.add_argument("--window", type=int, default=10,
                     help="Window size (default 10)")
    dr.add_argument("--threshold", type=float, default=0.1,
                     help="Drift delta threshold (default 0.1)")
    dr.add_argument("--format", choices=("json", "text"),
                     default="json")
    args = p.parse_args(argv)
    if args.cmd == "summary":
        out = summary(Path(args.db), run_id=args.run_id)
        print(json.dumps(out, indent=2))
        return 0
    if args.cmd == "leaderboard":
        roots = [Path(args.root)] if args.root else None
        out = leaderboard(roots=roots)
        print(json.dumps(out, indent=2))
        return 0
    # drift
    roots = [Path(args.root)] if args.root else None
    out = quality_drift(
        window=args.window, roots=roots,
        threshold=args.threshold,
    )
    if args.format == "json":
        print(json.dumps(out, indent=2))
    else:
        print(_render_drift_text(out))
    return 0


def _render_drift_text(report: dict) -> str:
    lines = [
        f"# Agent quality drift (window={report.get('window', 0)})",
        f"- DBs scanned: {report.get('n_dbs', 0)}",
        f"- Rows: {report.get('n_rows', 0)}",
        "",
    ]
    by_agent = report.get("by_agent") or {}
    if not by_agent:
        lines.append("_No quality data yet._")
        return "\n".join(lines)
    rows = sorted(by_agent.items(),
                   key=lambda kv: kv[1].get("delta_mean", 0))
    for agent, d in rows:
        direction = d.get("direction", "?")
        delta = d.get("delta_mean", 0)
        latest = d.get("latest_window", {})
        prior = d.get("prior_window", {})
        lines.append(
            f"- **{agent}** [{direction}] delta={delta:+.3f} "
            f"latest={latest.get('mean', 0):.3f} "
            f"(n={latest.get('n', 0)}) "
            f"prior={prior.get('mean', 0):.3f} "
            f"(n={prior.get('n', 0)})"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())

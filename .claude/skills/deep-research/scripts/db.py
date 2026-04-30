#!/usr/bin/env python3
"""deep-research DB helpers: init, record phases, record breaks, query state.

All run state lives in ~/.cache/coscientist/runs/run-<run_id>.db.
Schema is in lib/sqlite_schema.sql.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import run_db_path, run_inputs_dir  # noqa: E402
from lib.concept_velocity import (  # noqa: E402
    compute_velocities,
)
from lib.concept_velocity import (
    render_summary as _velocity_render,
)
from lib.disagreement import (  # noqa: E402
    compute_disagreement,
)
from lib.disagreement import (
    persist_to_run_db as _disagreement_persist,
)
from lib.disagreement import (
    render_summary as _disagreement_render,
)
from lib.era_detection import detect_inflections  # noqa: E402
from lib.era_detection import render_summary as _era_render
from lib.phase_groups import batchable as _phase_batchable  # noqa: E402
from lib.search_framework import (  # noqa: E402
    SearchStrategy,
    suggest_framework,
    template_for,
)

SCHEMA_PATH = _REPO_ROOT / "lib" / "sqlite_schema.sql"


def _resolve_json_arg(flag: str, val: str) -> str:
    """v0.191 — accept inline JSON literal OR file path.

    Heuristic: leading `{` or `[` (after stripping whitespace)
    means inline JSON. Otherwise treat as a file path. Inline
    literal is validated via `json.loads` and the original text
    returned. File paths are read into text.
    """
    if not val or not val.strip():
        raise SystemExit(
            f"{flag}: empty value",
        )
    stripped = val.lstrip()
    if stripped.startswith(("{", "[")):
        try:
            json.loads(val)
        except json.JSONDecodeError as e:
            raise SystemExit(
                f"{flag}: invalid inline JSON: {e}",
            ) from None
        return val
    if os.path.isfile(val):
        return Path(val).read_text()
    raise SystemExit(
        f"{flag}: not valid JSON literal and not a file path: "
        f"{val[:60]}",
    )


def _resolve_json_arg_path(flag: str, val: str) -> Path:
    """v0.191 — resolve to a real file path.

    For helpers (schema validator, rubric scorer) that need a
    Path. Inline JSON is materialized to a NamedTemporaryFile
    and the temp path returned. File paths returned as-is.
    """
    if not val or not val.strip():
        raise SystemExit(f"{flag}: empty value")
    stripped = val.lstrip()
    if stripped.startswith(("{", "[")):
        try:
            json.loads(val)
        except json.JSONDecodeError as e:
            raise SystemExit(
                f"{flag}: invalid inline JSON: {e}",
            ) from None
        import tempfile
        fd, path = tempfile.mkstemp(suffix=".json", prefix="coscientist-")
        with os.fdopen(fd, "w") as f:
            f.write(val)
        return Path(path)
    if os.path.isfile(val):
        return Path(val)
    raise SystemExit(
        f"{flag}: not valid JSON literal and not a file path: "
        f"{val[:60]}",
    )

# v0.46.4: Expedition rebrand. Old SEEKER names retained as aliases below
# for old run DBs (phases.name is TEXT — old rows survive untouched).
PHASES_IN_ORDER = [
    "scout",         # was: social
    "cartographer",  # was: grounder
    "chronicler",    # was: historian
    "surveyor",      # was: gaper
    "synthesist",    # was: vision
    "architect",     # was: theorist
    "inquisitor",    # was: rude
    "weaver",        # was: synthesizer
    "visionary",     # was: thinker
    "steward",       # was: scribe
]
# Backward-compat aliases — accept old phase names from in-flight runs that
# were started before v0.46.4. Maps old → new.
PHASE_ALIASES = {
    "social": "scout",
    "grounder": "cartographer",
    "historian": "chronicler",
    "gaper": "surveyor",
    "vision": "synthesist",
    "theorist": "architect",
    "rude": "inquisitor",
    "synthesizer": "weaver",
    "thinker": "visionary",
    "scribe": "steward",
}
BREAK_AFTER = {"scout": 0, "surveyor": 1, "weaver": 2}


def _connect(run_id: str) -> sqlite3.Connection:
    db = run_db_path(run_id)
    fresh = not db.exists()
    if fresh:
        # Build base schema first
        con = sqlite3.connect(db)
        con.executescript(SCHEMA_PATH.read_text())
        con.close()
    # v0.14: apply any unapplied migrations before returning the connection
    from lib.migrations import ensure_current
    ensure_current(db)
    # v0.66: WAL mode lets Phase-1 parallel-dispatch (cartographer +
    # chronicler + surveyor concurrent) write without SQLITE_BUSY.
    from lib.cache import connect_wal
    con = connect_wal(db)
    con.row_factory = sqlite3.Row
    return con


def is_overnight(con: sqlite3.Connection, run_id: str) -> bool:
    """Return True if the run was started with --overnight."""
    row = con.execute(
        "SELECT overnight FROM runs WHERE run_id=?", (run_id,)
    ).fetchone()
    if row is None:
        return False
    return bool(row["overnight"])


def cmd_init(args: argparse.Namespace) -> None:
    run_id = secrets.token_hex(4)
    con = _connect(run_id)
    config = (
        json.loads(Path(args.config).read_text()) if args.config else {}
    )
    overnight = 1 if getattr(args, "overnight", False) else 0

    # v0.53.5 — Wide → Deep handoff
    parent_run_id = getattr(args, "seed_from_wide", None)
    seed_mode = getattr(args, "seed_mode", None)
    seed_top_k = getattr(args, "seed_top_k", 30) or 30
    seed_papers: list[tuple[str, str]] = []  # (canonical_id, role)

    if parent_run_id:
        if not seed_mode:
            seed_mode = "abstract"
        if seed_mode not in ("abstract", "full-text", "cumulative"):
            raise SystemExit(
                f"--seed-mode must be abstract|full-text|cumulative "
                f"(got {seed_mode!r})"
            )
        seed_papers = _load_wide_seed(
            parent_run_id, seed_mode, seed_top_k,
            current_run_id=run_id,
        )
        if not seed_papers:
            raise SystemExit(
                f"no seed papers found from Wide run "
                f"{parent_run_id} — synthesis.json missing or empty"
            )

    with con:
        con.execute(
            "INSERT INTO runs (run_id, question, started_at, config_json, "
            "overnight, parent_run_id, seed_mode) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, args.question, datetime.now(UTC).isoformat(),
             json.dumps(config), overnight, parent_run_id, seed_mode),
        )
        for i, name in enumerate(PHASES_IN_ORDER):
            con.execute(
                "INSERT INTO phases (run_id, name, ordinal) VALUES (?, ?, ?)",
                (run_id, name, i),
            )
        # Seed papers_in_run with wide handoff
        for cid, role in seed_papers:
            con.execute(
                "INSERT OR IGNORE INTO papers_in_run "
                "(run_id, canonical_id, added_in_phase, role) "
                "VALUES (?, ?, ?, ?)",
                (run_id, cid, "seed-from-wide", role),
            )
    con.close()
    print(run_id)


def _load_wide_seed(
    wide_run_id: str, seed_mode: str, top_k: int,
    *, current_run_id: str | None = None,
) -> list[tuple[str, str]]:
    """Read Wide synthesis.json for handoff into Deep.

    Returns list of (canonical_id, role) tuples.

    seed_mode mapping:
      abstract   → triage top-K shortlist (relevance-sorted)
      full-text  → read digests (already extracted; full-text known)
      cumulative → both (Deep refines on top of Wide's full-text reads)

    role assignments:
      abstract  → 'seed'      (Deep scout will harvest more around them)
      full-text → 'supporting' (already vetted in Wide)

    v0.53.7 — cycle guard + partial-data warning.
    """
    from lib.cache import cache_root  # noqa: WPS433
    # Cycle guard: walk parent_run_id chain looking for current_run_id.
    if current_run_id:
        _check_no_cycle(wide_run_id, current_run_id)

    synth_path = (
        cache_root() / "runs" / f"run-{wide_run_id}" / "synthesis.json"
    )
    if not synth_path.exists():
        return []
    synth = json.loads(synth_path.read_text())

    # Partial-data warning — Wide may have aborted mid-run
    n_total = synth.get("n_total", 0)
    n_complete = synth.get("n_complete", 0)
    if n_total and n_complete < n_total:
        sys.stderr.write(
            f"WARN: Wide run {wide_run_id} synthesis is partial — "
            f"{n_complete}/{n_total} complete. Seed corpus may be "
            f"smaller than expected.\n"
        )

    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    if seed_mode in ("abstract", "cumulative"):
        for row in synth.get("top_shortlist", [])[:top_k]:
            cid = row.get("canonical_id")
            if cid and cid not in seen:
                seen.add(cid)
                out.append((cid, "seed"))
    if seed_mode in ("full-text", "cumulative"):
        for d in synth.get("digests", [])[:top_k]:
            cid = d.get("canonical_id")
            if cid and cid not in seen:
                seen.add(cid)
                out.append((cid, "supporting"))
    return out


def _check_no_cycle(parent_run_id: str, current_run_id: str) -> None:
    """Walk parent_run_id ancestor chain in run DBs; raise if cycle.

    Each Deep run logs its parent_run_id (from --seed-from-wide).
    Wide run plan.json may also carry parent_run_id (Deep → Wide loop).
    Bound walk at 16 hops for safety.
    """
    from lib.cache import cache_root  # noqa: WPS433
    visited = {current_run_id}
    cur = parent_run_id
    for _ in range(16):
        if cur is None:
            return
        if cur in visited:
            raise SystemExit(
                f"cycle detected in handoff lineage: run {cur!r} "
                f"is already an ancestor of {current_run_id!r}"
            )
        visited.add(cur)
        # Look up cur's parent — could be a Deep DB or a Wide plan.json
        deep_db = cache_root() / "runs" / f"run-{cur}.db"
        wide_plan = (
            cache_root() / "runs" / f"run-{cur}" / "plan.json"
        )
        next_parent: str | None = None
        if deep_db.exists():
            try:
                con = sqlite3.connect(deep_db)
                row = con.execute(
                    "SELECT parent_run_id FROM runs WHERE run_id=?",
                    (cur,),
                ).fetchone()
                con.close()
                next_parent = row[0] if row else None
            except sqlite3.Error:
                next_parent = None
        elif wide_plan.exists():
            try:
                pd = json.loads(wide_plan.read_text())
                next_parent = pd.get("parent_run_id")
            except (json.JSONDecodeError, OSError):
                next_parent = None
        cur = next_parent
    raise SystemExit(
        "handoff lineage too deep (>16 hops); aborting to avoid "
        "runaway walk"
    )


def cmd_record_phase(args: argparse.Namespace) -> None:
    con = _connect(args.run_id)
    # v0.46.4: accept old SEEKER phase names from in-flight runs (resume
    # safety). Map to new Expedition name before lookup.
    if args.phase in PHASE_ALIASES:
        args.phase = PHASE_ALIASES[args.phase]
    # Reject unknown phase names: a silent no-op UPDATE would let an
    # orchestrator typo (e.g. "theroist") silently desync the run state
    # from what the orchestrator believes is recorded.
    if args.phase not in PHASES_IN_ORDER:
        con.close()
        raise SystemExit(
            f"unknown phase {args.phase!r}; must be one of {PHASES_IN_ORDER}"
        )
    exists = con.execute(
        "SELECT 1 FROM phases WHERE run_id=? AND name=?",
        (args.run_id, args.phase),
    ).fetchone()
    if not exists:
        con.close()
        raise SystemExit(
            f"phase {args.phase!r} not found for run {args.run_id} — "
            "did you call init?"
        )
    now = datetime.now(UTC).isoformat()
    output = (
        _resolve_json_arg("--output-json", args.output_json)
        if args.output_json else None
    )
    with con:
        if args.start:
            con.execute(
                "UPDATE phases SET started_at=? WHERE run_id=? AND name=?",
                (now, args.run_id, args.phase),
            )
        if args.complete:
            con.execute(
                "UPDATE phases SET completed_at=?, output_json=? WHERE run_id=? AND name=?",
                (now, output, args.run_id, args.phase),
            )
        if args.error:
            con.execute(
                "UPDATE phases SET error=? WHERE run_id=? AND name=?",
                (args.error, args.run_id, args.phase),
            )
    con.close()
    # v0.93a — emit a v0.89 trace span mirror for live debugging.
    _emit_phase_span(args.run_id, args.phase,
                     start=args.start, complete=args.complete,
                     error=args.error, output_json=args.output_json)
    # v0.94/v0.103 — auto-quality scoring on phase completion.
    # Best-effort. Schema gate runs on output_json (record-phase
    # contract); rubric runs on --quality-artifact only. v0.94
    # fallback to output_json removed in v0.103 — rubrics expect
    # richer persona-side artifacts (e.g. /tmp/scout-shortlist.json),
    # not record-phase summary JSON.
    if args.complete:
        if args.output_json:
            try:
                resolved = _resolve_json_arg_path(
                    "--output-json", args.output_json,
                )
                _maybe_validate_schema(args.run_id, args.phase,
                                        str(resolved))
            except SystemExit:
                # already raised earlier; defensive — never reached
                pass
        rubric_target = getattr(args, "quality_artifact", None)
        if rubric_target:
            try:
                resolved = _resolve_json_arg_path(
                    "--quality-artifact", rubric_target,
                )
                _maybe_auto_score(args.run_id, args.phase,
                                   str(resolved))
            except SystemExit:
                pass
        # v0.203 — auto-tournament hook between inquisitor and weaver.
        # Fires only on inquisitor --complete and only when either the
        # --auto-tournament flag is passed OR COSCIENTIST_AUTO_TOURNAMENT=1.
        # Runs deterministic heuristic-judge pairwise matches across every
        # hypothesis tree in the run, then prunes low-Elo subtrees once.
        # Best-effort: errors surfaced in returned dict but never abort
        # the parent record-phase call.
        if (args.phase == "inquisitor" and
                (getattr(args, "auto_tournament", False) or
                 os.environ.get("COSCIENTIST_AUTO_TOURNAMENT") == "1")):
            try:
                from lib import auto_tournament
                from lib.cache import run_db_path
                run_db = run_db_path(args.run_id)
                # Honour the env-var gate inside should_auto_tournament
                # only when the explicit flag wasn't passed; the flag
                # itself is sufficient permission.
                ok = (getattr(args, "auto_tournament", False)
                      or auto_tournament.should_auto_tournament(run_db))
                if ok:
                    result = auto_tournament.run_auto_tournament(run_db)
                    print(json.dumps({
                        "auto_tournament": result,
                    }))
            except Exception as e:
                # Surface to stderr but don't fail the phase.
                print(f"auto-tournament hook error: {e}",
                      file=sys.stderr)


def _maybe_validate_schema(run_id: str, phase: str,
                            output_json: str) -> None:
    """v0.103 — validate record-phase output_json against the
    persona schema. On failure, emit a `gate`-kind schema-error span.
    Best-effort.
    """
    try:
        from lib import persona_schema, trace
        from lib.cache import run_db_path
        artifact = Path(output_json)
        if not artifact.exists():
            return
        res = persona_schema.validate(phase, artifact)
        if res.ok:
            return
        db = run_db_path(run_id)
        trace.init_trace(db, trace_id=run_id, run_id=run_id)
        try:
            with trace.start_span(
                db, run_id, "gate", f"schema-{phase}",
                attrs={"phase": phase, "error": res.error},
            ) as sp:
                sp.event("schema_error",
                         {"agent": phase, "error": res.error,
                          "artifact_path": str(artifact)})
        except Exception:
            pass
    except Exception:
        pass


def _maybe_auto_score(run_id: str, phase: str,
                       artifact_path: str) -> None:
    """v0.94 — auto-rubric score the persona artifact if a rubric exists.

    `artifact_path` is the rubric target (richer persona artifact
    or output_json fallback). Schema gate is no longer called here
    — caller (record-phase) invokes _maybe_validate_schema on the
    record-phase output_json separately.

    Personas without a rubric: noop. All errors swallowed.
    """
    try:
        from lib import agent_quality
        from lib.cache import run_db_path
        if phase not in agent_quality.RUBRICS:
            return
        artifact = Path(artifact_path)
        if not artifact.exists():
            return
        agent_quality.score_auto(
            db_path=run_db_path(run_id), run_id=run_id, span_id=None,
            agent_name=phase, artifact_path=artifact,
        )
    except Exception:
        pass


# v0.93a: per-phase span tracking. The CLI is one-shot per
# --start/--complete, so we model phases as "open span on start,
# close on complete/error" by storing span_id in the phases row's
# output_json prefix. Simpler: emit a one-off span per command call
# with kind='phase' so the trace shows when each transition fired.
def _emit_phase_span(run_id: str, phase: str, *,
                     start: bool, complete: bool, error: str | None,
                     output_json: str | None) -> None:
    """Mirror a phase-state transition into the v0.89 trace tables.

    Each command call emits ONE span:
      - --start: kind=phase, name=<phase>, status=running, attrs={op:start}
      - --complete: kind=phase, name=<phase>, status=ok, attrs={op:complete}
      - --error: kind=phase, name=<phase>, status=error, attrs={op:error}
    Trace ID = run_id (1:1 mapping).
    Failures inside this helper never abort the parent record-phase call.
    """
    try:
        from lib import trace
        from lib.cache import run_db_path
        db = run_db_path(run_id)
        # init_trace is idempotent — safe to call repeatedly.
        trace.init_trace(db, trace_id=run_id, run_id=run_id)
        op = "start" if start else ("complete" if complete else "error")
        from datetime import UTC
        from datetime import datetime as _dt
        # Use a manual span entry (not the context-manager API) since
        # the work has already happened.
        span_id = trace.make_span_id()
        now = _dt.now(UTC).isoformat()
        attrs = {"op": op, "phase": phase}
        if output_json:
            attrs["output_json_path"] = output_json
        status = (
            "ok" if complete else
            "error" if error else
            "running"
        )
        con = trace._connect(db)
        try:
            with con:
                con.execute(
                    "INSERT INTO spans (span_id, trace_id, parent_span_id, "
                    "kind, name, started_at, ended_at, duration_ms, "
                    "status, error_kind, error_msg, attrs_json) "
                    "VALUES (?, ?, NULL, 'phase', ?, ?, ?, 0, ?, ?, ?, ?)",
                    (span_id, run_id, phase, now, now, status,
                     "phase-error" if error else None,
                     error, _import_json().dumps(attrs)),
                )
        finally:
            con.close()
        if complete:
            trace.end_trace(db, trace_id=run_id, status="ok")
    except Exception:
        # Tracing is observability — never let it break the run.
        pass


def _import_json():
    import json
    return json


def cmd_record_break(args: argparse.Namespace) -> None:
    con = _connect(args.run_id)
    now = datetime.now(UTC).isoformat()
    with con:
        if args.prompt:
            con.execute(
                "INSERT INTO breaks (run_id, break_number, prompted_at) VALUES (?, ?, ?)",
                (args.run_id, args.break_number, now),
            )
        if args.resolve:
            con.execute(
                "UPDATE breaks SET resolved_at=?, user_input=? "
                "WHERE run_id=? AND break_number=? AND resolved_at IS NULL",
                (now, args.user_input or "", args.run_id, args.break_number),
            )
    con.close()


def cmd_record_claim(args: argparse.Namespace) -> None:
    con = _connect(args.run_id)
    # v0.200 — supporting_ids is paper canonical_ids ONLY. Reject hyp- or
    # claim-id-prefixed strings; they belong in --targets-hyp-id or
    # --references-claim-ids.
    supporting_list: list[str] = []
    if args.supporting_ids:
        supporting_list = [
            s.strip() for s in args.supporting_ids.split(",") if s.strip()
        ]
        for s in supporting_list:
            if s.startswith("hyp-") or s.startswith("hyp_"):
                raise SystemExit(
                    f"--supporting-ids must contain paper canonical_ids "
                    f"only; got hyp-prefixed {s!r}. Use --targets-hyp-id "
                    f"for hypothesis targets."
                )
    supporting = json.dumps(supporting_list) if supporting_list else None

    # v0.198 — validate side
    side = getattr(args, "side", None)
    if side is not None and side not in ("a", "b"):
        raise SystemExit(
            f"--side must be 'a' or 'b' (got {side!r})"
        )

    paired = getattr(args, "paired_claim_id", None)

    targets_hyp_id = getattr(args, "targets_hyp_id", None)

    refs_claim_ids: str | None = None
    refs_id_list: list[int] = []
    raw_refs = getattr(args, "references_claim_ids", None)
    if raw_refs:
        try:
            refs_id_list = [
                int(s.strip()) for s in raw_refs.split(",") if s.strip()
            ]
        except ValueError:
            raise SystemExit(
                f"--references-claim-ids must be a CSV of integers "
                f"(got {raw_refs!r})"
            )
        refs_claim_ids = json.dumps(refs_id_list)

    # v0.196 — claims gate: validate referenced IDs exist in run DB.
    # Default mode = warn + accept (back-compat); --strict-supporting-ids
    # rejects on any missing.
    strict = bool(getattr(args, "strict_supporting_ids", False))

    if supporting_list:
        cur = con.cursor()
        placeholders = ",".join(["?"] * len(supporting_list))
        found = {
            row[0] for row in cur.execute(
                "SELECT canonical_id FROM papers_in_run "
                "WHERE run_id=? AND canonical_id IN (" + placeholders + ")",
                (args.run_id, *supporting_list),
            )
        }
        missing = [c for c in supporting_list if c not in found]
        if missing:
            if strict:
                con.close()
                raise SystemExit(
                    f"--supporting-ids: {len(missing)} missing from "
                    f"papers_in_run: {missing}"
                )
            sys.stderr.write(
                f"warning: {len(missing)} supporting_ids not in "
                f"papers_in_run: {missing}\n"
            )

    if refs_id_list:
        cur = con.cursor()
        placeholders = ",".join(["?"] * len(refs_id_list))
        found_ids = {
            row[0] for row in cur.execute(
                "SELECT claim_id FROM claims "
                "WHERE run_id=? AND claim_id IN (" + placeholders + ")",
                (args.run_id, *refs_id_list),
            )
        }
        missing_refs = [c for c in refs_id_list if c not in found_ids]
        if missing_refs:
            if strict:
                con.close()
                raise SystemExit(
                    f"--references-claim-ids: {len(missing_refs)} missing "
                    f"from claims: {missing_refs}"
                )
            sys.stderr.write(
                f"warning: {len(missing_refs)} references_claim_ids not "
                f"in claims: {missing_refs}\n"
            )

    if targets_hyp_id:
        cur = con.cursor()
        hyp_row = cur.execute(
            "SELECT hyp_id FROM hypotheses WHERE run_id=? AND hyp_id=?",
            (args.run_id, targets_hyp_id),
        ).fetchone()
        if hyp_row is None:
            if strict:
                con.close()
                raise SystemExit(
                    f"--targets-hyp-id: {targets_hyp_id!r} missing from "
                    f"hypotheses"
                )
            sys.stderr.write(
                f"warning: targets_hyp_id {targets_hyp_id!r} not in "
                f"hypotheses\n"
            )

    with con:
        cur = con.execute(
            "INSERT INTO claims "
            "(run_id, canonical_id, agent_name, text, kind, confidence, "
            "supporting_ids, side, paired_claim_id, targets_hyp_id, "
            "references_claim_ids) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                args.run_id,
                args.canonical_id,
                args.agent_name,
                args.text,
                args.kind,
                args.confidence,
                supporting,
                side,
                paired,
                targets_hyp_id,
                refs_claim_ids,
            ),
        )
        new_id = cur.lastrowid
    con.close()
    sys.stdout.write(json.dumps({"claim_id": new_id}) + "\n")


def cmd_next_phase(args: argparse.Namespace) -> None:
    """Print the name of the next phase to run, or BREAK_<n>, or DONE."""
    con = _connect(args.run_id)
    rows = con.execute(
        "SELECT name, started_at, completed_at FROM phases WHERE run_id=? ORDER BY ordinal",
        (args.run_id,),
    ).fetchall()
    con.close()

    for row in rows:
        if row["completed_at"] is None:
            # If a break is configured after the *previous* phase and unresolved, return it
            prev_idx = PHASES_IN_ORDER.index(row["name"]) - 1
            if prev_idx >= 0:
                prev_name = PHASES_IN_ORDER[prev_idx]
                if prev_name in BREAK_AFTER:
                    bn = BREAK_AFTER[prev_name]
                    con = _connect(args.run_id)
                    unresolved = con.execute(
                        "SELECT 1 FROM breaks WHERE run_id=? AND break_number=? AND resolved_at IS NULL",
                        (args.run_id, bn),
                    ).fetchone()
                    con.close()
                    # If previous is completed but this break hasn't been resolved, signal it
                    prev_row = next(r for r in rows if r["name"] == prev_name)
                    if prev_row["completed_at"] is not None and unresolved:
                        print(f"BREAK_{bn}")
                        return
                    if prev_row["completed_at"] is not None and not unresolved:
                        # Check if break row even exists
                        con = _connect(args.run_id)
                        exists = con.execute(
                            "SELECT 1 FROM breaks WHERE run_id=? AND break_number=?",
                            (args.run_id, bn),
                        ).fetchone()
                        con.close()
                        if not exists:
                            print(f"BREAK_{bn}")
                            return
            print(row["name"])
            return
    print("DONE")


def cmd_next_phase_batch(args: argparse.Namespace) -> None:
    """v0.51 — return next batch of phases that can run concurrently.

    Behavior parallels cmd_next_phase, but instead of one phase, may
    return up to N phases that share a concurrency group (defined in
    lib.phase_groups.PHASE_GROUPS). Output JSON shape:

      {"action": "run", "phases": ["cartographer","chronicler","surveyor"]}
      {"action": "break", "break_number": 1}
      {"action": "done"}
      {"action": "error", "phase": "...", "error": "..."}

    Honors BREAK_AFTER — never returns a batch that crosses a break.
    Honors per-phase error state — stops at first errored phase.
    Uses ORDER BY ordinal (not started_at) so output is stable
    regardless of completion timing.
    """
    con = _connect(args.run_id)
    rows = con.execute(
        "SELECT name, started_at, completed_at, error "
        "FROM phases WHERE run_id=? ORDER BY ordinal",
        (args.run_id,),
    ).fetchall()
    con.close()

    # Find first incomplete phase
    first_incomplete_idx = None
    for i, row in enumerate(rows):
        if row["error"]:
            print(json.dumps({
                "action": "error",
                "phase": row["name"],
                "error": row["error"],
            }))
            return
        if row["completed_at"] is None:
            first_incomplete_idx = i
            break

    if first_incomplete_idx is None:
        print(json.dumps({"action": "done"}))
        return

    # Check for unresolved break before first_incomplete
    first = rows[first_incomplete_idx]
    prev_idx = PHASES_IN_ORDER.index(first["name"]) - 1
    if prev_idx >= 0:
        prev_name = PHASES_IN_ORDER[prev_idx]
        if prev_name in BREAK_AFTER:
            bn = BREAK_AFTER[prev_name]
            con = _connect(args.run_id)
            unresolved = con.execute(
                "SELECT 1 FROM breaks WHERE run_id=? AND "
                "break_number=? AND resolved_at IS NULL",
                (args.run_id, bn),
            ).fetchone()
            exists = con.execute(
                "SELECT 1 FROM breaks WHERE run_id=? AND break_number=?",
                (args.run_id, bn),
            ).fetchone()
            con.close()
            prev_row = next(r for r in rows if r["name"] == prev_name)
            if prev_row["completed_at"] is not None and (
                unresolved or not exists
            ):
                print(json.dumps({
                    "action": "break", "break_number": bn,
                }))
                return

    # Compute the largest concurrent batch from this point.
    # Restrict to incomplete phases only — skip any that are already
    # complete (could happen mid-batch on resume).
    remaining = [
        r["name"] for r in rows[first_incomplete_idx:]
        if r["completed_at"] is None
    ]
    # Don't let a batch cross a break — trim at any phase that has a
    # BREAK_AFTER, *including* the trigger itself in the same batch
    # (the break fires AFTER the phase completes).
    trimmed: list[str] = []
    for p in remaining:
        trimmed.append(p)
        if p in BREAK_AFTER:
            break
    batch = _phase_batchable(trimmed)

    print(json.dumps({"action": "run", "phases": batch}))


def cmd_resume(args: argparse.Namespace) -> None:
    """Print a summary of current state + next action + harvest status.

    v0.46.3: Sub-agents in some runtimes don't inherit MCP tools, so the
    six search-using personas (social, grounder, historian, gaper,
    theorist, thinker) read from orchestrator-harvested shortlist files.
    Resume reports which shortlists exist so the orchestrator knows
    whether harvest is required before invoking the next persona.
    """
    con = _connect(args.run_id)
    run = con.execute("SELECT * FROM runs WHERE run_id=?", (args.run_id,)).fetchone()
    if not run:
        con.close()
        raise SystemExit(f"no such run: {args.run_id}")
    phases = con.execute(
        "SELECT name, started_at, completed_at, error FROM phases WHERE run_id=? ORDER BY ordinal",
        (args.run_id,),
    ).fetchall()
    con.close()

    # Per-persona expected phase mapping (matches deep-research SKILL.md)
    # v0.46.4: SEEKER → Expedition rename. Old names (social, grounder, ...)
    # replaced with archetype names (scout, cartographer, ...).
    expected_harvests = [
        ("scout", "phase0"),
        ("cartographer", "phase1"),
        ("chronicler", "phase1"),
        ("surveyor", "phase1"),
        ("architect", "phase2"),
        ("visionary", "phase3"),
    ]
    from lib.persona_input import exists as _shortlist_exists
    harvest_status = []
    for persona, phase in expected_harvests:
        harvest_status.append({
            "persona": persona,
            "phase": phase,
            "shortlist_present": _shortlist_exists(
                args.run_id, persona, phase
            ),
        })

    print(json.dumps({
        "run_id": args.run_id,
        "question": run["question"],
        "status": run["status"],
        "phases": [dict(r) for r in phases],
        "harvests": harvest_status,
    }, indent=2))


def cmd_suggest_strategy(args: argparse.Namespace) -> None:
    """Heuristic framework suggestion for the run's question.

    Emits a draft SearchStrategy as JSON for the orchestrator to render
    + show user at Break 0. User confirms or adjusts, then orchestrator
    calls set-strategy to lock it in.
    """
    con = _connect(args.run_id)
    try:
        row = con.execute(
            "SELECT question FROM runs WHERE run_id=?", (args.run_id,)
        ).fetchone()
        if not row:
            raise SystemExit(f"unknown run_id {args.run_id!r}")
        question = row[0]
    finally:
        con.close()

    fw, rationale = suggest_framework(question)
    components = template_for(fw)

    draft = {
        "framework": fw,
        "rationale": rationale,
        "components": components,
        "note": (
            "This is a draft. Orchestrator should populate sub_areas + "
            "assigned_personas, then call set-strategy with the user-"
            "confirmed JSON."
        ),
    }
    sys.stdout.write(json.dumps(draft, indent=2) + "\n")


def cmd_get_strategy(args: argparse.Namespace) -> None:
    con = _connect(args.run_id)
    try:
        row = con.execute(
            "SELECT search_strategy_json FROM runs WHERE run_id=?",
            (args.run_id,),
        ).fetchone()
        if not row:
            raise SystemExit(f"unknown run_id {args.run_id!r}")
        if not row[0]:
            sys.stdout.write(
                json.dumps({"strategy": None,
                            "note": "No strategy set yet — call "
                                    "suggest-strategy + set-strategy."},
                           indent=2) + "\n"
            )
            return
        s = SearchStrategy.from_dict(json.loads(row[0]))
        sys.stdout.write(s.to_json() + "\n")
    finally:
        con.close()


def cmd_detect_eras(args: argparse.Namespace) -> None:
    """v0.52.3 — detect paradigm-shift inflections in run's corpus.

    Reads all harvest shortlists for the run, extracts year+abstract,
    runs Jensen-Shannon divergence over per-year n-gram distributions,
    returns top-K boundary candidates ranked by divergence.
    """
    inputs = run_inputs_dir(args.run_id)
    papers: list[dict] = []
    if inputs.exists():
        for shortlist_path in inputs.glob("*-phase*.json"):
            try:
                data = json.loads(shortlist_path.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            for entry in data.get("results", []):
                if entry.get("year") and entry.get("abstract"):
                    papers.append({
                        "year": entry["year"],
                        "abstract": entry["abstract"],
                    })
    inflections = detect_inflections(
        papers,
        min_papers_per_year=args.min_papers_per_year,
        top_k_inflections=args.top_k,
    )
    if args.format == "md":
        sys.stdout.write(_era_render(inflections) + "\n")
    else:
        sys.stdout.write(json.dumps(
            {"run_id": args.run_id,
             "n_papers_analyzed": len(papers),
             "inflections": [i.to_dict() for i in inflections]},
            indent=2,
        ) + "\n")


def cmd_compute_velocity(args: argparse.Namespace) -> None:
    """v0.52.6 — concept-velocity over abstract n-grams.

    Per-term linear regression over normalized year-frequency. Emerging
    = positive slope, deprecated = negative. Mechanically surfaces
    vocabulary trends invisible to manual review.
    """
    inputs = run_inputs_dir(args.run_id)
    papers: list[dict] = []
    if inputs.exists():
        for shortlist_path in inputs.glob("*-phase*.json"):
            try:
                data = json.loads(shortlist_path.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            for entry in data.get("results", []):
                if entry.get("year") and entry.get("abstract"):
                    papers.append({
                        "year": entry["year"],
                        "abstract": entry["abstract"],
                    })
    trends = compute_velocities(
        papers,
        min_papers_per_term=args.min_papers_per_term,
        min_years_per_term=args.min_years_per_term,
        top_k=args.top_k,
    )
    if args.format == "md":
        sys.stdout.write(_velocity_render(trends, top_k=args.top_k) + "\n")
    else:
        sys.stdout.write(json.dumps(
            {"run_id": args.run_id,
             "n_papers_analyzed": len(papers),
             "trends": [t.to_dict() for t in trends]},
            indent=2,
        ) + "\n")


def cmd_compute_disagreement(args: argparse.Namespace) -> None:
    """v0.52.4 — compute cross-persona disagreement scores for a run.

    Updates papers_in_run.disagreement_score in place. Surfaces top-K
    high-leverage papers (surfaced by some personas, missed by others).
    """
    inputs = run_inputs_dir(args.run_id)
    db = run_db_path(args.run_id)
    scores = compute_disagreement(args.run_id, db, inputs)
    n_updated = 0
    if args.persist:
        n_updated = _disagreement_persist(args.run_id, db, scores)
    if args.format == "md":
        sys.stdout.write(_disagreement_render(scores, top_k=args.top_k) + "\n")
    else:
        sys.stdout.write(json.dumps(
            {"run_id": args.run_id,
             "n_scored": len(scores),
             "n_persisted": n_updated,
             "top_k": [s.to_dict() for s in scores[:args.top_k]]},
            indent=2,
        ) + "\n")


def cmd_set_strategy(args: argparse.Namespace) -> None:
    """Lock in user-confirmed search strategy. Idempotent (overwrites)."""
    strategy_path = Path(args.strategy_json)
    if not strategy_path.exists():
        raise SystemExit(f"strategy file not found: {strategy_path}")
    payload = json.loads(strategy_path.read_text())
    # Validate by round-tripping through the dataclass
    s = SearchStrategy.from_dict(payload)
    con = _connect(args.run_id)
    try:
        with con:
            con.execute(
                "UPDATE runs SET search_strategy_json=? WHERE run_id=?",
                (s.to_json(), args.run_id),
            )
    finally:
        con.close()
    sys.stdout.write(json.dumps({
        "ok": True, "run_id": args.run_id,
        "framework": s.framework, "n_sub_areas": len(s.sub_areas),
    }, indent=2) + "\n")


def cmd_record_subagent(args: argparse.Namespace) -> None:
    """v0.119 — emit a sub-agent span around a Task dispatch.

    Two modes:
      --start: opens a span, writes span_id to sidecar file.
      --end:   reads span_id from sidecar, closes the span.

    Sidecar: ~/.cache/coscientist/runs/run-<rid>-subagent-state.json
    Keyed by `persona` so multiple personas can be in flight.
    """
    import json as _j
    from datetime import UTC
    from datetime import datetime as _dt

    from lib import trace
    from lib.cache import run_db_path
    db = run_db_path(args.run_id)
    sidecar = (run_db_path(args.run_id).parent /
                f"run-{args.run_id}-subagent-state.json")

    state: dict[str, Any] = {}
    if sidecar.exists():
        try:
            state = _j.loads(sidecar.read_text())
        except _j.JSONDecodeError:
            state = {}

    if args.start:
        try:
            trace.init_trace(db, trace_id=args.run_id,
                              run_id=args.run_id)
            span_id = trace.make_span_id()
            now = _dt.now(UTC).isoformat()
            con = trace._connect(db)
            try:
                with con:
                    con.execute(
                        "INSERT INTO spans (span_id, trace_id, "
                        "parent_span_id, kind, name, started_at, "
                        "status, attrs_json) "
                        "VALUES (?, ?, NULL, 'sub-agent', ?, ?, "
                        "'running', ?)",
                        (span_id, args.run_id, args.persona, now,
                         _j.dumps({"persona": args.persona})),
                    )
            finally:
                con.close()
            state[args.persona] = {
                "span_id": span_id, "started_at": now,
            }
            sidecar.write_text(_j.dumps(state))
            print(_j.dumps({
                "ok": True, "span_id": span_id,
                "persona": args.persona,
            }))
        except Exception as e:
            print(_j.dumps({"ok": False, "error": str(e)}))
            sys.exit(1)
        return

    if args.end:
        rec = state.get(args.persona)
        if not rec:
            print(_j.dumps({
                "ok": False,
                "error": f"no open sub-agent span for persona "
                          f"{args.persona!r}",
            }))
            sys.exit(1)
        span_id = rec["span_id"]
        started_at = rec["started_at"]
        ended = _dt.now(UTC).isoformat()
        try:
            started_dt = _dt.fromisoformat(
                started_at.replace("Z", "+00:00"),
            )
            ended_dt = _dt.fromisoformat(
                ended.replace("Z", "+00:00"),
            )
            duration_ms = int(
                (ended_dt - started_dt).total_seconds() * 1000,
            )
        except (ValueError, AttributeError):
            duration_ms = 0
        status = "error" if args.error else "ok"
        try:
            con = trace._connect(db)
            try:
                with con:
                    con.execute(
                        "UPDATE spans SET ended_at=?, "
                        "duration_ms=?, status=?, error_kind=?, "
                        "error_msg=? WHERE span_id=?",
                        (ended, duration_ms, status,
                         "sub-agent-error" if args.error else None,
                         args.error[:2000] if args.error else None,
                         span_id),
                    )
            finally:
                con.close()
            state.pop(args.persona, None)
            if state:
                sidecar.write_text(_j.dumps(state))
            else:
                sidecar.unlink(missing_ok=True)
            print(_j.dumps({
                "ok": True, "span_id": span_id,
                "duration_ms": duration_ms, "status": status,
            }))
        except Exception as e:
            print(_j.dumps({"ok": False, "error": str(e)}))
            sys.exit(1)
        return


def cmd_list_papers(args: argparse.Namespace) -> None:
    """v0.195 — list rows from papers_in_run for a run.

    Replaces raw `sqlite3 ... SELECT canonical_id, ... FROM papers_in_run`
    that cartographer was running directly. Sort: phase ordinal then
    canonical_id (stable). Output JSON or plain text.
    """
    if not run_db_path(args.run_id).exists():
        raise SystemExit(f"unknown run_id {args.run_id!r}")
    con = _connect(args.run_id)
    try:
        # Phase ordinal lookup so sort is by Expedition order, not alpha.
        ordinals = {n: i for i, n in enumerate(PHASES_IN_ORDER)}
        # Special phase aliases used outside the 10-phase list (e.g.
        # 'seed-from-wide' for cross-run handoff). Sort them after canon.
        sql = (
            "SELECT canonical_id, role, added_in_phase, harvest_count, "
            "cites_per_year, disagreement_score "
            "FROM papers_in_run WHERE run_id=?"
        )
        params: list[Any] = [args.run_id]
        if args.phase:
            sql += " AND added_in_phase=?"
            params.append(args.phase)
        rows = con.execute(sql, params).fetchall()
    finally:
        con.close()

    items = []
    for r in rows:
        items.append({
            "canonical_id": r["canonical_id"],
            "role": r["role"],
            "added_in_phase": r["added_in_phase"],
            "harvest_count": r["harvest_count"],
            "cites_per_year": r["cites_per_year"],
            "disagreement_score": r["disagreement_score"],
        })
    items.sort(key=lambda x: (
        ordinals.get(x["added_in_phase"], len(PHASES_IN_ORDER) + 1),
        x["canonical_id"],
    ))

    if args.format == "json":
        sys.stdout.write(json.dumps(items, indent=2) + "\n")
    else:
        if not items:
            sys.stdout.write("(no papers)\n")
            return
        for it in items:
            sys.stdout.write(
                f"{it['added_in_phase']}\t{it['role'] or ''}\t"
                f"hc={it['harvest_count']}\t{it['canonical_id']}\n"
            )


def cmd_list_claims(args: argparse.Namespace) -> None:
    """v0.195 — list rows from claims for a run.

    Same shape as list-papers — replaces raw sqlite that weaver/eval was
    using to inspect claim records.
    """
    if not run_db_path(args.run_id).exists():
        raise SystemExit(f"unknown run_id {args.run_id!r}")
    con = _connect(args.run_id)
    try:
        sql = (
            "SELECT claim_id, canonical_id, agent_name, text, kind, "
            "confidence, supporting_ids "
            "FROM claims WHERE run_id=?"
        )
        params: list[Any] = [args.run_id]
        if args.agent:
            sql += " AND agent_name=?"
            params.append(args.agent)
        if args.kind:
            sql += " AND kind=?"
            params.append(args.kind)
        sql += " ORDER BY claim_id"
        rows = con.execute(sql, params).fetchall()
    finally:
        con.close()

    items = []
    for r in rows:
        supporting: list[str] = []
        if r["supporting_ids"]:
            try:
                supporting = json.loads(r["supporting_ids"]) or []
            except json.JSONDecodeError:
                supporting = []
        items.append({
            "claim_id": r["claim_id"],
            "canonical_id": r["canonical_id"],
            "agent_name": r["agent_name"],
            "text": r["text"],
            "kind": r["kind"],
            "confidence": r["confidence"],
            "supporting_ids": supporting,
        })

    if args.format == "json":
        sys.stdout.write(json.dumps(items, indent=2) + "\n")
    else:
        if not items:
            sys.stdout.write("(no claims)\n")
            return
        for it in items:
            sys.stdout.write(
                f"#{it['claim_id']}\t{it['agent_name']}\t"
                f"{it['kind'] or ''}\t{it['text'][:80]}\n"
            )


def cmd_record_note(args: argparse.Namespace) -> None:
    """v0.197 — insert a row into the notes table.

    Replaces raw SQL inserts that weaver was running. Supports stdin
    via --text -.
    """
    if not run_db_path(args.run_id).exists():
        raise SystemExit(f"unknown run_id {args.run_id!r}")
    text = args.text
    if text == "-":
        text = sys.stdin.read()
    if not text or not text.strip():
        raise SystemExit("--text: empty (multi-line via '-' reads stdin)")
    con = _connect(args.run_id)
    try:
        with con:
            con.execute(
                "INSERT INTO notes (run_id, phase_id, author, text, at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    args.run_id,
                    args.phase_id,
                    args.author,
                    text,
                    datetime.now(UTC).isoformat(),
                ),
            )
    finally:
        con.close()


def cmd_score_quality(args: argparse.Namespace) -> None:
    """v0.93d — score a persona's output via the v0.92 auto-rubric.

    Persists to agent_quality. Run-id ties the row to the run +
    span trace. Best-effort — surfaces ok=False if no rubric exists.
    """
    from lib import agent_quality
    from lib.cache import run_db_path
    db = run_db_path(args.run_id)
    res = agent_quality.score_auto(
        db_path=db, run_id=args.run_id, span_id=None,
        agent_name=args.agent, artifact_path=Path(args.artifact_path),
    )
    print(json.dumps(res, indent=2))
    if not res.get("ok"):
        sys.exit(1)


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("init"); pi.add_argument("--question", required=True); pi.add_argument("--config", default=None); pi.add_argument("--overnight", action="store_true", default=False)
    pi.add_argument("--seed-from-wide", default=None,
                     help="Wide run_id whose synthesis.json seeds this Deep run")
    pi.add_argument("--seed-mode", default=None,
                     choices=["abstract", "full-text", "cumulative"],
                     help="Wide → Deep handoff level (default: abstract)")
    pi.add_argument("--seed-top-k", type=int, default=30,
                     help="Max seed papers from Wide (default 30)")
    pi.set_defaults(func=cmd_init)

    pp = sub.add_parser("record-phase")
    pp.add_argument("--run-id", required=True); pp.add_argument("--phase", required=True)
    pp.add_argument("--start", action="store_true"); pp.add_argument("--complete", action="store_true")
    pp.add_argument("--output-json", default=None); pp.add_argument("--error", default=None)
    pp.add_argument(
        "--quality-artifact", default=None,
        help="v0.103: separate richer artifact for auto-rubric "
             "scoring (e.g. /tmp/scout-shortlist.json). Falls "
             "back to --output-json if omitted.",
    )
    pp.add_argument(
        "--auto-tournament", action="store_true",
        help="v0.203: when phase=='inquisitor' and --complete, "
             "auto-dispatch a heuristic-judge pairwise tournament "
             "across every hypothesis tree in the run, then prune "
             "low-Elo subtrees once. Off by default — back-compat. "
             "Also activated by COSCIENTIST_AUTO_TOURNAMENT=1.",
    )
    pp.set_defaults(func=cmd_record_phase)

    pb = sub.add_parser("record-break")
    pb.add_argument("--run-id", required=True); pb.add_argument("--break-number", type=int, required=True)
    pb.add_argument("--prompt", action="store_true"); pb.add_argument("--resolve", action="store_true")
    pb.add_argument("--user-input", default=None)
    pb.set_defaults(func=cmd_record_break)

    pc = sub.add_parser("record-claim")
    pc.add_argument("--run-id", required=True); pc.add_argument("--agent-name", required=True)
    pc.add_argument("--text", required=True); pc.add_argument("--kind", default="finding")
    pc.add_argument("--canonical-id", default=None); pc.add_argument("--confidence", type=float, default=None)
    pc.add_argument("--supporting-ids", default="",
                    help="CSV of paper canonical_ids ONLY (v0.200)")
    # v0.198 — paired tension dual-side support
    pc.add_argument("--side", default=None, choices=("a", "b"),
                    help="Side label for paired tension claims (v0.198)")
    pc.add_argument("--paired-claim-id", type=int, default=None,
                    help="claim_id of the paired Side B/A counterpart (v0.198)")
    # v0.200 — decoupled non-paper ID fields
    pc.add_argument("--targets-hyp-id", default=None,
                    help="Single hyp_id this claim targets (inquisitor; v0.200)")
    pc.add_argument("--references-claim-ids", default=None,
                    help="CSV of claim_id integers (visionary cross-refs; v0.200)")
    # v0.196 — claims gate: enforce referenced IDs exist in run DB
    pc.add_argument("--strict-supporting-ids", action="store_true",
                    help="Reject claim if any --supporting-ids, "
                         "--references-claim-ids, or --targets-hyp-id is "
                         "missing from the run DB (v0.196). Default = warn.")
    pc.set_defaults(func=cmd_record_claim)

    pn = sub.add_parser("next-phase"); pn.add_argument("--run-id", required=True)
    pn.set_defaults(func=cmd_next_phase)

    pnb = sub.add_parser("next-phase-batch",
                          help="v0.51 — return next concurrent phase batch as JSON")
    pnb.add_argument("--run-id", required=True)
    pnb.set_defaults(func=cmd_next_phase_batch)

    pr = sub.add_parser("resume"); pr.add_argument("--run-id", required=True)
    pr.set_defaults(func=cmd_resume)

    # v0.52.1 — search-strategy commands
    ps = sub.add_parser("suggest-strategy",
                         help="Suggest framework + sub-area decomposition for the run's question")
    ps.add_argument("--run-id", required=True)
    ps.set_defaults(func=cmd_suggest_strategy)

    psg = sub.add_parser("get-strategy",
                          help="Show the locked-in search strategy for the run")
    psg.add_argument("--run-id", required=True)
    psg.set_defaults(func=cmd_get_strategy)

    pss = sub.add_parser("set-strategy",
                          help="Lock in the user-confirmed search strategy (JSON)")
    pss.add_argument("--run-id", required=True)
    pss.add_argument("--strategy-json", required=True,
                      help="Path to JSON file matching SearchStrategy.to_dict()")
    pss.set_defaults(func=cmd_set_strategy)

    # v0.52.3 — empirical era detection
    pde = sub.add_parser("detect-eras",
                          help="Detect paradigm-shift inflection points "
                               "in run's harvested corpus (JS divergence)")
    pde.add_argument("--run-id", required=True)
    pde.add_argument("--min-papers-per-year", type=int, default=3)
    pde.add_argument("--top-k", type=int, default=5)
    pde.add_argument("--format", choices=["json", "md"], default="json")
    pde.set_defaults(func=cmd_detect_eras)

    # v0.52.4 — cross-persona disagreement scoring
    pcd = sub.add_parser("compute-disagreement",
                          help="Compute cross-persona disagreement scores "
                               "for papers in this run; optionally persist")
    pcd.add_argument("--run-id", required=True)
    pcd.add_argument("--persist", action="store_true",
                      help="Update papers_in_run.disagreement_score")
    pcd.add_argument("--top-k", type=int, default=10)
    pcd.add_argument("--format", choices=["json", "md"], default="json")
    pcd.set_defaults(func=cmd_compute_disagreement)

    # v0.52.6 — concept velocity over abstract n-grams
    pcv = sub.add_parser("compute-velocity",
                          help="Compute per-term emerging/deprecated trends "
                               "via OLS over per-year frequency")
    pcv.add_argument("--run-id", required=True)
    pcv.add_argument("--min-papers-per-term", type=int, default=3)
    pcv.add_argument("--min-years-per-term", type=int, default=2)
    pcv.add_argument("--top-k", type=int, default=15)
    pcv.add_argument("--format", choices=["json", "md"], default="json")
    pcv.set_defaults(func=cmd_compute_velocity)

    # v0.195 — list-papers / list-claims (replace raw SQL).
    plp = sub.add_parser(
        "list-papers",
        help="List papers_in_run rows for a run",
    )
    plp.add_argument("--run-id", required=True)
    plp.add_argument("--phase", default=None,
                      help="Filter by added_in_phase (canonical name)")
    plp.add_argument("--format", choices=["json", "text"], default="json")
    plp.set_defaults(func=cmd_list_papers)

    plc = sub.add_parser(
        "list-claims",
        help="List claims rows for a run",
    )
    plc.add_argument("--run-id", required=True)
    plc.add_argument("--agent", default=None,
                      help="Filter by agent_name")
    plc.add_argument("--kind", default=None,
                      help="Filter by kind (finding|hypothesis|gap|tension|dead_end)")
    plc.add_argument("--format", choices=["json", "text"], default="json")
    plc.set_defaults(func=cmd_list_claims)

    # v0.197 — record-note replaces raw SQL note insertion.
    prn = sub.add_parser(
        "record-note",
        help="Insert a row into the notes table",
    )
    prn.add_argument("--run-id", required=True)
    prn.add_argument("--author", required=True,
                      help="agent name or 'user'")
    prn.add_argument("--text", required=True,
                      help="Note text. Use '-' to read from stdin.")
    prn.add_argument("--phase-id", type=int, default=None,
                      help="Optional phase_id (matches phases.phase_id)")
    prn.set_defaults(func=cmd_record_note)

    # v0.93d — auto-quality scoring after a persona finishes.
    psq = sub.add_parser("score-quality",
                          help="Score a persona's output via auto-rubric "
                               "(v0.92). Persists to agent_quality.")
    psq.add_argument("--run-id", required=True)
    psq.add_argument("--agent", required=True,
                     help="Persona name (scout, surveyor, architect, ...)")
    psq.add_argument("--artifact-path", required=True,
                     help="Path to the persona's output JSON or text file")
    psq.set_defaults(func=cmd_score_quality)

    # v0.119 — sub-agent span emission around Task dispatches.
    psa = sub.add_parser(
        "record-subagent",
        help="Emit a sub-agent span around a Task dispatch. "
             "Use --start before, --end after.",
    )
    psa.add_argument("--run-id", required=True)
    psa.add_argument("--persona", required=True,
                      help="Sub-agent name (scout, ranker, etc.)")
    psa.add_argument("--start", action="store_true",
                      help="Open a new sub-agent span.")
    psa.add_argument("--end", action="store_true",
                      help="Close the open sub-agent span.")
    psa.add_argument("--error", default=None,
                      help="With --end: mark span status=error.")
    psa.set_defaults(func=cmd_record_subagent)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

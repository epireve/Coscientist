"""v0.93b — emit a v0.89 trace span for a gate decision.

Helper used by `publishability-check`, `novelty-check`, and
`attack-vectors` gates to record gate verdicts in the run's
trace. Best-effort: any failure is swallowed.
"""
from __future__ import annotations

import json as _json
from pathlib import Path


def emit_gate_span(
    *,
    run_id: str | None,
    gate_name: str,
    verdict: str,                # "ok" | "rejected"
    errors: list[str] | None = None,
    warnings: list[str] | None = None,
    target_id: str | None = None,
    extra: dict | None = None,
) -> None:
    """Mirror a gate decision into the v0.89 trace tables.

    No-op if `run_id` is None or trace infra unreachable.
    """
    if not run_id:
        return
    try:
        from lib import trace
        from lib.cache import run_db_path
        db = run_db_path(run_id)
        trace.init_trace(db, trace_id=run_id, run_id=run_id)
        attrs = {
            "verdict": verdict,
            "target_id": target_id,
        }
        if extra:
            attrs.update(extra)
        if verdict == "ok":
            with trace.start_span(
                db, run_id, "gate", gate_name, attrs=attrs,
            ) as sp:
                if warnings:
                    sp.event("gate_warnings", {"warnings": warnings})
        else:
            try:
                with trace.start_span(
                    db, run_id, "gate", gate_name, attrs=attrs,
                ) as sp:
                    sp.event("gate_rejected", {
                        "errors": errors or [],
                        "warnings": warnings or [],
                    })
                    raise RuntimeError(
                        f"{gate_name} rejected: "
                        + ("; ".join(errors or [])[:200])
                    )
            except RuntimeError:
                pass
    except Exception:
        pass

"""v0.89 — execution traces over coscientist DBs.

OpenTelemetry-style span model in pure stdlib. Three tables
(`traces`, `spans`, `span_events`) created by migration v11.

Usage:

    from lib.trace import start_span, init_trace, end_trace

    init_trace(db_path, trace_id="trace-abc", run_id="run-xyz")

    with start_span(db_path, "trace-abc", "phase", "scout") as sp:
        sp.event("harvest_loaded", {"path": "/tmp/x.json", "n": 30})
        sp.set_attrs({"n_papers": 30})
        # nested child:
        with start_span(db_path, "trace-abc", "tool-call",
                         "lookup_doi", parent_span_id=sp.span_id) as sp2:
            ...

    end_trace(db_path, "trace-abc", status="ok")

Spans auto-record `started_at`, `ended_at`, `duration_ms`, status.
On exception, status='error' + error_kind + error_msg are persisted.

Pure stdlib. Idempotent. Reads/writes via `connect_wal`.
"""
from __future__ import annotations

import contextlib
import json
import sqlite3
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _connect(db_path: Path) -> sqlite3.Connection:
    from lib.cache import connect_wal
    from lib.migrations import ensure_current
    ensure_current(db_path)
    return connect_wal(db_path)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def make_trace_id() -> str:
    return f"trace-{uuid.uuid4().hex[:12]}"


def make_span_id() -> str:
    return f"span-{uuid.uuid4().hex[:12]}"


def init_trace(
    db_path: Path,
    *,
    trace_id: str,
    run_id: str | None = None,
) -> str:
    """Idempotent: re-using an existing trace_id is a no-op."""
    con = _connect(db_path)
    try:
        with con:
            con.execute(
                "INSERT OR IGNORE INTO traces "
                "(trace_id, run_id, started_at, status) "
                "VALUES (?, ?, ?, 'running')",
                (trace_id, run_id, _now_iso()),
            )
    finally:
        con.close()
    return trace_id


def end_trace(
    db_path: Path,
    trace_id: str,
    *,
    status: str = "ok",
) -> None:
    if status not in ("ok", "error"):
        raise ValueError(f"end_trace status must be ok|error; got {status!r}")
    con = _connect(db_path)
    try:
        with con:
            con.execute(
                "UPDATE traces SET completed_at=?, status=? "
                "WHERE trace_id=?",
                (_now_iso(), status, trace_id),
            )
    finally:
        con.close()


class _SpanHandle:
    """In-memory handle to an open span. End on context exit."""

    __slots__ = ("db_path", "trace_id", "span_id", "_attrs",
                 "_started_monotonic")

    def __init__(self, db_path: Path, trace_id: str, span_id: str):
        self.db_path = db_path
        self.trace_id = trace_id
        self.span_id = span_id
        self._attrs: dict[str, Any] = {}
        self._started_monotonic = time.monotonic()

    def event(self, name: str, payload: dict | None = None) -> None:
        """Append a span_event row."""
        con = _connect(self.db_path)
        try:
            with con:
                con.execute(
                    "INSERT INTO span_events "
                    "(span_id, name, payload_json, at) "
                    "VALUES (?, ?, ?, ?)",
                    (self.span_id, name,
                     json.dumps(payload) if payload else None,
                     _now_iso()),
                )
        finally:
            con.close()

    def set_attrs(self, attrs: dict) -> None:
        """Merge attrs into the span's attrs_json (last write wins)."""
        self._attrs.update(attrs)

    def _close(self, status: str, error_kind: str | None,
               error_msg: str | None) -> None:
        ended = _now_iso()
        duration_ms = int((time.monotonic() - self._started_monotonic) * 1000)
        con = _connect(self.db_path)
        try:
            with con:
                con.execute(
                    "UPDATE spans SET ended_at=?, duration_ms=?, "
                    "status=?, error_kind=?, error_msg=?, attrs_json=? "
                    "WHERE span_id=?",
                    (ended, duration_ms, status, error_kind, error_msg,
                     json.dumps(self._attrs) if self._attrs else None,
                     self.span_id),
                )
        finally:
            con.close()


@contextlib.contextmanager
def start_span(
    db_path: Path,
    trace_id: str,
    kind: str,
    name: str,
    *,
    parent_span_id: str | None = None,
    attrs: dict | None = None,
    capture_on_error: bool = False,
    snapshot_tables: list[str] | None = None,
):
    """Context manager: opens a span, yields the handle, closes on exit.

    On exception, status=error + error_kind/error_msg captured;
    exception re-raised after persistence.

    v0.90: pass `capture_on_error=True` to also append a structured
    `error_context` event with traceback. Pass `snapshot_tables` to
    include row counts at failure time.
    """
    valid_kinds = {"phase", "sub-agent", "tool-call", "gate",
                   "persist", "harvest", "other"}
    if kind not in valid_kinds:
        raise ValueError(f"kind must be one of {valid_kinds}; got {kind!r}")
    span_id = make_span_id()
    started = _now_iso()
    con = _connect(db_path)
    try:
        with con:
            con.execute(
                "INSERT INTO spans "
                "(span_id, trace_id, parent_span_id, kind, name, "
                "started_at, status, attrs_json) "
                "VALUES (?, ?, ?, ?, ?, ?, 'running', ?)",
                (span_id, trace_id, parent_span_id, kind, name,
                 started,
                 json.dumps(attrs) if attrs else None),
            )
    finally:
        con.close()
    handle = _SpanHandle(db_path, trace_id, span_id)
    if attrs:
        handle._attrs.update(attrs)
    try:
        yield handle
    except BaseException as e:  # noqa: BLE001 — re-raised below
        if capture_on_error:
            try:
                capture_error_context(
                    db_path, handle, e,
                    snapshot_tables=snapshot_tables,
                )
            except Exception:  # capture must not mask original
                pass
        handle._close(
            status="error",
            error_kind=type(e).__name__,
            error_msg=str(e)[:2000],
        )
        raise
    else:
        handle._close(status="ok", error_kind=None, error_msg=None)


def capture_error_context(
    db_path: Path,
    span: "_SpanHandle",
    exc: BaseException,
    *,
    stdout_tail: str | None = None,
    stderr_tail: str | None = None,
    snapshot_tables: list[str] | None = None,
    max_bytes: int = 4096,
) -> None:
    """v0.90 — append a structured `error_context` event with traceback,
    optional output tails, and DB row-count snapshot.

    Call from inside an exception handler before re-raising. Bounded
    payload (default 4KB per channel).
    """
    import traceback as _tb
    payload: dict[str, Any] = {
        "exception": {
            "type": type(exc).__name__,
            "msg": str(exc)[:max_bytes],
            "traceback": "".join(
                _tb.format_exception(type(exc), exc, exc.__traceback__)
            )[-max_bytes:],
        }
    }
    if stdout_tail is not None:
        payload["stdout_tail"] = stdout_tail[-max_bytes:]
    if stderr_tail is not None:
        payload["stderr_tail"] = stderr_tail[-max_bytes:]
    if snapshot_tables:
        payload["row_counts"] = _row_counts(db_path, snapshot_tables)
    span.event("error_context", payload)


def env_trace_context() -> tuple[Path | None, str | None]:
    """v0.93c — read trace context from env vars set by the orchestrator.

    Honored env:
      COSCIENTIST_TRACE_DB   — absolute path to the trace DB
      COSCIENTIST_TRACE_ID   — trace_id

    Returns (db_path, trace_id), each may be None.
    Used by MCP servers to opt into tool-call span emission without
    requiring callers to pass the trace IDs explicitly.
    """
    import os
    db_str = os.environ.get("COSCIENTIST_TRACE_DB")
    tid = os.environ.get("COSCIENTIST_TRACE_ID")
    db = Path(db_str) if db_str else None
    return db, tid


def maybe_emit_tool_call(
    tool_name: str,
    *,
    args_summary: dict | None = None,
    result_summary: dict | None = None,
    error: str | None = None,
) -> None:
    """v0.93c — best-effort tool-call span emission.

    Called from MCP server tool functions. If both env vars are set,
    emits a one-off `tool-call` span recording args + result summary.
    Silent no-op otherwise. Designed to be 100% safe to call.
    """
    try:
        db, tid = env_trace_context()
        if not db or not tid:
            return
        with start_span(
            db, tid, "tool-call", tool_name,
            attrs={"args": args_summary or {}},
        ) as sp:
            if result_summary:
                sp.event("result", result_summary)
            if error:
                sp.event("error", {"msg": error})
                # Force the span into error status by raising-and-catching
                # is too clever; instead patch attrs.
    except Exception:
        pass


def _row_counts(db_path: Path, tables: list[str]) -> dict[str, int]:
    """Best-effort row count per table; missing tables yield -1."""
    out: dict[str, int] = {}
    con = _connect(db_path)
    try:
        for t in tables:
            try:
                n = con.execute(
                    f'SELECT COUNT(*) FROM "{t}"'
                ).fetchone()[0]
                out[t] = int(n)
            except sqlite3.OperationalError:
                out[t] = -1
    finally:
        con.close()
    return out


def get_trace(db_path: Path, trace_id: str) -> dict | None:
    """Read full trace + spans + events for `trace_id`."""
    con = _connect(db_path)
    try:
        con.row_factory = sqlite3.Row
        trace_row = con.execute(
            "SELECT * FROM traces WHERE trace_id=?", (trace_id,),
        ).fetchone()
        if trace_row is None:
            return None
        spans = [
            dict(r) for r in con.execute(
                "SELECT * FROM spans WHERE trace_id=? "
                "ORDER BY started_at, span_id",
                (trace_id,),
            )
        ]
        events_by_span: dict[str, list[dict]] = {}
        for r in con.execute(
            "SELECT e.* FROM span_events e "
            "JOIN spans s ON s.span_id=e.span_id "
            "WHERE s.trace_id=? ORDER BY e.at, e.event_id",
            (trace_id,),
        ):
            events_by_span.setdefault(r[1], []).append(dict(r))
        for s in spans:
            s["events"] = events_by_span.get(s["span_id"], [])
        return {"trace": dict(trace_row), "spans": spans}
    finally:
        con.close()

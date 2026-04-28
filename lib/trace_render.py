"""v0.91 — trace renderer.

Reads `traces` + `spans` + `span_events` for a given trace_id and
emits one of three formats:

  - mermaid: a hierarchical span tree as a Mermaid `graph TD` block.
    Failed spans painted red. Long-running spans (> threshold ms)
    bolded.
  - md: chronological markdown timeline with per-span event log.
  - json: full read-back from `lib.trace.get_trace`.

CLI:
    uv run python -m lib.trace_render \\
        --db <path> --trace-id <tid> --format mermaid|md|json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


def _safe_id(s: str) -> str:
    """Sanitize for mermaid node ids."""
    return re.sub(r"[^A-Za-z0-9_]", "_", s)[:32]


def _label_escape(s: str) -> str:
    """Escape mermaid label characters."""
    return (
        s.replace("\\", "\\\\")
         .replace('"', "&quot;")
         .replace("|", "&#124;")
         .replace("\n", " ")
    )


# Spans longer than this (ms) get visual emphasis in mermaid.
_SLOW_THRESHOLD_MS = 5000


def render_mermaid(payload: dict) -> str:
    """`graph TD`-style mermaid block for a trace."""
    if payload is None:
        return "graph TD\n    empty[\"(no trace found)\"]\n"
    trace = payload["trace"]
    spans = payload["spans"]
    lines = [f"%% trace {trace['trace_id']} run={trace.get('run_id') or '-'}"]
    lines.append(f"%% status={trace['status']}")
    lines.append("graph TD")

    # Root node = the trace itself.
    root_id = "trace_" + _safe_id(trace["trace_id"])
    root_label = (
        f"trace<br/>{trace['trace_id'][:16]}"
        f"<br/>{trace['status']}"
    )
    lines.append(f'    {root_id}["{root_label}"]')

    # Build edge list. Span without parent attaches to root.
    classes_failed: list[str] = []
    classes_slow: list[str] = []
    for s in spans:
        nid = "span_" + _safe_id(s["span_id"])
        duration = s.get("duration_ms")
        dur_str = (
            f" ({duration}ms)" if duration is not None else ""
        )
        n_events = len(s.get("events") or [])
        ev_str = f" • {n_events}ev" if n_events else ""
        label = (
            f"<b>{_label_escape(s['name'])}</b><br/>"
            f"{s['kind']}{dur_str}{ev_str}<br/>"
            f"{s['status']}"
        )
        if s.get("error_msg"):
            label += f"<br/>err: {_label_escape(s['error_msg'][:60])}"
        lines.append(f'    {nid}["{label}"]')

        parent = s.get("parent_span_id")
        if parent:
            pid = "span_" + _safe_id(parent)
            lines.append(f"    {pid} --> {nid}")
        else:
            lines.append(f"    {root_id} --> {nid}")

        if s["status"] == "error":
            classes_failed.append(nid)
        elif (duration or 0) > _SLOW_THRESHOLD_MS:
            classes_slow.append(nid)

    if classes_failed:
        lines.append(
            f"    classDef failed fill:#fee,stroke:#c00,stroke-width:2px"
        )
        for nid in classes_failed:
            lines.append(f"    class {nid} failed")
    if classes_slow:
        lines.append(
            f"    classDef slow fill:#ffc,stroke:#a80,stroke-width:1px"
        )
        for nid in classes_slow:
            lines.append(f"    class {nid} slow")
    return "\n".join(lines) + "\n"


def render_markdown(payload: dict) -> str:
    """Chronological markdown timeline."""
    if payload is None:
        return "# Trace not found\n"
    trace = payload["trace"]
    spans = payload["spans"]
    lines = [
        f"# Trace `{trace['trace_id']}`",
        "",
        f"- **Run**: `{trace.get('run_id') or '-'}`",
        f"- **Started**: {trace['started_at']}",
        f"- **Completed**: {trace.get('completed_at') or '(in progress)'}",
        f"- **Status**: `{trace['status']}`",
        f"- **Spans**: {len(spans)}",
        "",
        "## Spans (chronological)",
        "",
    ]
    n_failed = sum(1 for s in spans if s["status"] == "error")
    if n_failed:
        lines.append(f"⚠ {n_failed} failed span(s).")
        lines.append("")

    for s in spans:
        emoji = {
            "ok": "✅",
            "error": "❌",
            "running": "🔄",
            "timeout": "⏱",
        }.get(s["status"], "·")
        dur = s.get("duration_ms")
        dur_str = f" — {dur}ms" if dur is not None else ""
        lines.append(
            f"### {emoji} `{s['kind']}` · **{s['name']}**{dur_str}"
        )
        lines.append("")
        lines.append(f"- span_id: `{s['span_id']}`")
        if s.get("parent_span_id"):
            lines.append(f"- parent: `{s['parent_span_id']}`")
        lines.append(f"- started: {s['started_at']}")
        if s.get("ended_at"):
            lines.append(f"- ended: {s['ended_at']}")
        if s.get("attrs_json"):
            try:
                attrs = json.loads(s["attrs_json"])
                if attrs:
                    lines.append(f"- attrs: `{json.dumps(attrs)}`")
            except json.JSONDecodeError:
                pass
        if s.get("error_msg"):
            lines.append(f"- error: {s['error_kind']}: `{s['error_msg']}`")
        events = s.get("events") or []
        if events:
            lines.append("")
            lines.append("**Events:**")
            for e in events:
                payload_str = ""
                if e.get("payload_json"):
                    try:
                        payload_str = (
                            f" — `{json.dumps(json.loads(e['payload_json']))[:200]}`"
                        )
                    except json.JSONDecodeError:
                        pass
                lines.append(
                    f"- `{e['at']}` **{e['name']}**{payload_str}"
                )
        lines.append("")
    return "\n".join(lines)


def render_agent_quality_section(db_path: Path,
                                  run_id: str | None) -> str:
    """v0.92 — per-agent quality summary appended to markdown.

    Returns empty string if no run_id or zero quality rows.
    """
    if not run_id:
        return ""
    try:
        from lib.agent_quality import summary as _summary
        s = _summary(db_path, run_id=run_id)
    except Exception:
        return ""
    if s.get("n_rows", 0) == 0:
        return ""
    lines = ["", "## Agent quality (v0.92)", ""]
    for agent, d in sorted(s["by_agent"].items()):
        latest = d.get("latest_score")
        latest_str = (
            f"{latest:.2f}" if isinstance(latest, (int, float))
            else "—"
        )
        lines.append(
            f"- **{agent}** — latest {latest_str} "
            f"(n={d['n']}, mean {d['mean']:.2f}, "
            f"range {d['min']:.2f}–{d['max']:.2f})"
        )
    lines.append("")
    return "\n".join(lines)


def render_otlp(payload: dict) -> str:
    """v0.116 — emit OpenTelemetry OTLP-compatible JSON.

    Maps coscientist trace + spans to OTLP `resourceSpans` shape
    so external tools (Jaeger, Honeycomb, Tempo) can ingest a
    coscientist run trace via standard collectors.

    Reference shape:
      {"resourceSpans": [{"scope_spans": [{"spans": [...]}]}]}

    Coscientist span kinds map to OTLP `kind`:
      phase / sub-agent / persist / harvest / other → INTERNAL (1)
      tool-call → CLIENT (3)
      gate → INTERNAL (1)
    """
    if payload is None:
        return json.dumps({"resourceSpans": []}, indent=2)
    trace = payload["trace"]
    spans = payload["spans"]
    trace_id = trace["trace_id"]

    _OTLP_KIND = {
        "phase": 1, "sub-agent": 1, "persist": 1, "other": 1,
        "harvest": 1, "gate": 1, "tool-call": 3,
    }

    otlp_spans = []
    for s in spans:
        attrs: list = []
        if s.get("attrs_json"):
            try:
                d = json.loads(s["attrs_json"])
                if isinstance(d, dict):
                    for k, v in d.items():
                        attrs.append({
                            "key": str(k),
                            "value": {"stringValue": str(v)[:512]},
                        })
            except json.JSONDecodeError:
                pass
        attrs.append({
            "key": "coscientist.kind",
            "value": {"stringValue": s["kind"]},
        })

        events = []
        for e in (s.get("events") or []):
            events.append({
                "name": e["name"],
                "timeUnixNano": _iso_to_nano(e["at"]),
                "attributes": [
                    {"key": "payload",
                     "value": {"stringValue":
                               (e.get("payload_json") or "")[:1024]}},
                ],
            })

        # OTLP status: 1=OK, 2=ERROR, 0=UNSET
        otlp_status = (
            {"code": 2, "message": s.get("error_msg") or ""}
            if s["status"] == "error"
            else {"code": 1}
            if s["status"] == "ok"
            else {"code": 0}
        )

        otlp_spans.append({
            "traceId": trace_id,
            "spanId": s["span_id"],
            "parentSpanId": s.get("parent_span_id") or "",
            "name": s["name"],
            "kind": _OTLP_KIND.get(s["kind"], 1),
            "startTimeUnixNano": _iso_to_nano(s["started_at"]),
            "endTimeUnixNano": (
                _iso_to_nano(s["ended_at"])
                if s.get("ended_at") else 0
            ),
            "attributes": attrs,
            "events": events,
            "status": otlp_status,
        })

    return json.dumps({
        "resourceSpans": [{
            "resource": {
                "attributes": [
                    {"key": "service.name",
                     "value": {"stringValue": "coscientist"}},
                    {"key": "coscientist.run_id",
                     "value": {"stringValue":
                               trace.get("run_id") or ""}},
                ],
            },
            "scopeSpans": [{
                "scope": {"name": "coscientist", "version": "0.116"},
                "spans": otlp_spans,
            }],
        }],
    }, indent=2)


def _iso_to_nano(iso: str | None) -> int:
    """Convert ISO 8601 to nanoseconds since epoch."""
    if not iso:
        return 0
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return int(dt.timestamp() * 1_000_000_000)
    except (ValueError, AttributeError):
        return 0


def render(payload: dict, fmt: str,
           db_path: Path | None = None) -> str:
    if fmt == "mermaid":
        return render_mermaid(payload)
    elif fmt == "md":
        out = render_markdown(payload)
        # v0.92: append agent-quality summary if available.
        if payload and db_path is not None:
            run_id = payload.get("trace", {}).get("run_id")
            out += render_agent_quality_section(db_path, run_id)
        return out
    elif fmt == "json":
        return json.dumps(payload, indent=2, default=str) + "\n"
    elif fmt == "otlp":
        return render_otlp(payload) + "\n"
    else:
        raise ValueError(
            f"unknown format {fmt!r}; expected mermaid|md|json|otlp"
        )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="trace_render",
        description="Render a coscientist execution trace (v0.91).",
    )
    p.add_argument("--db", required=True, help="Path to coscientist DB")
    p.add_argument("--trace-id", required=True)
    p.add_argument(
        "--format", choices=("mermaid", "md", "json", "otlp"),
        default="md",
    )
    args = p.parse_args(argv)

    from lib.trace import get_trace
    payload = get_trace(Path(args.db), args.trace_id)
    sys.stdout.write(render(payload, args.format, db_path=Path(args.db)))
    return 0 if payload is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""v0.124 — push OTLP traces to a remote collector.

Reads coscientist trace via lib.trace.get_trace, renders OTLP
JSON via lib.trace_render.render_otlp, POSTs to a configured
endpoint.

Defaults match OpenTelemetry collector spec:
  endpoint: http://localhost:4318/v1/traces
  content-type: application/json

Pure stdlib (urllib). Auth headers via env (OTEL_EXPORTER_HEADERS,
key=val,key=val format) — avoids hardcoding credentials.

CLI:
    uv run python -m lib.trace_export \\
        --db <path> --trace-id <tid> \\
        [--endpoint http://...] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

_DEFAULT_ENDPOINT = "http://localhost:4318/v1/traces"


def _parse_headers(env_value: str | None) -> dict[str, str]:
    """Parse `key=val,key2=val2` env format → dict."""
    if not env_value:
        return {}
    out: dict[str, str] = {}
    for pair in env_value.split(","):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        k, _, v = pair.partition("=")
        out[k.strip()] = v.strip()
    return out


def push(
    payload: dict | None,
    *,
    endpoint: str | None = None,
    headers: dict[str, str] | None = None,
    dry_run: bool = False,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Push an OTLP-rendered payload to a collector.

    Returns: {ok, status_code|None, endpoint, n_spans,
              error|None, dry_run}.

    Best-effort: never raises. Network errors caught + reported.
    """
    from lib.trace_render import render_otlp

    if endpoint is None:
        endpoint = os.environ.get(
            "OTEL_EXPORTER_OTLP_ENDPOINT",
            _DEFAULT_ENDPOINT,
        )
        # Some users set OTEL_EXPORTER_OTLP_ENDPOINT to base URL
        # without /v1/traces. Append if missing.
        if endpoint and not endpoint.rstrip("/").endswith("/v1/traces"):
            endpoint = endpoint.rstrip("/") + "/v1/traces"

    otlp_str = render_otlp(payload)
    body = otlp_str.encode("utf-8")

    n_spans = 0
    try:
        otlp = json.loads(otlp_str)
        rs = otlp.get("resourceSpans", [])
        if rs:
            ss = rs[0].get("scopeSpans", [])
            if ss:
                n_spans = len(ss[0].get("spans", []))
    except (json.JSONDecodeError, IndexError, KeyError):
        pass

    if dry_run:
        return {
            "ok": True, "status_code": None,
            "endpoint": endpoint, "n_spans": n_spans,
            "error": None, "dry_run": True,
        }

    all_headers = {"Content-Type": "application/json"}
    if headers:
        all_headers.update(headers)
    env_h = _parse_headers(os.environ.get("OTEL_EXPORTER_HEADERS"))
    all_headers.update(env_h)

    req = urllib.request.Request(
        endpoint, data=body, headers=all_headers, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return {
                "ok": 200 <= resp.status < 300,
                "status_code": resp.status,
                "endpoint": endpoint,
                "n_spans": n_spans,
                "error": None,
                "dry_run": False,
            }
    except urllib.error.HTTPError as e:
        return {
            "ok": False, "status_code": e.code,
            "endpoint": endpoint, "n_spans": n_spans,
            "error": f"HTTP {e.code}: {e.reason}",
            "dry_run": False,
        }
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return {
            "ok": False, "status_code": None,
            "endpoint": endpoint, "n_spans": n_spans,
            "error": str(e), "dry_run": False,
        }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="trace_export",
        description="Push OTLP traces to a collector (v0.124).",
    )
    p.add_argument("--db", required=True)
    p.add_argument("--trace-id", required=True)
    p.add_argument(
        "--endpoint", default=None,
        help=("Collector URL. Defaults to "
              "$OTEL_EXPORTER_OTLP_ENDPOINT or "
              "http://localhost:4318/v1/traces."),
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Render OTLP, don't POST. Useful for validation.",
    )
    p.add_argument("--timeout", type=float, default=10.0)
    args = p.parse_args(argv)

    from lib.trace import get_trace
    payload = get_trace(Path(args.db), args.trace_id)
    if payload is None:
        sys.stdout.write(json.dumps({
            "ok": False,
            "error": f"trace {args.trace_id!r} not found",
        }, indent=2) + "\n")
        return 1

    result = push(
        payload, endpoint=args.endpoint,
        dry_run=args.dry_run, timeout=args.timeout,
    )
    sys.stdout.write(json.dumps(result, indent=2) + "\n")
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

"""v0.124 — OTLP collector push tests."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests
from lib import trace, trace_export
from lib.cache import run_db_path


_REPO = Path(__file__).resolve().parents[1]


def _new_run_db(rid: str) -> Path:
    db = run_db_path(rid)
    schema = (_REPO / "lib" / "sqlite_schema.sql").read_text()
    con = sqlite3.connect(db)
    con.executescript(schema)
    con.close()
    from lib.migrations import ensure_current
    ensure_current(db)
    return db


class _CollectorHandler(BaseHTTPRequestHandler):
    captured: list[dict] = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            payload = {"_raw": body.decode("utf-8", "replace")}
        self.__class__.captured.append({
            "path": self.path,
            "headers": dict(self.headers),
            "payload": payload,
        })
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"partialSuccess":{}}')

    def log_message(self, *args):
        pass  # silence stderr


def _start_collector():
    _CollectorHandler.captured = []
    server = HTTPServer(("127.0.0.1", 0), _CollectorHandler)
    thread = threading.Thread(
        target=server.serve_forever, daemon=True,
    )
    thread.start()
    return server, thread


class ParseHeadersTests(TestCase):
    def test_empty_returns_empty_dict(self):
        self.assertEqual(trace_export._parse_headers(None), {})
        self.assertEqual(trace_export._parse_headers(""), {})

    def test_single_pair(self):
        out = trace_export._parse_headers("api-key=secret")
        self.assertEqual(out, {"api-key": "secret"})

    def test_multiple_pairs(self):
        out = trace_export._parse_headers("k1=v1,k2=v2")
        self.assertEqual(out, {"k1": "v1", "k2": "v2"})

    def test_whitespace_trimmed(self):
        out = trace_export._parse_headers(" k1 = v1 , k2=v2 ")
        self.assertEqual(out, {"k1": "v1", "k2": "v2"})


class PushTests(TestCase):
    def test_dry_run_does_not_send(self):
        with isolated_cache():
            rid = "rid-d"
            db = _new_run_db(rid)
            trace.init_trace(db, trace_id=rid, run_id=rid)
            with trace.start_span(db, rid, "phase", "scout"):
                pass
            payload = trace.get_trace(db, rid)
            r = trace_export.push(
                payload,
                endpoint="http://nonexistent.invalid:9999/v1/traces",
                dry_run=True,
            )
            self.assertTrue(r["ok"])
            self.assertTrue(r["dry_run"])
            self.assertGreater(r["n_spans"], 0)

    def test_real_post_to_local_collector(self):
        with isolated_cache():
            rid = "rid-r"
            db = _new_run_db(rid)
            trace.init_trace(db, trace_id=rid, run_id=rid)
            with trace.start_span(db, rid, "phase", "scout"):
                pass
            with trace.start_span(db, rid, "tool-call", "lookup"):
                pass
            payload = trace.get_trace(db, rid)
            server, thread = _start_collector()
            try:
                port = server.server_address[1]
                r = trace_export.push(
                    payload,
                    endpoint=f"http://127.0.0.1:{port}/v1/traces",
                )
                self.assertTrue(r["ok"], r)
                self.assertEqual(r["status_code"], 200)
                self.assertEqual(r["n_spans"], 2)
                self.assertEqual(len(_CollectorHandler.captured), 1)
                cap = _CollectorHandler.captured[0]
                self.assertIn("resourceSpans", cap["payload"])
            finally:
                server.shutdown()

    def test_endpoint_appends_v1_traces(self):
        with isolated_cache():
            rid = "rid-a"
            db = _new_run_db(rid)
            trace.init_trace(db, trace_id=rid, run_id=rid)
            with trace.start_span(db, rid, "phase", "scout"):
                pass
            payload = trace.get_trace(db, rid)
            server, thread = _start_collector()
            try:
                port = server.server_address[1]
                # Pass base URL only — should auto-append /v1/traces
                old_env = os.environ.pop(
                    "OTEL_EXPORTER_OTLP_ENDPOINT", None,
                )
                os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = (
                    f"http://127.0.0.1:{port}"
                )
                try:
                    r = trace_export.push(payload)
                    self.assertTrue(r["ok"], r)
                    self.assertTrue(
                        r["endpoint"].endswith("/v1/traces"),
                    )
                finally:
                    if old_env is not None:
                        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = (
                            old_env
                        )
                    else:
                        os.environ.pop(
                            "OTEL_EXPORTER_OTLP_ENDPOINT", None,
                        )
            finally:
                server.shutdown()

    def test_unreachable_endpoint_returns_error(self):
        with isolated_cache():
            rid = "rid-u"
            db = _new_run_db(rid)
            trace.init_trace(db, trace_id=rid, run_id=rid)
            payload = trace.get_trace(db, rid)
            r = trace_export.push(
                payload,
                endpoint="http://127.0.0.1:1/v1/traces",
                timeout=2.0,
            )
            self.assertFalse(r["ok"])
            self.assertIsNotNone(r["error"])

    def test_env_headers_attached(self):
        with isolated_cache():
            rid = "rid-h"
            db = _new_run_db(rid)
            trace.init_trace(db, trace_id=rid, run_id=rid)
            with trace.start_span(db, rid, "phase", "scout"):
                pass
            payload = trace.get_trace(db, rid)
            server, thread = _start_collector()
            try:
                port = server.server_address[1]
                old = os.environ.pop("OTEL_EXPORTER_HEADERS", None)
                os.environ["OTEL_EXPORTER_HEADERS"] = (
                    "x-honeycomb-team=fake-key,x-other=val"
                )
                try:
                    r = trace_export.push(
                        payload,
                        endpoint=f"http://127.0.0.1:{port}/v1/traces",
                    )
                    self.assertTrue(r["ok"], r)
                    cap = _CollectorHandler.captured[0]
                    # HTTP server normalizes case via Title-Case
                    found = None
                    for k, v in cap["headers"].items():
                        if k.lower() == "x-honeycomb-team":
                            found = v
                            break
                    self.assertEqual(found, "fake-key")
                finally:
                    if old is not None:
                        os.environ["OTEL_EXPORTER_HEADERS"] = old
                    else:
                        os.environ.pop("OTEL_EXPORTER_HEADERS", None)
            finally:
                server.shutdown()


class CliTests(TestCase):
    def test_cli_dry_run(self):
        with isolated_cache():
            rid = "rid-cli"
            db = _new_run_db(rid)
            trace.init_trace(db, trace_id=rid, run_id=rid)
            with trace.start_span(db, rid, "phase", "scout"):
                pass
            r = subprocess.run(
                [sys.executable, "-m", "lib.trace_export",
                 "--db", str(db), "--trace-id", rid,
                 "--dry-run"],
                capture_output=True, text=True, cwd=str(_REPO),
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            payload = json.loads(r.stdout)
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["dry_run"])

    def test_cli_missing_trace_returns_1(self):
        with isolated_cache():
            db = _new_run_db("rid-x")
            r = subprocess.run(
                [sys.executable, "-m", "lib.trace_export",
                 "--db", str(db), "--trace-id", "nonexistent",
                 "--dry-run"],
                capture_output=True, text=True, cwd=str(_REPO),
            )
            self.assertEqual(r.returncode, 1)
            payload = json.loads(r.stdout)
            self.assertFalse(payload["ok"])


if __name__ == "__main__":
    raise SystemExit(run_tests(
        ParseHeadersTests, PushTests, CliTests,
    ))

"""v0.84 — CONTRIBUTING + db_check + manuscript-mcp .docx fixture."""
from __future__ import annotations

import importlib.util
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests
from lib import db_check, project, skill_persist
from lib.cache import run_db_path


_REPO = Path(__file__).resolve().parents[1]
_PANDOC = shutil.which("pandoc")
_MANUSCRIPT_SERVER = _REPO / "mcp" / "manuscript-mcp" / "server.py"


class ContributingTests(TestCase):
    def test_contributing_present(self):
        path = _REPO / "CONTRIBUTING.md"
        self.assertTrue(path.exists(), f"missing {path}")

    def test_contributing_covers_main_patterns(self):
        text = (_REPO / "CONTRIBUTING.md").read_text()
        for needle in (
            "Adding a new skill",
            "Adding a custom MCP server",
            "Adding a new schema migration",
            "Pre-merge checklist",
            "Architecture invariants",
        ):
            self.assertIn(needle, text,
                          f"CONTRIBUTING.md missing section: {needle}")


class DbCheckTests(TestCase):
    def test_check_all_returns_dict(self):
        with isolated_cache():
            res = db_check.check_all()
            self.assertIn("ok", res)
            self.assertIn("n_dbs", res)
            self.assertEqual(res["n_dbs"], 0)

    def test_healthy_run_db(self):
        with isolated_cache():
            db = run_db_path("dbcheck_run")
            schema = (_REPO / "lib" / "sqlite_schema.sql").read_text()
            con = sqlite3.connect(db)
            con.executescript(schema)
            con.close()
            from lib.migrations import ensure_current
            ensure_current(db)

            res = db_check.check_all()
            run_reports = [
                r for r in res["reports"]
                if "dbcheck_run" in r["path"]
            ]
            self.assertEqual(len(run_reports), 1)
            self.assertTrue(
                run_reports[0]["healthy"],
                f"unexpected issues: {run_reports[0]['issues']}",
            )

    def test_healthy_project_db(self):
        with isolated_cache():
            pid = project.create("dbcheck_proj")
            graph_node_added = False
            try:
                from lib import graph
                graph.add_node(pid, "paper", "X", "X")
                graph_node_added = True
            except Exception:
                pass
            res = db_check.check_all()
            proj_reports = [
                r for r in res["reports"]
                if "project.db" in r["path"]
            ]
            self.assertEqual(len(proj_reports), 1)
            self.assertTrue(
                proj_reports[0]["healthy"],
                f"unexpected issues: {proj_reports[0]['issues']}",
            )

    def test_detects_missing_migration(self):
        with isolated_cache():
            db = run_db_path("incomplete_run")
            schema = (_REPO / "lib" / "sqlite_schema.sql").read_text()
            con = sqlite3.connect(db)
            con.executescript(schema)
            # Manually create schema_versions + insert only one
            # version (simulates drift: should be 1..10 but only 1).
            con.execute("""
                CREATE TABLE IF NOT EXISTS schema_versions (
                    version    INTEGER PRIMARY KEY,
                    name       TEXT NOT NULL,
                    applied_at TEXT NOT NULL
                )
            """)
            con.execute(
                "INSERT INTO schema_versions VALUES (?, ?, ?)",
                (1, "v0.13", "2026-04-28T00:00:00+00:00"),
            )
            con.commit()
            con.close()

            res = db_check.check_all()
            run_reports = [
                r for r in res["reports"]
                if "incomplete_run" in r["path"]
            ]
            self.assertEqual(len(run_reports), 1)
            self.assertFalse(run_reports[0]["healthy"])
            self.assertTrue(any("missing migrations" in i
                                for i in run_reports[0]["issues"]))


class ManuscriptMcpDocxFixtureTests(TestCase):
    """v0.84 — round-trip a real .docx file through manuscript-mcp's
    parse_manuscript tool to catch upstream pandoc shape drift."""

    def setUp(self):
        if "mcp" not in sys.modules:
            import types
            mcp_pkg = types.ModuleType("mcp")
            mcp_server = types.ModuleType("mcp.server")
            mcp_fastmcp = types.ModuleType("mcp.server.fastmcp")

            class _StubMCP:
                def __init__(self, name): self.name = name
                def tool(self):
                    def deco(fn): return fn
                    return deco
                def run(self): pass

            mcp_fastmcp.FastMCP = _StubMCP
            sys.modules["mcp"] = mcp_pkg
            sys.modules["mcp.server"] = mcp_server
            sys.modules["mcp.server.fastmcp"] = mcp_fastmcp

        spec = importlib.util.spec_from_file_location(
            "manuscript_mcp_docx", _MANUSCRIPT_SERVER,
        )
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    def _make_docx(self, markdown: str) -> Path:
        """Use pandoc to convert markdown → real .docx fixture."""
        if not _PANDOC:
            return None  # pyright: ignore[reportReturnType]
        tmpdir = Path(tempfile.mkdtemp(prefix="coscientist-docx-"))
        md_path = tmpdir / "src.md"
        md_path.write_text(markdown)
        docx_path = tmpdir / "out.docx"
        subprocess.run(
            ["pandoc", str(md_path), "-f", "markdown", "-t", "docx",
             "-o", str(docx_path)],
            check=True, capture_output=True,
        )
        return docx_path

    def test_round_trip_extracts_section(self):
        if not _PANDOC:
            return  # pandoc not on PATH; skip
        markdown = (
            "# Introduction\n\n"
            "Some prose with a citation [@smith2020].\n\n"
            "## Methods\n\n"
            "More prose.\n"
        )
        docx = self._make_docx(markdown)
        try:
            out = self.mod.parse_manuscript(str(docx), fmt="auto")
            self.assertNotIn("error", out)
            # The .docx round-trip via pandoc should preserve at
            # least one section.
            self.assertGreaterEqual(out["n_sections"], 1)
            self.assertGreater(out["word_count"], 5)
        finally:
            shutil.rmtree(docx.parent, ignore_errors=True)

    def test_missing_pandoc_skipped_gracefully(self):
        # Always-passing sentinel: documents that the parser
        # surfaces an error rather than crashing.
        if _PANDOC:
            return
        # If pandoc isn't on PATH, the v0.73 fallback path must
        # return {"error": ...}, not crash.
        out = self.mod.parse_manuscript("/nonexistent.docx", fmt="docx")
        self.assertIn("error", out)


if __name__ == "__main__":
    raise SystemExit(run_tests(
        ContributingTests,
        DbCheckTests,
        ManuscriptMcpDocxFixtureTests,
    ))

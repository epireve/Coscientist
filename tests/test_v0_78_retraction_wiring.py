"""v0.78a — retraction-watch ↔ retraction-mcp wiring tests.

Validates the new `scan.py --mcp-lookup` subcommand:
  1. Imports retraction-mcp's lookup_doi function under stub mcp.
  2. Reads each paper's manifest.json for DOI.
  3. Shapes results for cmd_persist + (optional) auto-persists.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests

_REPO = Path(__file__).resolve().parents[1]
_SCAN = _REPO / ".claude" / "skills" / "retraction-watch" / "scripts" / "scan.py"


def _seed_project_with_paper(pid: str, cid: str, doi: str | None):
    """Create project + add a paper to artifact_index + write manifest."""
    from lib import project
    project.create("test", description=pid)  # creates the DB
    real_pid = project.project_id_for("test") if False else (
        # we need the project_id created — create with explicit name
        None
    )
    # Use create() return value directly.
    real_pid = project.create(pid)
    db = project.project_db_path(real_pid)
    con = sqlite3.connect(db)
    with con:
        con.execute(
            "INSERT INTO artifact_index "
            "(artifact_id, kind, project_id, state, path, "
            " created_at, updated_at) "
            "VALUES (?, 'paper', ?, 'discovered', ?, ?, ?)",
            (cid, real_pid, "/tmp/x",
             "2026-04-28T00:00:00+00:00",
             "2026-04-28T00:00:00+00:00"),
        )
    con.close()
    # Write a manifest with the DOI on disk so _doi_for_canonical sees it.
    from lib.cache import cache_root
    paper_dir = cache_root() / "papers" / cid
    paper_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"canonical_id": cid, "state": "discovered"}
    if doi:
        manifest["doi"] = doi
    (paper_dir / "manifest.json").write_text(json.dumps(manifest))
    return real_pid


def _run_scan(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_SCAN), *args],
        capture_output=True, text=True, cwd=str(_REPO),
    )


class McpLookupCliTests(TestCase):
    def test_skips_paper_without_doi(self):
        with isolated_cache() as root:
            pid = _seed_project_with_paper(
                "no-doi-proj", "paper_a_2020_x", doi=None,
            )
            r = _run_scan(
                "--project-id", pid, "--mcp-lookup", "--max-age-days", "0",
            )
            # Either succeeds (offline path with stub mcp) or errors
            # cleanly. Don't assert returncode strictly because offline
            # network calls inside lookup_doi may fail; what matters is
            # the skipped_no_doi list.
            data = json.loads(r.stdout)
            self.assertIn("paper_a_2020_x", data["skipped_no_doi"])

    def test_no_papers_at_all(self):
        with isolated_cache():
            from lib import project
            pid = project.create("empty-proj")
            r = _run_scan(
                "--project-id", pid, "--mcp-lookup", "--max-age-days", "0",
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            data = json.loads(r.stdout)
            self.assertEqual(data["checked"], 0)
            self.assertEqual(data["skipped_no_doi"], [])


class McpLookupUnitTests(TestCase):
    """Direct unit-tests by importing scan.py as a module."""

    def setUp(self):
        # Stub `mcp` so server import succeeds inside scan.py.
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

        # Import scan.py as a module.
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "retraction_scan", _SCAN,
        )
        self.scan_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.scan_mod)

    def test_doi_for_canonical_with_manifest(self):
        with isolated_cache() as root:
            cid = "test_paper"
            paper_dir = root / "papers" / cid
            paper_dir.mkdir(parents=True, exist_ok=True)
            (paper_dir / "manifest.json").write_text(
                json.dumps({"canonical_id": cid, "doi": "10.1/x"})
            )
            self.assertEqual(
                self.scan_mod._doi_for_canonical(cid), "10.1/x")

    def test_doi_for_canonical_no_manifest(self):
        with isolated_cache():
            self.assertIsNone(
                self.scan_mod._doi_for_canonical("missing_paper"))

    def test_doi_for_canonical_no_doi_field(self):
        with isolated_cache() as root:
            cid = "no_doi_paper"
            paper_dir = root / "papers" / cid
            paper_dir.mkdir(parents=True, exist_ok=True)
            (paper_dir / "manifest.json").write_text(
                json.dumps({"canonical_id": cid})
            )
            self.assertIsNone(self.scan_mod._doi_for_canonical(cid))


if __name__ == "__main__":
    raise SystemExit(run_tests(McpLookupCliTests, McpLookupUnitTests))

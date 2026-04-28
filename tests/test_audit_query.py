"""v0.44 tests for audit-query skill."""

import json
import subprocess
import sys
from pathlib import Path

from tests import _shim  # noqa: F401
from tests.harness import TestCase, isolated_cache, run_tests

_ROOT = Path(__file__).resolve().parent.parent
QUERY = _ROOT / ".claude/skills/audit-query/scripts/query.py"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(QUERY), *args],
        capture_output=True, text=True,
    )


def _seed_audit_log(content: str) -> None:
    from lib.cache import audit_log_path
    p = audit_log_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def _seed_sandbox_log(records: list[dict]) -> None:
    from lib.cache import cache_root
    p = cache_root() / "sandbox_audit.log"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(r) for r in records) + "\n")


class FetchesTests(TestCase):
    def test_fetches_empty_logs(self):
        with isolated_cache():
            r = _run("fetches")
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            self.assertEqual(out["total_records"], 0)

    def test_fetches_legacy_line_parsed(self):
        with isolated_cache():
            _seed_audit_log(
                "2026-04-26T01:22:38 doi=None arxiv=2010.11929 tier=arxiv status=ok\n"
            )
            r = _run("fetches")
            out = json.loads(r.stdout)
            self.assertEqual(out["total_records"], 1)
            self.assertEqual(out["by_tier"], {"arxiv": 1})
            self.assertEqual(out["by_status"], {"ok": 1})

    def test_fetches_jsonl_record_parsed(self):
        with isolated_cache():
            _seed_audit_log(json.dumps({
                "at": "2026-04-27T10:00:00",
                "tier": "openalex",
                "status": "ok",
                "doi": "10.1038/s41586-020-2649-2",
            }) + "\n")
            r = _run("fetches")
            out = json.loads(r.stdout)
            self.assertEqual(out["total_records"], 1)
            self.assertIn("openalex", out["by_tier"])

    def test_fetches_failures_listed(self):
        with isolated_cache():
            lines = [
                json.dumps({"at": "2026-04-27", "tier": "unpaywall",
                            "status": "fail"}),
                json.dumps({"at": "2026-04-27", "tier": "unpaywall",
                            "status": "ok"}),
            ]
            _seed_audit_log("\n".join(lines) + "\n")
            r = _run("fetches")
            out = json.loads(r.stdout)
            self.assertEqual(len(out["recent_failures"]), 1)

    def test_fetches_since_filters(self):
        with isolated_cache():
            _seed_audit_log(
                "2026-04-01T00:00:00 tier=arxiv status=ok\n"
                "2026-04-27T00:00:00 tier=arxiv status=ok\n"
            )
            out = json.loads(_run("fetches", "--since", "2026-04-15").stdout)
            self.assertEqual(out["total_records"], 1)


class SandboxTests(TestCase):
    def test_sandbox_empty(self):
        with isolated_cache():
            r = _run("sandbox")
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            self.assertEqual(out["total_runs"], 0)

    def test_sandbox_counts_classes(self):
        with isolated_cache():
            _seed_sandbox_log([
                {"audit_id": "a", "started_at": "2026-04-26", "exit_code": 0,
                 "wall_time_seconds": 1.0, "timed_out": False,
                 "memory_oom": False, "error_class": None},
                {"audit_id": "b", "started_at": "2026-04-26", "exit_code": 124,
                 "wall_time_seconds": 5.0, "timed_out": True,
                 "memory_oom": False, "error_class": "timeout"},
                {"audit_id": "c", "started_at": "2026-04-26", "exit_code": 137,
                 "wall_time_seconds": 0.1, "timed_out": False,
                 "memory_oom": True, "error_class": "killed_or_oom"},
            ])
            out = json.loads(_run("sandbox").stdout)
            self.assertEqual(out["total_runs"], 3)
            self.assertEqual(out["n_timeouts"], 1)
            self.assertEqual(out["n_ooms"], 1)
            self.assertEqual(out["n_nonzero_exit"], 2)
            self.assertEqual(out["total_wall_time_seconds"], 6.1)
            self.assertEqual(out["by_error_class"]["timeout"], 1)
            self.assertEqual(out["by_error_class"]["killed_or_oom"], 1)
            self.assertEqual(out["by_error_class"]["ok"], 1)

    def test_sandbox_filter_by_error_class(self):
        with isolated_cache():
            _seed_sandbox_log([
                {"audit_id": "x", "started_at": "2026-04-26",
                 "exit_code": 137, "wall_time_seconds": 0.1,
                 "memory_oom": True, "error_class": "killed_or_oom"},
                {"audit_id": "y", "started_at": "2026-04-26",
                 "exit_code": 0, "wall_time_seconds": 1.0,
                 "error_class": None},
            ])
            out = json.loads(
                _run("sandbox", "--error-class", "killed_or_oom").stdout
            )
            self.assertEqual(out["total_runs"], 1)


class SummaryTests(TestCase):
    def test_summary_combines_both(self):
        with isolated_cache():
            _seed_audit_log("2026-04-27T00:00:00 tier=oa status=ok\n")
            _seed_sandbox_log([{
                "audit_id": "z", "started_at": "2026-04-27",
                "exit_code": 0, "wall_time_seconds": 2.0,
            }])
            r = _run("summary")
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            self.assertIn("fetches", out)
            self.assertIn("sandbox", out)
            self.assertEqual(out["fetches"]["total_records"], 1)
            self.assertEqual(out["sandbox"]["total_runs"], 1)

    def test_summary_markdown_format(self):
        with isolated_cache():
            _seed_audit_log("2026-04-27T00:00:00 tier=oa status=ok\n")
            r = _run("--format", "md", "summary")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("# audit-query", r.stdout)
            self.assertIn("## Fetches", r.stdout)
            self.assertIn("## Sandbox", r.stdout)


class IncludeArchivesTests(TestCase):
    def test_fetches_default_excludes_archives(self):
        with isolated_cache():
            from lib.cache import audit_log_path
            audit_log_path().write_text("2026-04-27 tier=arxiv status=ok\n")
            # Seed an archive next to it
            archive = audit_log_path().with_name(
                "audit.log.20260101T000000Z"
            )
            archive.write_text("2026-01-01 tier=oa status=ok\n")
            out = json.loads(_run("fetches").stdout)
            self.assertEqual(out["total_records"], 1)

    def test_fetches_include_archives_unions(self):
        with isolated_cache():
            from lib.cache import audit_log_path
            audit_log_path().write_text("2026-04-27 tier=arxiv status=ok\n")
            archive = audit_log_path().with_name(
                "audit.log.20260101T000000Z"
            )
            archive.write_text("2026-01-01 tier=oa status=ok\n")
            out = json.loads(_run("fetches", "--include-archives").stdout)
            self.assertEqual(out["total_records"], 2)

    def test_sandbox_include_archives_unions(self):
        with isolated_cache():
            from lib.cache import cache_root
            live = cache_root() / "sandbox_audit.log"
            live.write_text(json.dumps({
                "audit_id": "live", "started_at": "2026-04-27",
                "exit_code": 0, "wall_time_seconds": 1.0,
            }) + "\n")
            archive = live.with_name("sandbox_audit.log.20260101T000000Z")
            archive.write_text(json.dumps({
                "audit_id": "old", "started_at": "2026-01-01",
                "exit_code": 0, "wall_time_seconds": 2.0,
            }) + "\n")
            base = json.loads(_run("sandbox").stdout)
            self.assertEqual(base["total_runs"], 1)
            full = json.loads(_run("sandbox", "--include-archives").stdout)
            self.assertEqual(full["total_runs"], 2)
            self.assertEqual(full["total_wall_time_seconds"], 3.0)


class CliTests(TestCase):
    def test_no_subcommand_errors(self):
        r = _run()
        self.assertTrue(r.returncode != 0)

    def test_unknown_subcommand_errors(self):
        r = _run("nonexistent")
        self.assertTrue(r.returncode != 0)


if __name__ == "__main__":
    sys.exit(run_tests(
        FetchesTests, SandboxTests, SummaryTests,
        IncludeArchivesTests, CliTests,
    ))

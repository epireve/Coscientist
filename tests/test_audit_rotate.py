"""v0.45 tests for audit-rotate skill."""

from tests import _shim  # noqa: F401

import json
import re
import subprocess
import sys
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests

_ROOT = Path(__file__).resolve().parent.parent
ROTATE = _ROOT / ".claude/skills/audit-rotate/scripts/rotate.py"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROTATE), *args],
        capture_output=True, text=True,
    )


def _seed_logs(fetches_text: str = "", sandbox_lines: list[dict] | None = None):
    from lib.cache import audit_log_path, cache_root
    audit_log_path().write_text(fetches_text)
    sb = cache_root() / "sandbox_audit.log"
    sb.parent.mkdir(parents=True, exist_ok=True)
    if sandbox_lines is None:
        sandbox_lines = []
    sb.write_text("\n".join(json.dumps(r) for r in sandbox_lines)
                  + ("\n" if sandbox_lines else ""))


class InspectTests(TestCase):
    def test_inspect_empty(self):
        with isolated_cache():
            _seed_logs()
            r = _run("inspect")
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            self.assertIn("audit.log", out)
            self.assertIn("sandbox_audit.log", out)
            self.assertEqual(out["audit.log"]["line_count"], 0)

    def test_inspect_reports_size_and_line_count(self):
        with isolated_cache():
            _seed_logs(
                fetches_text="line1\nline2\nline3\n",
                sandbox_lines=[{"audit_id": "x"}],
            )
            out = json.loads(_run("inspect").stdout)
            self.assertEqual(out["audit.log"]["line_count"], 3)
            self.assertEqual(out["sandbox_audit.log"]["line_count"], 1)
            self.assertGreater(out["audit.log"]["size_bytes"], 0)


class RotateTests(TestCase):
    def test_rotate_under_threshold_skipped(self):
        with isolated_cache():
            _seed_logs(fetches_text="tiny\n")
            out = json.loads(_run("rotate").stdout)
            for r in out["rotations"]:
                if r["path"].endswith("audit.log"):
                    self.assertEqual(r["skipped"], "under-threshold")

    def test_rotate_force_creates_archive_and_resets(self):
        with isolated_cache():
            _seed_logs(fetches_text="content\n")
            out = json.loads(_run("rotate", "--force",
                                   "--target", "fetches").stdout)
            from lib.cache import audit_log_path
            live = audit_log_path()
            # archived path was returned
            res = next(r for r in out["rotations"]
                       if r["path"] == str(live))
            self.assertIn("archived_to", res)
            self.assertTrue(Path(res["archived_to"]).exists())
            # archive name follows the UTC stamp pattern
            archive_name = Path(res["archived_to"]).name
            self.assertTrue(re.match(
                r"^audit\.log\.\d{8}T\d{6}Z(_\d+)?$", archive_name
            ), archive_name)
            # live file recreated empty
            self.assertTrue(live.exists())
            self.assertEqual(live.read_text(), "")
            # archive preserves original content
            self.assertEqual(
                Path(res["archived_to"]).read_text(),
                "content\n"
            )

    def test_rotate_target_filter(self):
        with isolated_cache():
            _seed_logs(fetches_text="x\n",
                       sandbox_lines=[{"a": 1}])
            out = json.loads(_run("rotate", "--force",
                                   "--target", "sandbox").stdout)
            paths = [r["path"] for r in out["rotations"]]
            self.assertEqual(len(paths), 1)
            self.assertTrue(paths[0].endswith("sandbox_audit.log"))
            # fetches log untouched
            from lib.cache import audit_log_path
            self.assertEqual(audit_log_path().read_text(), "x\n")

    def test_rotate_no_file_skipped_cleanly(self):
        with isolated_cache():
            # don't seed; both files absent
            r = _run("rotate", "--force")
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            for res in out["rotations"]:
                self.assertEqual(res.get("skipped"), "no-such-file")

    def test_rotate_max_bytes_threshold_respected(self):
        with isolated_cache():
            _seed_logs(fetches_text="x" * 100)
            # 100 < 1000 → skip
            out_under = json.loads(_run("rotate", "--max-bytes", "1000",
                                          "--target", "fetches").stdout)
            res_under = next(r for r in out_under["rotations"]
                             if r["path"].endswith("audit.log"))
            self.assertEqual(res_under["skipped"], "under-threshold")
            # 100 >= 50 → rotate
            out_over = json.loads(_run("rotate", "--max-bytes", "50",
                                         "--target", "fetches").stdout)
            res_over = next(r for r in out_over["rotations"]
                            if r["path"].endswith("audit.log"))
            self.assertIn("archived_to", res_over)


class ListArchivesTests(TestCase):
    def test_list_empty_when_no_archives(self):
        with isolated_cache():
            _seed_logs()
            out = json.loads(_run("list-archives").stdout)
            self.assertEqual(out["count"], 0)

    def test_list_includes_rotated_archive(self):
        with isolated_cache():
            _seed_logs(fetches_text="data\n")
            _run("rotate", "--force", "--target", "fetches")
            out = json.loads(_run("list-archives").stdout)
            self.assertEqual(out["count"], 1)
            self.assertTrue(out["archives"][0]["archive"]
                            .startswith("audit.log."))


class CliTests(TestCase):
    def test_no_subcommand_errors(self):
        r = _run()
        self.assertTrue(r.returncode != 0)

    def test_unknown_subcommand_errors(self):
        r = _run("nonexistent")
        self.assertTrue(r.returncode != 0)


if __name__ == "__main__":
    sys.exit(run_tests(
        InspectTests, RotateTests, ListArchivesTests, CliTests,
    ))

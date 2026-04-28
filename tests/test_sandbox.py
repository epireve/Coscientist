"""Tests for reproducibility-mcp/sandbox.py — stub mode + helpers."""
from __future__ import annotations

import importlib.util as _ilu
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

from tests.harness import CoscientistTestCase, isolated_cache  # noqa


def _load():
    spec = _ilu.spec_from_file_location(
        "sandbox",
        _REPO_ROOT / ".claude/skills/reproducibility-mcp/scripts/sandbox.py",
    )
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class HelperTests(CoscientistTestCase):
    def test_truncate_under_cap(self):
        mod = _load()
        s, t = mod._truncate("hello", 1024)
        self.assertEqual(s, "hello")
        self.assertFalse(t)

    def test_truncate_over_cap(self):
        mod = _load()
        s, t = mod._truncate("a" * 5000, 100)
        self.assertTrue(t)
        self.assertTrue(len(s) <= 200)
        self.assertIn("TRUNCATED", s)

    def test_make_audit_id_unique(self):
        mod = _load()
        a = mod._make_audit_id("/tmp/x", "echo hi")
        b = mod._make_audit_id("/tmp/x", "echo hi")
        # Different time_ns → different ids
        self.assertFalse(a == b)
        self.assertEqual(len(a), 8)  # blake2s digest_size=4 → 8 hex chars

    def test_detect_oom_exit_137(self):
        mod = _load()
        self.assertTrue(mod._detect_oom("", 137))

    def test_detect_oom_killed_msg(self):
        mod = _load()
        self.assertTrue(mod._detect_oom("Container Killed: OOM", 1))

    def test_detect_oom_normal_failure(self):
        mod = _load()
        self.assertFalse(mod._detect_oom("script error", 1))


class BuildArgsTests(CoscientistTestCase):
    def test_build_docker_args_security_flags(self):
        mod = _load()
        import argparse
        args = argparse.Namespace(
            image="python:3.12-slim",
            memory_mb=4096,
            cpus=2.0,
            command="echo hi",
        )
        cmd = mod._build_docker_args(args, Path("/tmp/work"), "audit_xyz")
        joined = " ".join(cmd)
        self.assertIn("--network none", joined)
        self.assertIn("--memory 4096m", joined)
        self.assertIn("--memory-swap 4096m", joined)
        self.assertIn("--cpus 2.0", joined)
        self.assertIn("--read-only", joined)
        self.assertIn("--rm", joined)
        self.assertIn("--user 1000:1000", joined)
        self.assertIn("--security-opt no-new-privileges", joined)
        self.assertIn("/tmp/work:/workspace:rw", joined)
        self.assertIn("coscientist.audit_id=audit_xyz", joined)


class CheckCommandTests(CoscientistTestCase):
    def test_check_returns_status(self):
        with isolated_cache():
            mod = _load()
            import argparse
            import contextlib
            import io
            args = argparse.Namespace()
            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf):
                    mod.cmd_check(args)
            except SystemExit:
                # Daemon may not be running in test env — that's fine
                pass
            r = json.loads(buf.getvalue())
            self.assertIn("docker_binary_present", r)
            self.assertIn("docker_daemon_reachable", r)
            self.assertIn("ready", r)


class RunRequiresDaemonTests(CoscientistTestCase):
    def test_run_without_daemon_raises(self):
        """If daemon unreachable, run must SystemExit."""
        with isolated_cache():
            mod = _load()
            # Force unreachable
            original = mod._docker_available
            mod._docker_available = lambda: False
            try:
                import argparse
                args = argparse.Namespace(
                    workspace="/tmp", command="echo x",
                    image="python:3.12-slim", memory_mb=4096, cpus=2.0,
                    timeout_seconds=30, audit_id=None,
                )
                with self.assertRaises(SystemExit):
                    mod.cmd_run(args)
            finally:
                mod._docker_available = original

    def test_run_invalid_workspace_raises(self):
        with isolated_cache():
            mod = _load()
            mod._docker_available = lambda: True  # pretend daemon ok
            import argparse
            args = argparse.Namespace(
                workspace="/nonexistent/path/xyz", command="echo x",
                image="python:3.12-slim", memory_mb=4096, cpus=2.0,
                timeout_seconds=30, audit_id=None,
            )
            with self.assertRaises(SystemExit):
                mod.cmd_run(args)

    def test_run_empty_command_raises(self):
        with isolated_cache() as cache:
            mod = _load()
            mod._docker_available = lambda: True
            ws = cache / "workspace"
            ws.mkdir()
            import argparse
            args = argparse.Namespace(
                workspace=str(ws), command="   ",
                image="python:3.12-slim", memory_mb=4096, cpus=2.0,
                timeout_seconds=30, audit_id=None,
            )
            with self.assertRaises(SystemExit):
                mod.cmd_run(args)


class DiagnoseTests(CoscientistTestCase):
    def test_classify_image_not_found(self):
        mod = _load()
        self.assertEqual(
            mod._classify_run_error("Error: No such image: foo:bar", 125),
            "image_not_found",
        )

    def test_classify_pull_access_denied(self):
        mod = _load()
        self.assertEqual(
            mod._classify_run_error("pull access denied for x", 125),
            "image_not_found",
        )

    def test_classify_timeout_124(self):
        mod = _load()
        self.assertEqual(mod._classify_run_error("", 124), "timeout")

    def test_classify_killed_137(self):
        mod = _load()
        self.assertEqual(mod._classify_run_error("", 137), "killed_or_oom")

    def test_classify_daemon_died(self):
        mod = _load()
        self.assertEqual(
            mod._classify_run_error("Cannot connect to the Docker daemon", 1),
            "daemon_died",
        )

    def test_classify_normal_zero_returns_none(self):
        mod = _load()
        self.assertIsNone(mod._classify_run_error("", 0))


class ValidateWorkspaceTests(CoscientistTestCase):
    def test_nonexistent(self):
        mod = _load()
        ok, err = mod._validate_workspace(Path("/nonexistent/xyz/abc"))
        self.assertFalse(ok)
        self.assertIn("not found", err)

    def test_not_directory(self):
        with isolated_cache() as cache:
            mod = _load()
            f = cache / "afile"
            f.write_text("hi")
            ok, err = mod._validate_workspace(f)
            self.assertFalse(ok)
            self.assertIn("not a directory", err)

    def test_symlink_rejected(self):
        with isolated_cache() as cache:
            mod = _load()
            real = cache / "real_ws"
            real.mkdir()
            link = cache / "link_ws"
            import os
            os.symlink(real, link)
            ok, err = mod._validate_workspace(link)
            self.assertFalse(ok)
            self.assertIn("symlink", err)

    def test_sensitive_path_rejected(self):
        mod = _load()
        ok, err = mod._validate_workspace(Path("/etc"))
        self.assertFalse(ok)
        self.assertIn("sensitive", err)

    def test_valid_workspace(self):
        with isolated_cache() as cache:
            mod = _load()
            ws = cache / "ws"
            ws.mkdir()
            ok, err = mod._validate_workspace(ws)
            self.assertTrue(ok)
            self.assertEqual(err, "")


class CmdRunValidationTests(CoscientistTestCase):
    def test_run_invalid_memory_raises(self):
        with isolated_cache() as cache:
            mod = _load()
            mod._docker_available = lambda: True
            ws = cache / "ws"
            ws.mkdir()
            import argparse
            args = argparse.Namespace(
                workspace=str(ws), command="echo x",
                image="python:3.12-slim", memory_mb=8, cpus=2.0,
                timeout_seconds=30, audit_id=None,
            )
            with self.assertRaises(SystemExit):
                mod.cmd_run(args)

    def test_run_invalid_cpus_raises(self):
        with isolated_cache() as cache:
            mod = _load()
            mod._docker_available = lambda: True
            ws = cache / "ws"
            ws.mkdir()
            import argparse
            args = argparse.Namespace(
                workspace=str(ws), command="echo x",
                image="python:3.12-slim", memory_mb=64, cpus=0,
                timeout_seconds=30, audit_id=None,
            )
            with self.assertRaises(SystemExit):
                mod.cmd_run(args)

    def test_run_invalid_timeout_raises(self):
        with isolated_cache() as cache:
            mod = _load()
            mod._docker_available = lambda: True
            ws = cache / "ws"
            ws.mkdir()
            import argparse
            args = argparse.Namespace(
                workspace=str(ws), command="echo x",
                image="python:3.12-slim", memory_mb=64, cpus=2.0,
                timeout_seconds=0, audit_id=None,
            )
            with self.assertRaises(SystemExit):
                mod.cmd_run(args)

    def test_run_audit_id_collision_raises(self):
        with isolated_cache() as cache:
            mod = _load()
            mod._docker_available = lambda: True
            ws = cache / "ws"
            ws.mkdir()
            log = cache / "sandbox_audit.log"
            log.write_text(json.dumps({"audit_id": "dup1"}) + "\n")
            import argparse
            args = argparse.Namespace(
                workspace=str(ws), command="echo x",
                image="python:3.12-slim", memory_mb=64, cpus=2.0,
                timeout_seconds=30, audit_id="dup1",
            )
            with self.assertRaises(SystemExit):
                mod.cmd_run(args)


class WorkspaceLockTests(CoscientistTestCase):
    def test_concurrent_run_rejected_when_locked(self):
        """Second cmd_run on a locked workspace must SystemExit fast."""
        from lib.lockfile import artifact_lock
        with isolated_cache() as cache:
            mod = _load()
            mod._docker_available = lambda: True
            ws = cache / "ws"
            ws.mkdir()
            import argparse
            args = argparse.Namespace(
                workspace=str(ws), command="echo x",
                image="python:3.12-slim", memory_mb=64, cpus=2.0,
                timeout_seconds=30, audit_id=None, lock_timeout=0.0,
            )
            # Hold the lock from a "concurrent" caller
            with artifact_lock(ws, timeout=1.0):
                with self.assertRaises(SystemExit):
                    mod.cmd_run(args)

    def test_lock_released_on_normal_exit(self):
        """After cmd_run completes (or errors), lock must be free."""
        from lib.lockfile import LockTimeout, artifact_lock
        with isolated_cache() as cache:
            mod = _load()
            mod._docker_available = lambda: False  # forces SystemExit inside
            ws = cache / "ws"
            ws.mkdir()
            import argparse
            args = argparse.Namespace(
                workspace=str(ws), command="echo x",
                image="python:3.12-slim", memory_mb=64, cpus=2.0,
                timeout_seconds=30, audit_id=None, lock_timeout=0.0,
            )
            try:
                mod.cmd_run(args)
            except SystemExit:
                pass
            # Lock should be free now
            try:
                with artifact_lock(ws, timeout=0.5):
                    pass  # acquired cleanly
            except LockTimeout:
                self.fail("lock not released after cmd_run")


class AuditTests(CoscientistTestCase):
    def test_audit_empty(self):
        with isolated_cache():
            mod = _load()
            import argparse
            import contextlib
            import io
            args = argparse.Namespace(limit=10, filter=None)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_audit(args)
            r = json.loads(buf.getvalue())
            self.assertEqual(r["total"], 0)

    def test_audit_reads_log(self):
        with isolated_cache() as cache:
            mod = _load()
            log = cache / "sandbox_audit.log"
            log.write_text(
                json.dumps({"audit_id": "a1", "image": "python:3.12-slim",
                            "exit_code": 0}) + "\n"
                + json.dumps({"audit_id": "a2", "image": "alpine",
                              "exit_code": 1}) + "\n"
            )
            import argparse
            import contextlib
            import io
            args = argparse.Namespace(limit=10, filter=None)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_audit(args)
            r = json.loads(buf.getvalue())
            self.assertEqual(r["total"], 2)

    def test_audit_filter(self):
        with isolated_cache() as cache:
            mod = _load()
            log = cache / "sandbox_audit.log"
            log.write_text(
                json.dumps({"audit_id": "a1", "image": "python:3.12-slim"}) + "\n"
                + json.dumps({"audit_id": "a2", "image": "alpine"}) + "\n"
            )
            import argparse
            import contextlib
            import io
            args = argparse.Namespace(limit=10, filter="image=alpine")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_audit(args)
            r = json.loads(buf.getvalue())
            self.assertEqual(r["total"], 1)
            self.assertEqual(r["entries"][0]["audit_id"], "a2")

    def test_audit_limit(self):
        with isolated_cache() as cache:
            mod = _load()
            log = cache / "sandbox_audit.log"
            lines = [json.dumps({"audit_id": f"a{i}"}) for i in range(20)]
            log.write_text("\n".join(lines) + "\n")
            import argparse
            import contextlib
            import io
            args = argparse.Namespace(limit=5, filter=None)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_audit(args)
            r = json.loads(buf.getvalue())
            self.assertEqual(r["total"], 5)
            # Last 5 — a15..a19
            self.assertEqual(r["entries"][-1]["audit_id"], "a19")

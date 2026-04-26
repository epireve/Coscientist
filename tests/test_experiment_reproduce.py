"""Tests for experiment-reproduce skill (sandbox boundary mocked)."""
from __future__ import annotations

import importlib.util as _ilu
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

from tests.harness import CoscientistTestCase, isolated_cache  # noqa


def _load_reproduce():
    spec = _ilu.spec_from_file_location(
        "reproduce",
        _REPO_ROOT / ".claude/skills/experiment-reproduce/scripts/reproduce.py",
    )
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_design():
    spec = _ilu.spec_from_file_location(
        "design",
        _REPO_ROOT / ".claude/skills/experiment-design/scripts/design.py",
    )
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _setup_preregistered(cache: Path, design_mod, title="Test Exp"):
    """Build a preregistered experiment + return its eid."""
    import argparse, io, contextlib
    # init
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        design_mod.cmd_init(argparse.Namespace(
            title=title,
            hypothesis="X improves Y",
            falsifier="X does not improve Y",
            project_id=None, force=False,
        ))
    eid = json.loads(buf.getvalue())["experiment_id"]
    # variables
    for kind, name in [("independent", "method"), ("dependent", "accuracy")]:
        buf2 = io.StringIO()
        with contextlib.redirect_stdout(buf2):
            design_mod.cmd_variable(argparse.Namespace(
                experiment_id=eid, kind=kind, name=name, description="",
            ))
    # metric
    buf3 = io.StringIO()
    with contextlib.redirect_stdout(buf3):
        design_mod.cmd_metric(argparse.Namespace(
            experiment_id=eid, name="accuracy", type="scalar",
            target=0.85, comparison=">=",
        ))
    # preregister
    buf4 = io.StringIO()
    with contextlib.redirect_stdout(buf4):
        design_mod.cmd_preregister(argparse.Namespace(
            experiment_id=eid, rr_id=None,
            budget_seconds=60, memory_mb=2048, force=False,
        ))
    return eid


def _stub_sandbox_run(workspace_path: str, metric_value: float = 0.92,
                     write_result_json: bool = True, exit_code: int = 0):
    """Returns a sandbox.cmd_run replacement that emits a fixed JSON response."""
    def stubbed(args):
        # Optionally write result.json into workspace
        if write_result_json and exit_code == 0:
            (Path(workspace_path) / "result.json").write_text(
                json.dumps({"accuracy": metric_value})
            )
        response = {
            "audit_id": "test_audit_123",
            "image": args.image,
            "command": args.command,
            "workspace": str(workspace_path),
            "memory_mb": args.memory_mb,
            "cpus": args.cpus,
            "timeout_seconds": args.timeout_seconds,
            "started_at": "2026-04-27T00:00:00+00:00",
            "finished_at": "2026-04-27T00:00:01+00:00",
            "wall_time_seconds": 1.23,
            "exit_code": exit_code,
            "timed_out": False,
            "memory_oom": False,
            "stdout": (json.dumps({"accuracy": metric_value}) + "\n") if exit_code == 0 else "",
            "stderr": "" if exit_code == 0 else "boom",
            "stdout_bytes": 100, "stderr_bytes": 0,
            "stdout_truncated": False, "stderr_truncated": False,
        }
        print(json.dumps(response))
    return stubbed


class MetricExtractionTests(CoscientistTestCase):
    def test_extract_from_result_json(self):
        with isolated_cache() as cache:
            mod = _load_reproduce()
            ws = cache / "ws"
            ws.mkdir()
            (ws / "result.json").write_text(json.dumps({"accuracy": 0.91}))
            value, source = mod._extract_metric(ws, "", "accuracy")
            self.assertEqual(value, 0.91)
            self.assertEqual(source, "result.json")

    def test_extract_from_stdout_last_line(self):
        with isolated_cache() as cache:
            mod = _load_reproduce()
            ws = cache / "ws"
            ws.mkdir()
            stdout = "training...\n{\"accuracy\": 0.88}\n"
            value, source = mod._extract_metric(ws, stdout, "accuracy")
            self.assertEqual(value, 0.88)
            self.assertEqual(source, "stdout-json")

    def test_extract_no_metric_returns_none(self):
        with isolated_cache() as cache:
            mod = _load_reproduce()
            ws = cache / "ws"
            ws.mkdir()
            value, source = mod._extract_metric(ws, "no metric here\n", "accuracy")
            self.assertIsNone(value)

    def test_extract_nan_rejected(self):
        with isolated_cache() as cache:
            mod = _load_reproduce()
            ws = cache / "ws"
            ws.mkdir()
            # JSON NaN is non-standard but Python json accepts it
            (ws / "result.json").write_text('{"accuracy": NaN}')
            value, _ = mod._extract_metric(ws, "", "accuracy")
            self.assertIsNone(value)

    def test_extract_infinity_rejected(self):
        with isolated_cache() as cache:
            mod = _load_reproduce()
            ws = cache / "ws"
            ws.mkdir()
            (ws / "result.json").write_text('{"accuracy": Infinity}')
            value, _ = mod._extract_metric(ws, "", "accuracy")
            self.assertIsNone(value)

    def test_extract_bool_rejected(self):
        with isolated_cache() as cache:
            mod = _load_reproduce()
            ws = cache / "ws"
            ws.mkdir()
            (ws / "result.json").write_text(json.dumps({"accuracy": True}))
            value, _ = mod._extract_metric(ws, "", "accuracy")
            self.assertIsNone(value)

    def test_is_finite_number_helper(self):
        mod = _load_reproduce()
        self.assertTrue(mod._is_finite_number(1.5))
        self.assertTrue(mod._is_finite_number(0))
        self.assertTrue(mod._is_finite_number(-3.2))
        self.assertFalse(mod._is_finite_number(True))
        self.assertFalse(mod._is_finite_number("0.5"))
        self.assertFalse(mod._is_finite_number(None))
        self.assertFalse(mod._is_finite_number(float("nan")))
        self.assertFalse(mod._is_finite_number(float("inf")))


class RunStateTransitionTests(CoscientistTestCase):
    def test_run_advances_to_completed(self):
        with isolated_cache() as cache:
            design = _load_design()
            mod = _load_reproduce()
            eid = _setup_preregistered(cache, design)

            ws = cache / "ws"
            ws.mkdir()

            # Stub sandbox.cmd_run + _docker_available
            sandbox_mod = mod._load_sandbox()
            sandbox_mod._docker_available = lambda: True
            sandbox_mod.cmd_run = _stub_sandbox_run(str(ws), metric_value=0.92)
            mod._load_sandbox = lambda: sandbox_mod

            import argparse, io, contextlib
            args = argparse.Namespace(
                experiment_id=eid, workspace=str(ws),
                entry_command=None, image="python:3.12-slim", cpus=2.0,
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_run(args)
            r = json.loads(buf.getvalue())
            self.assertEqual(r["state"], "completed")
            self.assertEqual(r["metric_value"], 0.92)
            self.assertEqual(r["metric_source"], "result.json")
            self.assertFalse(r["error"])

    def test_run_requires_preregistered_state(self):
        with isolated_cache() as cache:
            design = _load_design()
            mod = _load_reproduce()
            # Init only — state=designed, not preregistered
            import argparse, io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                design.cmd_init(argparse.Namespace(
                    title="X", hypothesis="h", falsifier="f",
                    project_id=None, force=False,
                ))
            eid = json.loads(buf.getvalue())["experiment_id"]

            ws = cache / "ws"
            ws.mkdir()
            args = argparse.Namespace(
                experiment_id=eid, workspace=str(ws),
                entry_command=None, image="python:3.12-slim", cpus=2.0,
            )
            with self.assertRaises(SystemExit):
                mod.cmd_run(args)

    def test_run_workspace_missing_raises(self):
        with isolated_cache() as cache:
            design = _load_design()
            mod = _load_reproduce()
            eid = _setup_preregistered(cache, design)
            import argparse
            args = argparse.Namespace(
                experiment_id=eid, workspace="/nonexistent/path",
                entry_command=None, image="python:3.12-slim", cpus=2.0,
            )
            with self.assertRaises(SystemExit):
                mod.cmd_run(args)

    def test_run_failed_exit_code_marks_error(self):
        with isolated_cache() as cache:
            design = _load_design()
            mod = _load_reproduce()
            eid = _setup_preregistered(cache, design)

            ws = cache / "ws"
            ws.mkdir()
            sandbox_mod = mod._load_sandbox()
            sandbox_mod._docker_available = lambda: True
            sandbox_mod.cmd_run = _stub_sandbox_run(str(ws), exit_code=1)
            mod._load_sandbox = lambda: sandbox_mod

            import argparse, io, contextlib
            args = argparse.Namespace(
                experiment_id=eid, workspace=str(ws),
                entry_command=None, image="python:3.12-slim", cpus=2.0,
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_run(args)
            r = json.loads(buf.getvalue())
            self.assertTrue(r["error"])

    def test_run_no_docker_rolls_back_state(self):
        with isolated_cache() as cache:
            design = _load_design()
            mod = _load_reproduce()
            eid = _setup_preregistered(cache, design)

            ws = cache / "ws"
            ws.mkdir()
            sandbox_mod = mod._load_sandbox()
            sandbox_mod._docker_available = lambda: False
            mod._load_sandbox = lambda: sandbox_mod

            import argparse
            args = argparse.Namespace(
                experiment_id=eid, workspace=str(ws),
                entry_command=None, image="python:3.12-slim", cpus=2.0,
            )
            with self.assertRaises(SystemExit):
                mod.cmd_run(args)
            # State should be rolled back to preregistered
            manifest = mod._load_manifest(eid)
            self.assertEqual(manifest["state"], "preregistered")


class AnalyzeTests(CoscientistTestCase):
    def test_analyze_passes_when_metric_meets_target(self):
        with isolated_cache() as cache:
            design = _load_design()
            mod = _load_reproduce()
            eid = _setup_preregistered(cache, design)
            ws = cache / "ws"
            ws.mkdir()

            sandbox_mod = mod._load_sandbox()
            sandbox_mod._docker_available = lambda: True
            sandbox_mod.cmd_run = _stub_sandbox_run(str(ws), metric_value=0.92)
            mod._load_sandbox = lambda: sandbox_mod

            import argparse, io, contextlib
            with contextlib.redirect_stdout(io.StringIO()):
                mod.cmd_run(argparse.Namespace(
                    experiment_id=eid, workspace=str(ws),
                    entry_command=None, image="python:3.12-slim", cpus=2.0,
                ))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_analyze(argparse.Namespace(experiment_id=eid))
            r = json.loads(buf.getvalue())
            self.assertEqual(r["state"], "analyzed")
            self.assertTrue(r["passed"])

    def test_analyze_fails_when_metric_misses_target(self):
        with isolated_cache() as cache:
            design = _load_design()
            mod = _load_reproduce()
            eid = _setup_preregistered(cache, design)
            ws = cache / "ws"
            ws.mkdir()

            sandbox_mod = mod._load_sandbox()
            sandbox_mod._docker_available = lambda: True
            # Metric below target 0.85
            sandbox_mod.cmd_run = _stub_sandbox_run(str(ws), metric_value=0.50)
            mod._load_sandbox = lambda: sandbox_mod

            import argparse, io, contextlib
            with contextlib.redirect_stdout(io.StringIO()):
                mod.cmd_run(argparse.Namespace(
                    experiment_id=eid, workspace=str(ws),
                    entry_command=None, image="python:3.12-slim", cpus=2.0,
                ))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_analyze(argparse.Namespace(experiment_id=eid))
            r = json.loads(buf.getvalue())
            self.assertFalse(r["passed"])

    def test_analyze_requires_completed_state(self):
        with isolated_cache() as cache:
            design = _load_design()
            mod = _load_reproduce()
            eid = _setup_preregistered(cache, design)
            import argparse
            with self.assertRaises(SystemExit):
                mod.cmd_analyze(argparse.Namespace(experiment_id=eid))


class ReproduceCheckTests(CoscientistTestCase):
    def _full_pipeline_to_analyzed(self, cache, mod, design, first_value=0.92):
        eid = _setup_preregistered(cache, design)
        ws = cache / "ws"
        ws.mkdir()
        sandbox_mod = mod._load_sandbox()
        sandbox_mod._docker_available = lambda: True
        sandbox_mod.cmd_run = _stub_sandbox_run(str(ws), metric_value=first_value)
        mod._load_sandbox = lambda: sandbox_mod

        import argparse, io, contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            mod.cmd_run(argparse.Namespace(
                experiment_id=eid, workspace=str(ws),
                entry_command=None, image="python:3.12-slim", cpus=2.0,
            ))
            mod.cmd_analyze(argparse.Namespace(experiment_id=eid))
        return eid, ws, sandbox_mod

    def test_reproduce_within_tolerance(self):
        with isolated_cache() as cache:
            design = _load_design()
            mod = _load_reproduce()
            eid, ws, sandbox_mod = self._full_pipeline_to_analyzed(
                cache, mod, design, first_value=0.92
            )
            # Second run: 0.93 (within 5% of 0.92)
            sandbox_mod.cmd_run = _stub_sandbox_run(str(ws), metric_value=0.93)

            import argparse, io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_reproduce_check(argparse.Namespace(
                    experiment_id=eid, workspace=str(ws),
                    tolerance=0.05, entry_command=None,
                    image="python:3.12-slim", cpus=2.0,
                ))
            r = json.loads(buf.getvalue())
            self.assertEqual(r["state"], "reproduced")
            self.assertTrue(r["within_tolerance"])

    def test_reproduce_outside_tolerance(self):
        with isolated_cache() as cache:
            design = _load_design()
            mod = _load_reproduce()
            eid, ws, sandbox_mod = self._full_pipeline_to_analyzed(
                cache, mod, design, first_value=0.92
            )
            # Second run: 0.50 (very different)
            sandbox_mod.cmd_run = _stub_sandbox_run(str(ws), metric_value=0.50)

            import argparse, io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_reproduce_check(argparse.Namespace(
                    experiment_id=eid, workspace=str(ws),
                    tolerance=0.05, entry_command=None,
                    image="python:3.12-slim", cpus=2.0,
                ))
            r = json.loads(buf.getvalue())
            self.assertFalse(r["within_tolerance"])
            # State stays analyzed; reproduction_failed flag set
            manifest = mod._load_manifest(eid)
            self.assertEqual(manifest["state"], "analyzed")
            self.assertTrue(manifest.get("reproduction_failed"))


class StatusTests(CoscientistTestCase):
    def test_status_shows_full_pipeline(self):
        with isolated_cache() as cache:
            design = _load_design()
            mod = _load_reproduce()
            eid = _setup_preregistered(cache, design)
            import argparse, io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_status(argparse.Namespace(experiment_id=eid))
            r = json.loads(buf.getvalue())
            self.assertEqual(r["state"], "preregistered")
            self.assertEqual(r["primary_metric"]["name"], "accuracy")
            self.assertIsNone(r["last_run"])
            self.assertEqual(r["run_count"], 0)

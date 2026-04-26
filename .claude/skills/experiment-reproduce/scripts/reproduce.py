#!/usr/bin/env python3
"""experiment-reproduce: run preregistered experiments via reproducibility-mcp."""
from __future__ import annotations

import argparse
import importlib.util as _ilu
import json
import operator as op
import sys
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import cache_root  # noqa: E402

VALID_STATES = ("designed", "preregistered", "running", "completed", "analyzed", "reproduced")

COMPARISON_OPS = {
    ">": op.gt, ">=": op.ge,
    "<": op.lt, "<=": op.le,
    "==": op.eq, "!=": op.ne,
}


def experiment_dir(eid: str) -> Path:
    return cache_root() / "experiments" / eid


def _load_manifest(eid: str) -> dict:
    p = experiment_dir(eid) / "manifest.json"
    if not p.exists():
        raise FileNotFoundError(f"experiment {eid!r} not found")
    return json.loads(p.read_text())


def _load_protocol(eid: str) -> dict:
    p = experiment_dir(eid) / "protocol.json"
    if not p.exists():
        raise FileNotFoundError(f"protocol not found for {eid!r}")
    return json.loads(p.read_text())


def _save_manifest(eid: str, manifest: dict) -> None:
    manifest["updated_at"] = datetime.now(UTC).isoformat()
    (experiment_dir(eid) / "manifest.json").write_text(json.dumps(manifest, indent=2))


def _load_sandbox():
    """Lazy-load the sandbox.py module from reproducibility-mcp."""
    spec = _ilu.spec_from_file_location(
        "sandbox",
        _REPO_ROOT / ".claude/skills/reproducibility-mcp/scripts/sandbox.py",
    )
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _runs_dir(eid: str) -> Path:
    d = experiment_dir(eid) / "runs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save_run_artifact(eid: str, audit_id: str, response: dict) -> None:
    rd = _runs_dir(eid) / audit_id
    rd.mkdir(parents=True, exist_ok=True)
    (rd / "result.json").write_text(json.dumps({
        "audit_id": audit_id,
        "exit_code": response.get("exit_code"),
        "wall_time_seconds": response.get("wall_time_seconds"),
        "timed_out": response.get("timed_out"),
        "memory_oom": response.get("memory_oom"),
        "stdout_truncated": response.get("stdout_truncated"),
        "stderr_truncated": response.get("stderr_truncated"),
    }, indent=2))
    (rd / "stdout.log").write_text(response.get("stdout") or "")
    (rd / "stderr.log").write_text(response.get("stderr") or "")


def _extract_metric(workspace: Path, stdout: str, metric_name: str) -> tuple[float | None, str]:
    """Find primary metric. Returns (value, source) or (None, '')."""
    rp = workspace / "result.json"
    if rp.exists():
        try:
            data = json.loads(rp.read_text())
            if metric_name in data:
                v = data[metric_name]
                if isinstance(v, (int, float)):
                    return float(v), "result.json"
        except (json.JSONDecodeError, OSError):
            pass

    # Try last non-empty line of stdout as JSON
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if not line:
            continue
        if not line.startswith("{"):
            break
        try:
            data = json.loads(line)
            if isinstance(data, dict) and metric_name in data:
                v = data[metric_name]
                if isinstance(v, (int, float)):
                    return float(v), "stdout-json"
        except json.JSONDecodeError:
            pass
        break

    return None, ""


def cmd_run(args: argparse.Namespace) -> None:
    manifest = _load_manifest(args.experiment_id)
    protocol = _load_protocol(args.experiment_id)

    if manifest["state"] != "preregistered":
        raise SystemExit(
            f"experiment must be in 'preregistered' state to run; "
            f"current: {manifest['state']!r}"
        )

    workspace = Path(args.workspace).resolve()
    if not workspace.exists():
        raise SystemExit(f"workspace not found: {workspace}")
    if not workspace.is_dir():
        raise SystemExit(f"workspace is not a directory: {workspace}")

    budget = protocol.get("budget", {})
    timeout_seconds = budget.get("compute_seconds")
    memory_mb = budget.get("memory_mb")
    if not timeout_seconds or not memory_mb:
        raise SystemExit("protocol budget incomplete; preregister first")

    command = args.entry_command or "python entry.py"

    # Advance to running before invocation
    manifest["state"] = "running"
    _save_manifest(args.experiment_id, manifest)

    sandbox = _load_sandbox()
    if not sandbox._docker_available():
        # Roll back state on infra failure
        manifest["state"] = "preregistered"
        _save_manifest(args.experiment_id, manifest)
        raise SystemExit("Docker daemon not reachable")

    sandbox_args = argparse.Namespace(
        workspace=str(workspace),
        command=command,
        image=args.image,
        memory_mb=memory_mb,
        cpus=args.cpus,
        timeout_seconds=timeout_seconds,
        audit_id=None,
    )

    # Run sandbox; capture printed JSON via stdout redirect
    import io, contextlib
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            sandbox.cmd_run(sandbox_args)
        response = json.loads(buf.getvalue())
    except SystemExit as e:
        manifest["state"] = "preregistered"
        _save_manifest(args.experiment_id, manifest)
        raise SystemExit(f"sandbox failed: {e}")

    audit_id = response["audit_id"]
    _save_run_artifact(args.experiment_id, audit_id, response)

    # Try to extract metric
    metric_name = protocol["primary_metric"]["name"]
    value, source = _extract_metric(workspace, response.get("stdout") or "", metric_name)

    error = response.get("exit_code") != 0 or value is None

    # Update manifest
    manifest["state"] = "completed"
    manifest["last_run"] = {
        "audit_id": audit_id,
        "exit_code": response.get("exit_code"),
        "wall_time_seconds": response.get("wall_time_seconds"),
        "timed_out": response.get("timed_out", False),
        "memory_oom": response.get("memory_oom", False),
        "metric_name": metric_name,
        "metric_value": value,
        "metric_source": source,
        "error": error,
    }
    _save_manifest(args.experiment_id, manifest)

    print(json.dumps({
        "experiment_id": args.experiment_id,
        "audit_id": audit_id,
        "state": "completed",
        "exit_code": response.get("exit_code"),
        "wall_time_seconds": response.get("wall_time_seconds"),
        "timed_out": response.get("timed_out", False),
        "memory_oom": response.get("memory_oom", False),
        "metric_name": metric_name,
        "metric_value": value,
        "metric_source": source,
        "error": error,
    }, indent=2))


def cmd_analyze(args: argparse.Namespace) -> None:
    manifest = _load_manifest(args.experiment_id)
    protocol = _load_protocol(args.experiment_id)

    if manifest["state"] != "completed":
        raise SystemExit(
            f"experiment must be 'completed' to analyze; current: {manifest['state']!r}"
        )

    last_run = manifest.get("last_run") or {}
    value = last_run.get("metric_value")
    if value is None:
        raise SystemExit("no metric value recorded; cannot analyze")

    pm = protocol["primary_metric"]
    target = pm["target"]
    comparison = pm["comparison"]
    op_fn = COMPARISON_OPS.get(comparison)
    if op_fn is None:
        raise SystemExit(f"unknown comparison: {comparison!r}")

    passed = op_fn(value, target)
    analysis = {
        "primary_metric": pm["name"],
        "recorded_value": value,
        "target": target,
        "comparison": comparison,
        "passed": passed,
        "audit_id": last_run.get("audit_id"),
        "analyzed_at": datetime.now(UTC).isoformat(),
    }
    (experiment_dir(args.experiment_id) / "analysis.json").write_text(
        json.dumps(analysis, indent=2)
    )

    manifest["state"] = "analyzed"
    manifest["analysis"] = analysis
    _save_manifest(args.experiment_id, manifest)

    print(json.dumps({
        "experiment_id": args.experiment_id,
        "state": "analyzed",
        "passed": passed,
        "metric_value": value,
        "target": target,
        "comparison": comparison,
    }, indent=2))


def cmd_reproduce_check(args: argparse.Namespace) -> None:
    manifest = _load_manifest(args.experiment_id)
    if manifest["state"] != "analyzed":
        raise SystemExit(
            f"experiment must be 'analyzed' to reproduce-check; current: {manifest['state']!r}"
        )
    analysis = manifest.get("analysis") or {}
    first_value = analysis.get("recorded_value")
    if first_value is None:
        raise SystemExit("no recorded value to reproduce against")

    # Re-run via same workspace
    if not args.workspace:
        raise SystemExit("--workspace required for reproduce-check")
    workspace = Path(args.workspace).resolve()
    if not workspace.exists() or not workspace.is_dir():
        raise SystemExit(f"workspace invalid: {workspace}")

    protocol = _load_protocol(args.experiment_id)
    metric_name = protocol["primary_metric"]["name"]
    budget = protocol["budget"]
    command = args.entry_command or "python entry.py"

    sandbox = _load_sandbox()
    if not sandbox._docker_available():
        raise SystemExit("Docker daemon not reachable")

    sandbox_args = argparse.Namespace(
        workspace=str(workspace),
        command=command,
        image=args.image,
        memory_mb=budget["memory_mb"],
        cpus=args.cpus,
        timeout_seconds=budget["compute_seconds"],
        audit_id=None,
    )
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        sandbox.cmd_run(sandbox_args)
    response = json.loads(buf.getvalue())
    second_audit_id = response["audit_id"]
    _save_run_artifact(args.experiment_id, second_audit_id, response)

    second_value, source = _extract_metric(workspace, response.get("stdout") or "", metric_name)
    if second_value is None:
        raise SystemExit("reproduction run produced no metric")

    # Relative diff vs first run
    if first_value == 0:
        rel_diff = abs(second_value)
    else:
        rel_diff = abs(second_value - first_value) / abs(first_value)

    within = rel_diff <= args.tolerance
    reproduction = {
        "first_value": first_value,
        "second_value": second_value,
        "relative_diff": rel_diff,
        "tolerance": args.tolerance,
        "within_tolerance": within,
        "second_audit_id": second_audit_id,
        "checked_at": datetime.now(UTC).isoformat(),
    }
    (experiment_dir(args.experiment_id) / "reproduction.json").write_text(
        json.dumps(reproduction, indent=2)
    )

    if within:
        manifest["state"] = "reproduced"
    else:
        manifest["reproduction_failed"] = True
    manifest["reproduction"] = reproduction
    _save_manifest(args.experiment_id, manifest)

    print(json.dumps({
        "experiment_id": args.experiment_id,
        "state": manifest["state"],
        "within_tolerance": within,
        "first_value": first_value,
        "second_value": second_value,
        "relative_diff": rel_diff,
        "tolerance": args.tolerance,
    }, indent=2))


def cmd_status(args: argparse.Namespace) -> None:
    manifest = _load_manifest(args.experiment_id)
    protocol = _load_protocol(args.experiment_id)
    runs_dir = _runs_dir(args.experiment_id)
    run_count = len([d for d in runs_dir.iterdir() if d.is_dir()]) if runs_dir.exists() else 0

    print(json.dumps({
        "experiment_id": args.experiment_id,
        "title": protocol.get("title"),
        "state": manifest.get("state"),
        "primary_metric": protocol.get("primary_metric"),
        "budget": protocol.get("budget"),
        "last_run": manifest.get("last_run"),
        "analysis": manifest.get("analysis"),
        "reproduction": manifest.get("reproduction"),
        "run_count": run_count,
    }, indent=2))


def main() -> None:
    p = argparse.ArgumentParser(description="Run preregistered experiments via reproducibility-mcp.")
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("run")
    pr.add_argument("--experiment-id", required=True)
    pr.add_argument("--workspace", required=True)
    pr.add_argument("--entry-command", default=None,
                    help="Override default 'python entry.py'")
    pr.add_argument("--image", default="python:3.12-slim")
    pr.add_argument("--cpus", type=float, default=2.0)
    pr.set_defaults(func=cmd_run)

    pa = sub.add_parser("analyze")
    pa.add_argument("--experiment-id", required=True)
    pa.set_defaults(func=cmd_analyze)

    prp = sub.add_parser("reproduce-check")
    prp.add_argument("--experiment-id", required=True)
    prp.add_argument("--workspace", required=True)
    prp.add_argument("--tolerance", type=float, default=0.05)
    prp.add_argument("--entry-command", default=None)
    prp.add_argument("--image", default="python:3.12-slim")
    prp.add_argument("--cpus", type=float, default=2.0)
    prp.set_defaults(func=cmd_reproduce_check)

    ps = sub.add_parser("status")
    ps.add_argument("--experiment-id", required=True)
    ps.set_defaults(func=cmd_status)

    args = p.parse_args()
    try:
        args.func(args)
    except (FileNotFoundError, ValueError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

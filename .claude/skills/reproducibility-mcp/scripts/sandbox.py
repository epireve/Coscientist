#!/usr/bin/env python3
"""reproducibility-mcp: Docker-backed sandboxed execution."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import cache_root  # noqa: E402

DEFAULT_IMAGE = "python:3.12-slim"
DEFAULT_MEMORY_MB = 4096
DEFAULT_CPUS = 2.0
DEFAULT_TIMEOUT_SECONDS = 600
STDOUT_CAP_BYTES = 1024 * 1024  # 1 MB
AUDIT_LOG_PATH = "sandbox_audit.log"


def _audit_log_path() -> Path:
    return cache_root() / AUDIT_LOG_PATH


def _make_audit_id(workspace: str, command: str) -> str:
    seed = f"{workspace}::{command}::{time.time_ns()}"
    return hashlib.blake2s(seed.encode(), digest_size=4).hexdigest()


def _docker_available() -> bool:
    """Return True if `docker` binary is on PATH AND daemon responds."""
    if not shutil.which("docker"):
        return False
    try:
        result = subprocess.run(
            ["docker", "info"], capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def cmd_check(args: argparse.Namespace) -> None:
    has_binary = bool(shutil.which("docker"))
    daemon_ok = _docker_available()
    print(json.dumps({
        "docker_binary_present": has_binary,
        "docker_daemon_reachable": daemon_ok,
        "ready": has_binary and daemon_ok,
    }, indent=2))
    if not (has_binary and daemon_ok):
        sys.exit(1)


def _build_docker_args(args: argparse.Namespace, workspace: Path,
                      audit_id: str) -> list[str]:
    """Build the docker run command line."""
    return [
        "docker", "run",
        "--rm",
        "--network", "none",
        "--memory", f"{args.memory_mb}m",
        "--memory-swap", f"{args.memory_mb}m",
        "--cpus", str(args.cpus),
        "--read-only",
        "--tmpfs", "/tmp:rw,size=128m",
        "--user", "1000:1000",
        "--security-opt", "no-new-privileges",
        "--workdir", "/workspace",
        "--volume", f"{workspace}:/workspace:rw",
        "--label", f"coscientist.audit_id={audit_id}",
        args.image,
        "sh", "-c", args.command,
    ]


def _truncate(s: str, cap: int) -> tuple[str, bool]:
    encoded = s.encode("utf-8", errors="replace")
    if len(encoded) <= cap:
        return s, False
    return encoded[:cap].decode("utf-8", errors="replace") + "\n...[TRUNCATED]", True


def _detect_oom(stderr: str, exit_code: int) -> bool:
    """Heuristic: docker reports exit code 137 on SIGKILL (often OOM)."""
    if exit_code == 137:
        return True
    return "killed" in stderr.lower() and "oom" in stderr.lower()


def cmd_run(args: argparse.Namespace) -> None:
    if not _docker_available():
        raise SystemExit("Docker daemon not reachable. Run `sandbox.py check`.")

    workspace = Path(args.workspace).resolve()
    if not workspace.exists():
        raise SystemExit(f"workspace not found: {workspace}")
    if not workspace.is_dir():
        raise SystemExit(f"workspace is not a directory: {workspace}")
    if not args.command.strip():
        raise SystemExit("--command must be non-empty")

    audit_id = args.audit_id or _make_audit_id(str(workspace), args.command)
    docker_args = _build_docker_args(args, workspace, audit_id)
    started_at = datetime.now(UTC).isoformat()
    t0 = time.monotonic()
    timed_out = False

    try:
        result = subprocess.run(
            docker_args,
            capture_output=True,
            timeout=args.timeout_seconds,
            text=True,
        )
        exit_code = result.returncode
        stdout = result.stdout
        stderr = result.stderr
    except subprocess.TimeoutExpired as e:
        # Force kill any lingering container with our label
        timed_out = True
        try:
            kill_result = subprocess.run(
                ["docker", "ps", "-q", "--filter", f"label=coscientist.audit_id={audit_id}"],
                capture_output=True, text=True, timeout=5,
            )
            for cid in kill_result.stdout.strip().splitlines():
                if cid:
                    subprocess.run(["docker", "kill", cid], capture_output=True, timeout=5)
        except Exception:
            pass
        exit_code = 124  # standard timeout exit code
        stdout = (e.stdout.decode("utf-8", "replace") if e.stdout else "") or ""
        stderr = (e.stderr.decode("utf-8", "replace") if e.stderr else "") or ""

    wall = round(time.monotonic() - t0, 3)
    finished_at = datetime.now(UTC).isoformat()

    stdout_t, stdout_truncated = _truncate(stdout, STDOUT_CAP_BYTES)
    stderr_t, stderr_truncated = _truncate(stderr, STDOUT_CAP_BYTES)

    audit_entry = {
        "audit_id": audit_id,
        "image": args.image,
        "command": args.command,
        "workspace": str(workspace),
        "memory_mb": args.memory_mb,
        "cpus": args.cpus,
        "timeout_seconds": args.timeout_seconds,
        "started_at": started_at,
        "finished_at": finished_at,
        "wall_time_seconds": wall,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "memory_oom": _detect_oom(stderr, exit_code),
        "stdout_bytes": len(stdout.encode("utf-8", "replace")),
        "stderr_bytes": len(stderr.encode("utf-8", "replace")),
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
    }

    # Append to audit log (one JSON object per line)
    log_path = _audit_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a") as f:
        f.write(json.dumps(audit_entry) + "\n")

    response = dict(audit_entry)
    response["stdout"] = stdout_t
    response["stderr"] = stderr_t
    print(json.dumps(response, indent=2))


def cmd_audit(args: argparse.Namespace) -> None:
    log_path = _audit_log_path()
    if not log_path.exists():
        print(json.dumps({"entries": [], "total": 0}))
        return
    entries = []
    with log_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if args.filter:
        # filter form: key=value
        if "=" in args.filter:
            k, v = args.filter.split("=", 1)
            entries = [e for e in entries if str(e.get(k)) == v]
    entries = entries[-args.limit:]
    print(json.dumps({"entries": entries, "total": len(entries)}, indent=2))


def main() -> None:
    p = argparse.ArgumentParser(description="Docker sandbox for sandboxed execution.")
    sub = p.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("check")
    pc.set_defaults(func=cmd_check)

    pr = sub.add_parser("run")
    pr.add_argument("--workspace", required=True,
                    help="Host path mounted as /workspace (rw)")
    pr.add_argument("--command", required=True,
                    help="Shell command to run inside container")
    pr.add_argument("--image", default=DEFAULT_IMAGE)
    pr.add_argument("--memory-mb", type=int, default=DEFAULT_MEMORY_MB)
    pr.add_argument("--cpus", type=float, default=DEFAULT_CPUS)
    pr.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    pr.add_argument("--audit-id", default=None,
                    help="Pre-set audit ID (links to experiment run)")
    pr.set_defaults(func=cmd_run)

    pa = sub.add_parser("audit")
    pa.add_argument("--limit", type=int, default=20)
    pa.add_argument("--filter", default=None,
                    help="key=value filter (e.g. image=python:3.12-slim)")
    pa.set_defaults(func=cmd_audit)

    args = p.parse_args()
    try:
        args.func(args)
    except (FileNotFoundError, ValueError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

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
from lib.lockfile import LockTimeout, artifact_lock  # noqa: E402

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
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def _docker_diagnose() -> dict:
    """Return structured diagnosis of why Docker is/isn't usable.

    Distinguishes binary-missing, daemon-down, daemon-slow, permission-denied.
    """
    if not shutil.which("docker"):
        return {
            "ready": False,
            "reason": "binary_missing",
            "detail": "`docker` not on PATH",
            "remediation": "Install Docker (e.g. brew install --cask docker) or fix PATH.",
        }
    try:
        result = subprocess.run(
            ["docker", "info"], capture_output=True, timeout=5, text=True,
        )
    except subprocess.TimeoutExpired:
        return {
            "ready": False,
            "reason": "daemon_slow",
            "detail": "`docker info` timed out after 5s",
            "remediation": "Daemon may be starting. Wait + retry, or restart Docker.",
        }
    except (FileNotFoundError, OSError) as e:
        return {
            "ready": False,
            "reason": "binary_broken",
            "detail": f"Failed to invoke docker binary: {e}",
            "remediation": "Reinstall Docker; check that /usr/local/bin/docker symlink resolves.",
        }
    if result.returncode == 0:
        return {"ready": True, "reason": None}
    stderr = (result.stderr or "").lower()
    if "permission denied" in stderr:
        return {
            "ready": False,
            "reason": "permission_denied",
            "detail": result.stderr.strip()[:200],
            "remediation": "Add user to docker group (Linux) or restart Docker Desktop.",
        }
    if "cannot connect" in stderr or "is the docker daemon running" in stderr:
        return {
            "ready": False,
            "reason": "daemon_down",
            "detail": result.stderr.strip()[:200],
            "remediation": "Start Docker Desktop (`open /Applications/Docker.app`) or `systemctl start docker`.",
        }
    return {
        "ready": False,
        "reason": "unknown",
        "detail": result.stderr.strip()[:200] or f"docker info returned {result.returncode}",
        "remediation": "Run `docker info` directly to diagnose.",
    }


def _classify_run_error(stderr: str, exit_code: int) -> str | None:
    """Classify common Docker run-time error patterns. None if normal."""
    if exit_code == 0:
        return None
    s = (stderr or "").lower()
    if "no such image" in s or "manifest unknown" in s or "pull access denied" in s:
        return "image_not_found"
    if "network" in s and ("failed" in s or "timeout" in s or "unreachable" in s):
        return "network_error"
    if "permission denied" in s:
        return "permission_denied"
    if "is the docker daemon running" in s or "cannot connect to the docker daemon" in s:
        return "daemon_died"
    if exit_code == 124:
        return "timeout"
    if exit_code == 137:
        return "killed_or_oom"
    if exit_code == 125:
        # docker run's own error (bad flags, bad image)
        return "docker_invocation_error"
    return None


def _validate_workspace(workspace: Path) -> tuple[bool, str]:
    """Pre-flight checks on workspace dir. Returns (ok, error_message)."""
    if not workspace.exists():
        return False, f"workspace not found: {workspace}"
    if not workspace.is_dir():
        return False, f"workspace is not a directory: {workspace}"
    # Sensitive-path check first — applies to both raw input path and its
    # symlink-resolved form. macOS /etc → /private/etc; both are sensitive.
    # NOTE: /private/var is NOT sensitive (macOS tmpdirs live there).
    # /var/run is — and resolves to /private/var/run on macOS — so we list
    # both forms explicitly rather than blanket-block /private/var.
    sensitive_prefixes = ("/etc", "/var/run", "/proc", "/sys", "/dev",
                          "/private/etc", "/private/var/run")
    rp = str(workspace.resolve())
    raw = str(workspace)
    for prefix in sensitive_prefixes:
        for candidate in (raw, rp):
            if candidate == prefix or candidate.startswith(prefix + "/"):
                return False, (
                    f"workspace inside sensitive system path {prefix}: {candidate}"
                )
    # Reject symlink workspace (bind mount of symlink can escape)
    if workspace.is_symlink():
        return False, f"workspace is a symlink (refusing for security): {workspace}"
    if not os.access(workspace, os.R_OK):
        return False, f"workspace not readable: {workspace}"
    if not os.access(workspace, os.W_OK):
        return False, f"workspace not writable: {workspace}"
    return True, ""


def cmd_check(args: argparse.Namespace) -> None:
    diag = _docker_diagnose()
    has_binary = bool(shutil.which("docker"))
    out = {
        "docker_binary_present": has_binary,
        "docker_daemon_reachable": diag["ready"],
        "ready": diag["ready"],
        "reason": diag.get("reason"),
        "detail": diag.get("detail"),
        "remediation": diag.get("remediation"),
    }
    print(json.dumps(out, indent=2))
    if not diag["ready"]:
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
    """Acquire workspace lock then delegate to _cmd_run_locked."""
    workspace = Path(args.workspace).resolve()
    # Lockfile lives in workspace if valid; otherwise let _cmd_run_locked
    # raise the right error for the bad path.
    if not workspace.exists() or not workspace.is_dir():
        return _cmd_run_locked(args)
    lock_timeout = getattr(args, "lock_timeout", 0.0) or 0.0
    try:
        with artifact_lock(workspace, timeout=lock_timeout):
            _cmd_run_locked(args)
    except LockTimeout as e:
        raise SystemExit(
            f"Concurrent run on workspace {workspace}; "
            f"lock held by another process. {e}"
        )


def _cmd_run_locked(args: argparse.Namespace) -> None:
    if not _docker_available():
        diag = _docker_diagnose()
        raise SystemExit(
            f"Docker not ready ({diag.get('reason')}): {diag.get('detail')}. "
            f"{diag.get('remediation', '')} Run `sandbox.py check` for details."
        )

    workspace = Path(args.workspace).resolve()
    ok, err = _validate_workspace(workspace)
    if not ok:
        raise SystemExit(err)
    if not args.command.strip():
        raise SystemExit("--command must be non-empty")
    if args.memory_mb is not None and args.memory_mb < 16:
        raise SystemExit(f"memory_mb must be >= 16; got {args.memory_mb}")
    if args.cpus is not None and args.cpus <= 0:
        raise SystemExit(f"cpus must be > 0; got {args.cpus}")
    if args.timeout_seconds is not None and args.timeout_seconds <= 0:
        raise SystemExit(f"timeout_seconds must be > 0; got {args.timeout_seconds}")

    audit_id = args.audit_id or _make_audit_id(str(workspace), args.command)
    # Reject audit_id collision when caller forced one
    if args.audit_id:
        log_path = _audit_log_path()
        if log_path.exists():
            try:
                with log_path.open() as f:
                    for line in f:
                        try:
                            e = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if e.get("audit_id") == args.audit_id:
                            raise SystemExit(
                                f"audit_id collision: {args.audit_id!r} already in log"
                            )
            except OSError:
                pass
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

    error_class = _classify_run_error(stderr, exit_code) if not timed_out else "timeout"

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
        "error_class": error_class,
        "stdout_bytes": len(stdout.encode("utf-8", "replace")),
        "stderr_bytes": len(stderr.encode("utf-8", "replace")),
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
    }

    # Append to audit log (non-fatal on disk errors)
    audit_log_warning = None
    try:
        log_path = _audit_log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a") as f:
            f.write(json.dumps(audit_entry) + "\n")
    except OSError as e:
        audit_log_warning = f"audit log write failed: {e}"

    response = dict(audit_entry)
    response["stdout"] = stdout_t
    response["stderr"] = stderr_t
    if audit_log_warning:
        response["audit_log_warning"] = audit_log_warning
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
    pr.add_argument("--lock-timeout", type=float, default=0.0,
                    help="Seconds to wait for workspace lock (default 0 = fail fast)")
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

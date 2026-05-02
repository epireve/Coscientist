---
name: reproducibility-mcp
description: Sandboxed execution via Docker. Runs untrusted scripts inside an isolated container with CPU/memory/wall-time caps, no network, restricted filesystem (only /workspace writable). Audit log per run. Used by experiment-reproduce; can also be invoked directly for ad-hoc sandboxed runs. Despite the name, this is a CLI skill, not an MCP server.
when_to_use: User says "run sandboxed", "reproduce experiment", "isolated exec", "sandbox this script". Required before any code execution from preregistered experiments.
---

# reproducibility-mcp

Docker-backed sandbox for reproducible script execution. Inspired by Sakana AI Scientist's iteration loop and karpathy/autoresearch's fixed-budget pattern.

## Why Docker

- Resource limits enforced by kernel cgroups (CPU, memory, OOM-kill)
- Network isolation via `--network none` (no exfiltration, no API leakage)
- Filesystem isolation via bind mounts (only mounted dirs writable)
- Per-run cleanup via `--rm`
- Reproducible base image (pinned digest)

## Scripts

| Script | Subcommand | Purpose |
|---|---|---|
| `sandbox.py` | `run` | Execute a script inside Docker with limits |
| | `check` | Verify Docker daemon is reachable |
| | `audit` | Tail recent sandbox audit log entries |

## Subcommands

```
sandbox.py check
sandbox.py run --workspace /path/to/dir --command "python entry.py" \
               [--image python:3.12-slim] [--memory-mb 4096] [--cpus 2.0] \
               [--timeout-seconds 600] [--audit-id RUN_ID]
sandbox.py audit [--limit 20] [--filter image=...]
```

## Security model

| Restriction | Enforcement |
|---|---|
| No network | `--network none` flag on container |
| Memory cap | `--memory <mb>m --memory-swap <mb>m` (no swap) |
| CPU cap | `--cpus <n>` |
| Wall-time cap | `subprocess.run(timeout=)` + `docker kill` on timeout |
| Filesystem write only to `/workspace` | bind mount `<host>:/workspace:rw`; rest of container read-only via `--read-only` + `--tmpfs /tmp` |
| Container removed after run | `--rm` |
| Non-root user | `--user 1000:1000` |
| No SUID | `--security-opt no-new-privileges` |

## Output

`run` emits JSON:

```json
{
  "audit_id": "abc123",
  "exit_code": 0,
  "wall_time_seconds": 4.21,
  "stdout": "...",
  "stderr": "...",
  "stdout_truncated": false,
  "memory_oom": false,
  "timed_out": false,
  "error_class": null,
  "image": "python:3.12-slim@sha256:...",
  "command": "python entry.py"
}
```

stdout/stderr capped at 1 MB each (truncated flag set if exceeded).

`error_class` is one of: `null` (success), `image_not_found`, `network_error`,
`permission_denied`, `daemon_died`, `timeout`, `killed_or_oom`,
`docker_invocation_error`, `unknown`. Lets callers (e.g. experiment-reproduce)
distinguish infra failures from genuine script failures.

If the audit log can't be written (disk full, permission denied), the run still
succeeds and `audit_log_warning` is set in the response. Audit-log persistence
is best-effort — the run result itself is authoritative.

## Pre-flight validation

`run` rejects before invoking Docker if:

- workspace doesn't exist / isn't a directory / not r+w
- workspace is a symlink (mount-escape risk)
- workspace resolves under `/etc`, `/var/run`, `/proc`, `/sys`, `/dev`
- `--memory-mb < 16` or `--cpus <= 0` or `--timeout-seconds <= 0`
- caller-supplied `--audit-id` collides with an existing audit log entry
- command is whitespace-only

Call `sandbox.py check` for structured Docker readiness diagnosis. Output
includes `reason` (`binary_missing`, `daemon_down`, `daemon_slow`,
`permission_denied`, `binary_broken`, `unknown`), `detail`, and a
`remediation` hint.

## Audit log

Append-only at `~/.cache/coscientist/sandbox_audit.log` (JSONL). One line per run with full metadata. Never deleted automatically.

## Caveats

- **Docker daemon must be running.** `check` returns nonzero if unreachable.
- **First run pulls the image.** ~150 MB for `python:3.12-slim`. Cache locally.
- **No GPU support yet.** Future: `--gpus all` + `nvidia-runtime` requirement.
- **Timeout granularity is whole seconds.** `kill -9` after grace period.
- **Container kill uses `docker kill --signal SIGKILL`** — no graceful shutdown.

## What this skill does NOT do

- Doesn't pull arbitrary images automatically — explicit `--image` only
- Doesn't write to user's `$HOME` — workspace is the only writable mount
- Doesn't expose ports — network is fully isolated
- Doesn't install the script's dependencies — caller's job (e.g. `pip install` inside the workspace before invoking)

## CLI flag reference (drift coverage)

- `sandbox.py`: `--lock-timeout`

"""v0.81 — verify Coscientist plugins + MCPs are installed correctly.

Inspects:
  - .claude-plugin/marketplace.json — declared plugins.
  - Each plugin's plugin.json + .mcp.json + server file.
  - For MCP plugins: server.py compiles, declares mcpServers entry.
  - Optional: shell out to `claude mcp list` (best-effort) to see
    what the host actually loaded.

Pure stdlib + subprocess. Returns structured result; CLI emits JSON.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_MARKETPLACE = _REPO / ".claude-plugin" / "marketplace.json"


@dataclass
class CheckResult:
    plugin: str
    source: str
    plugin_json_ok: bool = False
    server_present: bool = False
    server_compiles: bool = False
    mcp_json_ok: bool = False
    issues: list[str] = field(default_factory=list)

    def healthy(self) -> bool:
        return (
            self.plugin_json_ok
            and (self.server_present and self.server_compiles)
            == self.server_present  # MCP plugins must compile if they have a server
            and not self.issues
        )


def _check_plugin(entry: dict) -> CheckResult:
    out = CheckResult(plugin=entry["name"], source=entry["source"])
    src = (_REPO / entry["source"]).resolve()
    if not src.exists():
        out.issues.append(f"source path missing: {src}")
        return out
    pj = src / ".claude-plugin" / "plugin.json"
    if not pj.exists():
        out.issues.append("plugin.json missing")
        return out
    try:
        pj_data = json.loads(pj.read_text())
    except json.JSONDecodeError as e:
        out.issues.append(f"plugin.json parse error: {e}")
        return out
    out.plugin_json_ok = True
    if pj_data.get("name") != entry["name"]:
        out.issues.append(
            f"name drift: marketplace={entry['name']!r} "
            f"plugin.json={pj_data.get('name')!r}"
        )
    if pj_data.get("version") != entry["version"]:
        out.issues.append(
            f"version drift: marketplace={entry['version']!r} "
            f"plugin.json={pj_data.get('version')!r}"
        )

    # MCP plugins: check server + .mcp.json
    server = src / "server" / "server.py"
    mcp_json = src / ".mcp.json"
    if server.exists():
        out.server_present = True
        # Try compiling the server (syntax check, no execution).
        try:
            compile(server.read_text(), str(server), "exec")
            out.server_compiles = True
        except SyntaxError as e:
            out.issues.append(f"server.py SyntaxError: {e}")
    if mcp_json.exists():
        try:
            cfg = json.loads(mcp_json.read_text())
            if not cfg.get("mcpServers"):
                out.issues.append(".mcp.json has no mcpServers")
            else:
                out.mcp_json_ok = True
        except json.JSONDecodeError as e:
            out.issues.append(f".mcp.json parse error: {e}")
    elif server.exists():
        out.issues.append(".mcp.json missing for plugin with server")
    return out


def claude_mcp_list() -> dict:
    """Best-effort: shell out to `claude mcp list` if available."""
    if not shutil.which("claude"):
        return {"available": False, "reason": "`claude` CLI not on PATH"}
    try:
        r = subprocess.run(
            ["claude", "mcp", "list"],
            capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        return {"available": False, "reason": str(e)}
    return {
        "available": True,
        "returncode": r.returncode,
        "stdout": r.stdout,
        "stderr": r.stderr,
    }


def run_checks(*, with_mcp_list: bool = False) -> dict:
    if not _MARKETPLACE.exists():
        return {"ok": False, "error": "marketplace.json missing"}
    market = json.loads(_MARKETPLACE.read_text())
    results: list[CheckResult] = []
    for entry in market.get("plugins", []):
        results.append(_check_plugin(entry))
    payload = {
        "ok": all(r.healthy() for r in results),
        "n_plugins": len(results),
        "n_healthy": sum(1 for r in results if r.healthy()),
        "results": [
            {
                "plugin": r.plugin,
                "source": r.source,
                "plugin_json_ok": r.plugin_json_ok,
                "server_present": r.server_present,
                "server_compiles": r.server_compiles,
                "mcp_json_ok": r.mcp_json_ok,
                "issues": r.issues,
                "healthy": r.healthy(),
            }
            for r in results
        ],
    }
    if with_mcp_list:
        payload["claude_mcp_list"] = claude_mcp_list()
    return payload


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(
        prog="install_check",
        description="Verify Coscientist plugins + MCPs (v0.81).",
    )
    p.add_argument("--with-mcp-list", action="store_true",
                   help="Also shell out to `claude mcp list` (best-effort)")
    args = p.parse_args(argv)
    payload = run_checks(with_mcp_list=args.with_mcp_list)
    print(json.dumps(payload, indent=2))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

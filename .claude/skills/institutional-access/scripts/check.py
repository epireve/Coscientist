#!/usr/bin/env python3
"""institutional-access: dry-run health check for adapters + session.

Validates the harness without burning a real fetch. Reports:
- Adapter modules: import OK, exposes async fetch_pdf, declares DOMAIN
- Playwright availability
- storage_state.json: exists, age, cookie count
- Per-adapter rate-limit configuration

Run before any real institutional fetch dogfood.
"""
from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

STATE_FILE = _HERE.parent / "state" / "storage_state.json"


def _check_adapter(name: str) -> dict:
    """Validate a single adapter module."""
    out = {"name": name, "ok": False, "errors": []}
    sys.path.insert(0, str(_HERE))
    try:
        mod = __import__(f"adapters.{name}", fromlist=[name])
    except ImportError as e:
        out["errors"].append(f"import failed: {e}")
        return out

    if not hasattr(mod, "DOMAIN"):
        out["errors"].append("missing DOMAIN constant")
    else:
        out["domain"] = mod.DOMAIN

    if not hasattr(mod, "fetch_pdf"):
        out["errors"].append("missing fetch_pdf")
    else:
        fn = mod.fetch_pdf
        if not asyncio.iscoroutinefunction(fn):
            out["errors"].append("fetch_pdf is not async")
        else:
            sig = inspect.signature(fn)
            params = list(sig.parameters.keys())
            if params != ["context", "doi", "out_path"]:
                out["errors"].append(
                    f"fetch_pdf signature mismatch: got {params!r}, "
                    f"expected ['context', 'doi', 'out_path']"
                )

    out["ok"] = not out["errors"]
    return out


def _check_playwright() -> dict:
    try:
        import playwright  # noqa: F401
        from playwright.async_api import async_playwright  # noqa: F401
        return {"installed": True}
    except ImportError as e:
        return {"installed": False, "error": str(e)}


def _check_storage_state() -> dict:
    if not STATE_FILE.exists():
        return {
            "present": False,
            "path": str(STATE_FILE),
            "remediation": "Run login.py to create one.",
        }
    try:
        data = json.loads(STATE_FILE.read_text())
    except (OSError, json.JSONDecodeError) as e:
        return {
            "present": True,
            "path": str(STATE_FILE),
            "valid_json": False,
            "error": str(e),
        }
    cookies = data.get("cookies") or []
    mtime = datetime.fromtimestamp(STATE_FILE.stat().st_mtime, tz=UTC)
    now = datetime.now(UTC)
    age_hours = (now - mtime).total_seconds() / 3600.0
    return {
        "present": True,
        "valid_json": True,
        "path": str(STATE_FILE),
        "cookie_count": len(cookies),
        "modified_at": mtime.isoformat(),
        "age_hours": round(age_hours, 2),
        "stale": age_hours > 24 * 14,  # OpenAthens cookies typically <14d
    }


def _check_registry() -> dict:
    """Read adapters/__init__.py registry mapping."""
    sys.path.insert(0, str(_HERE))
    try:
        from adapters import registry  # type: ignore
    except ImportError as e:
        return {"error": f"registry import failed: {e}"}
    return {"prefixes": sorted(registry.keys()),
            "count": len(registry)}


def cmd_check(args: argparse.Namespace) -> None:
    adapters_dir = _HERE / "adapters"
    names = sorted(
        p.stem for p in adapters_dir.glob("*.py")
        if p.stem not in ("__init__", "_common")
    )

    adapter_results = [_check_adapter(n) for n in names]
    pw = _check_playwright()
    state = _check_storage_state()
    registry = _check_registry()

    all_adapters_ok = all(a["ok"] for a in adapter_results)
    ready = (
        all_adapters_ok
        and pw["installed"]
        and state.get("present", False)
        and state.get("valid_json", False)
    )

    out = {
        "ready": ready,
        "playwright": pw,
        "storage_state": state,
        "registry": registry,
        "adapters": adapter_results,
        "summary": {
            "adapter_count": len(adapter_results),
            "adapters_ok": sum(1 for a in adapter_results if a["ok"]),
            "adapters_failing": [a["name"] for a in adapter_results if not a["ok"]],
        },
    }
    print(json.dumps(out, indent=2))
    if not ready:
        sys.exit(1)


def main() -> None:
    p = argparse.ArgumentParser(
        description="Dry-run health check for institutional-access."
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    pc = sub.add_parser("check")
    pc.set_defaults(func=cmd_check)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

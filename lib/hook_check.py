"""v0.136 — detect missing pre-commit hook installation.

Read-only check that `.git/hooks/pre-commit` symlinks to
`scripts/pre-commit`. Surface install hint when missing.

CLI:
    uv run python -m lib.hook_check
        # → exit 0 installed, exit 1 missing/wrong
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def check() -> dict:
    """Return install state of the pre-commit hook.

    Shape:
      {ok, hook_path, target, expected, message, action}
    """
    root = _repo_root()
    hook = root / ".git" / "hooks" / "pre-commit"
    expected_src = "../../scripts/pre-commit"
    out: dict = {
        "ok": False,
        "hook_path": str(hook),
        "target": None,
        "expected": expected_src,
        "message": "",
        "action": "scripts/install_hooks.sh",
    }
    if not (root / ".git").exists():
        out["ok"] = True
        out["message"] = "not a git repo (skipped)"
        return out
    # Check is_symlink BEFORE exists — broken symlinks fail
    # exists() but indicate misinstall, not absence.
    if hook.is_symlink():
        target = os.readlink(hook)
        out["target"] = target
        if target == expected_src:
            if not hook.exists():
                out["message"] = (
                    f"symlink target broken: {target!r} doesn't "
                    f"resolve. Rerun scripts/install_hooks.sh."
                )
                return out
            out["ok"] = True
            out["message"] = "installed correctly"
            return out
        out["message"] = (
            f"symlink points to {target!r}, expected "
            f"{expected_src!r}; rerun scripts/install_hooks.sh"
        )
        return out
    if not hook.exists():
        out["message"] = (
            "pre-commit hook not installed; run "
            "scripts/install_hooks.sh once"
        )
        return out
    # Regular file (not a symlink) — could be sample or custom.
    out["message"] = (
        "pre-commit exists but is not a symlink; either custom "
        "or stale. Run scripts/install_hooks.sh to replace."
    )
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="hook_check",
        description="v0.136 — verify pre-commit hook install.",
    )
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)
    r = check()
    if not args.quiet:
        mark = "✅" if r["ok"] else "⚠️"
        sys.stdout.write(
            f"{mark} {r['message']}\n"
        )
        if not r["ok"]:
            sys.stdout.write(f"   action: {r['action']}\n")
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

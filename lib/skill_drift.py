"""v0.185 — universal SKILL.md vs script CLI drift detector.

Auto-discovers every `.claude/skills/<skill>/scripts/*.py`, runs
`--help` on it (and on each subcommand if argparse uses subparsers),
extracts `--flag` patterns, and audits whether SKILL.md mentions
each non-trivial flag. Best-effort — never crashes on a single
broken script.

Pure stdlib. Subprocess timeout 20s per script.

CLI:
    uv run python -m lib.skill_drift [--format json|text]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable

_REPO = Path(__file__).resolve().parents[1]
_SKILLS_DIR = _REPO / ".claude" / "skills"

# Universal flags too common to require per-SKILL.md mention.
_TRIVIAL_FLAGS = frozenset({
    "--help", "-h", "--version",
    "--format", "--project-id", "--canonical-id",
    "--manuscript-id", "--paper-id", "--run-id", "--paths",
})

_FLAG_RE = re.compile(r"(--[a-z][a-z0-9\-]+)")
_USAGE_SUBCMD_RE = re.compile(r"\{([a-z0-9_\-,]+)\}")
_HELP_TIMEOUT = 20


def discover_skill_scripts() -> list[tuple[str, Path]]:
    """Walk .claude/skills/*/scripts/*.py. Skip __pycache__ + dunders."""
    out: list[tuple[str, Path]] = []
    if not _SKILLS_DIR.is_dir():
        return out
    for skill_dir in sorted(_SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        scripts_dir = skill_dir / "scripts"
        if not scripts_dir.is_dir():
            continue
        for py in sorted(scripts_dir.glob("*.py")):
            if py.name.startswith("_"):
                continue
            out.append((skill_dir.name, py))
    return out


def _run_help(script_path: Path, subcmd: str | None = None) -> str | None:
    """Run `python <script> [subcmd] --help`. Return stdout or None on error."""
    cmd = [sys.executable, str(script_path)]
    if subcmd:
        cmd.append(subcmd)
    cmd.append("--help")
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True,
            cwd=str(_REPO), timeout=_HELP_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if r.returncode != 0:
        return None
    return r.stdout or ""


def _parse_subcommands(help_text: str) -> list[str]:
    """Extract `{a,b,c}` subcommand list from argparse usage line."""
    if not help_text:
        return []
    # Scan only first ~5 lines (usage line is at top)
    head = "\n".join(help_text.splitlines()[:6])
    m = _USAGE_SUBCMD_RE.search(head)
    if not m:
        return []
    raw = m.group(1)
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    # Filter false positives (numeric, single-char)
    return [p for p in parts if len(p) >= 2 and not p.isdigit()]


def _parse_flags(help_text: str) -> set[str]:
    if not help_text:
        return set()
    return set(_FLAG_RE.findall(help_text))


def extract_argparse_flags(script_path: Path) -> list[str]:
    """Return sorted unique non-trivial flags across the script's CLI surface.

    Recurses into subcommands when argparse usage shows `{a,b,c}`.
    """
    top = _run_help(script_path)
    if top is None:
        return []
    flags = _parse_flags(top)
    for sub in _parse_subcommands(top):
        sub_help = _run_help(script_path, sub)
        if sub_help:
            flags |= _parse_flags(sub_help)
    flags -= _TRIVIAL_FLAGS
    return sorted(flags)


def extract_subcommands(script_path: Path) -> list[str]:
    top = _run_help(script_path)
    if top is None:
        return []
    return sorted(set(_parse_subcommands(top)))


def _load_allowlist(skill_dir: Path) -> set[str]:
    p = skill_dir / ".drift-allowlist.json"
    if not p.is_file():
        return set()
    try:
        data = json.loads(p.read_text())
        return set(data.get("undocumented_flags", []))
    except (OSError, json.JSONDecodeError):
        return set()


def audit_skill(skill_dir: Path, script_path: Path) -> dict:
    """Audit one (skill, script) pair.

    Returns dict with keys: skill, script, flags_in_help, flags_in_md,
    missing_in_md, missing_in_help, ok.
    """
    skill_name = skill_dir.name
    try:
        rel_script = str(script_path.relative_to(_REPO))
    except ValueError:
        rel_script = str(script_path)
    flags_in_help = extract_argparse_flags(script_path)
    allowlist = _load_allowlist(skill_dir)

    skill_md = skill_dir / "SKILL.md"
    body = skill_md.read_text() if skill_md.is_file() else ""

    flags_in_md: list[str] = []
    missing_in_md: list[str] = []
    for flag in flags_in_help:
        if flag in body:
            flags_in_md.append(flag)
        elif flag in allowlist:
            flags_in_md.append(flag)  # silenced
        else:
            missing_in_md.append(flag)

    # Reverse direction: flags mentioned in MD but not in --help.
    # Best-effort — only catch flags formatted as `--foo` in MD.
    md_flags = set(_FLAG_RE.findall(body)) - _TRIVIAL_FLAGS
    help_set = set(flags_in_help)
    # Filter out flags that aren't this script's responsibility (cross-skill mentions are common).
    # Heuristic: only flag missing_in_help if MD references it AND it's not in help AND it's not allowlisted.
    missing_in_help = sorted(md_flags - help_set - allowlist) if help_set else []

    return {
        "skill": skill_name,
        "script": rel_script,
        "flags_in_help": flags_in_help,
        "flags_in_md": sorted(flags_in_md),
        "missing_in_md": sorted(missing_in_md),
        "missing_in_help": missing_in_help,
        "ok": not missing_in_md,
    }


def audit_all() -> list[dict]:
    out: list[dict] = []
    for skill_name, script_path in discover_skill_scripts():
        skill_dir = _SKILLS_DIR / skill_name
        try:
            out.append(audit_skill(skill_dir, script_path))
        except Exception as e:  # best-effort
            try:
                rel = str(script_path.relative_to(_REPO))
            except ValueError:
                rel = str(script_path)
            out.append({
                "skill": skill_name,
                "script": rel,
                "flags_in_help": [],
                "flags_in_md": [],
                "missing_in_md": [],
                "missing_in_help": [],
                "ok": True,
                "error": f"{type(e).__name__}: {e}",
            })
    return out


def _render_text(report: list[dict]) -> str:
    lines: list[str] = []
    total = len(report)
    drift = [r for r in report if r["missing_in_md"]]
    lines.append(f"# SKILL.md drift report")
    lines.append("")
    lines.append(f"Audited: {total} (skill, script) pairs")
    lines.append(f"With drift: {len(drift)}")
    lines.append("")
    if drift:
        # Sort by drift count desc
        drift_sorted = sorted(drift, key=lambda r: -len(r["missing_in_md"]))
        lines.append("## Top offenders")
        lines.append("")
        for r in drift_sorted:
            miss = ", ".join(r["missing_in_md"])
            lines.append(f"- **{r['skill']}** (`{r['script']}`): {len(r['missing_in_md'])} undocumented — {miss}")
        lines.append("")
    lines.append("## All audits")
    lines.append("")
    for r in sorted(report, key=lambda x: x["skill"]):
        status = "OK" if r["ok"] else f"DRIFT ({len(r['missing_in_md'])})"
        lines.append(f"- {r['skill']} / {Path(r['script']).name}: {status}")
        if r.get("error"):
            lines.append(f"    error: {r['error']}")
        if r["missing_in_md"]:
            lines.append(f"    missing-in-md: {', '.join(r['missing_in_md'])}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Universal SKILL.md drift detector.")
    p.add_argument("--format", choices=["json", "text"], default="text")
    args = p.parse_args(argv)

    report = audit_all()
    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(_render_text(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

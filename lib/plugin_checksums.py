"""v0.85 — plugin file integrity manifest.

Generates / verifies SHA-256 checksums for every file under each
Coscientist plugin. Used to detect tampering between marketplace
publish and `/plugin install` on the user's machine.

Manifest format: `<plugin>/CHECKSUMS.txt` — one line per file:

    <sha256-hex>  <relative-path>

Standard `sha256sum -c CHECKSUMS.txt` works. Pure stdlib.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_PLUGINS_ROOT = _REPO / "plugin"

# Files NOT included in the manifest (build artifacts, the
# checksum file itself, generated caches).
_EXCLUDE_NAMES = {
    "CHECKSUMS.txt",
    "__pycache__",
    ".pyc",
    ".DS_Store",
    "dist",
    "build",
    "*.egg-info",
}


def _is_excluded(p: Path) -> bool:
    name = p.name
    if name in _EXCLUDE_NAMES:
        return True
    if name.endswith(".pyc"):
        return True
    # Anything under a __pycache__ directory anywhere in the path.
    return any(part in _EXCLUDE_NAMES for part in p.parts)


def _walk_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if _is_excluded(p.relative_to(root)):
            continue
        out.append(p)
    return out


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class ManifestEntry:
    sha256: str
    path: str  # relative to plugin root


def generate_manifest(plugin_dir: Path) -> list[ManifestEntry]:
    """Return one (sha256, relpath) per file under `plugin_dir`."""
    out: list[ManifestEntry] = []
    for f in _walk_files(plugin_dir):
        out.append(ManifestEntry(
            sha256=_sha256(f),
            path=str(f.relative_to(plugin_dir)),
        ))
    return out


def render_manifest(entries: list[ManifestEntry]) -> str:
    lines = []
    for e in sorted(entries, key=lambda x: x.path):
        lines.append(f"{e.sha256}  {e.path}")
    return "\n".join(lines) + "\n"


def write_manifest(plugin_dir: Path) -> Path:
    """Compute + write `<plugin>/CHECKSUMS.txt`."""
    manifest = generate_manifest(plugin_dir)
    out_path = plugin_dir / "CHECKSUMS.txt"
    out_path.write_text(render_manifest(manifest))
    return out_path


@dataclass
class VerifyResult:
    plugin: str
    ok: bool
    n_files: int
    n_mismatches: int
    n_missing: int
    n_extra: int
    issues: list[str] = field(default_factory=list)


def verify_manifest(plugin_dir: Path) -> VerifyResult:
    """Compare `<plugin>/CHECKSUMS.txt` against current files."""
    plugin_name = plugin_dir.name
    manifest_path = plugin_dir / "CHECKSUMS.txt"
    if not manifest_path.exists():
        return VerifyResult(
            plugin=plugin_name, ok=False, n_files=0, n_mismatches=0,
            n_missing=0, n_extra=0,
            issues=["CHECKSUMS.txt missing"],
        )
    declared: dict[str, str] = {}
    for line in manifest_path.read_text().splitlines():
        if not line.strip():
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        declared[parts[1]] = parts[0]
    actual = {
        str(f.relative_to(plugin_dir)): _sha256(f)
        for f in _walk_files(plugin_dir)
    }
    issues: list[str] = []
    n_mismatches = 0
    n_missing = 0
    n_extra = 0
    for path, decl_sha in declared.items():
        cur = actual.get(path)
        if cur is None:
            n_missing += 1
            issues.append(f"missing: {path}")
        elif cur != decl_sha:
            n_mismatches += 1
            issues.append(f"sha mismatch: {path}")
    for path in actual:
        if path not in declared:
            n_extra += 1
            issues.append(f"unmanifested: {path}")
    return VerifyResult(
        plugin=plugin_name,
        ok=(not issues),
        n_files=len(declared),
        n_mismatches=n_mismatches,
        n_missing=n_missing,
        n_extra=n_extra,
        issues=issues,
    )


def all_plugins() -> list[Path]:
    """Every directory under plugin/ with a .claude-plugin/plugin.json."""
    if not _PLUGINS_ROOT.exists():
        return []
    out: list[Path] = []
    for d in sorted(_PLUGINS_ROOT.iterdir()):
        if (d / ".claude-plugin" / "plugin.json").exists():
            out.append(d)
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(
        prog="plugin_checksums",
        description="Generate or verify plugin file checksums (v0.85).",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pg = sub.add_parser("generate",
                         help="Write CHECKSUMS.txt to every plugin")
    pg.add_argument("--plugin", default=None,
                    help="Only this plugin (default: all)")

    pv = sub.add_parser("verify",
                         help="Compare existing CHECKSUMS.txt vs files")
    pv.add_argument("--plugin", default=None)

    args = p.parse_args(argv)

    targets = all_plugins()
    if args.plugin:
        targets = [t for t in targets if t.name == args.plugin]
        if not targets:
            print(json.dumps({"error": f"plugin {args.plugin!r} not found"}))
            return 1

    if args.cmd == "generate":
        out = []
        for d in targets:
            path = write_manifest(d)
            out.append({"plugin": d.name, "manifest": str(path)})
        print(json.dumps({"ok": True, "generated": out}, indent=2))
        return 0
    else:  # verify
        results = []
        all_ok = True
        for d in targets:
            r = verify_manifest(d)
            results.append({
                "plugin": r.plugin,
                "ok": r.ok,
                "n_files": r.n_files,
                "n_mismatches": r.n_mismatches,
                "n_missing": r.n_missing,
                "n_extra": r.n_extra,
                "issues": r.issues[:10],  # truncate noise
            })
            if not r.ok:
                all_ok = False
        print(json.dumps({"ok": all_ok, "results": results}, indent=2))
        return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

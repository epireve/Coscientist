#!/usr/bin/env python3
"""dataset-agent: local dataset registry with hash tracking."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import cache_root  # noqa: E402

VALID_STATES = ("registered", "deposited", "versioned")
KNOWN_LICENSES = {
    "MIT", "Apache-2.0", "BSD-3-Clause", "BSD-2-Clause", "GPL-3.0", "LGPL-3.0",
    "CC0-1.0", "CC-BY-4.0", "CC-BY-SA-4.0", "CC-BY-NC-4.0", "CC-BY-ND-4.0",
    "CC-BY-NC-SA-4.0", "CC-BY-NC-ND-4.0",
    "proprietary", "restricted", "embargo",
}
LARGE_FILE_BYTES = 100 * 1024 * 1024  # 100 MB


def _slug(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "_", text)
    return text[:40].strip("_")


def make_dataset_id(title: str) -> str:
    h = hashlib.blake2s(title.encode(), digest_size=3).hexdigest()
    return f"{_slug(title)}_{h}"


def dataset_dir(dataset_id: str) -> Path:
    return cache_root() / "datasets" / dataset_id


def _load_manifest(dataset_id: str) -> dict:
    p = dataset_dir(dataset_id) / "manifest.json"
    if not p.exists():
        raise FileNotFoundError(f"dataset {dataset_id!r} not found")
    return json.loads(p.read_text())


def _load_record(dataset_id: str) -> dict:
    p = dataset_dir(dataset_id) / "dataset.json"
    if not p.exists():
        raise FileNotFoundError(f"dataset record not found for {dataset_id!r}")
    return json.loads(p.read_text())


def _load_versions(dataset_id: str) -> list:
    p = dataset_dir(dataset_id) / "versions.json"
    if not p.exists():
        return []
    return json.loads(p.read_text())


def _save_manifest(dataset_id: str, manifest: dict) -> None:
    manifest["updated_at"] = datetime.now(UTC).isoformat()
    (dataset_dir(dataset_id) / "manifest.json").write_text(
        json.dumps(manifest, indent=2)
    )


def _save_record(dataset_id: str, record: dict) -> None:
    (dataset_dir(dataset_id) / "dataset.json").write_text(
        json.dumps(record, indent=2)
    )


def _save_versions(dataset_id: str, versions: list) -> None:
    (dataset_dir(dataset_id) / "versions.json").write_text(
        json.dumps(versions, indent=2)
    )


def _hash_file(path: Path, algorithm: str = "sha256",
               force_large: bool = False) -> tuple[str | None, int, str | None]:
    """Return (hex_digest, byte_size, error_or_None)."""
    if not path.exists():
        return None, 0, f"file not found: {path}"
    if not path.is_file():
        return None, 0, f"not a regular file: {path}"
    size = path.stat().st_size
    if size > LARGE_FILE_BYTES and not force_large:
        return None, size, f"file >{LARGE_FILE_BYTES} bytes; use --force-large"

    h = hashlib.new(algorithm)
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest(), size, None


def _combined_hash(per_file: dict, algorithm: str) -> str:
    """Manifest-level hash: hash of sorted (relpath, file_hash) pairs."""
    h = hashlib.new(algorithm)
    for k in sorted(per_file):
        digest = per_file[k].get("hash") or ""
        h.update(k.encode())
        h.update(b"\0")
        h.update(digest.encode())
        h.update(b"\n")
    return h.hexdigest()


def _register_in_project(project_id: str, dataset_id: str, state: str) -> None:
    try:
        from lib.project import register_artifact
        register_artifact(
            project_id=project_id,
            artifact_id=dataset_id,
            kind="dataset",
            state=state,
            path=dataset_dir(dataset_id),
        )
    except Exception as e:
        print(json.dumps({"warning": f"could not register: {e}"}), file=sys.stderr)


def cmd_register(args: argparse.Namespace) -> None:
    if not args.title.strip():
        raise SystemExit("--title must be non-empty")
    if not args.description.strip():
        raise SystemExit("--description must be non-empty")
    if not args.license.strip():
        raise SystemExit("--license must be non-empty")

    dataset_id = make_dataset_id(args.title)
    dd = dataset_dir(dataset_id)
    if (dd / "manifest.json").exists() and not args.force:
        raise SystemExit(f"dataset {dataset_id!r} already exists. Use --force.")
    dd.mkdir(parents=True, exist_ok=True)

    license_warnings = []
    if args.license not in KNOWN_LICENSES:
        license_warnings.append(
            f"license {args.license!r} not in known list — review before deposit"
        )

    now = datetime.now(UTC).isoformat()
    manifest = {
        "artifact_id": dataset_id,
        "kind": "dataset",
        "state": "registered",
        "project_id": args.project_id,
        "created_at": now,
        "updated_at": now,
    }
    record = {
        "dataset_id": dataset_id,
        "title": args.title,
        "description": args.description,
        "license": args.license,
        "license_warnings": license_warnings,
        "source_url": args.source_url,
        "doi": args.doi,
        "paths": list(args.paths or []),
        "hashes": {},
        "registered_at": now,
        "project_id": args.project_id,
    }
    _save_manifest(dataset_id, manifest)
    _save_record(dataset_id, record)
    _save_versions(dataset_id, [])

    if args.project_id:
        _register_in_project(args.project_id, dataset_id, "registered")

    print(json.dumps({
        "dataset_id": dataset_id,
        "state": "registered",
        "license_warnings": license_warnings,
        "path": str(dd),
    }, indent=2))


def cmd_hash(args: argparse.Namespace) -> None:
    record = _load_record(args.dataset_id)
    paths = record.get("paths") or []
    if not paths:
        raise SystemExit(f"dataset {args.dataset_id!r} has no paths to hash")

    algorithm = args.algorithm
    per_file: dict = {}
    errors = []

    for path_str in paths:
        path = Path(path_str)
        if path.is_dir():
            files = sorted(p for p in path.rglob("*") if p.is_file())
        elif path.is_file():
            files = [path]
        else:
            errors.append(f"missing path: {path_str}")
            continue
        for f in files:
            digest, size, err = _hash_file(f, algorithm, args.force_large)
            rel = str(f)
            if err:
                errors.append(f"{rel}: {err}")
                per_file[rel] = {"hash": None, "size": size, "error": err}
            else:
                per_file[rel] = {"hash": digest, "size": size}

    combined = _combined_hash(per_file, algorithm)
    record["hashes"] = {
        "algorithm": algorithm,
        "per_file": per_file,
        "combined": combined,
        "computed_at": datetime.now(UTC).isoformat(),
        "errors": errors,
    }
    _save_record(args.dataset_id, record)

    print(json.dumps({
        "dataset_id": args.dataset_id,
        "algorithm": algorithm,
        "files_hashed": sum(1 for v in per_file.values() if v.get("hash")),
        "total_files": len(per_file),
        "combined_hash": combined,
        "errors": errors,
    }, indent=2))


def cmd_version(args: argparse.Namespace) -> None:
    if not args.label.strip():
        raise SystemExit("--label must be non-empty")
    versions = _load_versions(args.dataset_id)
    if any(v["label"] == args.label for v in versions):
        raise SystemExit(f"version {args.label!r} already exists")

    record = _load_record(args.dataset_id)
    versions.append({
        "label": args.label,
        "registered_at": datetime.now(UTC).isoformat(),
        "hashes": record.get("hashes", {}),
        "notes": args.notes or "",
    })
    _save_versions(args.dataset_id, versions)

    manifest = _load_manifest(args.dataset_id)
    manifest["state"] = "versioned"
    _save_manifest(args.dataset_id, manifest)

    if manifest.get("project_id"):
        _register_in_project(manifest["project_id"], args.dataset_id, "versioned")

    print(json.dumps({
        "dataset_id": args.dataset_id,
        "label": args.label,
        "version_count": len(versions),
        "state": "versioned",
    }, indent=2))


def cmd_status(args: argparse.Namespace) -> None:
    record = _load_record(args.dataset_id)
    manifest = _load_manifest(args.dataset_id)
    versions = _load_versions(args.dataset_id)
    print(json.dumps({
        "dataset_id": args.dataset_id,
        "title": record.get("title"),
        "state": manifest.get("state"),
        "license": record.get("license"),
        "license_warnings": record.get("license_warnings", []),
        "doi": record.get("doi"),
        "paths_count": len(record.get("paths", [])),
        "version_count": len(versions),
        "has_hashes": bool(record.get("hashes", {}).get("combined")),
        "project_id": manifest.get("project_id"),
    }, indent=2))


def cmd_list(args: argparse.Namespace) -> None:
    base = cache_root() / "datasets"
    if not base.exists():
        print(json.dumps({"datasets": [], "total": 0}))
        return
    out = []
    for sub in sorted(base.iterdir()):
        manifest_p = sub / "manifest.json"
        record_p = sub / "dataset.json"
        if not (manifest_p.exists() and record_p.exists()):
            continue
        manifest = json.loads(manifest_p.read_text())
        record = json.loads(record_p.read_text())
        if args.project_id and manifest.get("project_id") != args.project_id:
            continue
        if args.state and manifest.get("state") != args.state:
            continue
        out.append({
            "dataset_id": manifest.get("artifact_id"),
            "title": record.get("title"),
            "state": manifest.get("state"),
            "license": record.get("license"),
            "doi": record.get("doi"),
        })
    print(json.dumps({"datasets": out, "total": len(out)}, indent=2))


def main() -> None:
    p = argparse.ArgumentParser(description="Dataset registry + integrity tracking.")
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("register")
    pr.add_argument("--title", required=True)
    pr.add_argument("--description", required=True)
    pr.add_argument("--license", required=True)
    pr.add_argument("--source-url", default=None)
    pr.add_argument("--doi", default=None)
    pr.add_argument("--paths", nargs="+", default=[])
    pr.add_argument("--project-id", default=None)
    pr.add_argument("--force", action="store_true", default=False)
    pr.set_defaults(func=cmd_register)

    ph = sub.add_parser("hash")
    ph.add_argument("--dataset-id", required=True)
    ph.add_argument("--algorithm", default="sha256", choices=["sha256", "blake2s", "sha512"])
    ph.add_argument("--force-large", action="store_true", default=False)
    ph.set_defaults(func=cmd_hash)

    pv = sub.add_parser("version")
    pv.add_argument("--dataset-id", required=True)
    pv.add_argument("--label", required=True)
    pv.add_argument("--notes", default=None)
    pv.set_defaults(func=cmd_version)

    pst = sub.add_parser("status")
    pst.add_argument("--dataset-id", required=True)
    pst.set_defaults(func=cmd_status)

    pl = sub.add_parser("list")
    pl.add_argument("--project-id", default=None)
    pl.add_argument("--state", default=None, choices=VALID_STATES)
    pl.set_defaults(func=cmd_list)

    args = p.parse_args()
    try:
        args.func(args)
    except (FileNotFoundError, ValueError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

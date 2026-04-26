#!/usr/bin/env python3
"""zenodo-deposit: bridge dataset-agent → Zenodo REST API."""
from __future__ import annotations

import argparse, json, os, sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import cache_root  # noqa: E402

ZENODO_PROD = "https://zenodo.org"
ZENODO_SANDBOX = "https://sandbox.zenodo.org"


def _dataset_dir(dataset_id: str) -> Path:
    return cache_root() / "datasets" / dataset_id


def _load_dataset(dataset_id: str) -> tuple[dict, dict]:
    dd = _dataset_dir(dataset_id)
    mp = dd / "manifest.json"
    rp = dd / "dataset.json"
    if not mp.exists() or not rp.exists():
        raise FileNotFoundError(f"dataset {dataset_id!r} not found (run dataset-agent register first)")
    return json.loads(mp.read_text()), json.loads(rp.read_text())


def _build_metadata(record: dict) -> dict:
    """Build Zenodo deposition metadata payload."""
    license_map = {
        "MIT": "MIT", "Apache-2.0": "Apache-2.0", "BSD-3-Clause": "BSD-3-Clause",
        "CC0-1.0": "CC0-1.0", "CC-BY-4.0": "CC-BY-4.0",
        "CC-BY-SA-4.0": "CC-BY-SA-4.0",
    }
    lic = license_map.get(record.get("license"), "CC-BY-4.0")
    return {
        "metadata": {
            "title": record.get("title", "Untitled Dataset"),
            "upload_type": "dataset",
            "description": record.get("description", "(no description)"),
            "creators": [{"name": "Researcher (set via skill)"}],
            "license": lic,
            "access_right": "open",
        }
    }


def _validate(record: dict) -> list[str]:
    errors = []
    if not record.get("title"):
        errors.append("missing title")
    if not record.get("description"):
        errors.append("missing description")
    if not record.get("license"):
        errors.append("missing license")
    if not record.get("paths"):
        errors.append("no paths to upload")
    if not record.get("hashes", {}).get("combined"):
        errors.append("hashes not computed (run `dataset-agent hash` first)")
    return errors


def cmd_prepare(args: argparse.Namespace) -> None:
    manifest, record = _load_dataset(args.dataset_id)
    errors = _validate(record)
    metadata = _build_metadata(record)
    out_path = _dataset_dir(args.dataset_id) / "zenodo_metadata.json"
    out_path.write_text(json.dumps(metadata, indent=2))
    print(json.dumps({
        "dataset_id": args.dataset_id,
        "metadata_path": str(out_path),
        "validation_errors": errors,
        "ready_to_upload": not errors,
        "metadata": metadata,
    }, indent=2))


def cmd_upload(args: argparse.Namespace) -> None:
    manifest, record = _load_dataset(args.dataset_id)
    errors = _validate(record)
    if errors:
        raise SystemExit(f"validation failed: {errors}")

    token_var = "ZENODO_SANDBOX_TOKEN" if args.sandbox else "ZENODO_TOKEN"
    token = os.environ.get(token_var)
    if not token:
        raise SystemExit(f"missing env var: ${token_var}")

    base = ZENODO_SANDBOX if args.sandbox else ZENODO_PROD

    # Real API calls. Import at use-time so the prepare command works without urllib edge-cases
    import urllib.request as _ur
    import urllib.error as _ue

    metadata = _build_metadata(record)
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}

    # Step 1: create deposition
    create_url = urljoin(base, "/api/deposit/depositions")
    req = _ur.Request(
        create_url,
        data=json.dumps({}).encode(),
        method="POST",
        headers=headers,
    )
    try:
        with _ur.urlopen(req, timeout=30) as resp:
            deposit = json.loads(resp.read())
    except _ue.HTTPError as e:
        raise SystemExit(f"Zenodo create failed: {e.code} {e.read().decode(errors='ignore')}")

    deposit_id = deposit["id"]
    bucket_url = deposit["links"]["bucket"]

    # Step 2: upload files
    uploaded = []
    for path_str in record["paths"]:
        p = Path(path_str)
        if not p.is_file():
            continue
        with p.open("rb") as f:
            data = f.read()
        put_url = f"{bucket_url}/{p.name}"
        req = _ur.Request(
            put_url, data=data, method="PUT",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/octet-stream"},
        )
        try:
            with _ur.urlopen(req, timeout=120) as resp:
                uploaded.append({"name": p.name, "status": resp.status})
        except _ue.HTTPError as e:
            uploaded.append({"name": p.name, "status": e.code, "error": e.read().decode(errors='ignore')})

    # Step 3: set metadata
    meta_url = f"{create_url}/{deposit_id}"
    req = _ur.Request(
        meta_url, data=json.dumps(metadata).encode(),
        method="PUT", headers=headers,
    )
    try:
        with _ur.urlopen(req, timeout=30) as resp:
            json.loads(resp.read())
    except _ue.HTTPError as e:
        raise SystemExit(f"Zenodo metadata update failed: {e.code} {e.read().decode(errors='ignore')}")

    # Step 4: publish
    publish_url = f"{create_url}/{deposit_id}/actions/publish"
    req = _ur.Request(publish_url, method="POST", headers=headers, data=b"")
    try:
        with _ur.urlopen(req, timeout=60) as resp:
            published = json.loads(resp.read())
    except _ue.HTTPError as e:
        raise SystemExit(f"Zenodo publish failed: {e.code} {e.read().decode(errors='ignore')}")

    doi = published.get("doi") or published.get("metadata", {}).get("doi")

    # Persist response
    (_dataset_dir(args.dataset_id) / "zenodo_response.json").write_text(json.dumps(published, indent=2))

    # Update dataset state
    manifest["state"] = "deposited"
    manifest["updated_at"] = datetime.now(UTC).isoformat()
    record["doi"] = doi
    (_dataset_dir(args.dataset_id) / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (_dataset_dir(args.dataset_id) / "dataset.json").write_text(json.dumps(record, indent=2))

    print(json.dumps({
        "dataset_id": args.dataset_id,
        "deposit_id": deposit_id,
        "doi": doi,
        "uploaded_files": uploaded,
        "sandbox": args.sandbox,
        "published_url": published.get("links", {}).get("record_html"),
    }, indent=2))


def cmd_status(args: argparse.Namespace) -> None:
    manifest, record = _load_dataset(args.dataset_id)
    print(json.dumps({
        "dataset_id": args.dataset_id,
        "state": manifest.get("state"),
        "doi": record.get("doi"),
        "has_zenodo_response": (_dataset_dir(args.dataset_id) / "zenodo_response.json").exists(),
    }, indent=2))


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("prepare")
    pp.add_argument("--dataset-id", required=True)
    pp.set_defaults(func=cmd_prepare)
    pu = sub.add_parser("upload")
    pu.add_argument("--dataset-id", required=True)
    pu.add_argument("--sandbox", action="store_true", default=False)
    pu.set_defaults(func=cmd_upload)
    ps = sub.add_parser("status")
    ps.add_argument("--dataset-id", required=True)
    ps.set_defaults(func=cmd_status)
    args = p.parse_args()
    try:
        args.func(args)
    except (FileNotFoundError, ValueError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

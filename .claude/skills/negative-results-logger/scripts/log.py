#!/usr/bin/env python3
"""negative-results-logger: log failed experiments / disconfirmed hypotheses as artifacts."""
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

VALID_STATES = ("logged", "analyzed", "shared")
VALID_SHARED_VIA = {"preprint", "blog", "talk", "github", "other"}


def _slug(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "_", text)
    return text[:40].strip("_")


def make_result_id(title: str) -> str:
    h = hashlib.blake2s(title.encode(), digest_size=3).hexdigest()
    return f"{_slug(title)}_{h}"


def result_dir(result_id: str) -> Path:
    return cache_root() / "negative_results" / result_id


def _load_manifest(result_id: str) -> dict:
    p = result_dir(result_id) / "manifest.json"
    if not p.exists():
        raise FileNotFoundError(f"negative result {result_id!r} not found")
    return json.loads(p.read_text())


def _load_record(result_id: str) -> dict:
    p = result_dir(result_id) / "result.json"
    if not p.exists():
        raise FileNotFoundError(f"record not found for {result_id!r}")
    return json.loads(p.read_text())


def _save_manifest(result_id: str, manifest: dict) -> None:
    manifest["updated_at"] = datetime.now(UTC).isoformat()
    (result_dir(result_id) / "manifest.json").write_text(
        json.dumps(manifest, indent=2)
    )


def _save_record(result_id: str, record: dict) -> None:
    (result_dir(result_id) / "result.json").write_text(
        json.dumps(record, indent=2)
    )


def _register(project_id: str, result_id: str, state: str) -> None:
    """Register in project DB artifact_index. Best-effort."""
    try:
        from lib.project import register_artifact
        register_artifact(
            project_id=project_id,
            artifact_id=result_id,
            kind="negative-result",
            state=state,
            path=result_dir(result_id),
        )
    except Exception as e:
        print(json.dumps({"warning": f"could not register in project: {e}"}), file=sys.stderr)


def cmd_init(args: argparse.Namespace) -> None:
    for field in ("title", "hypothesis", "approach", "expected", "observed"):
        if not getattr(args, field, "").strip():
            raise SystemExit(f"--{field} must be non-empty")

    result_id = make_result_id(args.title)
    rd = result_dir(result_id)
    if (rd / "manifest.json").exists() and not args.force:
        raise SystemExit(f"negative result {result_id!r} already exists. Use --force.")
    rd.mkdir(parents=True, exist_ok=True)

    now = datetime.now(UTC).isoformat()
    manifest = {
        "artifact_id": result_id,
        "kind": "negative-result",
        "state": "logged",
        "project_id": args.project_id,
        "created_at": now,
        "updated_at": now,
    }
    record = {
        "result_id": result_id,
        "title": args.title,
        "hypothesis": args.hypothesis,
        "approach": args.approach,
        "expected": args.expected,
        "observed": args.observed,
        "state": "logged",
        "logged_at": now,
        "project_id": args.project_id,
    }
    _save_manifest(result_id, manifest)
    _save_record(result_id, record)

    if args.project_id:
        _register(args.project_id, result_id, "logged")

    print(json.dumps({
        "result_id": result_id,
        "state": "logged",
        "path": str(rd),
    }, indent=2))


def cmd_analyze(args: argparse.Namespace) -> None:
    if not args.root_cause.strip():
        raise SystemExit("--root-cause must be non-empty")
    if not args.lessons.strip():
        raise SystemExit("--lessons must be non-empty")

    record = _load_record(args.result_id)
    manifest = _load_manifest(args.result_id)
    record["root_cause"] = args.root_cause
    record["lessons"] = args.lessons
    record["analyzed_at"] = datetime.now(UTC).isoformat()
    record["state"] = "analyzed"
    manifest["state"] = "analyzed"

    _save_record(args.result_id, record)
    _save_manifest(args.result_id, manifest)

    if manifest.get("project_id"):
        _register(manifest["project_id"], args.result_id, "analyzed")

    print(json.dumps({
        "result_id": args.result_id,
        "state": "analyzed",
    }, indent=2))


def cmd_share(args: argparse.Namespace) -> None:
    if args.shared_via not in VALID_SHARED_VIA:
        raise SystemExit(
            f"--shared-via must be one of {sorted(VALID_SHARED_VIA)}; got {args.shared_via!r}"
        )

    record = _load_record(args.result_id)
    manifest = _load_manifest(args.result_id)
    if record.get("state") not in ("analyzed", "shared"):
        raise SystemExit(
            f"can only share an analyzed result; current state: {record.get('state')!r}"
        )

    record["shared_via"] = args.shared_via
    record["share_url"] = args.url or ""
    record["shared_at"] = datetime.now(UTC).isoformat()
    record["state"] = "shared"
    manifest["state"] = "shared"

    _save_record(args.result_id, record)
    _save_manifest(args.result_id, manifest)

    if manifest.get("project_id"):
        _register(manifest["project_id"], args.result_id, "shared")

    print(json.dumps({
        "result_id": args.result_id,
        "state": "shared",
        "shared_via": args.shared_via,
    }, indent=2))


def cmd_status(args: argparse.Namespace) -> None:
    record = _load_record(args.result_id)
    manifest = _load_manifest(args.result_id)
    print(json.dumps({
        "result_id": args.result_id,
        "title": record.get("title"),
        "state": manifest.get("state"),
        "project_id": manifest.get("project_id"),
        "logged_at": record.get("logged_at"),
        "analyzed_at": record.get("analyzed_at"),
        "shared_at": record.get("shared_at"),
    }, indent=2))


def cmd_list(args: argparse.Namespace) -> None:
    base = cache_root() / "negative_results"
    if not base.exists():
        print(json.dumps({"results": [], "total": 0}))
        return

    out = []
    for sub in sorted(base.iterdir()):
        manifest_p = sub / "manifest.json"
        record_p = sub / "result.json"
        if not (manifest_p.exists() and record_p.exists()):
            continue
        manifest = json.loads(manifest_p.read_text())
        record = json.loads(record_p.read_text())
        if args.project_id and manifest.get("project_id") != args.project_id:
            continue
        if args.state and manifest.get("state") != args.state:
            continue
        out.append({
            "result_id": manifest.get("artifact_id"),
            "title": record.get("title"),
            "state": manifest.get("state"),
            "project_id": manifest.get("project_id"),
            "logged_at": record.get("logged_at"),
        })
    print(json.dumps({"results": out, "total": len(out)}, indent=2))


def main() -> None:
    p = argparse.ArgumentParser(description="Log a negative research result.")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("init")
    pi.add_argument("--title", required=True)
    pi.add_argument("--hypothesis", required=True)
    pi.add_argument("--approach", required=True)
    pi.add_argument("--expected", required=True)
    pi.add_argument("--observed", required=True)
    pi.add_argument("--project-id", default=None)
    pi.add_argument("--force", action="store_true", default=False)
    pi.set_defaults(func=cmd_init)

    pa = sub.add_parser("analyze")
    pa.add_argument("--result-id", required=True)
    pa.add_argument("--root-cause", required=True)
    pa.add_argument("--lessons", required=True)
    pa.set_defaults(func=cmd_analyze)

    ps = sub.add_parser("share")
    ps.add_argument("--result-id", required=True)
    ps.add_argument("--shared-via", required=True)
    ps.add_argument("--url", default=None)
    ps.set_defaults(func=cmd_share)

    pst = sub.add_parser("status")
    pst.add_argument("--result-id", required=True)
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

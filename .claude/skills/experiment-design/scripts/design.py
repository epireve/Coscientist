#!/usr/bin/env python3
"""experiment-design: Karpathy-style experiment scaffold."""
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

VALID_STATES = ("designed", "preregistered", "running", "completed", "analyzed", "reproduced")
VALID_VAR_KINDS = {"independent", "dependent", "control"}
VALID_METRIC_TYPES = {"scalar", "rate", "count", "duration_seconds"}
VALID_COMPARISONS = {">", ">=", "<", "<=", "==", "!="}


def _slug(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "_", text)
    return text[:40].strip("_")


def make_experiment_id(title: str) -> str:
    h = hashlib.blake2s(title.encode(), digest_size=3).hexdigest()
    return f"{_slug(title)}_{h}"


def experiment_dir(eid: str) -> Path:
    return cache_root() / "experiments" / eid


def _load_manifest(eid: str) -> dict:
    p = experiment_dir(eid) / "manifest.json"
    if not p.exists():
        raise FileNotFoundError(f"experiment {eid!r} not found")
    return json.loads(p.read_text())


def _load_protocol(eid: str) -> dict:
    p = experiment_dir(eid) / "protocol.json"
    if not p.exists():
        raise FileNotFoundError(f"protocol not found for {eid!r}")
    return json.loads(p.read_text())


def _save_manifest(eid: str, manifest: dict) -> None:
    manifest["updated_at"] = datetime.now(UTC).isoformat()
    (experiment_dir(eid) / "manifest.json").write_text(json.dumps(manifest, indent=2))


def _save_protocol(eid: str, protocol: dict) -> None:
    (experiment_dir(eid) / "protocol.json").write_text(json.dumps(protocol, indent=2))


def _register(project_id: str, eid: str, state: str) -> None:
    try:
        from lib.project import register_artifact
        register_artifact(
            project_id=project_id,
            artifact_id=eid,
            kind="experiment",
            state=state,
            path=experiment_dir(eid),
        )
    except Exception as e:
        print(json.dumps({"warning": f"could not register: {e}"}), file=sys.stderr)


def cmd_init(args: argparse.Namespace) -> None:
    if not args.title.strip():
        raise SystemExit("--title must be non-empty")
    if not args.hypothesis.strip():
        raise SystemExit("--hypothesis must be non-empty")
    if not args.falsifier.strip():
        raise SystemExit("--falsifier must be non-empty")
    if args.hypothesis.strip() == args.falsifier.strip():
        raise SystemExit("--hypothesis and --falsifier must differ")

    eid = make_experiment_id(args.title)
    d = experiment_dir(eid)
    if (d / "manifest.json").exists() and not args.force:
        raise SystemExit(f"experiment {eid!r} already exists. Use --force.")
    d.mkdir(parents=True, exist_ok=True)

    now = datetime.now(UTC).isoformat()
    manifest = {
        "artifact_id": eid,
        "kind": "experiment",
        "state": "designed",
        "project_id": args.project_id,
        "created_at": now,
        "updated_at": now,
    }
    protocol = {
        "experiment_id": eid,
        "title": args.title,
        "hypothesis": args.hypothesis,
        "falsifier": args.falsifier,
        "variables": {"independent": [], "dependent": [], "control": []},
        "primary_metric": None,
        "budget": {"compute_seconds": None, "memory_mb": None},
        "preregistration": None,
        "deviations": [],
        "created_at": now,
        "project_id": args.project_id,
    }
    _save_manifest(eid, manifest)
    _save_protocol(eid, protocol)

    if args.project_id:
        _register(args.project_id, eid, "designed")

    print(json.dumps({
        "experiment_id": eid,
        "state": "designed",
        "path": str(d),
    }, indent=2))


def cmd_variable(args: argparse.Namespace) -> None:
    if args.kind not in VALID_VAR_KINDS:
        raise SystemExit(f"--kind must be one of {sorted(VALID_VAR_KINDS)}")
    if not args.name.strip():
        raise SystemExit("--name must be non-empty")

    protocol = _load_protocol(args.experiment_id)
    bucket = protocol["variables"][args.kind]
    # Reject duplicate variable names within the same kind
    if any(v["name"] == args.name for v in bucket):
        raise SystemExit(f"variable {args.name!r} already exists under {args.kind!r}")
    bucket.append({"name": args.name, "description": args.description or ""})
    _save_protocol(args.experiment_id, protocol)

    print(json.dumps({
        "experiment_id": args.experiment_id,
        "kind": args.kind,
        "name": args.name,
        "total_in_kind": len(bucket),
    }, indent=2))


def cmd_metric(args: argparse.Namespace) -> None:
    if args.type not in VALID_METRIC_TYPES:
        raise SystemExit(f"--type must be one of {sorted(VALID_METRIC_TYPES)}")
    if args.comparison not in VALID_COMPARISONS:
        raise SystemExit(f"--comparison must be one of {sorted(VALID_COMPARISONS)}")
    if not args.name.strip():
        raise SystemExit("--name must be non-empty")

    protocol = _load_protocol(args.experiment_id)
    protocol["primary_metric"] = {
        "name": args.name,
        "type": args.type,
        "target": args.target,
        "comparison": args.comparison,
    }
    _save_protocol(args.experiment_id, protocol)

    print(json.dumps({
        "experiment_id": args.experiment_id,
        "primary_metric": protocol["primary_metric"],
        "replaced": True,  # always replaces — single metric discipline
    }, indent=2))


def _check_rr_state(rr_id: str) -> None:
    """Verify linked RR is in stage-1-drafted or later."""
    rr_path = cache_root() / "registered_reports" / rr_id / "manifest.json"
    if not rr_path.exists():
        raise SystemExit(f"linked RR {rr_id!r} not found")
    rr = json.loads(rr_path.read_text())
    if rr["state"] == "stage-1-drafted":
        return
    # Anything past stage-1-drafted is fine (already further along)
    valid_later = {"stage-1-submitted", "in-principle-accepted", "data-collected",
                   "stage-2-drafted", "stage-2-submitted", "published"}
    if rr["state"] not in valid_later:
        raise SystemExit(f"RR {rr_id!r} in unexpected state: {rr['state']}")


def cmd_preregister(args: argparse.Namespace) -> None:
    manifest = _load_manifest(args.experiment_id)
    protocol = _load_protocol(args.experiment_id)

    if manifest["state"] != "designed" and not args.force:
        raise SystemExit(
            f"experiment {args.experiment_id!r} is already in state {manifest['state']!r}. Use --force."
        )

    # Gates
    errors = []
    if not protocol.get("hypothesis", "").strip():
        errors.append("hypothesis is empty")
    if not protocol.get("falsifier", "").strip():
        errors.append("falsifier is empty")
    if protocol.get("hypothesis", "").strip() == protocol.get("falsifier", "").strip():
        errors.append("hypothesis and falsifier are identical")
    if len(protocol["variables"]["independent"]) < 1:
        errors.append("need ≥1 independent variable")
    if len(protocol["variables"]["dependent"]) < 1:
        errors.append("need ≥1 dependent variable")
    if not protocol.get("primary_metric"):
        errors.append("primary metric not set")
    if args.budget_seconds is None or args.budget_seconds <= 0:
        errors.append("--budget-seconds must be > 0")
    if args.memory_mb is None or args.memory_mb <= 0:
        errors.append("--memory-mb must be > 0")
    if errors:
        raise SystemExit(f"preregistration gate failed: {errors}")

    if args.rr_id:
        _check_rr_state(args.rr_id)

    now = datetime.now(UTC).isoformat()
    protocol["budget"] = {
        "compute_seconds": args.budget_seconds,
        "memory_mb": args.memory_mb,
    }

    # Build human-readable preregistration.md
    lines = [
        f"# Preregistration: {protocol['title']}",
        "",
        f"**Experiment ID:** `{args.experiment_id}`",
        f"**Preregistered at:** {now}",
    ]
    if args.rr_id:
        lines.append(f"**Linked Registered Report:** `{args.rr_id}`")
    lines += [
        "",
        "## Hypothesis",
        "",
        protocol["hypothesis"],
        "",
        "## Falsifier",
        "",
        protocol["falsifier"],
        "",
        "## Variables",
        "",
        "### Independent",
    ]
    for v in protocol["variables"]["independent"]:
        lines.append(f"- **{v['name']}**: {v['description']}")
    lines += ["", "### Dependent"]
    for v in protocol["variables"]["dependent"]:
        lines.append(f"- **{v['name']}**: {v['description']}")
    lines += ["", "### Control"]
    if protocol["variables"]["control"]:
        for v in protocol["variables"]["control"]:
            lines.append(f"- **{v['name']}**: {v['description']}")
    else:
        lines.append("- *(none specified)*")
    pm = protocol["primary_metric"]
    lines += [
        "",
        "## Primary Metric",
        "",
        f"- **Name:** {pm['name']}",
        f"- **Type:** {pm['type']}",
        f"- **Target:** {pm['comparison']} {pm['target']}",
        "",
        "## Compute Budget",
        "",
        f"- **Wall time:** {args.budget_seconds} seconds",
        f"- **Memory:** {args.memory_mb} MB",
    ]
    prereg_path = experiment_dir(args.experiment_id) / "preregistration.md"
    prereg_path.write_text("\n".join(lines))

    protocol["preregistration"] = {
        "preregistered_at": now,
        "rr_id": args.rr_id,
        "preregistration_path": str(prereg_path),
    }
    manifest["state"] = "preregistered"

    _save_protocol(args.experiment_id, protocol)
    _save_manifest(args.experiment_id, manifest)

    if manifest.get("project_id"):
        _register(manifest["project_id"], args.experiment_id, "preregistered")

    print(json.dumps({
        "experiment_id": args.experiment_id,
        "state": "preregistered",
        "preregistration_path": str(prereg_path),
        "linked_rr": args.rr_id,
    }, indent=2))


def cmd_status(args: argparse.Namespace) -> None:
    manifest = _load_manifest(args.experiment_id)
    protocol = _load_protocol(args.experiment_id)
    completeness = {
        "hypothesis_set": bool(protocol.get("hypothesis", "").strip()),
        "falsifier_set": bool(protocol.get("falsifier", "").strip()),
        "independent_count": len(protocol["variables"]["independent"]),
        "dependent_count": len(protocol["variables"]["dependent"]),
        "control_count": len(protocol["variables"]["control"]),
        "primary_metric_set": bool(protocol.get("primary_metric")),
        "budget_set": all(protocol.get("budget", {}).get(k)
                          for k in ("compute_seconds", "memory_mb")),
    }
    completeness["ready_to_preregister"] = (
        completeness["hypothesis_set"]
        and completeness["falsifier_set"]
        and completeness["independent_count"] >= 1
        and completeness["dependent_count"] >= 1
        and completeness["primary_metric_set"]
    )
    print(json.dumps({
        "experiment_id": args.experiment_id,
        "title": protocol["title"],
        "state": manifest["state"],
        "project_id": manifest.get("project_id"),
        "completeness": completeness,
        "preregistration": protocol.get("preregistration"),
    }, indent=2))


def cmd_list(args: argparse.Namespace) -> None:
    base = cache_root() / "experiments"
    if not base.exists():
        print(json.dumps({"experiments": [], "total": 0}))
        return
    out = []
    for sub in sorted(base.iterdir()):
        mp = sub / "manifest.json"
        pp = sub / "protocol.json"
        if not (mp.exists() and pp.exists()):
            continue
        manifest = json.loads(mp.read_text())
        protocol = json.loads(pp.read_text())
        if args.project_id and manifest.get("project_id") != args.project_id:
            continue
        if args.state and manifest.get("state") != args.state:
            continue
        out.append({
            "experiment_id": manifest["artifact_id"],
            "title": protocol["title"],
            "state": manifest["state"],
            "project_id": manifest.get("project_id"),
        })
    print(json.dumps({"experiments": out, "total": len(out)}, indent=2))


def main() -> None:
    p = argparse.ArgumentParser(description="Karpathy-style experiment design.")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("init")
    pi.add_argument("--title", required=True)
    pi.add_argument("--hypothesis", required=True)
    pi.add_argument("--falsifier", required=True)
    pi.add_argument("--project-id", default=None)
    pi.add_argument("--force", action="store_true", default=False)
    pi.set_defaults(func=cmd_init)

    pv = sub.add_parser("variable")
    pv.add_argument("--experiment-id", required=True)
    pv.add_argument("--kind", required=True, choices=sorted(VALID_VAR_KINDS))
    pv.add_argument("--name", required=True)
    pv.add_argument("--description", default="")
    pv.set_defaults(func=cmd_variable)

    pm = sub.add_parser("metric")
    pm.add_argument("--experiment-id", required=True)
    pm.add_argument("--name", required=True)
    pm.add_argument("--type", required=True, choices=sorted(VALID_METRIC_TYPES))
    pm.add_argument("--target", type=float, required=True)
    pm.add_argument("--comparison", required=True, choices=sorted(VALID_COMPARISONS))
    pm.set_defaults(func=cmd_metric)

    pp = sub.add_parser("preregister")
    pp.add_argument("--experiment-id", required=True)
    pp.add_argument("--rr-id", default=None)
    pp.add_argument("--budget-seconds", type=int, default=None)
    pp.add_argument("--memory-mb", type=int, default=None)
    pp.add_argument("--force", action="store_true", default=False)
    pp.set_defaults(func=cmd_preregister)

    ps = sub.add_parser("status")
    ps.add_argument("--experiment-id", required=True)
    ps.set_defaults(func=cmd_status)

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

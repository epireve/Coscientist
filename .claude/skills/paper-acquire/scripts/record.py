#!/usr/bin/env python3
"""paper-acquire: record a successful (or failed) acquisition attempt.

Writes the PDF into raw/, advances state, appends to the audit log.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import audit_log_path  # noqa: E402
from lib.paper_artifact import PaperArtifact, State  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--canonical-id", required=True)
    p.add_argument("--source", required=True, help="tier tag: arxiv|oa-fallback|zotero|institutional|scihub")
    p.add_argument("--pdf-path", help="absolute path to downloaded pdf")
    p.add_argument("--failed", action="store_true")
    p.add_argument("--detail", default="", help="free-form detail for audit log")
    args = p.parse_args()

    art = PaperArtifact(args.canonical_id)
    manifest = art.load_manifest()

    entry = {
        "at": datetime.now(UTC).isoformat(),
        "canonical_id": args.canonical_id,
        "doi": manifest.doi,
        "source": args.source,
        "action": "failed" if args.failed else "fetched",
        "detail": args.detail,
    }

    if args.failed:
        art.record_source_attempt(args.source, "failed", {"detail": args.detail})
    else:
        if not args.pdf_path:
            raise SystemExit("--pdf-path required on success")
        src = Path(args.pdf_path)
        if not src.exists():
            raise SystemExit(f"pdf not found: {src}")
        dst = art.raw_dir / f"{args.source}.pdf"
        shutil.copy2(src, dst)
        entry["pdf"] = str(dst)
        art.record_source_attempt(args.source, "ok", {"pdf": str(dst)})
        art.set_state(State.acquired)

    with audit_log_path().open("a") as f:
        f.write(json.dumps(entry) + "\n")

    print(json.dumps(entry))


if __name__ == "__main__":
    main()

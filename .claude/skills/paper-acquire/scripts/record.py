#!/usr/bin/env python3
"""paper-acquire: record a successful (or failed) acquisition attempt.

Writes the PDF into raw/, advances state, appends to the audit log.

v0.12.1: integrity check (magic bytes + min size) before accepting a PDF.
v0.14: artifact_lock around manifest mutations so concurrent
    paper-acquire / paper-triage runs against the same paper serialize.
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
from lib.lockfile import artifact_lock  # noqa: E402
from lib.paper_artifact import PaperArtifact, State  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--canonical-id", required=True)
    p.add_argument("--source", required=True,
                   help="tier tag: arxiv|oa-fallback|zotero|institutional|scihub")
    p.add_argument("--pdf-path", help="absolute path to downloaded pdf")
    p.add_argument("--failed", action="store_true")
    p.add_argument("--detail", default="", help="free-form detail for audit log")
    args = p.parse_args()

    art = PaperArtifact(args.canonical_id)

    # v0.14: serialize manifest writes against any other concurrent writer
    # for this paper (e.g. paper-triage running in parallel).
    with artifact_lock(art.root, timeout=30.0):
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
            art.record_source_attempt(args.source, "failed",
                                      {"detail": args.detail})
        else:
            if not args.pdf_path:
                raise SystemExit("--pdf-path required on success")
            src = Path(args.pdf_path)
            if not src.exists():
                raise SystemExit(f"pdf not found: {src}")
            # v0.12.1: integrity check — magic bytes + minimum size
            size = src.stat().st_size
            if size < 200:
                raise SystemExit(
                    f"file too small to be a real PDF ({size} bytes): {src}"
                )
            with src.open("rb") as fh:
                head = fh.read(8)
            if not head.startswith(b"%PDF-"):
                raise SystemExit(
                    f"file is not a PDF (magic bytes: {head[:5]!r}): {src}. "
                    "Likely a paywall HTML page or login redirect."
                )
            dst = art.raw_dir / f"{args.source}.pdf"
            shutil.copy2(src, dst)
            entry["pdf"] = str(dst)
            entry["bytes"] = size
            art.record_source_attempt(
                args.source, "ok",
                {"pdf": str(dst), "bytes": size},
            )
            art.set_state(State.acquired)

        with audit_log_path().open("a") as f:
            f.write(json.dumps(entry) + "\n")

    print(json.dumps(entry))


if __name__ == "__main__":
    main()

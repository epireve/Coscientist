#!/usr/bin/env python3
"""manuscript-ingest: copy a markdown draft into a manuscript artifact."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.artifact import ArtifactKind, ManuscriptArtifact  # noqa: E402


def _slugify(s: str) -> str:
    out: list[str] = []
    for ch in (s or "").lower():
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != "-":
            out.append("-")
    return "".join(out).strip("-")[:60] or "untitled"


def derive_manuscript_id(title: str, source_text: str) -> str:
    slug = _slugify(title)
    h = hashlib.blake2s(source_text.encode("utf-8"), digest_size=3).hexdigest()
    return f"{slug}_{h}"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--source", required=True, help="Path to manuscript .md file")
    p.add_argument("--title", required=True)
    p.add_argument("--project-id", default=None)
    args = p.parse_args()

    src = Path(args.source).expanduser().resolve()
    if not src.exists():
        raise SystemExit(f"source not found: {src}")
    if src.suffix.lower() not in (".md", ".markdown"):
        raise SystemExit(f"only markdown supported in this iteration; got {src.suffix}")

    text = src.read_text()
    if not text.strip():
        raise SystemExit("source is empty")

    mid = derive_manuscript_id(args.title, text)
    art = ManuscriptArtifact(mid)
    (art.root / "source.md").write_text(text)

    m = art.load_manifest()
    m.extras["title"] = args.title
    m.extras["source_path"] = str(src)
    m.extras["char_count"] = len(text)
    art.save_manifest(m)

    if args.project_id:
        # lib.project imports slugify — import lazily so the core ingest path
        # doesn't require it.
        from lib.project import register_artifact  # noqa: WPS433
        register_artifact(args.project_id, mid, ArtifactKind.manuscript.value,
                          "drafted", art.root)

    print(mid)


if __name__ == "__main__":
    main()

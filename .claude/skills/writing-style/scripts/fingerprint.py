#!/usr/bin/env python3
"""writing-style: extract a voice profile from N manuscripts.

Reads plain markdown files (no LLM calls) and aggregates lexical,
syntactic, and structural statistics. Writes to the project dir.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import cache_root  # noqa: E402

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
from _textstats import (  # noqa: E402
    british_or_american,
    first_person_rate,
    hedge_density,
    paragraph_length_stats,
    paragraphs,
    passive_voice_rate,
    sentence_length_stats,
    sentence_starters,
    sentences,
    signpost_phrases,
    top_terms,
    words,
)


def build_profile(sources: list[Path]) -> dict:
    combined_text_parts: list[str] = []
    all_sents: list[str] = []
    all_paras: list[str] = []
    for src in sources:
        if not src.exists():
            raise SystemExit(f"source not found: {src}")
        text = src.read_text()
        combined_text_parts.append(text)
        all_sents.extend(sentences(text))
        all_paras.extend(paragraphs(text))
    combined = "\n\n".join(combined_text_parts)
    word_list = words(combined)

    mean_sent, std_sent = sentence_length_stats(all_sents)
    mean_para, std_para = paragraph_length_stats(all_paras)

    return {
        "profile_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "sample_count": len(sources),
        "word_count": len(word_list),
        "sentence_count": len(all_sents),
        "paragraph_count": len(all_paras),
        "lexical": {
            "top_terms": top_terms(word_list, top_k=40),
            "hedge_density": round(hedge_density(all_sents), 4),
            "first_person_rate": round(first_person_rate(all_sents), 4),
            "british_american": british_or_american(combined),
            "sentence_starters": sentence_starters(all_sents, top_k=15),
        },
        "syntactic": {
            "avg_sentence_length": round(mean_sent, 2),
            "sentence_length_std": round(std_sent, 2),
            "passive_voice_rate": round(passive_voice_rate(all_sents), 4),
        },
        "structural": {
            "avg_paragraph_length_sentences": round(mean_para, 2),
            "paragraph_length_std": round(std_para, 2),
            "signpost_phrases": signpost_phrases(all_sents, top_k=15),
        },
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--project-id", required=True)
    p.add_argument("--sources", nargs="+", required=True,
                   help="Paths to prior manuscript .md files")
    p.add_argument("--out", default=None,
                   help="Override output path (default: project dir)")
    args = p.parse_args()

    sources = [Path(s).expanduser().resolve() for s in args.sources]
    profile = build_profile(sources)

    if args.out:
        out_path = Path(args.out)
    else:
        proj_dir = cache_root() / "projects" / args.project_id
        if not proj_dir.exists():
            raise SystemExit(f"no project dir at {proj_dir}")
        out_path = proj_dir / "style_profile.json"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(profile, indent=2))

    # Update projects.style_profile_path if the project DB exists
    proj_db = cache_root() / "projects" / args.project_id / "project.db"
    if proj_db.exists():
        con = sqlite3.connect(proj_db)
        with con:
            con.execute(
                "UPDATE projects SET style_profile_path=? WHERE project_id=?",
                (str(out_path), args.project_id),
            )
        con.close()

    print(f"{len(sources)} samples, {profile['word_count']} words → {out_path}")


if __name__ == "__main__":
    main()

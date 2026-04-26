#!/usr/bin/env python3
"""slide-draft: manuscript → slide deck via pandoc."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import cache_root  # noqa: E402

# ─────────────────────────────────────────────
# Style templates — section-to-slide mapping
# ─────────────────────────────────────────────

STYLE_TEMPLATES: dict[str, list[dict]] = {
    "standard": [
        {"title": "Title", "from_section": None, "type": "title"},
        {"title": "Motivation", "from_section": "Introduction", "type": "content"},
        {"title": "Background", "from_section": "Background", "type": "content"},
        {"title": "Approach", "from_section": "Methods", "type": "content"},
        {"title": "Method Details", "from_section": "Methods", "type": "content"},
        {"title": "Setup", "from_section": "Experiments", "type": "content"},
        {"title": "Main Results", "from_section": "Results", "type": "content"},
        {"title": "Ablations", "from_section": "Results", "type": "content"},
        {"title": "Comparison", "from_section": "Discussion", "type": "content"},
        {"title": "Limitations", "from_section": "Discussion", "type": "content"},
        {"title": "Future Work", "from_section": "Conclusion", "type": "content"},
        {"title": "Conclusion", "from_section": "Conclusion", "type": "content"},
        {"title": "Acknowledgements", "from_section": None, "type": "ack"},
        {"title": "Questions?", "from_section": None, "type": "qa"},
        {"title": "References", "from_section": "References", "type": "refs"},
    ],
    "short-talk": [
        {"title": "Title", "from_section": None, "type": "title"},
        {"title": "Problem", "from_section": "Introduction", "type": "content"},
        {"title": "Approach", "from_section": "Methods", "type": "content"},
        {"title": "Results", "from_section": "Results", "type": "content"},
        {"title": "Limitations", "from_section": "Discussion", "type": "content"},
        {"title": "Takeaway", "from_section": "Conclusion", "type": "content"},
        {"title": "Thanks", "from_section": None, "type": "ack"},
        {"title": "Questions?", "from_section": None, "type": "qa"},
    ],
    "long-talk": [
        {"title": "Title", "from_section": None, "type": "title"},
        {"title": "Roadmap", "from_section": None, "type": "outline"},
        {"title": "Motivation: Why this matters", "from_section": "Introduction", "type": "content"},
        {"title": "Motivation: Real-world stakes", "from_section": "Introduction", "type": "content"},
        {"title": "Background", "from_section": "Background", "type": "content"},
        {"title": "Prior Work", "from_section": "Background", "type": "content"},
        {"title": "Gaps", "from_section": "Background", "type": "content"},
        {"title": "Our Approach: Overview", "from_section": "Methods", "type": "content"},
        {"title": "Method Details (1/3)", "from_section": "Methods", "type": "content"},
        {"title": "Method Details (2/3)", "from_section": "Methods", "type": "content"},
        {"title": "Method Details (3/3)", "from_section": "Methods", "type": "content"},
        {"title": "Theoretical Properties", "from_section": "Methods", "type": "content"},
        {"title": "Experimental Setup", "from_section": "Experiments", "type": "content"},
        {"title": "Datasets", "from_section": "Experiments", "type": "content"},
        {"title": "Baselines", "from_section": "Experiments", "type": "content"},
        {"title": "Main Results", "from_section": "Results", "type": "content"},
        {"title": "Detailed Comparison", "from_section": "Results", "type": "content"},
        {"title": "Ablations (1/2)", "from_section": "Results", "type": "content"},
        {"title": "Ablations (2/2)", "from_section": "Results", "type": "content"},
        {"title": "Qualitative Examples", "from_section": "Results", "type": "content"},
        {"title": "Discussion", "from_section": "Discussion", "type": "content"},
        {"title": "Why It Works", "from_section": "Discussion", "type": "content"},
        {"title": "Limitations", "from_section": "Discussion", "type": "content"},
        {"title": "Future Work", "from_section": "Conclusion", "type": "content"},
        {"title": "Broader Impact", "from_section": "Conclusion", "type": "content"},
        {"title": "Conclusion", "from_section": "Conclusion", "type": "content"},
        {"title": "Acknowledgements", "from_section": None, "type": "ack"},
        {"title": "Questions?", "from_section": None, "type": "qa"},
        {"title": "Backup: Hyperparameters", "from_section": "Appendix", "type": "backup"},
        {"title": "References", "from_section": "References", "type": "refs"},
    ],
    "poster": [
        {"title": "Title + Authors", "from_section": None, "type": "title"},
        {"title": "Motivation", "from_section": "Introduction", "type": "content"},
        {"title": "Method", "from_section": "Methods", "type": "content"},
        {"title": "Results", "from_section": "Results", "type": "content"},
        {"title": "Conclusion", "from_section": "Conclusion", "type": "content"},
        {"title": "References", "from_section": "References", "type": "refs"},
    ],
}

VALID_FORMATS = {"beamer", "pptx", "revealjs", "slidev"}
FORMAT_EXT = {
    "beamer": "tex",
    "pptx": "pptx",
    "revealjs": "html",
    "slidev": "md",
}


def manuscript_dir(manuscript_id: str) -> Path:
    return cache_root() / "manuscripts" / manuscript_id


def slides_dir(manuscript_id: str) -> Path:
    d = manuscript_dir(manuscript_id) / "slides"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _outline_path(mid: str) -> Path:
    return slides_dir(mid) / "outline.json"


def _exports_dir(mid: str) -> Path:
    d = slides_dir(mid) / "exports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _source_path(mid: str) -> Path:
    return manuscript_dir(mid) / "source.md"


def _strip_placeholders(text: str) -> str:
    text = re.sub(r"\[PLACEHOLDER[^\]]*\]", "", text)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    return text


def _split_sections(source_md: str) -> dict[str, str]:
    """Split markdown by ## headers. Returns {heading: body}."""
    out: dict[str, str] = {}
    current_h: str | None = None
    buf: list[str] = []
    for line in source_md.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            if current_h is not None:
                out[current_h] = "\n".join(buf).strip()
            current_h = m.group(1).strip()
            buf = []
        else:
            buf.append(line)
    if current_h is not None:
        out[current_h] = "\n".join(buf).strip()
    return out


def _find_section_match(sections: dict[str, str], target: str) -> str | None:
    """Case-insensitive prefix match on section names."""
    if target is None:
        return None
    target_lower = target.lower()
    for h in sections:
        if h.lower() == target_lower:
            return h
    for h in sections:
        if h.lower().startswith(target_lower):
            return h
    for h in sections:
        if target_lower in h.lower():
            return h
    return None


def cmd_outline(args: argparse.Namespace) -> None:
    if args.style not in STYLE_TEMPLATES:
        raise SystemExit(f"unknown style: {args.style}. Valid: {sorted(STYLE_TEMPLATES)}")
    src = _source_path(args.manuscript_id)
    if not src.exists():
        raise SystemExit(f"manuscript source not found: {src}")

    out_path = _outline_path(args.manuscript_id)
    if out_path.exists() and not args.force:
        raise SystemExit(f"outline already exists. Use --force.")

    template = STYLE_TEMPLATES[args.style]
    slides = []
    for i, s in enumerate(template, start=1):
        slides.append({
            "id": i,
            "title": s["title"],
            "from_section": s["from_section"],
            "type": s["type"],
            "notes": "",
        })
    outline = {
        "manuscript_id": args.manuscript_id,
        "style": args.style,
        "slide_count": len(slides),
        "created_at": datetime.now(UTC).isoformat(),
        "slides": slides,
    }
    out_path.write_text(json.dumps(outline, indent=2))
    print(json.dumps({
        "manuscript_id": args.manuscript_id,
        "style": args.style,
        "slide_count": len(slides),
        "outline_path": str(out_path),
    }, indent=2))


def _build_slide_md(outline: dict, sections: dict[str, str], format: str) -> str:
    """Build a markdown source for slides, format-specific separators."""
    lines: list[str] = []

    # Front-matter for slidev
    if format == "slidev":
        lines.append("---")
        lines.append("theme: default")
        lines.append("layout: cover")
        lines.append("---")
        lines.append("")

    for s in outline["slides"]:
        title = s["title"]
        sec_name = s.get("from_section")
        slide_type = s.get("type", "content")

        if format == "slidev":
            if s["id"] > 1:
                lines.append("---")
            lines.append("")
        elif format == "beamer":
            # Beamer uses # at slide level via slide-level=2; we'll emit ## per slide
            pass

        lines.append(f"## {title}")
        lines.append("")

        if slide_type in ("title", "ack", "qa"):
            # Generic placeholders — user fills in
            if slide_type == "title":
                lines.append("*[Author names, affiliation, date]*")
            elif slide_type == "ack":
                lines.append("*[Acknowledgements]*")
            elif slide_type == "qa":
                lines.append("**Questions?**")
        elif sec_name:
            matched = _find_section_match(sections, sec_name)
            if matched:
                body = sections[matched]
                # Truncate to ~5 sentences for slide-friendly content
                sentences = re.split(r"(?<=[.!?])\s+", body)
                excerpt = " ".join(sentences[:5]).strip()
                if excerpt:
                    lines.append(excerpt)
                else:
                    lines.append(f"*[Content from section: {sec_name}]*")
            else:
                lines.append(f"*[Section not found: {sec_name}]*")
        else:
            lines.append(f"*[Content for: {title}]*")

        lines.append("")

    return "\n".join(lines)


def cmd_render(args: argparse.Namespace) -> None:
    if args.format not in VALID_FORMATS:
        raise SystemExit(f"unknown format: {args.format}. Valid: {sorted(VALID_FORMATS)}")

    out_path = _outline_path(args.manuscript_id)
    if not out_path.exists():
        raise SystemExit(f"no outline found. Run `outline` first.")
    src_path = _source_path(args.manuscript_id)
    if not src_path.exists():
        raise SystemExit(f"manuscript source missing: {src_path}")

    outline = json.loads(out_path.read_text())
    source_md = _strip_placeholders(src_path.read_text())
    sections = _split_sections(source_md)

    slide_md = _build_slide_md(outline, sections, args.format)

    # Determine output path
    ext = FORMAT_EXT[args.format]
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = _exports_dir(args.manuscript_id) / f"deck.{ext}"

    if args.format == "slidev":
        # slidev is just markdown — write directly, no pandoc
        output_path.write_text(slide_md)
        print(json.dumps({
            "format": args.format,
            "output": str(output_path),
            "pandoc_used": False,
            "slide_count": outline["slide_count"],
        }, indent=2))
        return

    # All other formats use pandoc
    if not shutil.which("pandoc"):
        raise SystemExit("pandoc not on PATH; install pandoc to render this format")

    # Write intermediate markdown
    intermediate = slides_dir(args.manuscript_id) / "_slides_source.md"
    intermediate.write_text(slide_md)

    pandoc_args = [
        "pandoc",
        str(intermediate),
        "-o", str(output_path),
        "--slide-level=2",
    ]
    if args.format == "beamer":
        pandoc_args += ["--to=beamer", "--standalone"]
    elif args.format == "pptx":
        pandoc_args += ["--to=pptx"]
    elif args.format == "revealjs":
        pandoc_args += ["--to=revealjs", "--standalone", "-V", "theme=white"]

    try:
        result = subprocess.run(pandoc_args, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        raise SystemExit("pandoc timed out after 60s")

    if result.returncode != 0:
        raise SystemExit(f"pandoc failed: {result.stderr.strip()}")

    print(json.dumps({
        "format": args.format,
        "output": str(output_path),
        "pandoc_used": True,
        "slide_count": outline["slide_count"],
    }, indent=2))


def cmd_list(args: argparse.Namespace) -> None:
    exports = _exports_dir(args.manuscript_id)
    files = []
    for p in sorted(exports.iterdir()):
        if p.is_file():
            files.append({
                "name": p.name,
                "size_bytes": p.stat().st_size,
                "modified": datetime.fromtimestamp(
                    p.stat().st_mtime, tz=UTC
                ).isoformat(),
            })
    out_path = _outline_path(args.manuscript_id)
    has_outline = out_path.exists()
    print(json.dumps({
        "manuscript_id": args.manuscript_id,
        "has_outline": has_outline,
        "exports": files,
    }, indent=2))


def cmd_clean(args: argparse.Namespace) -> None:
    sd = slides_dir(args.manuscript_id)
    removed: list[str] = []
    for p in sd.glob("**/*"):
        if p.is_file():
            removed.append(str(p))
            p.unlink()
    # also remove empty subdirs
    for p in sorted(sd.glob("**/*"), reverse=True):
        if p.is_dir():
            try:
                p.rmdir()
            except OSError:
                pass
    print(json.dumps({
        "manuscript_id": args.manuscript_id,
        "removed_count": len(removed),
    }, indent=2))


def cmd_formats(args: argparse.Namespace) -> None:
    print(json.dumps({
        "formats": sorted(VALID_FORMATS),
        "format_extensions": FORMAT_EXT,
        "styles": sorted(STYLE_TEMPLATES),
        "pandoc_available": bool(shutil.which("pandoc")),
    }, indent=2))


def main() -> None:
    p = argparse.ArgumentParser(description="Manuscript → slide deck.")
    sub = p.add_subparsers(dest="cmd", required=True)

    po = sub.add_parser("outline")
    po.add_argument("--manuscript-id", required=True)
    po.add_argument("--style", default="standard", choices=sorted(STYLE_TEMPLATES))
    po.add_argument("--force", action="store_true", default=False)
    po.set_defaults(func=cmd_outline)

    pr = sub.add_parser("render")
    pr.add_argument("--manuscript-id", required=True)
    pr.add_argument("--format", required=True, choices=sorted(VALID_FORMATS))
    pr.add_argument("--output", default=None)
    pr.set_defaults(func=cmd_render)

    pl = sub.add_parser("list")
    pl.add_argument("--manuscript-id", required=True)
    pl.set_defaults(func=cmd_list)

    pc = sub.add_parser("clean")
    pc.add_argument("--manuscript-id", required=True)
    pc.set_defaults(func=cmd_clean)

    pf = sub.add_parser("formats")
    pf.set_defaults(func=cmd_formats)

    args = p.parse_args()
    try:
        args.func(args)
    except (FileNotFoundError, ValueError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

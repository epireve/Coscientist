"""The paper artifact contract — read/write helpers for the cache layout.

Every skill uses this. Never write raw JSON to a paper dir without going
through PaperArtifact.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from slugify import slugify

from lib.cache import paper_dir


class State(str, Enum):
    discovered = "discovered"
    triaged = "triaged"
    acquired = "acquired"
    extracted = "extracted"
    read = "read"
    cited = "cited"


@dataclass
class Manifest:
    canonical_id: str
    state: State = State.discovered
    doi: str | None = None
    arxiv_id: str | None = None
    pmid: str | None = None
    pmcid: str | None = None
    s2_id: str | None = None
    openalex_id: str | None = None
    sources_tried: list[dict[str, Any]] = field(default_factory=list)
    triage: dict[str, Any] | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class Metadata:
    title: str
    authors: list[str] = field(default_factory=list)
    venue: str | None = None
    year: int | None = None
    abstract: str | None = None
    tldr: str | None = None
    keywords: list[str] = field(default_factory=list)
    claims: list[dict[str, Any]] = field(default_factory=list)
    citation_count: int | None = None
    reference_count: int | None = None
    discovered_via: list[str] = field(default_factory=list)


def canonical_id(
    title: str,
    year: int | None = None,
    first_author: str | None = None,
    doi: str | None = None,
) -> str:
    """Deterministic canonical_id: <author>_<year>_<title-slug>_<6hash>.

    The hash prevents collisions across near-duplicate titles.
    """
    author_part = slugify(first_author or "anon").split("-")[-1] or "anon"
    year_part = str(year) if year else "nd"
    title_part = slugify(title)[:60] if title else "untitled"
    fingerprint = (doi or f"{title}|{year}|{first_author}").lower()
    hashsuffix = hashlib.blake2s(fingerprint.encode("utf-8"), digest_size=3).hexdigest()
    return f"{author_part}_{year_part}_{title_part}_{hashsuffix}"


class PaperArtifact:
    """Thin helper for the per-paper artifact directory."""

    def __init__(self, cid: str):
        self.canonical_id = cid
        self.root = paper_dir(cid)

    # --- manifest -----------------------------------------------------
    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.json"

    def load_manifest(self) -> Manifest:
        if not self.manifest_path.exists():
            return Manifest(canonical_id=self.canonical_id)
        data = json.loads(self.manifest_path.read_text())
        data["state"] = State(data.get("state", "discovered"))
        return Manifest(**data)

    def save_manifest(self, m: Manifest) -> None:
        m.updated_at = datetime.now(UTC).isoformat()
        payload = asdict(m)
        payload["state"] = m.state.value
        self.manifest_path.write_text(json.dumps(payload, indent=2, default=str))

    def set_state(self, state: State) -> Manifest:
        m = self.load_manifest()
        m.state = state
        self.save_manifest(m)
        return m

    def record_source_attempt(
        self, source: str, outcome: str, detail: dict[str, Any] | None = None
    ) -> None:
        m = self.load_manifest()
        m.sources_tried.append(
            {
                "source": source,
                "outcome": outcome,
                "at": datetime.now(UTC).isoformat(),
                "detail": detail or {},
            }
        )
        self.save_manifest(m)

    # --- metadata -----------------------------------------------------
    @property
    def metadata_path(self) -> Path:
        return self.root / "metadata.json"

    def load_metadata(self) -> Metadata | None:
        if not self.metadata_path.exists():
            return None
        return Metadata(**json.loads(self.metadata_path.read_text()))

    def save_metadata(self, m: Metadata) -> None:
        self.metadata_path.write_text(json.dumps(asdict(m), indent=2))

    # --- content ------------------------------------------------------
    @property
    def content_path(self) -> Path:
        return self.root / "content.md"

    @property
    def frontmatter_path(self) -> Path:
        return self.root / "frontmatter.yaml"

    @property
    def raw_dir(self) -> Path:
        return self.root / "raw"

    @property
    def figures_dir(self) -> Path:
        return self.root / "figures"

    @property
    def tables_dir(self) -> Path:
        return self.root / "tables"

    @property
    def figures_json(self) -> Path:
        return self.root / "figures.json"

    @property
    def equations_json(self) -> Path:
        return self.root / "equations.json"

    @property
    def references_json(self) -> Path:
        return self.root / "references.json"

    @property
    def extraction_log(self) -> Path:
        return self.root / "extraction.log"

    # --- helpers ------------------------------------------------------
    def has_full_text(self) -> bool:
        return self.content_path.exists() and self.content_path.stat().st_size > 0

    def has_raw_pdf(self) -> bool:
        return any(self.raw_dir.glob("*.pdf"))

    def primary_pdf(self) -> Path | None:
        pdfs = sorted(self.raw_dir.glob("*.pdf"))
        return pdfs[0] if pdfs else None


# --- ID extraction helpers ---------------------------------------------

ARXIV_RE = re.compile(r"\b(\d{4}\.\d{4,5})(v\d+)?\b", re.IGNORECASE)
DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.IGNORECASE)


def extract_arxiv_id(s: str) -> str | None:
    m = ARXIV_RE.search(s)
    return m.group(1) if m else None


def extract_doi(s: str) -> str | None:
    m = DOI_RE.search(s)
    return m.group(0).rstrip(".") if m else None

"""Polymorphic artifact foundation.

The existing `PaperArtifact` in lib/paper_artifact.py remains the canonical
implementation for papers. This module adds:

- A thin `ArtifactKind` enum and kind → root directory mapping
- A tiny `ArtifactRef` dataclass that points to an artifact regardless of
  kind, so cross-kind code (project dashboard, graph layer) doesn't need
  to know each kind's internal layout
- Concrete `ManuscriptArtifact` and `ExperimentArtifact` stubs that
  mirror the paper contract but under their own roots and state machines

Existing skills keep using `PaperArtifact` directly. New kinds use
these classes. No migration required; both coexist.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from lib.cache import cache_root


class ArtifactKind(str, Enum):
    paper = "paper"
    manuscript = "manuscript"
    experiment = "experiment"
    dataset = "dataset"
    figure = "figure"
    review = "review"
    grant = "grant"
    journal_entry = "journal-entry"
    protocol = "protocol"


# state machines per kind
STATES = {
    ArtifactKind.paper: ("discovered", "triaged", "acquired", "extracted", "read", "cited"),
    ArtifactKind.manuscript: ("drafted", "audited", "critiqued", "revised", "submitted", "published"),
    ArtifactKind.experiment: ("designed", "preregistered", "running", "completed", "analyzed", "reproduced"),
    ArtifactKind.dataset: ("registered", "deposited", "versioned"),
    ArtifactKind.figure: ("drafted", "styled", "finalized"),
    ArtifactKind.review: ("drafted", "submitted"),
    ArtifactKind.grant: ("drafted", "submitted", "awarded", "rejected"),
    ArtifactKind.journal_entry: ("written",),
    ArtifactKind.protocol: ("drafted", "approved", "executed"),
}


def kind_root(kind: ArtifactKind) -> Path:
    """Cache root per kind."""
    mapping = {
        ArtifactKind.paper: "papers",
        ArtifactKind.manuscript: "manuscripts",
        ArtifactKind.experiment: "experiments",
        ArtifactKind.dataset: "datasets",
        ArtifactKind.figure: "figures",
        ArtifactKind.review: "reviews",
        ArtifactKind.grant: "grants",
        ArtifactKind.journal_entry: "journal",
        ArtifactKind.protocol: "protocols",
    }
    p = cache_root() / mapping[kind]
    p.mkdir(parents=True, exist_ok=True)
    return p


def artifact_dir(kind: ArtifactKind, artifact_id: str) -> Path:
    p = kind_root(kind) / artifact_id
    p.mkdir(parents=True, exist_ok=True)
    return p


@dataclass
class ArtifactRef:
    """Lightweight pointer to an artifact regardless of kind."""
    artifact_id: str
    kind: ArtifactKind
    path: Path
    project_id: str | None = None
    state: str | None = None


@dataclass
class BaseManifest:
    """Shared manifest fields across all artifact kinds."""
    artifact_id: str
    kind: ArtifactKind
    state: str
    project_id: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    extras: dict[str, Any] = field(default_factory=dict)


class BaseArtifact:
    """Minimal shared behavior. Subclass per kind for kind-specific fields."""
    kind: ArtifactKind = ArtifactKind.paper

    def __init__(self, artifact_id: str):
        self.artifact_id = artifact_id
        self.root = artifact_dir(self.kind, artifact_id)

    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.json"

    def load_manifest(self) -> BaseManifest:
        if not self.manifest_path.exists():
            initial_state = STATES[self.kind][0]
            return BaseManifest(
                artifact_id=self.artifact_id, kind=self.kind, state=initial_state
            )
        data = json.loads(self.manifest_path.read_text())
        data["kind"] = ArtifactKind(data.get("kind", self.kind.value))
        return BaseManifest(**data)

    def save_manifest(self, m: BaseManifest) -> None:
        m.updated_at = datetime.now(UTC).isoformat()
        payload = asdict(m)
        payload["kind"] = m.kind.value
        self.manifest_path.write_text(json.dumps(payload, indent=2, default=str))

    def set_state(self, state: str) -> None:
        valid = STATES[self.kind]
        if state not in valid:
            raise ValueError(f"state {state!r} not valid for kind {self.kind.value}: {valid}")
        m = self.load_manifest()
        m.state = state
        self.save_manifest(m)


class ManuscriptArtifact(BaseArtifact):
    """User's own manuscripts. Consumed by manuscript-audit/critique/reflect.

    Layout:
      manuscripts/<manuscript_id>/
        manifest.json
        source.md | source.tex | source.docx     # original
        structured.json                          # parsed AST
        claims.json                              # extracted claims
        audit.json                               # manuscript-audit output
        critique.json                            # manuscript-critique output
        reflect.json                             # manuscript-reflect output
        versions/                                # git-tracked or snapshot history
    """
    kind = ArtifactKind.manuscript


class ExperimentArtifact(BaseArtifact):
    """Experiment designs, runs, results, reproduction attempts.

    Layout:
      experiments/<experiment_id>/
        manifest.json
        design.json                              # hypothesis, variables, power
        preregistration.md                       # OSF-format (optional)
        env/                                     # env lockfile, Dockerfile
        code/                                    # experiment code (or link)
        runs/<run_id>/                           # per-execution artifacts
        results.json                             # analyzed outcomes
        reproducibility.json                     # for reproduction attempts
    """
    kind = ArtifactKind.experiment

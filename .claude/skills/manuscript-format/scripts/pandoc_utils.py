"""pandoc_utils — small helpers for manuscript-format.

Functions
---------
pandoc_available() -> bool
    Return True if pandoc is on PATH.

pandoc_version() -> str
    Return pandoc version string, or "unknown" if not installed.

strip_placeholders(text: str) -> str
    Remove [PLACEHOLDER ...] blocks and <!-- ... --> HTML comments from
    markdown text before passing to pandoc.

build_pandoc_args(venue, output_format, source_path, output_path) -> list[str]
    Construct the pandoc CLI argument list for a given venue + format.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

# ---------------------------------------------------------------------------
# Venue → pandoc metadata / options map
# ---------------------------------------------------------------------------

# YAML block prepended to the stripped source before pandoc sees it.
# We inject document-class settings this way so we don't need template files.
_VENUE_YAML: dict[str, str] = {
    "neurips": """\
---
documentclass: article
classoption:
  - 11pt
  - preprint
geometry: margin=1in
---
""",
    "acl": """\
---
documentclass: article
classoption:
  - 11pt
geometry: margin=1in
---
""",
    "nature": """\
---
documentclass: article
classoption:
  - 12pt
geometry: margin=1in
---
""",
    "imrad": """\
---
documentclass: article
classoption:
  - 12pt
geometry: margin=1in
---
""",
    "arxiv": """\
---
documentclass: article
classoption:
  - 12pt
geometry: margin=1in
---
""",
    "docx": "",  # no extra YAML for Word
}

# Venues that produce LaTeX output (output_format=tex)
_LATEX_VENUES = {"neurips", "acl", "nature", "imrad", "arxiv"}

KNOWN_VENUES = set(_VENUE_YAML.keys())
KNOWN_OUTPUT_FORMATS = {"tex", "docx", "pdf"}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def pandoc_available() -> bool:
    """Return True if pandoc is on PATH."""
    return shutil.which("pandoc") is not None


def pandoc_version() -> str:
    """Return pandoc version string or 'unknown'."""
    if not pandoc_available():
        return "unknown"
    try:
        result = subprocess.run(
            ["pandoc", "--version"],
            capture_output=True, text=True, timeout=10,
        )
        first_line = result.stdout.splitlines()[0] if result.stdout else ""
        # "pandoc 3.1.2" → "3.1.2"
        parts = first_line.split()
        return parts[1] if len(parts) >= 2 else first_line or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


# Matches [PLACEHOLDER ...] on a line by itself (with optional trailing content)
_PLACEHOLDER_LINE = re.compile(
    r"^\[PLACEHOLDER[^\]]*\]\s*$",
    re.MULTILINE,
)
# Matches [PLACEHOLDER...] that may span multiple lines or inline blocks
_PLACEHOLDER_BLOCK = re.compile(
    r"\[PLACEHOLDER[^\]]*\]",
    re.DOTALL,
)
# Matches HTML comments <!-- ... --> (may be multi-line)
_HTML_COMMENT = re.compile(
    r"<!--.*?-->",
    re.DOTALL,
)


def strip_placeholders(text: str) -> str:
    """Remove [PLACEHOLDER ...] blocks and <!-- ... --> HTML comments.

    Leaves all real content intact. Safe to call on the full source.md text.
    """
    # Remove HTML comments first (<!-- ... -->)
    text = _HTML_COMMENT.sub("", text)
    # Remove [PLACEHOLDER ...] blocks (single-line and inline)
    text = _PLACEHOLDER_BLOCK.sub("", text)
    # Collapse runs of blank lines left by removal (more than 2 → 2)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def build_pandoc_args(
    venue: str,
    output_format: str,
    source_path: Path,
    output_path: Path,
) -> list[str]:
    """Construct the pandoc argument list.

    Parameters
    ----------
    venue:
        One of KNOWN_VENUES.
    output_format:
        One of {"tex", "docx", "pdf"}.
    source_path:
        Path to the (already stripped) source markdown file.
    output_path:
        Desired output file path.

    Returns
    -------
    list[str]
        Full argument list starting with "pandoc".
    """
    args = ["pandoc", str(source_path), "-o", str(output_path)]

    if output_format == "tex":
        args += ["--to", "latex", "--standalone"]
    elif output_format == "docx":
        args += ["--to", "docx"]
    elif output_format == "pdf":
        # Pandoc infers PDF via latex engine
        args += ["--pdf-engine=pdflatex"]

    # Venue-specific options
    if venue == "neurips":
        args += ["--variable", "fontsize=11pt"]
    elif venue == "acl":
        args += ["--variable", "fontsize=11pt"]
    elif venue == "nature":
        args += ["--variable", "fontsize=12pt"]

    return args

"""Publisher adapter registry, keyed by DOI prefix.

Each adapter module must export:
- DOMAIN: str (for rate-limit keying; "*" for the generic fallback)
- SessionExpired: re-exported from _common
- async def fetch_pdf(context, doi: str, out_path: Path) -> Path

Specific adapters cover ~80% of paywalled DOIs we'll see. The generic
fallback handles the long tail (Taylor & Francis, Cambridge UP, Oxford
UP, SAGE, etc.) by scanning for any "Download PDF" link.

Registry is consulted prefix-first; fall back to `generic` if no match.
"""

from __future__ import annotations

from . import acm, acs, elsevier, emerald, generic, ieee, nature, sage, springer, wiley
from ._common import SessionExpired

# Sized to UM's actual A-Z subscriptions (umlibguides.um.edu.my/az/databases)
# plus high-volume CS publishers (ACM, IEEE) and the broad chem/bio coverage.
registry = {
    "10.1016": elsevier,    # Elsevier / ScienceDirect (UM core)
    "10.1109": ieee,        # IEEE Xplore (UM core)
    "10.1177": sage,        # SAGE Journals (UM core)
    "10.1108": emerald,     # Emerald Insight (UM core)
    "10.1007": springer,    # Springer
    "10.1002": wiley,       # Wiley
    "10.1038": nature,      # Nature / Springer Nature journals
    "10.1021": acs,         # ACS
    "10.1145": acm,         # ACM Digital Library
}

# Caller uses this when prefix lookup misses.
fallback = generic

__all__ = ["registry", "fallback", "SessionExpired"]

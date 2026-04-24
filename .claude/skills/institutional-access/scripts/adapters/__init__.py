"""Publisher adapter registry, keyed by DOI prefix.

Each adapter module must export:
- DOMAIN: str (for rate-limit keying)
- SessionExpired: re-exported from _common
- async def fetch_pdf(context, doi: str, out_path: Path) -> Path
"""

from __future__ import annotations

from . import acs, elsevier, ieee, nature, springer, wiley
from ._common import SessionExpired

registry = {
    "10.1016": elsevier,
    "10.1007": springer,
    "10.1002": wiley,
    "10.1109": ieee,
    "10.1038": nature,
    "10.1021": acs,
}

__all__ = ["registry", "SessionExpired"]

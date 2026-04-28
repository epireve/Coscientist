"""Publisher adapter registry with smart routing.

Each adapter module exports:
- DOMAIN: str (rate-limit key; "*" for the generic fallback)
- async def fetch_pdf(context, doi: str, out_path: Path) -> Path

Routing strategy (smart resolver):
1. Fast path: DOI prefix → adapter (cheap, no network)
2. Fallback: HEAD-resolve DOI → final hostname → host_registry match
3. Last resort: generic adapter (scans landing for any PDF link)

This keeps the publisher mapping general — works for any user
authenticated to any institution that subscribes. Per-publisher HTML
quirks live in adapters; per-institution auth lives in idp_runner.py.
"""

from __future__ import annotations

from urllib.parse import urlparse

from . import (
    acm,
    acs,
    elsevier,
    emerald,
    generic,
    ieee,
    jstor,
    nature,
    sage,
    springer,
    wiley,
)
from ._common import SessionExpired

# Fast path: DOI prefix → adapter module
prefix_registry = {
    "10.1016": elsevier,    # Elsevier / ScienceDirect (UM core)
    "10.1109": ieee,        # IEEE Xplore (UM core)
    "10.1177": sage,        # SAGE Journals (UM core)
    "10.1108": emerald,     # Emerald Insight (UM core)
    "10.1007": springer,    # Springer
    "10.1002": wiley,       # Wiley
    "10.1038": nature,      # Nature / Springer Nature journals
    "10.1021": acs,         # ACS
    "10.1145": acm,         # ACM Digital Library
    "10.2307": jstor,       # JSTOR
}

# Slow path: hostname (suffix match) → adapter module
# Used when prefix isn't registered. Resolved via doi.org HEAD redirect.
# Suffix match because publishers use multiple subdomains
# (www.sciencedirect.com, dx.sciencedirect.com, etc.)
host_registry = {
    "sciencedirect.com": elsevier,
    "linkinghub.elsevier.com": elsevier,
    "ieeexplore.ieee.org": ieee,
    "journals.sagepub.com": sage,
    "emerald.com": emerald,
    "link.springer.com": springer,
    "onlinelibrary.wiley.com": wiley,
    "nature.com": nature,
    "pubs.acs.org": acs,
    "dl.acm.org": acm,
    "jstor.org": jstor,
}

# Catch-all when neither prefix nor host matches
fallback = generic

# Backwards-compat alias — fetch.py reads this.
registry = prefix_registry


def adapter_for_prefix(prefix: str):
    """Fast path: DOI prefix → adapter, or None."""
    return prefix_registry.get(prefix)


def adapter_for_host(url: str):
    """Slow path: URL → adapter via hostname suffix match, or None."""
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return None
    for suffix, mod in host_registry.items():
        if host == suffix or host.endswith("." + suffix):
            return mod
    return None


async def resolve_adapter(context, doi: str):
    """Smart routing: try prefix first, then host-resolve, then generic.

    Returns (adapter_module, resolution_path: str). The path string is
    one of: 'prefix', 'host', 'fallback'. Useful for logging.

    Network only happens on the host fallback (HEAD request to doi.org).
    """
    prefix = doi.split("/", 1)[0] if "/" in doi else doi
    a = adapter_for_prefix(prefix)
    if a is not None:
        return a, "prefix"

    # Host fallback: resolve doi.org via Playwright context.request to
    # avoid pulling in `requests` as a dep. Follow redirects manually
    # so we capture the final landing host.
    try:
        resp = await context.request.head(
            f"https://doi.org/{doi}",
            max_redirects=10,
            timeout=15000,
        )
        a = adapter_for_host(resp.url)
        if a is not None:
            return a, "host"
    except Exception:
        pass

    return fallback, "fallback"


__all__ = [
    "registry",
    "prefix_registry",
    "host_registry",
    "fallback",
    "adapter_for_prefix",
    "adapter_for_host",
    "resolve_adapter",
    "SessionExpired",
]

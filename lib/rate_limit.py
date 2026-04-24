"""Per-domain rate limiting for polite publisher fetching.

Uses a filesystem mutex so it works across skill invocations.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from urllib.parse import urlparse

from lib.cache import cache_root

DEFAULT_DELAY_SECONDS = 10


def _marker(domain: str) -> Path:
    d = cache_root() / "rate_limit"
    d.mkdir(parents=True, exist_ok=True)
    safe = domain.replace(":", "_").replace("/", "_")
    return d / f"{safe}.last"


def _domain_of(url_or_domain: str) -> str:
    if "://" in url_or_domain:
        return urlparse(url_or_domain).netloc.lower()
    return url_or_domain.lower()


def wait(url_or_domain: str, delay_seconds: float | None = None) -> None:
    """Block until the configured delay has elapsed since the last call for this domain."""
    delay = (
        delay_seconds
        if delay_seconds is not None
        else float(os.environ.get("COSCIENTIST_PUBLISHER_DELAY", DEFAULT_DELAY_SECONDS))
    )
    domain = _domain_of(url_or_domain)
    marker = _marker(domain)
    now = time.time()
    if marker.exists():
        last = marker.stat().st_mtime
        elapsed = now - last
        if elapsed < delay:
            time.sleep(delay - elapsed)
    marker.touch()

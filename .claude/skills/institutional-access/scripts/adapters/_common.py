"""Shared adapter utilities."""

from __future__ import annotations

from pathlib import Path


class SessionExpired(Exception):
    """Raised when the publisher redirects us back to the IdP."""


def looks_like_idp(url: str) -> bool:
    markers = ("openathens", "shibboleth", "login", "sso", "idp", "saml")
    u = url.lower()
    return any(m in u for m in markers)


async def wait_for_download(page, click_selector: str, out_path: Path, timeout_ms: int = 60000) -> Path:
    """Click a selector and capture the resulting file download."""
    async with page.expect_download(timeout=timeout_ms) as dl_info:
        await page.click(click_selector)
    download = await dl_info.value
    await download.save_as(str(out_path))
    return out_path

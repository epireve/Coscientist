"""Springer / SpringerLink adapter.

DOI prefix: 10.1007
"""

from __future__ import annotations

from pathlib import Path

from ._common import SessionExpired, looks_like_idp, wait_for_download

DOMAIN = "link.springer.com"


async def fetch_pdf(context, doi: str, out_path: Path) -> Path:
    page = await context.new_page()
    await page.goto(f"https://doi.org/{doi}", wait_until="domcontentloaded", timeout=45000)

    if looks_like_idp(page.url):
        raise SessionExpired(page.url)

    # SpringerLink exposes a direct /content/pdf/<doi>.pdf link
    try:
        return await wait_for_download(page, "a[data-track-action='Pdf download']", out_path)
    except Exception:
        # Fallback: any link ending in .pdf
        return await wait_for_download(page, "a[href$='.pdf']", out_path)

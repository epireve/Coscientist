"""JSTOR adapter.

DOI prefix: 10.2307
Landing: https://www.jstor.org/stable/<id>

Older JSTOR content lacks DOIs entirely; route by host instead in that
case (smart resolver in __init__.py handles host-based fallback).
"""
from __future__ import annotations

from pathlib import Path

from ._common import SessionExpired, looks_like_idp, wait_for_download

DOMAIN = "jstor.org"


async def fetch_pdf(context, doi: str, out_path: Path) -> Path:
    page = await context.new_page()
    await page.goto(
        f"https://doi.org/{doi}",
        wait_until="domcontentloaded",
        timeout=45000,
    )
    if looks_like_idp(page.url):
        raise SessionExpired(page.url)

    selectors = [
        'a[data-qa="download-pdf"]',
        'a:has-text("Download PDF")',
        'a[href*="/stable/pdf/"]',
        'a[href*=".pdf"]',
    ]
    last_err: Exception | None = None
    for sel in selectors:
        try:
            await page.wait_for_selector(sel, timeout=8000)
            return await wait_for_download(page, sel, out_path)
        except Exception as e:
            last_err = e
            continue
    raise last_err or RuntimeError("no PDF link found on JSTOR page")

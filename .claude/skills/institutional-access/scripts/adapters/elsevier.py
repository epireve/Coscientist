"""Elsevier / ScienceDirect adapter.

DOI prefix: 10.1016
Landing: https://www.sciencedirect.com/science/article/pii/<pii>
"""

from __future__ import annotations

from pathlib import Path

from ._common import SessionExpired, looks_like_idp, wait_for_download

DOMAIN = "sciencedirect.com"


async def fetch_pdf(context, doi: str, out_path: Path) -> Path:
    page = await context.new_page()
    await page.goto(f"https://doi.org/{doi}", wait_until="domcontentloaded", timeout=45000)

    if looks_like_idp(page.url):
        raise SessionExpired(page.url)

    # ScienceDirect "Download PDF" button
    try:
        await page.wait_for_selector("a.pdf-download-btn-link, a.PdfDownloadButton", timeout=20000)
        return await wait_for_download(page, "a.pdf-download-btn-link, a.PdfDownloadButton", out_path)
    except Exception as e:
        # Fall through to a more robust link-text based locator
        try:
            return await wait_for_download(page, "text=/^Download\\s+PDF/i", out_path)
        except Exception:
            raise e

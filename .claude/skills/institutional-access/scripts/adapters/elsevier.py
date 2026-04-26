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

    # ScienceDirect "View PDF" / "Download PDF" — selectors evolve;
    # try a cascade in order of specificity.
    selectors = [
        'a[aria-label*="View PDF" i]',
        'a[aria-label*="Download" i][aria-label*="PDF" i]',
        'a[data-aa-button="link_pdf-download"]',
        'a.anchor-pdf-download',
        'a.pdf-download-btn-link',
        'a.PdfDownloadButton',
        'a[href*="/pdfft"]',
        'a[href$=".pdf"]',
        'text=/^View\\s+PDF/i',
        'text=/^Download\\s+PDF/i',
    ]
    last_err: Exception | None = None
    for sel in selectors:
        try:
            await page.wait_for_selector(sel, timeout=8000)
            return await wait_for_download(page, sel, out_path)
        except Exception as e:
            last_err = e
            continue
    raise last_err or RuntimeError("no PDF link found on ScienceDirect page")

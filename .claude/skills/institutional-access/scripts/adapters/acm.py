"""ACM Digital Library adapter.

DOI prefix: 10.1145
Landing: https://dl.acm.org/doi/<doi>
"""
from __future__ import annotations

from pathlib import Path

from ._common import SessionExpired, looks_like_idp, wait_for_download

DOMAIN = "dl.acm.org"


async def fetch_pdf(context, doi: str, out_path: Path) -> Path:
    page = await context.new_page()
    # ACM resolves DOI directly to its landing page
    await page.goto(
        f"https://dl.acm.org/doi/{doi}",
        wait_until="domcontentloaded",
        timeout=45000,
    )

    if looks_like_idp(page.url):
        raise SessionExpired(page.url)

    # ACM "PDF" or "Download PDF" button — multiple selectors over recent
    # ACM redesigns. Try in order from most-specific to most-generic.
    selectors = [
        'a.btn--icon[title*="PDF" i]',
        'a[data-title="PDF"]',
        'a.btn--secondary[href*="/doi/pdf/"]',
        'a[href*="/doi/pdf/"]',
        'text=/^Download\\s+PDF/i',
        'text=/^PDF$/i',
    ]
    last_err: Exception | None = None
    for sel in selectors:
        try:
            await page.wait_for_selector(sel, timeout=8000)
            return await wait_for_download(page, sel, out_path)
        except Exception as e:
            last_err = e
            continue
    raise last_err or RuntimeError("no PDF link found on ACM page")

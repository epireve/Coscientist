"""Nature / Springer Nature adapter.

DOI prefix: 10.1038
"""

from __future__ import annotations

from pathlib import Path

from ._common import SessionExpired, looks_like_idp, wait_for_download

DOMAIN = "nature.com"


async def fetch_pdf(context, doi: str, out_path: Path) -> Path:
    page = await context.new_page()
    await page.goto(f"https://doi.org/{doi}", wait_until="domcontentloaded", timeout=45000)

    if looks_like_idp(page.url):
        raise SessionExpired(page.url)

    try:
        return await wait_for_download(page, "a[data-track-action='download pdf']", out_path)
    except Exception:
        return await wait_for_download(page, "a:has-text('Download PDF')", out_path)

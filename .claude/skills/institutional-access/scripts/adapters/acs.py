"""ACS Publications adapter.

DOI prefix: 10.1021
"""

from __future__ import annotations

from pathlib import Path

from ._common import SessionExpired, looks_like_idp, wait_for_download

DOMAIN = "pubs.acs.org"


async def fetch_pdf(context, doi: str, out_path: Path) -> Path:
    page = await context.new_page()
    await page.goto(f"https://doi.org/{doi}", wait_until="domcontentloaded", timeout=45000)

    if looks_like_idp(page.url):
        raise SessionExpired(page.url)

    # ACS uses a standard PDF nav with a per-article slug
    try:
        return await wait_for_download(page, "a[title='PDF'], a.article-cover__pdf-link", out_path)
    except Exception:
        return await wait_for_download(page, "a:has-text('PDF')", out_path)

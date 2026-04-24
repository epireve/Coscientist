"""IEEE Xplore adapter.

DOI prefix: 10.1109
"""

from __future__ import annotations

from pathlib import Path

from ._common import SessionExpired, looks_like_idp, wait_for_download

DOMAIN = "ieeexplore.ieee.org"


async def fetch_pdf(context, doi: str, out_path: Path) -> Path:
    page = await context.new_page()
    await page.goto(f"https://doi.org/{doi}", wait_until="domcontentloaded", timeout=45000)

    if looks_like_idp(page.url):
        raise SessionExpired(page.url)

    # IEEE opens PDF in an in-page viewer; the "Download PDF" link triggers a blob download
    return await wait_for_download(
        page, "a.doc-actions-link-btn:has-text('PDF'), a[title='PDF Download']", out_path
    )

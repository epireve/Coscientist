"""Wiley Online Library adapter.

DOI prefix: 10.1002
"""

from __future__ import annotations

from pathlib import Path

from ._common import SessionExpired, looks_like_idp, wait_for_download

DOMAIN = "onlinelibrary.wiley.com"


async def fetch_pdf(context, doi: str, out_path: Path) -> Path:
    page = await context.new_page()
    # Wiley's direct PDF endpoint
    pdf_url = f"https://onlinelibrary.wiley.com/doi/pdfdirect/{doi}?download=true"
    await page.goto(f"https://doi.org/{doi}", wait_until="domcontentloaded", timeout=45000)

    if looks_like_idp(page.url):
        raise SessionExpired(page.url)

    # Try the direct endpoint first — it triggers a download when entitled
    try:
        async with page.expect_download(timeout=45000) as dl_info:
            await page.goto(pdf_url)
        download = await dl_info.value
        await download.save_as(str(out_path))
        return out_path
    except Exception:
        return await wait_for_download(page, "a.pdf-download, a[title*='PDF']", out_path)

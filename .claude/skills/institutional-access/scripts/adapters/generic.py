"""Generic publisher fallback adapter.

DOI prefix: * (catch-all for publishers without a dedicated adapter)
Landing: https://doi.org/<doi> → publisher chooses

Strategy: resolve DOI, look for any "Download PDF" link or PDF embed,
click it, capture download. Covers Taylor & Francis (10.1080),
Cambridge UP (10.1017), Oxford UP (10.1093), SAGE (10.1177), etc.

Less reliable than per-publisher adapters because publisher HTML varies.
Used when paper-acquire's prefix lookup misses.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from ._common import SessionExpired, looks_like_idp, wait_for_download

DOMAIN = "*"  # catch-all


async def fetch_pdf(context, doi: str, out_path: Path) -> Path:
    page = await context.new_page()
    await page.goto(
        f"https://doi.org/{doi}",
        wait_until="domcontentloaded",
        timeout=45000,
    )

    if looks_like_idp(page.url):
        raise SessionExpired(page.url)

    # Try a cascading set of selectors covering the common patterns:
    # 1. Explicit "Download PDF" labelled controls
    # 2. <a href> ending in .pdf or containing /pdf/
    # 3. data-pdf-url attributes
    # 4. iframe[src] pointing at a PDF (some publishers embed)
    selectors = [
        'a:has-text("Download PDF")',
        'button:has-text("Download PDF")',
        'a:has-text("Full text PDF")',
        'a[aria-label*="PDF" i][href]',
        'a[href$=".pdf"]',
        'a[href*="/pdfdirect/"]',
        'a[href*="/pdf/"]',
        'a[data-pdf-url]',
        'a[download][href*="pdf"]',
    ]

    last_err: Exception | None = None
    for sel in selectors:
        try:
            await page.wait_for_selector(sel, timeout=6000)
            return await wait_for_download(page, sel, out_path)
        except Exception as e:
            last_err = e
            continue

    # Fallback: scan for any <a href> that looks like a PDF link via JS
    pdf_url = await page.evaluate(
        """
        () => {
            const links = Array.from(document.querySelectorAll('a[href]'));
            const pdf = links.find(a => {
                const h = (a.getAttribute('href') || '').toLowerCase();
                return h.endsWith('.pdf') || h.includes('/pdf/') ||
                       h.includes('/pdfdirect/') || h.includes('/pdf?');
            });
            return pdf ? pdf.href : null;
        }
        """
    )
    if pdf_url:
        # Direct PDF URL — fetch via context.request to avoid click ambiguity
        resp = await context.request.get(pdf_url)
        if resp.ok and "pdf" in (resp.headers.get("content-type") or "").lower():
            out_path.write_bytes(await resp.body())
            return out_path

    raise last_err or RuntimeError(
        f"no PDF link found on generic landing for {doi} "
        f"(host={urlparse(page.url).netloc})"
    )

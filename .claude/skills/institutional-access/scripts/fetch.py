#!/usr/bin/env python3
"""institutional-access: DOI → PDF via per-publisher adapter + Playwright.

Exit codes:
  0   — success, PDF saved
  2   — no DOI on manifest
  3   — no adapter for this publisher (caller should fall back to browser-use MCP)
  10  — session expired; re-run login.py
  1   — other error
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.paper_artifact import PaperArtifact  # noqa: E402
from lib.rate_limit import wait as rate_limit_wait  # noqa: E402
from lib.retry import aretry_with_backoff  # noqa: E402  v0.14

STATE_FILE = Path(__file__).resolve().parent.parent / "state" / "storage_state.json"


async def run(cid: str) -> int:
    art = PaperArtifact(cid)
    manifest = art.load_manifest()
    if not manifest.doi:
        print("[fetch] no DOI on manifest", file=sys.stderr)
        return 2

    # Python packages can't be imported as `.adapters` from a plain script — fix path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from adapters import resolve_adapter  # type: ignore

    if not STATE_FILE.exists():
        print("[fetch] no storage_state.json — run login.py first", file=sys.stderr)
        return 10

    try:
        from playwright.async_api import async_playwright
    except ImportError as e:
        raise SystemExit("playwright not installed.") from e

    out_path = art.raw_dir / "institutional.pdf"

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context(storage_state=str(STATE_FILE))
        try:
            # Smart routing: prefix → host → generic
            adapter, route = await resolve_adapter(context, manifest.doi)
            print(f"[fetch] adapter={adapter.__name__.rsplit('.',1)[-1]} "
                  f"route={route}", file=sys.stderr)
            rate_limit_wait(adapter.DOMAIN)

            # v0.14: retry transient adapter errors (timeouts, network blips,
            # publisher 429s) with exponential backoff. SessionExpired is
            # NOT retryable — bubble it up immediately.
            retryable: tuple[type[BaseException], ...] = (TimeoutError,
                                                           ConnectionError, OSError)
            try:
                from playwright.async_api import TimeoutError as PWTimeout
                retryable = (*retryable, PWTimeout)
            except ImportError:
                pass

            async def attempt():
                return await adapter.fetch_pdf(context, manifest.doi, out_path)

            pdf = await aretry_with_backoff(
                attempt,
                max_attempts=3,
                base_delay=2.0,
                retryable=retryable,
            )
            print(str(pdf))
            return 0
        except adapter.SessionExpired:
            print("[fetch] session expired — re-run login.py", file=sys.stderr)
            return 10
        except Exception as e:
            print(f"[fetch] adapter error: {e}", file=sys.stderr)
            return 1
        finally:
            await browser.close()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--canonical-id", required=True)
    args = p.parse_args()
    sys.exit(asyncio.run(run(args.canonical_id)))


if __name__ == "__main__":
    main()

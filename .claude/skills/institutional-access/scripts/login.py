#!/usr/bin/env python3
"""One-time OpenAthens login bootstrap for institutional-access.

Opens a real Chromium window. You complete SSO + MFA manually, then press
Enter here to persist `storage_state.json` (cookies + local storage).

Re-run whenever the session expires.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

STATE_DIR = Path(__file__).resolve().parent.parent / "state"
STATE_FILE = STATE_DIR / "storage_state.json"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--idp",
        default="https://my.openathens.net/?passiveLogin=false",
        help="OpenAthens entry URL (override if your library gives you a direct one)",
    )
    args = p.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise SystemExit("playwright not installed. Run `uv sync && uv run playwright install chromium`.") from e

    STATE_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, channel="chrome" if _chrome_available() else None)
        context = browser.new_context(
            storage_state=str(STATE_FILE) if STATE_FILE.exists() else None,
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()
        page.goto(args.idp)

        print("=" * 70)
        print("Complete your institution's SSO (+ MFA) in the browser window.")
        print("When you're at your OpenAthens dashboard, return here and press Enter.")
        print("=" * 70)
        try:
            input("Press Enter to save session... ")
        except (EOFError, KeyboardInterrupt):
            print("\naborted", file=sys.stderr)
            browser.close()
            sys.exit(1)

        context.storage_state(path=str(STATE_FILE))
        print(f"saved → {STATE_FILE}")
        browser.close()


def _chrome_available() -> bool:
    # Playwright uses bundled Chromium by default; real Chrome via channel='chrome' is preferred
    # for lower bot-detection surface. Fall back silently if not installed.
    import shutil
    return any(
        shutil.which(x) for x in ("google-chrome", "chrome", "chromium", "chromium-browser")
    )


if __name__ == "__main__":
    main()

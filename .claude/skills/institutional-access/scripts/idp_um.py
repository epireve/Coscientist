#!/usr/bin/env python3
"""University Malaya (UM) IdP auto-login via OpenAthens.

Fills the Shibboleth credential form on UM's IdP after OpenAthens
redirects to it. Credentials read from env (preferred) or .env file.

Per-publisher entry URLs route SAML through UM's OpenAthens org
(80252862, entityID https://idp.um.edu.my/entity), then to UM's
Shibboleth IdP, then back to publisher with auth cookies.

Usage:
    # one-time: persist cookies
    UM_USERNAME=... UM_PASSWORD=... python idp_um.py login

    # Or .env file at repo root with UM_USERNAME=... / UM_PASSWORD=...
    python idp_um.py login

    # Refresh just one publisher's cookies
    python idp_um.py login --publisher elsevier

NEVER commit credentials. .env is gitignored.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Optional

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[3]
STATE_DIR = _HERE.parent / "state"
STATE_FILE = STATE_DIR / "storage_state.json"

# UM's OpenAthens entityID + organisation ID (from observed redirects).
UM_ENTITY_ID = "https://idp.um.edu.my/entity"
UM_OA_ORG = "80252862"

# Per-publisher SSO entry URLs. Each takes the user through their
# WAYF, OpenAthens, UM IdP, then back to publisher with cookies set.
PUBLISHER_ENTRY = {
    "elsevier": (
        "https://auth.elsevier.com/ShibAuth/institutionLogin"
        f"?entityID={UM_ENTITY_ID}"
        "&appReturnURL=https%3A%2F%2Fwww.sciencedirect.com%2F"
    ),
    "acm": (
        "https://dl.acm.org/action/ssostart"
        f"?idp={UM_ENTITY_ID}"
        "&redirectUri=https%3A%2F%2Fdl.acm.org%2Fdl.cfm"
    ),
    # Generic OpenAthens dashboard — covers any publisher that lets you
    # start from there (Wiley, Springer, Nature, IEEE, etc.)
    "openathens": "https://my.openathens.net/?passiveLogin=false",
}


def _load_env_file() -> dict[str, str]:
    """Lightweight .env reader. No dependencies."""
    env_path = _REPO_ROOT / ".env"
    if not env_path.exists():
        return {}
    out: dict[str, str] = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        # strip optional quotes
        v = v.strip().strip('"').strip("'")
        out[k.strip()] = v
    return out


def _get_credentials() -> tuple[str, str]:
    """Read UM_USERNAME + UM_PASSWORD from env or .env. Fail loud if absent."""
    env_file = _load_env_file()
    user = os.environ.get("UM_USERNAME") or env_file.get("UM_USERNAME")
    pw = os.environ.get("UM_PASSWORD") or env_file.get("UM_PASSWORD")
    if not user or not pw:
        raise SystemExit(
            "UM_USERNAME and UM_PASSWORD required. Set as env vars or in "
            ".env at repo root. Never commit them — .env is gitignored."
        )
    return user, pw


async def _fill_idp_form(page, user: str, pw: str) -> None:
    """Fill UM Shibboleth credential form.

    UM uses Microsoft-style OAuth2/OIDC redirect (login.microsoftonline.com)
    for SSO. Form selectors are MS-standard:
      - input[name="loginfmt"]   — email/username
      - input[name="passwd"]     — password
      - input[type="submit"]     — Next/Sign in buttons
    On the "Stay signed in?" page we click "No" to keep cookies session-only
    in the browser context (Playwright's storage_state captures them anyway).
    """
    # Username step
    await page.wait_for_selector('input[name="loginfmt"]', timeout=20000)
    await page.fill('input[name="loginfmt"]', user)
    await page.click('input[type="submit"]')

    # Password step
    await page.wait_for_selector('input[name="passwd"]', timeout=20000)
    await page.fill('input[name="passwd"]', pw)
    await page.click('input[type="submit"]')

    # MFA may appear here. We can't auto-handle MFA — hand off to the user.
    # Detect by looking for the KMSI ("Stay signed in") prompt OR an MFA
    # challenge page. Wait up to 120s for one of them.
    try:
        await page.wait_for_selector(
            'input[name="DontShowAgain"], '
            'input[type="submit"][value*="No"], '
            'div[id*="idDiv_SAOTCAS_Title"]',
            timeout=120000,
        )
    except Exception:
        # Either we got bounced past KMSI (some IdPs skip it) or we're stuck
        # on MFA. The caller's --interactive flag covers the manual case.
        return

    # If MFA is showing, leave it to the user. If KMSI is showing, click No.
    has_kmsi = await page.locator(
        'input[type="submit"][value*="No"]'
    ).count()
    if has_kmsi:
        await page.click('input[type="submit"][value*="No"]')


async def _login_flow(publisher: str, interactive: bool, timeout_seconds: int) -> int:
    try:
        from playwright.async_api import async_playwright
    except ImportError as e:
        raise SystemExit(
            "playwright not installed. "
            "Run `uv sync && uv run playwright install chromium`."
        ) from e

    user, pw = _get_credentials()
    entry = PUBLISHER_ENTRY.get(publisher)
    if not entry:
        raise SystemExit(
            f"unknown publisher {publisher!r}. "
            f"Known: {sorted(PUBLISHER_ENTRY.keys())}"
        )

    STATE_DIR.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,  # Headful by design — auth flows + MFA need it.
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            storage_state=str(STATE_FILE) if STATE_FILE.exists() else None,
            viewport={"width": 1280, "height": 900},
            # Standard UA to avoid trivial bot fingerprinting
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        print(f"[idp_um] navigating to {publisher} entry → {entry}", file=sys.stderr)
        await page.goto(entry, wait_until="networkidle")

        # Try auto-fill. If UM IdP form not seen within 30s, assume we're
        # already logged in (cookies survived) or in interactive mode.
        try:
            await _fill_idp_form(page, user, pw)
            print("[idp_um] credentials submitted", file=sys.stderr)
        except Exception as e:
            print(f"[idp_um] auto-fill failed: {e}", file=sys.stderr)
            if not interactive:
                print(
                    "[idp_um] re-run with --interactive to complete manually",
                    file=sys.stderr,
                )

        if interactive:
            print("=" * 70, file=sys.stderr)
            print("Complete any remaining MFA / consent in the browser.",
                  file=sys.stderr)
            print("When you reach the publisher landing page, press Enter here.",
                  file=sys.stderr)
            print("=" * 70, file=sys.stderr)
            try:
                input()
            except (EOFError, KeyboardInterrupt):
                await browser.close()
                return 1
        else:
            # Non-interactive: wait until network settles after IdP redirects
            try:
                await page.wait_for_load_state("networkidle", timeout=timeout_seconds * 1000)
            except Exception:
                pass

        await context.storage_state(path=str(STATE_FILE))
        cookie_count = len((await context.cookies()) or [])
        print(f"[idp_um] saved {cookie_count} cookies → {STATE_FILE}",
              file=sys.stderr)
        await browser.close()
    return 0


def cmd_login(args: argparse.Namespace) -> None:
    rc = asyncio.run(_login_flow(
        publisher=args.publisher,
        interactive=args.interactive,
        timeout_seconds=args.timeout,
    ))
    sys.exit(rc)


def cmd_publishers(args: argparse.Namespace) -> None:
    import json
    print(json.dumps({
        "entityID": UM_ENTITY_ID,
        "openathens_org": UM_OA_ORG,
        "publishers": PUBLISHER_ENTRY,
    }, indent=2))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("login", help="Run SSO flow + persist cookies")
    pl.add_argument("--publisher", default="openathens",
                    choices=sorted(PUBLISHER_ENTRY.keys()),
                    help="Which entry URL to start from")
    pl.add_argument("--interactive", action="store_true",
                    help="Wait for Enter after auto-fill (use for MFA)")
    pl.add_argument("--timeout", type=int, default=60,
                    help="Seconds to wait for network idle (non-interactive)")
    pl.set_defaults(func=cmd_login)

    pp = sub.add_parser("publishers", help="List known publisher entry URLs")
    pp.set_defaults(func=cmd_publishers)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

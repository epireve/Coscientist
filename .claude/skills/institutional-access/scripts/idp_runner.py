#!/usr/bin/env python3
"""Generic IdP auto-login runner.

Reads an institution config (institutions/<slug>.json) and runs the
SSO flow: navigate to publisher entry → fill credentials → persist
cookies.

Replaces the old `idp_um.py`. Works for any institution that publishes
its OpenAthens entityID + IdP form profile.

Usage:
    # Use the UM config
    python idp_runner.py login --institution um --interactive

    # List configured institutions
    python idp_runner.py institutions

    # Inspect publisher entry URLs for a config
    python idp_runner.py publishers --institution um

To add your own institution:
1. Copy institutions/_template.json to institutions/<your_slug>.json
2. Fill in entityID, idp_kind, credential_env names
3. Add UM_USERNAME-style env vars to .env (gitignored)
4. Run: python idp_runner.py login --institution <your_slug>
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[3]
INSTITUTIONS_DIR = _HERE.parent / "institutions"
STATE_DIR = _HERE.parent / "state"
STATE_FILE = STATE_DIR / "storage_state.json"


# IdP form-fill profiles. Each profile knows the selectors for its
# particular SSO product. Add new ones here as institutions are added.
IDP_PROFILES = {
    "ms_entra": {
        "username_selector": 'input[name="loginfmt"]',
        "password_selector": 'input[name="passwd"]',
        "submit_selector": 'input[type="submit"]',
        "kmsi_selector": 'input[type="submit"][value*="No" i]',
        "mfa_marker": (
            'input[name="DontShowAgain"], '
            'input[type="submit"][value*="No" i], '
            'div[id*="idDiv_SAOTCAS_Title"]'
        ),
    },
    "shibboleth_classic": {
        "username_selector": 'input[name="j_username"]',
        "password_selector": 'input[name="j_password"]',
        "submit_selector": 'button[type="submit"], input[type="submit"]',
        "kmsi_selector": None,
        "mfa_marker": None,
    },
    "cas": {
        "username_selector": 'input[name="username"]',
        "password_selector": 'input[name="password"]',
        "submit_selector": 'button[type="submit"], input[type="submit"]',
        "kmsi_selector": None,
        "mfa_marker": None,
    },
    "simplesaml": {
        # SimpleSAMLphp default form
        "username_selector": 'input[id="username"], input[name="username"]',
        "password_selector": 'input[id="password"], input[name="password"]',
        "submit_selector": 'button[type="submit"], input[type="submit"]',
        "kmsi_selector": None,
        "mfa_marker": None,
    },
    "okta": {
        "username_selector": 'input[name="identifier"]',
        "password_selector": 'input[name="credentials.passcode"], input[name="password"]',
        "submit_selector": 'input[type="submit"], button[type="submit"]',
        "kmsi_selector": None,
        "mfa_marker": 'div[data-se="factor-list"], input[name="credentials.passcode"]',
    },
    "auth0": {
        "username_selector": 'input[name="username"], input[name="email"]',
        "password_selector": 'input[name="password"]',
        "submit_selector": 'button[type="submit"]',
        "kmsi_selector": None,
        "mfa_marker": None,
    },
    "manual": None,  # disable auto-fill
}


def _load_env_file() -> dict[str, str]:
    # Allow tests / sandboxed runs to bypass repo .env (e.g. to verify the
    # "missing credentials" error path even when the developer has a real .env).
    if os.environ.get("COSCIENTIST_NO_ENV_FILE") == "1":
        return {}
    env_path = _REPO_ROOT / ".env"
    if not env_path.exists():
        return {}
    out: dict[str, str] = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip().strip('"').strip("'")
        out[k.strip()] = v
    return out


def _load_institution(slug: str) -> dict:
    path = INSTITUTIONS_DIR / f"{slug}.json"
    if not path.exists():
        avail = sorted(p.stem for p in INSTITUTIONS_DIR.glob("*.json")
                       if not p.stem.startswith("_"))
        raise SystemExit(
            f"institution {slug!r} not found at {path}. "
            f"Available: {avail}"
        )
    cfg = json.loads(path.read_text())
    # Sanity-check required fields
    for key in ("name", "entityID", "idp_kind", "credential_env",
                "publisher_entry_urls"):
        if key not in cfg:
            raise SystemExit(f"{path}: missing required field {key!r}")
    if cfg["idp_kind"] not in IDP_PROFILES:
        raise SystemExit(
            f"{path}: unknown idp_kind {cfg['idp_kind']!r}. "
            f"Known: {sorted(IDP_PROFILES.keys())}"
        )
    return cfg


def _get_credentials(cfg: dict) -> tuple[str, str]:
    user_var = cfg["credential_env"]["username"]
    pw_var = cfg["credential_env"]["password"]
    env_file = _load_env_file()
    user = os.environ.get(user_var) or env_file.get(user_var)
    pw = os.environ.get(pw_var) or env_file.get(pw_var)
    if not user or not pw:
        raise SystemExit(
            f"{user_var} and {pw_var} required. Set as env vars or in "
            f".env at repo root. Never commit them — .env is gitignored."
        )
    return user, pw


def _resolve_entry_url(cfg: dict, publisher: str) -> str:
    urls = cfg["publisher_entry_urls"]
    if publisher not in urls:
        raise SystemExit(
            f"publisher {publisher!r} not configured for {cfg['name']}. "
            f"Available: {sorted(urls.keys())}. "
            f"Add it to institutions/<slug>.json publisher_entry_urls."
        )
    template = urls[publisher]
    return template.replace("{entityID}", cfg["entityID"])


async def _fill_form(page, profile: dict, user: str, pw: str) -> None:
    """Fill a credential form using the profile's selectors."""
    await page.wait_for_selector(profile["username_selector"], timeout=20000)
    await page.fill(profile["username_selector"], user)
    await page.click(profile["submit_selector"])

    # Some IdPs put password on the next page (MS Entra), others on same page.
    await page.wait_for_selector(profile["password_selector"], timeout=20000)
    await page.fill(profile["password_selector"], pw)
    await page.click(profile["submit_selector"])

    # MFA / KMSI handling — best-effort
    if profile.get("mfa_marker"):
        try:
            await page.wait_for_selector(profile["mfa_marker"], timeout=120000)
        except Exception:
            return
    if profile.get("kmsi_selector"):
        try:
            count = await page.locator(profile["kmsi_selector"]).count()
            if count:
                await page.click(profile["kmsi_selector"])
        except Exception:
            pass


async def _login_flow(slug: str, publisher: str, interactive: bool,
                       timeout_seconds: int) -> int:
    try:
        from playwright.async_api import async_playwright
    except ImportError as e:
        raise SystemExit(
            "playwright not installed. "
            "Run `uv sync && uv run playwright install chromium`."
        ) from e

    cfg = _load_institution(slug)
    profile = IDP_PROFILES[cfg["idp_kind"]]
    user, pw = _get_credentials(cfg)
    entry = _resolve_entry_url(cfg, publisher)

    STATE_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[idp] institution={cfg['name']} ({slug}) "
          f"publisher={publisher} idp_kind={cfg['idp_kind']}",
          file=sys.stderr)

    # Persistent context: real on-disk profile dir. Captcha vendors look
    # for fresh-profile signals (no history, no extensions, no prior
    # cookies). Persistent dir builds up legitimate browsing state over
    # successive runs and dodges the captcha after the first warm-up.
    import shutil
    profile_dir = STATE_DIR / "chrome_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    # Clear stale Singleton* locks from prior crashed Chrome processes
    for sentinel in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        try:
            (profile_dir / sentinel).unlink(missing_ok=True)
        except OSError:
            pass

    # Use Playwright's bundled Chromium, NOT real Chrome (channel='chrome').
    # Real Chrome's lockfiles (GCM Store, password store, keychain) collide
    # with the user's daily-driver Chrome, breaking persistent_context.
    # Bundled Chromium runs in isolation. Captcha vendors fingerprint the
    # bundled build slightly differently but persistent profile dir + the
    # navigator.webdriver patch are enough.
    has_chrome = False

    async with async_playwright() as p:
        launch_kwargs = {
            "user_data_dir": str(profile_dir),
            "headless": False,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--no-default-browser-check",
                "--no-first-run",
            ],
            "viewport": {"width": 1280, "height": 900},
            "locale": "en-US",
            # No spoofed UA — let real Chrome supply its own. Spoofed UA
            # is the #1 captcha trigger because the version always lags.
        }
        if has_chrome:
            launch_kwargs["channel"] = "chrome"
        # launch_persistent_context returns a BrowserContext directly
        context = await p.chromium.launch_persistent_context(**launch_kwargs)
        # Strip navigator.webdriver flag — biggest headless-detection tell
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', "
            "{get: () => undefined});"
        )
        page = await context.new_page()

        print(f"[idp] navigating to {entry}", file=sys.stderr)
        await page.goto(entry, wait_until="networkidle")

        if profile is not None:
            try:
                await _fill_form(page, profile, user, pw)
                print("[idp] credentials submitted", file=sys.stderr)
            except Exception as e:
                print(f"[idp] auto-fill failed: {e}", file=sys.stderr)
                if not interactive:
                    print(
                        "[idp] re-run with --interactive to complete manually",
                        file=sys.stderr,
                    )
        else:
            print("[idp] idp_kind=manual — type credentials in the browser",
                  file=sys.stderr)

        if interactive:
            print("=" * 70, file=sys.stderr)
            print("Complete any remaining MFA / consent / captcha in the "
                  "browser.", file=sys.stderr)
            print("When you reach the publisher landing page (signed in), "
                  "press Enter here.", file=sys.stderr)
            print("=" * 70, file=sys.stderr)
            try:
                input()
            except (EOFError, KeyboardInterrupt):
                await context.close()
                return 1
        else:
            try:
                await page.wait_for_load_state(
                    "networkidle", timeout=timeout_seconds * 1000
                )
            except Exception:
                pass

        # Persistent context auto-saves cookies to user_data_dir on close.
        # Also write storage_state.json as a stable handle for fetch.py.
        await context.storage_state(path=str(STATE_FILE))
        cookie_count = len((await context.cookies()) or [])
        print(f"[idp] saved {cookie_count} cookies → profile {profile_dir}",
              file=sys.stderr)
        print(f"[idp] storage_state mirror → {STATE_FILE}", file=sys.stderr)
        await context.close()
    return 0


def cmd_login(args: argparse.Namespace) -> None:
    rc = asyncio.run(_login_flow(
        slug=args.institution,
        publisher=args.publisher,
        interactive=args.interactive,
        timeout_seconds=args.timeout,
    ))
    sys.exit(rc)


def cmd_publishers(args: argparse.Namespace) -> None:
    cfg = _load_institution(args.institution)
    resolved = {
        name: tmpl.replace("{entityID}", cfg["entityID"])
        for name, tmpl in cfg["publisher_entry_urls"].items()
    }
    print(json.dumps({
        "institution": cfg["name"],
        "slug": args.institution,
        "entityID": cfg["entityID"],
        "idp_kind": cfg["idp_kind"],
        "publishers": resolved,
    }, indent=2))


def cmd_institutions(args: argparse.Namespace) -> None:
    out = []
    for p in sorted(INSTITUTIONS_DIR.glob("*.json")):
        if p.stem.startswith("_"):
            continue
        try:
            cfg = json.loads(p.read_text())
            out.append({
                "slug": p.stem,
                "name": cfg.get("name"),
                "country": cfg.get("country"),
                "entityID": cfg.get("entityID"),
                "idp_kind": cfg.get("idp_kind"),
                "publishers_configured": sorted(
                    cfg.get("publisher_entry_urls", {}).keys()
                ),
            })
        except json.JSONDecodeError:
            out.append({"slug": p.stem, "error": "invalid JSON"})
    print(json.dumps({"institutions": out}, indent=2))


def main() -> None:
    p = argparse.ArgumentParser(description="Institution-agnostic IdP runner.")
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("login", help="Run SSO flow + persist cookies")
    pl.add_argument("--institution", required=True,
                    help="Institution slug (file in institutions/<slug>.json)")
    pl.add_argument("--publisher", default="openathens",
                    help="Which entry URL to start from")
    pl.add_argument("--interactive", action="store_true",
                    help="Wait for Enter after auto-fill (use for MFA)")
    pl.add_argument("--timeout", type=int, default=60)
    pl.set_defaults(func=cmd_login)

    pp = sub.add_parser("publishers",
                         help="List entry URLs for an institution")
    pp.add_argument("--institution", required=True)
    pp.set_defaults(func=cmd_publishers)

    pi = sub.add_parser("institutions",
                         help="List all configured institutions")
    pi.set_defaults(func=cmd_institutions)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

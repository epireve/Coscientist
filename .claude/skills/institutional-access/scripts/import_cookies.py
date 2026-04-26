#!/usr/bin/env python3
"""Import cookies from real Chrome → Playwright storage_state.json.

When OpenAthens captcha blocks Playwright automation but real Chrome
gets through, log in via real Chrome, then export cookies and feed them
here. The persisted state lets fetch.py reuse the authenticated session
without re-running idp_runner.py.

How to export cookies from real Chrome:

  1. In Chrome, install "Cookie-Editor" extension (cookie-editor.com).
  2. Log in to ScienceDirect via UM library SSO.
  3. Visit each domain and Cookie-Editor → Export → JSON:
     - .sciencedirect.com
     - .elsevier.com
     - .openathens.net
     - .um.edu.my
     - sso-umlib.um.edu.my
  4. Concatenate the JSON arrays into one file: cookies.json
  5. Run:
       python import_cookies.py --input cookies.json

The script merges them into a Playwright-compatible storage_state.json
under .claude/skills/institutional-access/state/.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
STATE_DIR = _HERE.parent / "state"
STATE_FILE = STATE_DIR / "storage_state.json"


def _normalize_cookie(c: dict) -> dict:
    """Convert Cookie-Editor format → Playwright format."""
    out = {
        "name": c["name"],
        "value": c["value"],
        "domain": c["domain"],
        "path": c.get("path", "/"),
        "secure": bool(c.get("secure", False)),
        "httpOnly": bool(c.get("httpOnly", False)),
        # Playwright wants sameSite as "Lax" | "Strict" | "None"
        "sameSite": (c.get("sameSite") or "Lax").capitalize(),
    }
    if c.get("sameSite") in (None, "no_restriction", "unspecified"):
        out["sameSite"] = "None" if out["secure"] else "Lax"
    # expirationDate (Cookie-Editor) → expires (Playwright). -1 = session.
    if "expirationDate" in c and c["expirationDate"]:
        out["expires"] = float(c["expirationDate"])
    elif "expires" in c and c["expires"]:
        out["expires"] = float(c["expires"])
    else:
        out["expires"] = -1
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True,
                   help="Path to JSON cookie export from Cookie-Editor")
    p.add_argument("--output", default=str(STATE_FILE),
                   help="Where to write Playwright storage_state.json")
    args = p.parse_args()

    raw = json.loads(Path(args.input).read_text())
    if isinstance(raw, dict) and "cookies" in raw:
        cookies_in = raw["cookies"]
    elif isinstance(raw, list):
        cookies_in = raw
    else:
        raise SystemExit("input JSON must be a list or {cookies: [...]}")

    cookies_out = []
    for c in cookies_in:
        try:
            cookies_out.append(_normalize_cookie(c))
        except KeyError as e:
            print(f"[skip] missing field {e} in cookie {c.get('name')}",
                  file=sys.stderr)

    state = {"cookies": cookies_out, "origins": []}
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(state, indent=2))
    print(f"wrote {len(cookies_out)} cookies → {out_path}")
    domains = sorted({c["domain"] for c in cookies_out})
    print(f"domains: {domains}")


if __name__ == "__main__":
    main()

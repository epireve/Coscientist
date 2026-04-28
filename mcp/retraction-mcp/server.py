#!/usr/bin/env python3
"""retraction-mcp — stdio MCP server for Retraction Watch + PubPeer lookups.

Three tools:
  lookup_doi(doi)         — Crossref-based retraction status for one DOI.
  batch_lookup(dois)      — same, vectorized over a list (sequential, polite).
  pubpeer_comments(doi)   — PubPeer comment count + URL for one DOI.

Sources:
  - Crossref `/works/{doi}` exposes the `update-to` field, which records
    formal retraction / correction notices linked from the original DOI.
    Public, no API key required.
  - PubPeer `https://api.pubpeer.com/v3/publications/?q=<DOI>` returns
    comment metadata. Public, no API key required.

Pure stdlib networking via `urllib.request` + `json` to avoid adding
deps to the parent project. Caller is expected to invoke via:
    uv run --with mcp python mcp/retraction-mcp/server.py
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as e:
    raise SystemExit(
        "retraction-mcp requires the `mcp` package. Run via:\n"
        "  uv run --with mcp python mcp/retraction-mcp/server.py\n"
        f"(import error: {e})"
    )


_USER_AGENT = "coscientist-retraction-mcp/0.1 (mailto:i@firdaus.my)"
_CROSSREF_BASE = "https://api.crossref.org/works/"
_PUBPEER_BASE = "https://api.pubpeer.com/v3/publications/"
_TIMEOUT = 15.0


def _http_get_json(url: str) -> dict[str, Any]:
    """GET a URL, parse JSON. Raises on HTTP error."""
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _normalize_doi(doi: str) -> str:
    """Strip leading 'doi:' / URL prefixes; lowercase."""
    s = doi.strip()
    for prefix in ("doi:", "https://doi.org/", "http://doi.org/",
                   "https://dx.doi.org/", "http://dx.doi.org/"):
        if s.lower().startswith(prefix):
            s = s[len(prefix):]
            break
    return s.lower()


def _parse_crossref_message(msg: dict[str, Any]) -> dict[str, Any]:
    """Pull retraction-relevant fields out of a Crossref `message`."""
    update_to = msg.get("update-to") or []
    updated_by = msg.get("updated-by") or []
    has_retraction = any(
        (u.get("type") or "").lower() == "retraction"
        for u in update_to + updated_by
    )
    has_correction = any(
        (u.get("type") or "").lower()
        in ("correction", "erratum", "expression-of-concern")
        for u in update_to + updated_by
    )
    notices: list[dict[str, Any]] = []
    for u in update_to + updated_by:
        notices.append({
            "type": u.get("type"),
            "doi": u.get("DOI"),
            "label": u.get("label"),
            "date": (u.get("updated") or {}).get("date-parts"),
        })
    return {
        "title": (msg.get("title") or [None])[0],
        "container": (msg.get("container-title") or [None])[0],
        "year": ((msg.get("issued") or {}).get("date-parts") or [[None]])[0][0],
        "is_retracted": has_retraction,
        "has_correction_or_eoc": has_correction,
        "notices": notices,
    }


mcp = FastMCP("retraction-mcp")


@mcp.tool()
def lookup_doi(doi: str) -> dict[str, Any]:
    """Look up retraction status for one DOI via Crossref.

    Returns:
      {
        "doi": <normalized>,
        "found": bool,
        "is_retracted": bool,
        "has_correction_or_eoc": bool,
        "notices": [{type, doi, label, date}, ...],
        "title": str | None,
        "container": str | None,
        "year": int | None,
        "source": "crossref"
      }

    Errors are returned as {"doi": <doi>, "found": False, "error": <msg>}.
    """
    norm = _normalize_doi(doi)
    if not norm:
        return {"doi": doi, "found": False, "error": "empty DOI"}
    url = _CROSSREF_BASE + urllib.parse.quote(norm, safe="")
    try:
        data = _http_get_json(url)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"doi": norm, "found": False,
                    "error": "not in Crossref"}
        return {"doi": norm, "found": False, "error": f"HTTP {e.code}"}
    except Exception as e:
        return {"doi": norm, "found": False, "error": str(e)}
    msg = data.get("message") or {}
    parsed = _parse_crossref_message(msg)
    return {"doi": norm, "found": True, "source": "crossref", **parsed}


@mcp.tool()
def batch_lookup(dois: list[str], delay_seconds: float = 0.2) -> list[dict[str, Any]]:
    """Look up multiple DOIs sequentially with a polite per-request delay.

    Crossref is generous (~50 rps) but we throttle to be a good neighbor.
    Returns a list of per-DOI lookup results in input order.
    """
    out: list[dict[str, Any]] = []
    for i, doi in enumerate(dois):
        if i > 0 and delay_seconds > 0:
            time.sleep(delay_seconds)
        out.append(lookup_doi(doi))
    return out


@mcp.tool()
def pubpeer_comments(doi: str) -> dict[str, Any]:
    """Look up PubPeer comment metadata for one DOI.

    Returns:
      {
        "doi": <normalized>,
        "found": bool,
        "comment_count": int,
        "publication_url": str | None,
        "source": "pubpeer"
      }
    """
    norm = _normalize_doi(doi)
    if not norm:
        return {"doi": doi, "found": False, "error": "empty DOI"}
    url = f"{_PUBPEER_BASE}?q={urllib.parse.quote(norm, safe='')}"
    try:
        data = _http_get_json(url)
    except urllib.error.HTTPError as e:
        return {"doi": norm, "found": False, "error": f"HTTP {e.code}"}
    except Exception as e:
        return {"doi": norm, "found": False, "error": str(e)}
    pubs = data.get("data") or data.get("publications") or []
    if not pubs:
        return {"doi": norm, "found": False, "comment_count": 0,
                "publication_url": None, "source": "pubpeer"}
    pub = pubs[0]
    return {
        "doi": norm,
        "found": True,
        "comment_count": int(
            pub.get("comments_count") or pub.get("total_comments") or 0
        ),
        "publication_url": pub.get("url"),
        "source": "pubpeer",
    }


if __name__ == "__main__":
    mcp.run()

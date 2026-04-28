"""v0.144 — OpenAlex API client + result cache.

Pure-stdlib urllib client for https://api.openalex.org. Free
polite-pool (10 req/s with mailto identifier) or premium API
key (100 req/s).

Auth precedence:
  1. Constructor api_key kwarg
  2. $OPENALEX_API_KEY env
  3. Constructor mailto kwarg (polite-pool)
  4. $OPENALEX_MAILTO env (polite-pool)
  5. None (anonymous, lower rate limits)

All methods return dict|list (success) or {"error": str} (failure).
Never raises — observability discipline.

**Cost optimization (v0.144)**:
  - Result cache (SQLite) keyed by (path, params). 30-day TTL
    by default. Configurable per-instance.
  - `select` parameter on search_works to slim payloads.
  - Batched id lookups via `filter=ids.openalex:W1|W2|W3` for up
    to 50 IDs per call.
  - Polite-pool is the recommended default (free, sufficient for
    coscientist workloads at ~700 calls/day).

Trace integration: every call emits a `tool-call` span via
`maybe_emit_tool_call` when env trace context set.
Rate-limit integration: per-call `lib.rate_limit.wait` against
`api.openalex.org` domain.

Spec reference: https://docs.openalex.org/api-entities/works
Auth reference: https://developers.openalex.org/api-reference/authentication
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

_BASE = "https://api.openalex.org"
_DEFAULT_PER_PAGE = 25
_MAX_PER_PAGE = 200  # OpenAlex hard limit
_MAX_BATCH_IDS = 50  # OpenAlex `filter=ids.openalex:A|B|C` limit
_USER_AGENT = "coscientist-openalex-client/0.144"
_DEFAULT_TIMEOUT = 30.0
_DEFAULT_CACHE_TTL_DAYS = 30
_CACHE_TABLE = """
    CREATE TABLE IF NOT EXISTS openalex_cache (
        cache_key TEXT PRIMARY KEY,
        response_json TEXT NOT NULL,
        fetched_at TEXT NOT NULL
    )
"""


def _resolve_auth(
    *,
    api_key: str | None = None,
    mailto: str | None = None,
) -> tuple[str | None, str | None]:
    """Return (api_key, mailto) with env fallback."""
    key = api_key or os.environ.get("OPENALEX_API_KEY")
    mail = mailto or os.environ.get("OPENALEX_MAILTO")
    return key, mail


def _cache_key(path: str, params: dict) -> str:
    """Canonical key: path + sorted params (auth excluded)."""
    relevant = {
        k: v for k, v in (params or {}).items()
        if k not in ("api_key", "mailto")
    }
    parts = [path]
    for k in sorted(relevant.keys()):
        parts.append(f"{k}={relevant[k]}")
    return "|".join(parts)


def _default_cache_path():
    from pathlib import Path as _P
    try:
        from lib.cache import cache_root
        return cache_root() / "openalex_cache.db"
    except Exception:
        return _P.home() / ".cache" / "coscientist" / "openalex_cache.db"


def _normalize_id(oa_id_or_url: str) -> str:
    """Accept full URL, work ID with W prefix, or DOI.

    Examples:
      'W2741809807' → 'W2741809807'
      'https://openalex.org/W2741809807' → 'W2741809807'
      '10.7717/peerj.4375' → 'doi:10.7717/peerj.4375'
      'doi:10.7717/peerj.4375' → 'doi:10.7717/peerj.4375'
    """
    s = oa_id_or_url.strip()
    if s.startswith("https://openalex.org/"):
        s = s[len("https://openalex.org/"):]
    if s.startswith("http://openalex.org/"):
        s = s[len("http://openalex.org/"):]
    if s.startswith("doi:") or s.startswith("orcid:") \
            or s.startswith("ror:") or s.startswith("pmid:"):
        return s
    if s.startswith("10."):
        return f"doi:{s}"
    return s


class OpenAlexClient:
    """Stdlib HTTP client for OpenAlex.

    Construct once per session; thread-safe (no mutable state
    after init). All methods are stateless GET + JSON parse.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        mailto: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
        rate_limit_domain: str | None = "api.openalex.org",
        cache_enabled: bool = True,
        cache_path: "str | None" = None,
        cache_ttl_days: int = _DEFAULT_CACHE_TTL_DAYS,
    ):
        self._api_key, self._mailto = _resolve_auth(
            api_key=api_key, mailto=mailto,
        )
        self.timeout = timeout
        self._rate_limit_domain = rate_limit_domain
        self._cache_enabled = cache_enabled
        from pathlib import Path as _P
        self._cache_path = (
            _P(cache_path) if cache_path
            else _default_cache_path()
        )
        self._cache_ttl_days = cache_ttl_days

    # -------- Cache --------

    def _cache_get(self, key: str) -> Any:
        """Look up cached response. None on miss/expired/disabled."""
        if not self._cache_enabled:
            return None
        try:
            import sqlite3
            from datetime import UTC, datetime, timedelta
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            con = sqlite3.connect(self._cache_path)
            try:
                con.execute(_CACHE_TABLE)
                row = con.execute(
                    "SELECT response_json, fetched_at "
                    "FROM openalex_cache WHERE cache_key=?",
                    (key,),
                ).fetchone()
                if not row:
                    return None
                fetched = datetime.fromisoformat(
                    row[1].replace("Z", "+00:00"),
                )
                age = datetime.now(UTC) - fetched
                if age > timedelta(days=self._cache_ttl_days):
                    return None  # expired
                return json.loads(row[0])
            finally:
                con.close()
        except Exception:
            return None  # cache failures must never block

    def _cache_put(self, key: str, response: Any) -> None:
        """Persist response to cache. Silent on errors."""
        if not self._cache_enabled:
            return
        if isinstance(response, dict) and "error" in response:
            return  # don't cache errors
        try:
            import sqlite3
            from datetime import UTC, datetime
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            con = sqlite3.connect(self._cache_path)
            try:
                con.execute(_CACHE_TABLE)
                with con:
                    con.execute(
                        "INSERT OR REPLACE INTO openalex_cache "
                        "(cache_key, response_json, fetched_at) "
                        "VALUES (?, ?, ?)",
                        (key, json.dumps(response),
                         datetime.now(UTC).isoformat()),
                    )
            finally:
                con.close()
        except Exception:
            pass

    def cache_stats(self) -> dict:
        """Return cache size + age stats. Useful for monitoring."""
        if not self._cache_enabled:
            return {"enabled": False}
        try:
            import sqlite3
            con = sqlite3.connect(self._cache_path)
            try:
                con.execute(_CACHE_TABLE)
                row = con.execute(
                    "SELECT COUNT(*), MIN(fetched_at), MAX(fetched_at) "
                    "FROM openalex_cache",
                ).fetchone()
                return {
                    "enabled": True,
                    "n_rows": row[0] or 0,
                    "oldest": row[1],
                    "newest": row[2],
                    "path": str(self._cache_path),
                    "ttl_days": self._cache_ttl_days,
                }
            finally:
                con.close()
        except Exception as e:
            return {"enabled": True, "error": str(e)}

    def cache_clear(self) -> int:
        """Drop all cache rows. Returns number deleted."""
        try:
            import sqlite3
            con = sqlite3.connect(self._cache_path)
            try:
                con.execute(_CACHE_TABLE)
                with con:
                    cur = con.execute(
                        "DELETE FROM openalex_cache",
                    )
                    return cur.rowcount or 0
            finally:
                con.close()
        except Exception:
            return 0

    def _request(
        self,
        path: str,
        params: dict | None = None,
    ) -> Any:
        """GET request with cache + auth + rate-limit."""
        # Cache lookup first (cuts API calls on repeat lookups)
        ck = _cache_key(path, params or {})
        cached = self._cache_get(ck)
        if cached is not None:
            # Trace cache hit
            try:
                from lib.trace import maybe_emit_tool_call
                maybe_emit_tool_call(
                    f"openalex_cache/{path.lstrip('/').split('/')[0]}",
                    args_summary={"path": path, "cache": "hit"},
                    result_summary={"cached": True},
                )
            except Exception:
                pass
            return cached

        full_params = dict(params or {})
        if self._api_key:
            full_params["api_key"] = self._api_key
        elif self._mailto:
            full_params["mailto"] = self._mailto
        url = _BASE + path
        if full_params:
            url += "?" + urllib.parse.urlencode(full_params)

        # Rate limit before issuing request
        if self._rate_limit_domain:
            try:
                from lib.rate_limit import wait
                # 0.1s for premium, 1.0s for free polite-pool,
                # but rate_limit module operates in seconds; use
                # short delay since OpenAlex burst tolerance is
                # generous.
                delay = 0.1 if self._api_key else 1.0
                wait(self._rate_limit_domain, delay_seconds=delay)
            except Exception:
                pass

        req = urllib.request.Request(
            url,
            headers={"User-Agent": _USER_AGENT},
        )
        result: Any
        error: str | None = None
        try:
            with urllib.request.urlopen(
                req, timeout=self.timeout,
            ) as resp:
                body = resp.read().decode("utf-8")
            result = json.loads(body)
        except urllib.error.HTTPError as e:
            try:
                err_body = e.read().decode("utf-8", errors="replace")
            except Exception:
                err_body = ""
            error = f"HTTP {e.code}: {err_body[:200]}"
            result = {"error": error}
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            error = f"network error: {e}"
            result = {"error": error}
        except json.JSONDecodeError as e:
            error = f"JSON decode error: {e}"
            result = {"error": error}

        # Cache on success
        if not error:
            self._cache_put(ck, result)

        # Trace emit (best-effort)
        try:
            from lib.trace import maybe_emit_tool_call
            n_results = 0
            if isinstance(result, dict):
                if "results" in result and isinstance(
                    result["results"], list,
                ):
                    n_results = len(result["results"])
                elif "id" in result:
                    n_results = 1
            maybe_emit_tool_call(
                f"openalex/{path.lstrip('/').split('/')[0]}",
                args_summary={
                    "path": path,
                    "params_keys": sorted(full_params.keys()),
                },
                result_summary={
                    "n_results": n_results,
                    "auth": (
                        "key" if self._api_key
                        else "mailto" if self._mailto
                        else "anon"
                    ),
                },
                error=error,
            )
        except Exception:
            pass

        return result

    # -------- Works (papers) --------

    def get_work(self, oa_id_or_doi: str) -> dict[str, Any]:
        """Fetch one work by OpenAlex ID, DOI, PMID, or arXiv ID."""
        norm = _normalize_id(oa_id_or_doi)
        return self._request(f"/works/{norm}")

    def get_works_batch(
        self, oa_ids: list[str], *, select: list[str] | None = None,
    ) -> dict[str, Any]:
        """Fetch up to 50 works in one request via OR filter.

        v0.144 cost optimization: 50× fewer API calls vs N
        individual `get_work` calls. Returns OpenAlex search-shape:
        {"meta": ..., "results": [...]}.

        IDs must be OpenAlex `Wxxx` form (DOIs not supported in
        batch filter — use one-shot get_work for those).
        """
        if not oa_ids:
            return {"meta": {}, "results": []}
        # Normalize + drop non-W prefixes
        norm_ids = []
        for x in oa_ids:
            n = _normalize_id(x)
            if n.startswith("W") and not n.startswith("doi:"):
                norm_ids.append(n)
        if not norm_ids:
            return {
                "error": "no valid Wxxx IDs in batch",
                "meta": {}, "results": [],
            }
        # Chunk into max 50
        all_results: list[dict] = []
        last_meta: dict = {}
        for i in range(0, len(norm_ids), _MAX_BATCH_IDS):
            chunk = norm_ids[i:i + _MAX_BATCH_IDS]
            params: dict[str, str] = {
                "filter": f"ids.openalex:{'|'.join(chunk)}",
                "per_page": str(min(len(chunk), _MAX_PER_PAGE)),
            }
            if select:
                params["select"] = ",".join(select)
            res = self._request("/works", params)
            if isinstance(res, dict) and "error" in res:
                continue  # skip failed chunks; partial OK
            last_meta = res.get("meta") or last_meta
            all_results.extend(res.get("results") or [])
        return {"meta": last_meta, "results": all_results}

    def search_works(
        self,
        query: str,
        *,
        per_page: int = _DEFAULT_PER_PAGE,
        page: int = 1,
        filters: dict[str, str] | None = None,
        sort: str | None = None,
        select: list[str] | None = None,
    ) -> dict[str, Any]:
        """Search works by query string.

        Returns: {meta, results: [...], group_by: ?}.
        meta has next_cursor for pagination beyond page 1.
        """
        params: dict[str, str] = {
            "search": query,
            "per_page": str(min(per_page, _MAX_PER_PAGE)),
            "page": str(page),
        }
        if filters:
            params["filter"] = ",".join(
                f"{k}:{v}" for k, v in filters.items()
            )
        if sort:
            params["sort"] = sort
        if select:
            params["select"] = ",".join(select)
        return self._request("/works", params)

    def get_work_references(
        self, oa_id: str,
    ) -> list[dict[str, Any]]:
        """Return list of referenced works (cited papers).

        Wraps get_work + extracts referenced_works field.
        """
        work = self.get_work(oa_id)
        if "error" in work:
            return [work]
        return work.get("referenced_works") or []

    def get_cited_by(
        self,
        oa_id: str,
        *,
        per_page: int = _DEFAULT_PER_PAGE,
    ) -> dict[str, Any]:
        """Return papers that cite the given work."""
        norm = _normalize_id(oa_id)
        return self._request(
            "/works",
            {
                "filter": f"cites:{norm}",
                "per_page": str(min(per_page, _MAX_PER_PAGE)),
            },
        )

    def fulltext_search(
        self,
        query: str,
        *,
        per_page: int = _DEFAULT_PER_PAGE,
    ) -> dict[str, Any]:
        """Full-text search inside paper bodies (OA papers only).

        Coverage ~50% of corpus (subset that's OA + parsed).
        Returns same shape as search_works.
        """
        return self._request(
            "/works",
            {
                "fulltext.search": query,
                "per_page": str(min(per_page, _MAX_PER_PAGE)),
            },
        )

    # -------- Authors --------

    def get_author(self, oa_id_or_orcid: str) -> dict[str, Any]:
        """Fetch author by OpenAlex ID or ORCID."""
        norm = _normalize_id(oa_id_or_orcid)
        return self._request(f"/authors/{norm}")

    def search_authors(
        self,
        query: str,
        *,
        per_page: int = _DEFAULT_PER_PAGE,
    ) -> dict[str, Any]:
        return self._request(
            "/authors",
            {
                "search": query,
                "per_page": str(min(per_page, _MAX_PER_PAGE)),
            },
        )

    # -------- Institutions --------

    def get_institution(self, oa_id_or_ror: str) -> dict[str, Any]:
        """Fetch institution by OpenAlex ID or ROR."""
        norm = _normalize_id(oa_id_or_ror)
        return self._request(f"/institutions/{norm}")

    # -------- Topics --------

    def get_topic(self, oa_id: str) -> dict[str, Any]:
        norm = _normalize_id(oa_id)
        return self._request(f"/topics/{norm}")

    # -------- Helper extractors --------

    @staticmethod
    def extract_oa_url(work: dict) -> str | None:
        """Pull best OA PDF URL from a work record.

        Order of preference:
          1. open_access.oa_url (curated)
          2. primary_location.pdf_url (when is_oa)
          3. any locations[].pdf_url (when is_oa)
        Returns None when no OA URL available.
        """
        if "error" in work:
            return None
        oa = work.get("open_access") or {}
        if oa.get("oa_url"):
            return oa["oa_url"]
        primary = work.get("primary_location") or {}
        if primary.get("is_oa") and primary.get("pdf_url"):
            return primary["pdf_url"]
        for loc in (work.get("locations") or []):
            if loc.get("is_oa") and loc.get("pdf_url"):
                return loc["pdf_url"]
        return None

    @staticmethod
    def reconstruct_abstract(
        inverted_index: dict[str, list[int]] | None,
    ) -> str:
        """OpenAlex stores abstracts as inverted index for legal
        reasons (avoids being a 'reproduction'). Rebuild plain text.
        """
        if not inverted_index:
            return ""
        positions: dict[int, str] = {}
        for word, idxs in inverted_index.items():
            for i in idxs:
                positions[i] = word
        if not positions:
            return ""
        n = max(positions.keys()) + 1
        return " ".join(
            positions.get(i, "") for i in range(n)
        ).strip()

    @staticmethod
    def extract_topics(
        work: dict, *, min_score: float = 0.5,
    ) -> list[dict[str, Any]]:
        """Filter topics by score threshold; return list of
        {id, display_name, score, level, wikidata_id?}."""
        if "error" in work:
            return []
        out = []
        for t in (work.get("topics") or []):
            score = float(t.get("score") or 0.0)
            if score < min_score:
                continue
            out.append({
                "id": t.get("id"),
                "display_name": t.get("display_name"),
                "score": score,
                "level": t.get("level"),
                "wikidata_id": (
                    t.get("subfield", {}).get("id")
                    if t.get("subfield") else None
                ),
            })
        return out


def main(argv: list[str] | None = None) -> int:
    """CLI: smoke-test client against live API."""
    import argparse
    import sys
    p = argparse.ArgumentParser(prog="openalex_client")
    sub = p.add_subparsers(dest="cmd", required=True)

    pg = sub.add_parser("get-work")
    pg.add_argument("--id", required=True,
                     help="OpenAlex ID, DOI, PMID, or arXiv ID")

    ps = sub.add_parser("search")
    ps.add_argument("--query", required=True)
    ps.add_argument("--per-page", type=int, default=10)

    pa = sub.add_parser("get-author")
    pa.add_argument("--id", required=True,
                     help="OpenAlex ID or ORCID")

    args = p.parse_args(argv)
    client = OpenAlexClient()

    if args.cmd == "get-work":
        out = client.get_work(args.id)
    elif args.cmd == "search":
        out = client.search_works(
            args.query, per_page=args.per_page,
        )
    elif args.cmd == "get-author":
        out = client.get_author(args.id)
    else:
        return 2

    sys.stdout.write(json.dumps(out, indent=2)[:5000] + "\n")
    return 0 if not (
        isinstance(out, dict) and "error" in out
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())

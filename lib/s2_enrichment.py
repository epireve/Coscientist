"""v0.149 — Semantic Scholar enrichment client.

Pure-stdlib S2 client focused on the **enrichment phase** —
fetches TL;DR, SPECTER2 embedding, influential-citation count, and
the citation/reference graph for batches of already-triaged papers.

Why a second client (separate from OpenAlex):
  - S2 has data OpenAlex lacks: TLDR (SPECTER2), embeddings,
    influentialCitationCount.
  - Discovery flow stays on Consensus; ingestion stays on OpenAlex.
  - This module is for the *triaged* set only — top-N candidates
    after discovery has decided what's worth paying attention to.

Auth precedence: kwarg → `S2_API_KEY` env → anonymous.
Rate limit: anon 1 req/s; with key 100 req/s. Default uses
`lib.rate_limit` against domain `api.semanticscholar.org`.

Trace: emits `tool-call` spans `s2/<endpoint>` when
`COSCIENTIST_TRACE_DB` + `COSCIENTIST_TRACE_ID` env set.
Cache: SQLite-backed at
`~/.cache/coscientist/s2_cache.db`, 30-day TTL.

CLI:
    uv run python -m lib.s2_enrichment batch --ids 'DOI:10.1/x,W123' \\
        --fields tldr,embedding,influentialCitationCount

All errors return `{"error": str}` — never raises in caller-facing API.
"""
from __future__ import annotations

import json
import os
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from lib.cache import cache_root, connect_wal
from lib.rate_limit import wait as rate_wait

S2_BASE = "https://api.semanticscholar.org/graph/v1"
DEFAULT_FIELDS = (
    "paperId,corpusId,title,abstract,tldr,embedding,"
    "influentialCitationCount,citationCount,referenceCount,"
    "openAccessPdf,externalIds,authors,year,venue,publicationDate,"
    "fieldsOfStudy,s2FieldsOfStudy"
)
BATCH_LIMIT = 500


def _resolve_auth(*, api_key: str | None = None) -> str | None:
    if api_key:
        return api_key
    return os.environ.get("S2_API_KEY") or None


def _default_cache_path() -> Path:
    return cache_root() / "s2_cache.db"


def _cache_key(path: str, params: dict | None, body: Any | None = None) -> str:
    """Stable key. Auth headers are NOT part of the key — same query
    with/without key hits same cache."""
    p = sorted((params or {}).items())
    base = f"{path}?{urllib.parse.urlencode(p)}"
    if body is not None:
        base += f"|body={json.dumps(body, sort_keys=True)}"
    return base


def _maybe_emit_tool_call(*args, **kwargs):
    """Best-effort wrapper around lib.trace.maybe_emit_tool_call. Silent
    no-op on any failure to avoid breaking callers."""
    try:
        from lib.trace import maybe_emit_tool_call
        maybe_emit_tool_call(*args, **kwargs)
    except Exception:
        pass


class S2Client:
    """Semantic Scholar Graph API client (enrichment phase).

    Public methods:
        batch_get_papers(ids, *, fields=None) -> dict
        get_paper(paper_id, *, fields=None) -> dict
        get_paper_references(paper_id, *, limit=100, fields=None) -> dict
        get_paper_citations(paper_id, *, limit=100, fields=None) -> dict
        search_papers(query, *, limit=10, fields=None) -> dict
        cache_stats() -> dict
        cache_clear() -> int
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        timeout: float = 30.0,
        rate_limit_domain: str = "api.semanticscholar.org",
        cache_enabled: bool = True,
        cache_path: Path | None = None,
        cache_ttl_days: int = 30,
    ):
        self._api_key = _resolve_auth(api_key=api_key)
        self._timeout = timeout
        self._rate_domain = rate_limit_domain
        self._cache_enabled = cache_enabled
        self._cache_path = cache_path or _default_cache_path()
        self._cache_ttl = timedelta(days=cache_ttl_days)
        if self._cache_enabled:
            self._init_cache()

    # ---- cache --------------------------------------------------------

    def _init_cache(self) -> None:
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            con = connect_wal(self._cache_path)
            try:
                con.execute(
                    "CREATE TABLE IF NOT EXISTS s2_cache ("
                    "  cache_key TEXT PRIMARY KEY,"
                    "  response_json TEXT NOT NULL,"
                    "  fetched_at TEXT NOT NULL"
                    ")"
                )
                con.commit()
            finally:
                con.close()
        except Exception:
            self._cache_enabled = False

    def _cache_get(self, key: str) -> Any | None:
        if not self._cache_enabled:
            return None
        try:
            con = sqlite3.connect(self._cache_path)
            try:
                row = con.execute(
                    "SELECT response_json, fetched_at FROM s2_cache "
                    "WHERE cache_key=?",
                    (key,),
                ).fetchone()
            finally:
                con.close()
            if not row:
                return None
            fetched = datetime.fromisoformat(row[1])
            if datetime.now(UTC) - fetched > self._cache_ttl:
                return None
            return json.loads(row[0])
        except Exception:
            return None

    def _cache_put(self, key: str, response: Any) -> None:
        if not self._cache_enabled:
            return
        if isinstance(response, dict) and "error" in response:
            return  # don't cache errors
        try:
            con = connect_wal(self._cache_path)
            try:
                con.execute(
                    "INSERT OR REPLACE INTO s2_cache "
                    "(cache_key, response_json, fetched_at) "
                    "VALUES (?, ?, ?)",
                    (
                        key,
                        json.dumps(response),
                        datetime.now(UTC).isoformat(),
                    ),
                )
                con.commit()
            finally:
                con.close()
        except Exception:
            pass

    def cache_stats(self) -> dict:
        if not self._cache_enabled:
            return {"enabled": False}
        try:
            con = sqlite3.connect(self._cache_path)
            try:
                row = con.execute(
                    "SELECT COUNT(*), MIN(fetched_at), MAX(fetched_at) "
                    "FROM s2_cache"
                ).fetchone()
            finally:
                con.close()
            return {
                "enabled": True,
                "path": str(self._cache_path),
                "entries": row[0],
                "oldest": row[1],
                "newest": row[2],
                "ttl_days": self._cache_ttl.days,
            }
        except Exception as e:
            return {"enabled": True, "error": str(e)}

    def cache_clear(self) -> int:
        if not self._cache_enabled:
            return 0
        try:
            con = connect_wal(self._cache_path)
            try:
                cur = con.execute("DELETE FROM s2_cache")
                con.commit()
                return cur.rowcount or 0
            finally:
                con.close()
        except Exception:
            return 0

    # ---- request core -------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        body: Any | None = None,
    ) -> Any:
        # Try cache first (GET only — POST batch endpoint uses body for key).
        cache_key = _cache_key(path, params, body)
        cached = self._cache_get(cache_key)
        if cached is not None:
            _maybe_emit_tool_call(
                tool_name=f"s2_cache/{path.strip('/')}",
                args_summary=json.dumps(
                    {"params": params or {}, "ids": _ids_summary(body)}),
                result_summary=json.dumps({"hit": True}),
            )
            return cached

        rate_wait(self._rate_domain)

        url = S2_BASE + path
        if params:
            url += "?" + urllib.parse.urlencode(params)

        headers = {"Accept": "application/json",
                   "User-Agent": "coscientist/0.149"}
        if self._api_key:
            headers["x-api-key"] = self._api_key

        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(
            url, data=data, headers=headers, method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            _maybe_emit_tool_call(
                tool_name=f"s2/{path.strip('/')}",
                args_summary=json.dumps(
                    {"params": params or {}, "ids": _ids_summary(body)}),
                result_summary=json.dumps({"status": "ok"}),
            )
            self._cache_put(cache_key, payload)
            return payload
        except urllib.error.HTTPError as e:
            err = {"error": f"HTTP {e.code}: {e.reason}",
                   "status": e.code}
            _maybe_emit_tool_call(
                tool_name=f"s2/{path.strip('/')}",
                args_summary=json.dumps(
                    {"params": params or {}, "ids": _ids_summary(body)}),
                result_summary=json.dumps(err),
                error=err["error"],
            )
            return err
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            err = {"error": f"network: {e}"}
            _maybe_emit_tool_call(
                tool_name=f"s2/{path.strip('/')}",
                args_summary=json.dumps({"params": params or {}}),
                result_summary=json.dumps(err),
                error=err["error"],
            )
            return err
        except json.JSONDecodeError as e:
            return {"error": f"invalid JSON: {e}"}

    # ---- public API ---------------------------------------------------

    def batch_get_papers(
        self,
        ids: list[str],
        *,
        fields: str | None = None,
    ) -> dict:
        """Batch-fetch up to 500 papers in a single request.

        `ids` accept multiple formats: bare paperId, `DOI:...`,
        `ARXIV:...`, `MAG:...`, `ACL:...`, `PMID:...`, `PMCID:...`,
        `URL:...`, `CorpusId:...`. S2 resolves each.

        Returns: `{"results": list[paper-dict | None]}` aligned with
        input order. None for IDs that didn't match.
        Or `{"error": str}` on failure.
        """
        if not ids:
            return {"results": []}
        if len(ids) > BATCH_LIMIT:
            return {"error": f"batch size {len(ids)} exceeds {BATCH_LIMIT}"}
        params = {"fields": fields or DEFAULT_FIELDS}
        res = self._request("POST", "/paper/batch",
                            params=params, body={"ids": ids})
        if isinstance(res, list):
            return {"results": res}
        if isinstance(res, dict) and "error" in res:
            return res
        return {"error": "unexpected response shape"}

    def get_paper(
        self,
        paper_id: str,
        *,
        fields: str | None = None,
    ) -> dict:
        params = {"fields": fields or DEFAULT_FIELDS}
        return self._request("GET", f"/paper/{paper_id}", params=params)

    def get_paper_references(
        self,
        paper_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
        fields: str | None = None,
    ) -> dict:
        params = {
            "limit": limit, "offset": offset,
            "fields": fields or "title,authors,year,externalIds",
        }
        return self._request(
            "GET", f"/paper/{paper_id}/references", params=params,
        )

    def get_paper_citations(
        self,
        paper_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
        fields: str | None = None,
    ) -> dict:
        params = {
            "limit": limit, "offset": offset,
            "fields": fields or "title,authors,year,externalIds,"
                                "influentialCitationCount",
        }
        return self._request(
            "GET", f"/paper/{paper_id}/citations", params=params,
        )

    def search_papers(
        self,
        query: str,
        *,
        limit: int = 10,
        offset: int = 0,
        fields: str | None = None,
    ) -> dict:
        params = {
            "query": query, "limit": limit, "offset": offset,
            "fields": fields or DEFAULT_FIELDS,
        }
        return self._request("GET", "/paper/search", params=params)

    # ---- static helpers ----------------------------------------------

    @staticmethod
    def extract_tldr(paper: dict) -> str | None:
        """Return TL;DR text or None."""
        if not isinstance(paper, dict):
            return None
        tldr = paper.get("tldr")
        if isinstance(tldr, dict):
            return tldr.get("text")
        return None

    @staticmethod
    def extract_embedding(paper: dict) -> list[float] | None:
        """Return SPECTER2 embedding vector or None."""
        if not isinstance(paper, dict):
            return None
        emb = paper.get("embedding")
        if isinstance(emb, dict):
            return emb.get("vector")
        return None

    @staticmethod
    def extract_influential_count(paper: dict) -> int:
        """Return influentialCitationCount or 0."""
        if not isinstance(paper, dict):
            return 0
        v = paper.get("influentialCitationCount")
        return int(v) if v is not None else 0

    @staticmethod
    def extract_external_ids(paper: dict) -> dict:
        """Pull every ID S2 emits — DOI, ArXiv, MAG, PubMed, ACL,
        PMC, CorpusId. Returns `{}` on missing.
        """
        if not isinstance(paper, dict):
            return {}
        ext = paper.get("externalIds") or {}
        out = {}
        for k, v in ext.items():
            if v is None:
                continue
            kk = k.lower()
            if kk == "doi":
                out["doi"] = str(v).lower()
            elif kk == "arxiv":
                out["arxiv_id"] = v
            elif kk in ("pubmed", "pmid"):
                out["pmid"] = str(v)
            elif kk == "pubmedcentral":
                out["pmcid"] = v
            elif kk == "mag":
                out["mag_id"] = str(v)
            elif kk == "acl":
                out["acl_id"] = v
            elif kk == "corpusid":
                out["s2_corpus_id"] = str(v)
            else:
                out[kk] = v
        if paper.get("paperId"):
            out["s2_paper_id"] = paper["paperId"]
        return out


def _ids_summary(body: Any | None) -> int | None:
    if isinstance(body, dict) and isinstance(body.get("ids"), list):
        return len(body["ids"])
    return None


# ---------------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="s2_enrichment")
    sub = p.add_subparsers(dest="cmd", required=True)

    pb = sub.add_parser("batch", help="batch-fetch papers")
    pb.add_argument("--ids", required=True,
                    help="comma-separated S2 IDs/DOIs/ARXIV:...")
    pb.add_argument("--fields")

    pp = sub.add_parser("paper", help="single paper lookup")
    pp.add_argument("--id", required=True)
    pp.add_argument("--fields")

    ps = sub.add_parser("search", help="search papers")
    ps.add_argument("--query", required=True)
    ps.add_argument("--limit", type=int, default=10)
    ps.add_argument("--fields")

    pc = sub.add_parser("cache", help="cache info / clear")
    pc.add_argument("--clear", action="store_true")

    a = p.parse_args(argv)
    cli = S2Client()

    if a.cmd == "batch":
        ids = [s.strip() for s in a.ids.split(",") if s.strip()]
        out = cli.batch_get_papers(ids, fields=a.fields)
    elif a.cmd == "paper":
        out = cli.get_paper(a.id, fields=a.fields)
    elif a.cmd == "search":
        out = cli.search_papers(
            a.query, limit=a.limit, fields=a.fields,
        )
    elif a.cmd == "cache":
        if a.clear:
            n = cli.cache_clear()
            out = {"cleared": n}
        else:
            out = cli.cache_stats()
    else:
        p.error("unknown subcommand")
        return 2

    print(json.dumps(out, indent=2))
    return 0 if not (isinstance(out, dict) and out.get("error")) else 1


if __name__ == "__main__":
    raise SystemExit(main())

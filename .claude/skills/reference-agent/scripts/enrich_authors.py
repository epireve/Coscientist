#!/usr/bin/env python3
"""reference-agent: enrich author nodes w/ ORCID + institution data.

For every author node in a project graph (kind='author'):

1. Resolve author against OpenAlex (or S2 fallback). Resolution order:
     a. external_ids_json.openalex_author_id  → get_author(oa_id)
     b. external_ids_json.orcid               → get_author(orcid)
     c. search_authors(label)                 → best-match pick
2. Merge cross-source IDs onto the author node:
     openalex_author_id, orcid, s2_author_id (when available)
3. For each `last_known_institutions[]` entry on the resolved
   author record:
     - upsert institution node (kind=institution, ref=ror slug or
       openalex_id) with external_ids = {ror_id, openalex_id,
       country_code}, source = "openalex"
     - add `affiliated-with` edge author → institution
       (idempotent: pre-checked against project DB)

CLI:
   uv run python enrich_authors.py --project-id <pid>
       walks all author nodes in the project graph.
   uv run python enrich_authors.py --author-nid 'author:doe-j' --project-id <pid>
       enriches a single author node.
   --source openalex (default) | s2

All errors return dicts with `"error"` key — never raises.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib import graph as graph_mod  # noqa: E402
from lib.cache import cache_root  # noqa: E402


# ---------------------------------------------------------------------- helpers


def _project_db(project_id: str) -> Path:
    return cache_root() / "projects" / project_id / "project.db"


def _connect(project_id: str) -> sqlite3.Connection:
    p = _project_db(project_id)
    if not p.exists():
        raise FileNotFoundError(f"no project DB at {p}")
    con = sqlite3.connect(p)
    con.row_factory = sqlite3.Row
    return con


def _list_author_nodes(project_id: str) -> list[dict]:
    """Return [{node_id, label, external_ids, source}] for kind=author."""
    con = _connect(project_id)
    cols = [r[1] for r in con.execute("PRAGMA table_info(graph_nodes)")]
    has_v13 = "external_ids_json" in cols and "source" in cols
    if has_v13:
        rows = con.execute(
            "SELECT node_id, label, external_ids_json, source "
            "FROM graph_nodes WHERE kind='author'",
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT node_id, label FROM graph_nodes WHERE kind='author'",
        ).fetchall()
    con.close()
    out: list[dict] = []
    for r in rows:
        d = dict(r)
        ext_raw = d.get("external_ids_json")
        try:
            d["external_ids"] = json.loads(ext_raw) if ext_raw else {}
        except (TypeError, json.JSONDecodeError):
            d["external_ids"] = {}
        out.append(d)
    return out


def _get_author_node(project_id: str, nid: str) -> dict | None:
    con = _connect(project_id)
    cols = [r[1] for r in con.execute("PRAGMA table_info(graph_nodes)")]
    has_v13 = "external_ids_json" in cols and "source" in cols
    if has_v13:
        row = con.execute(
            "SELECT node_id, label, external_ids_json, source "
            "FROM graph_nodes WHERE node_id=? AND kind='author'",
            (nid,),
        ).fetchone()
    else:
        row = con.execute(
            "SELECT node_id, label FROM graph_nodes "
            "WHERE node_id=? AND kind='author'",
            (nid,),
        ).fetchone()
    con.close()
    if not row:
        return None
    d = dict(row)
    ext_raw = d.get("external_ids_json")
    try:
        d["external_ids"] = json.loads(ext_raw) if ext_raw else {}
    except (TypeError, json.JSONDecodeError):
        d["external_ids"] = {}
    return d


def _edge_exists(con, from_n: str, to_n: str, relation: str) -> bool:
    return con.execute(
        "SELECT 1 FROM graph_edges "
        "WHERE from_node=? AND to_node=? AND relation=? LIMIT 1",
        (from_n, to_n, relation),
    ).fetchone() is not None


def _add_edge_if_new(
    project_id: str, from_n: str, to_n: str, relation: str,
) -> bool:
    con = sqlite3.connect(_project_db(project_id))
    try:
        if _edge_exists(con, from_n, to_n, relation):
            return False
    finally:
        con.close()
    graph_mod.add_edge(project_id, from_n, to_n, relation)
    return True


def _strip_prefix(s: str, *prefixes: str) -> str:
    for p in prefixes:
        if s.startswith(p):
            return s[len(p):]
    return s


# ---------------------------------------------------------------------- ID extractors (OpenAlex)


def _normalize_oa_author_id(raw: str | None) -> str | None:
    if not raw:
        return None
    return _strip_prefix(
        raw, "https://openalex.org/", "http://openalex.org/",
    )


def _normalize_orcid(raw: str | None) -> str | None:
    if not raw:
        return None
    return _strip_prefix(
        raw, "https://orcid.org/", "http://orcid.org/",
    )


def _normalize_ror(raw: str | None) -> str | None:
    if not raw:
        return None
    return _strip_prefix(
        raw, "https://ror.org/", "http://ror.org/",
    )


def _ids_from_oa_author(author: dict) -> dict:
    out: dict = {}
    oa_id = _normalize_oa_author_id(author.get("id"))
    if oa_id:
        out["openalex_author_id"] = oa_id
    orcid = _normalize_orcid(author.get("orcid"))
    if orcid:
        out["orcid"] = orcid
    ids = author.get("ids") or {}
    if ids.get("scopus"):
        out["scopus_id"] = str(ids["scopus"])
    if ids.get("twitter"):
        out["twitter"] = str(ids["twitter"])
    return out


def _ids_from_oa_institution(inst: dict) -> dict:
    out: dict = {}
    oa_id = _normalize_oa_author_id(inst.get("id"))  # same prefix
    if oa_id:
        out["openalex_id"] = oa_id
    ror = _normalize_ror(inst.get("ror"))
    if ror:
        out["ror_id"] = ror
    cc = inst.get("country_code")
    if cc:
        out["country_code"] = cc
    return out


def _institution_ref(inst: dict) -> str | None:
    """Pick a stable ref for the institution node.

    Priority: ROR slug > OpenAlex id > slugged display_name.
    """
    ror = _normalize_ror(inst.get("ror"))
    if ror:
        return ror
    oa = _normalize_oa_author_id(inst.get("id"))
    if oa:
        return oa
    name = inst.get("display_name") or ""
    if name:
        import re as _re
        return _re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or None
    return None


# ---------------------------------------------------------------------- ID extractors (S2)


def _ids_from_s2_author(author: dict) -> dict:
    out: dict = {}
    if author.get("authorId"):
        out["s2_author_id"] = str(author["authorId"])
    ext = author.get("externalIds") or {}
    if ext.get("ORCID"):
        out["orcid"] = _normalize_orcid(ext["ORCID"])
    return out


# ---------------------------------------------------------------------- resolve


def _resolve_openalex(
    author_node: dict, client,
) -> tuple[dict | None, str | None]:
    """Return (author_record, error). author_record may be None."""
    ext = author_node.get("external_ids") or {}
    oa_id = ext.get("openalex_author_id")
    orcid = ext.get("orcid")
    label = author_node.get("label") or ""

    # 1) OpenAlex ID
    if oa_id:
        rec = client.get_author(oa_id)
        if isinstance(rec, dict) and "error" not in rec:
            return rec, None

    # 2) ORCID
    if orcid:
        norm = _normalize_orcid(orcid)
        # OpenAlex accepts either 'orcid:xxxx' or full URL
        rec = client.get_author(f"orcid:{norm}")
        if isinstance(rec, dict) and "error" not in rec:
            return rec, None

    # 3) Name search
    if not label:
        return None, "no openalex_author_id, orcid, or label to resolve"
    res = client.search_authors(label)
    if isinstance(res, dict) and "error" in res:
        return None, res["error"]
    candidates = (res or {}).get("results") or []
    if not candidates:
        return None, f"no OpenAlex matches for '{label}'"
    # Prefer exact display_name match; tiebreak by works_count
    exact = [
        c for c in candidates
        if (c.get("display_name") or "").lower() == label.lower()
    ]
    pool = exact if exact else candidates
    pool_sorted = sorted(
        pool, key=lambda c: c.get("works_count") or 0, reverse=True,
    )
    return pool_sorted[0], None


def _resolve_s2(
    author_node: dict, client,
) -> tuple[dict | None, str | None]:
    ext = author_node.get("external_ids") or {}
    s2_id = ext.get("s2_author_id")
    label = author_node.get("label") or ""
    if s2_id and hasattr(client, "get_author"):
        rec = client.get_author(s2_id)
        if isinstance(rec, dict) and "error" not in rec:
            return rec, None
    if not label:
        return None, "no s2_author_id or label to resolve"
    if not hasattr(client, "search_authors"):
        return None, "S2 client lacks search_authors"
    res = client.search_authors(label)
    if isinstance(res, dict) and "error" in res:
        return None, res["error"]
    data = (res or {}).get("data") or []
    if not data:
        return None, f"no S2 matches for '{label}'"
    exact = [
        c for c in data
        if (c.get("name") or "").lower() == label.lower()
    ]
    pool = exact if exact else data
    pool_sorted = sorted(
        pool, key=lambda c: c.get("paperCount") or 0, reverse=True,
    )
    return pool_sorted[0], None


# ---------------------------------------------------------------------- per-author enrichment


def _enrich_one_openalex(
    project_id: str, author_node: dict, *, client,
    s2_client=None, allow_s2_fallback: bool = True,
) -> dict:
    nid = author_node["node_id"]
    rec, err = _resolve_openalex(author_node, client)
    if err and allow_s2_fallback and s2_client is not None:
        # Fall back to S2 when OpenAlex 404s / no match
        return _enrich_one_s2(
            project_id, author_node, client=s2_client,
        )
    if err:
        return {"author_nid": nid, "error": err}

    # Merge author IDs onto node
    new_ids = _ids_from_oa_author(rec)
    try:
        graph_mod.merge_external_ids(
            project_id, nid, new_ids, source="openalex",
        )
    except Exception as e:  # noqa: BLE001
        return {"author_nid": nid, "error": f"merge failed: {e}"}

    institutions_added = 0
    edges_added = 0
    inst_seen: list[str] = []

    insts = rec.get("last_known_institutions") or []
    for inst in insts:
        if not isinstance(inst, dict):
            continue
        ref = _institution_ref(inst)
        if not ref:
            continue
        ext_ids = _ids_from_oa_institution(inst)
        # data payload — keep useful fields searchable
        data = {
            "type": inst.get("type"),
            "country_code": inst.get("country_code"),
        }
        try:
            inst_nid = graph_mod.add_node(
                project_id, "institution", ref,
                inst.get("display_name") or ref,
                data=data,
                external_ids=ext_ids or None,
                source="openalex",
            )
        except Exception as e:  # noqa: BLE001
            return {"author_nid": nid, "error": f"add_node failed: {e}"}
        # Merge IDs in case the node already existed
        if ext_ids:
            try:
                graph_mod.merge_external_ids(
                    project_id, inst_nid, ext_ids, source="openalex",
                )
            except Exception:
                pass
        institutions_added += 1
        inst_seen.append(inst_nid)
        if _add_edge_if_new(
            project_id, nid, inst_nid, "affiliated-with",
        ):
            edges_added += 1

    return {
        "author_nid": nid,
        "source": "openalex",
        "ids_merged": new_ids,
        "institutions_seen": institutions_added,
        "institution_nids": inst_seen,
        "edges_added": edges_added,
    }


def _enrich_one_s2(
    project_id: str, author_node: dict, *, client,
) -> dict:
    nid = author_node["node_id"]
    rec, err = _resolve_s2(author_node, client)
    if err:
        return {"author_nid": nid, "error": err}
    new_ids = _ids_from_s2_author(rec)
    try:
        graph_mod.merge_external_ids(
            project_id, nid, new_ids, source="s2",
        )
    except Exception as e:  # noqa: BLE001
        return {"author_nid": nid, "error": f"merge failed: {e}"}
    # S2 author records carry `affiliations` as plain strings
    # (no ROR / country). We don't synthesize institution nodes from
    # those — institution enrichment is OpenAlex-only by design.
    return {
        "author_nid": nid,
        "source": "s2",
        "ids_merged": new_ids,
        "institutions_seen": 0,
        "institution_nids": [],
        "edges_added": 0,
    }


# ---------------------------------------------------------------------- top-level


def enrich_author(
    project_id: str, author_nid: str, *,
    source: str = "openalex", client=None, s2_client=None,
) -> dict:
    """Single-author enrichment. Returns per-author result dict."""
    try:
        node = _get_author_node(project_id, author_nid)
    except FileNotFoundError as e:
        return {"error": str(e)}
    if not node:
        return {"error": f"no author node {author_nid}"}

    if source == "openalex":
        if client is None:
            try:
                from lib.openalex_client import OpenAlexClient
                client = OpenAlexClient()
            except Exception as e:  # noqa: BLE001
                return {"error": f"failed to init OpenAlexClient: {e}"}
        return _enrich_one_openalex(
            project_id, node, client=client,
            s2_client=s2_client,
            allow_s2_fallback=s2_client is not None,
        )
    elif source == "s2":
        if client is None:
            try:
                from lib.s2_enrichment import S2Client
                client = S2Client()
            except Exception as e:  # noqa: BLE001
                return {"error": f"failed to init S2Client: {e}"}
        return _enrich_one_s2(project_id, node, client=client)
    else:
        return {"error": f"unknown source: {source}"}


def enrich_project(
    project_id: str, *, source: str = "openalex",
    client=None, s2_client=None,
) -> dict:
    """Walk all author nodes in the project."""
    try:
        nodes = _list_author_nodes(project_id)
    except FileNotFoundError as e:
        return {"error": str(e)}

    if not nodes:
        return {
            "authors_processed": 0,
            "institutions_added": 0,
            "edges_added": 0,
            "errors": [],
        }

    if source == "openalex" and client is None:
        try:
            from lib.openalex_client import OpenAlexClient
            client = OpenAlexClient()
        except Exception as e:  # noqa: BLE001
            return {"error": f"failed to init OpenAlexClient: {e}"}
    if source == "s2" and client is None:
        try:
            from lib.s2_enrichment import S2Client
            client = S2Client()
        except Exception as e:  # noqa: BLE001
            return {"error": f"failed to init S2Client: {e}"}

    totals = {
        "authors_processed": 0,
        "institutions_added": 0,
        "edges_added": 0,
        "errors": [],
        "source": source,
    }
    for node in nodes:
        if source == "openalex":
            r = _enrich_one_openalex(
                project_id, node, client=client,
                s2_client=s2_client,
                allow_s2_fallback=s2_client is not None,
            )
        else:
            r = _enrich_one_s2(project_id, node, client=client)
        if "error" in r:
            totals["errors"].append({
                "author_nid": r.get("author_nid", node["node_id"]),
                "error": r["error"],
            })
            continue
        totals["authors_processed"] += 1
        totals["institutions_added"] += r.get("institutions_seen", 0)
        totals["edges_added"] += r.get("edges_added", 0)
    return totals


# ---------------------------------------------------------------------- CLI


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--project-id", required=True)
    p.add_argument(
        "--author-nid",
        help="enrich single author node (e.g. 'author:doe-j'); "
             "omit for project-wide batch",
    )
    p.add_argument(
        "--source", default="openalex",
        choices=["openalex", "s2"],
    )
    args = p.parse_args()

    if args.author_nid:
        result = enrich_author(
            args.project_id, args.author_nid, source=args.source,
        )
    else:
        result = enrich_project(args.project_id, source=args.source)

    print(json.dumps(result, indent=2))
    if isinstance(result, dict) and "error" in result:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

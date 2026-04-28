#!/usr/bin/env python3
"""reference-agent: populate citation edges in the project graph.

Two modes:

A. **File mode** (legacy / default): reads pre-fetched citation
   records from `--input` JSON and ingests edges. Backward
   compatible with v0.149 and earlier.

   Input JSON shape:

   [
     {
       "from_canonical_id": "vaswani_2017_attention_abc123",
       "references": [
         {"canonical_id": "bahdanau_2014_xxx", "title": "...", "year": 2014}
       ],
       "citations": [
         {"canonical_id": "devlin_2019_bert_yyy", "title": "...", "year": 2019}
       ]
     },
     ...
   ]

B. **Live mode** (v0.150): fetches references + citations directly
   from a backend for one paper. Selected via `--source openalex |
   s2 | s2-influential` and `--paper-id <canonical_id>`. The paper
   artifact's manifest provides the upstream ID (openalex_id, doi,
   or s2_id). For `s2-influential`, only citers/refs with
   `influentialCitationCount > 0` are kept.

For each ingested record:
- Ensure the `from` paper exists as a graph_node (create if missing)
- For each reference: create graph_node + `cites` edge from→ref +
  `cited-by` edge ref→from
- For each citation: create graph_node + `cited-by` edge from→citer
  + `cites` edge citer→from

When `source` is set, new nodes are stamped with that source
(via `lib.graph.add_node` v0.148 kwargs) and any external IDs
returned by the backend are merged onto existing nodes.

Idempotent: re-running is safe. We pre-check edge existence
against the DB before inserting.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib import graph as graph_mod  # noqa: E402
from lib.cache import cache_root  # noqa: E402
from lib.paper_artifact import PaperArtifact, canonical_id as _mk_cid  # noqa: E402


# ---------------------------------------------------------------------- helpers


def _project_db(project_id: str) -> Path:
    p = cache_root() / "projects" / project_id / "project.db"
    if not p.exists():
        raise SystemExit(f"no project DB at {p}")
    return p


def _ensure_node(
    project_id: str,
    cid: str,
    label: str,
    data: dict | None,
    *,
    external_ids: dict | None = None,
    source: str | None = None,
) -> str:
    """Create node if absent; merge external_ids on existing node."""
    nid = graph_mod.add_node(
        project_id, "paper", cid, label,
        data=data or None,
        external_ids=external_ids or None,
        source=source,
    )
    if external_ids:
        try:
            graph_mod.merge_external_ids(
                project_id, nid, external_ids, source=source,
            )
        except Exception:
            pass
    return nid


def _edge_exists(con, from_n: str, to_n: str, relation: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM graph_edges "
        "WHERE from_node=? AND to_node=? AND relation=? LIMIT 1",
        (from_n, to_n, relation),
    ).fetchone()
    return row is not None


def _add_edge_if_new(
    project_id: str, from_n: str, to_n: str, relation: str,
) -> bool:
    """Pre-check for duplicate, then insert. Returns True if added."""
    import sqlite3
    con = sqlite3.connect(_project_db(project_id))
    try:
        if _edge_exists(con, from_n, to_n, relation):
            return False
    finally:
        con.close()
    graph_mod.add_edge(project_id, from_n, to_n, relation)
    return True


# ---------------------------------------------------------------------- file mode


def populate(records: list[dict], project_id: str) -> dict:
    """Ingest legacy records (no upstream backend involved)."""
    added_edges = 0
    skipped = 0
    nodes_seen: set[str] = set()
    started = datetime.now(UTC).isoformat()

    for rec in records:
        from_cid = rec.get("from_canonical_id")
        if not from_cid:
            skipped += 1
            continue
        from_node = _ensure_node(
            project_id, from_cid, from_cid, {},
        )
        nodes_seen.add(from_node)

        for ref in rec.get("references") or []:
            rcid = ref.get("canonical_id")
            if not rcid:
                continue
            ref_node = _ensure_node(
                project_id, rcid, ref.get("title") or rcid,
                {"year": ref.get("year"), "doi": ref.get("doi")},
            )
            nodes_seen.add(ref_node)
            if _add_edge_if_new(project_id, from_node, ref_node, "cites"):
                added_edges += 1
            if _add_edge_if_new(project_id, ref_node, from_node, "cited-by"):
                added_edges += 1

        for cit in rec.get("citations") or []:
            ccid = cit.get("canonical_id")
            if not ccid:
                continue
            cit_node = _ensure_node(
                project_id, ccid, cit.get("title") or ccid,
                {"year": cit.get("year"), "doi": cit.get("doi")},
            )
            nodes_seen.add(cit_node)
            if _add_edge_if_new(project_id, cit_node, from_node, "cites"):
                added_edges += 1
            if _add_edge_if_new(project_id, from_node, cit_node, "cited-by"):
                added_edges += 1

    return {
        "edges_added": added_edges,
        "nodes_touched": len(nodes_seen),
        "skipped": skipped,
        "started_at": started,
    }


# ---------------------------------------------------------------------- live mode helpers


def _load_manifest(paper_id: str) -> dict:
    art = PaperArtifact(paper_id)
    if not art.manifest_path.exists():
        return {}
    return json.loads(art.manifest_path.read_text())


def _cid_from_openalex_work(work: dict) -> str | None:
    """Derive canonical_id for an OpenAlex `Work` dict."""
    if not isinstance(work, dict):
        return None
    title = work.get("display_name") or work.get("title") or ""
    year = work.get("publication_year")
    auths = work.get("authorships") or []
    first = None
    if auths:
        a = auths[0].get("author") or {}
        first = a.get("display_name")
    doi_url = work.get("doi") or ""
    doi = (
        doi_url.replace("https://doi.org/", "").lower()
        if doi_url else None
    )
    if not (title or doi):
        return None
    return _mk_cid(title=title, year=year, first_author=first, doi=doi)


def _ids_from_openalex_work(work: dict) -> dict:
    """Extract cross-source IDs from an OpenAlex Work."""
    out: dict = {}
    oa_id = work.get("id") or ""
    if oa_id.startswith("https://openalex.org/"):
        oa_id = oa_id[len("https://openalex.org/"):]
    if oa_id:
        out["openalex_id"] = oa_id
    doi_url = work.get("doi") or ""
    if doi_url:
        out["doi"] = doi_url.replace("https://doi.org/", "").lower()
    ids = work.get("ids") or {}
    if ids.get("pmid"):
        pmid = ids["pmid"]
        if isinstance(pmid, str) and "/" in pmid:
            pmid = pmid.rsplit("/", 1)[-1]
        out["pmid"] = str(pmid)
    if ids.get("mag"):
        out["mag_id"] = str(ids["mag"])
    return out


def _cid_from_s2_paper(paper: dict) -> str | None:
    if not isinstance(paper, dict):
        return None
    title = paper.get("title") or ""
    year = paper.get("year")
    auths = paper.get("authors") or []
    first = auths[0].get("name") if auths else None
    ext = paper.get("externalIds") or {}
    doi_raw = ext.get("DOI") or ext.get("doi")
    doi = doi_raw.lower() if isinstance(doi_raw, str) else None
    if not (title or doi):
        return None
    return _mk_cid(title=title, year=year, first_author=first, doi=doi)


def _ids_from_s2_paper(paper: dict) -> dict:
    """Lifted from S2Client.extract_external_ids without the import."""
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
        elif kk == "corpusid":
            out["s2_corpus_id"] = str(v)
    if paper.get("paperId"):
        out["s2_paper_id"] = paper["paperId"]
    return out


# ---------------------------------------------------------------------- live mode


def populate_from_openalex(
    paper_id: str,
    project_id: str,
    *,
    client=None,
) -> dict:
    """Fetch refs+citers from OpenAlex; ingest edges."""
    manifest = _load_manifest(paper_id)
    if not manifest:
        return {"error": f"no manifest for paper {paper_id}"}
    oa_id = manifest.get("openalex_id")
    if not oa_id:
        doi = manifest.get("doi")
        if not doi:
            return {"error": (
                f"paper {paper_id} has no openalex_id or doi in manifest"
            )}
        oa_id = doi if doi.startswith("doi:") else f"doi:{doi}"

    if client is None:
        from lib.openalex_client import OpenAlexClient
        client = OpenAlexClient()

    from_node = _ensure_node(
        project_id, paper_id, paper_id, None,
        external_ids={
            k: v for k, v in {
                "openalex_id": manifest.get("openalex_id"),
                "doi": manifest.get("doi"),
                "arxiv_id": manifest.get("arxiv_id"),
                "pmid": manifest.get("pmid"),
                "s2_paper_id": manifest.get("s2_id"),
            }.items() if v
        } or None,
        source="openalex",
    )

    edges_added = 0
    nodes_touched: set[str] = {from_node}

    # ---- references (this paper cites these) ----
    refs = client.get_work_references(oa_id)
    if isinstance(refs, list) and refs and isinstance(refs[0], dict) \
            and "error" in refs[0]:
        return refs[0]
    ref_ids = [
        r if isinstance(r, str) else r.get("id")
        for r in (refs or [])
    ]
    ref_ids = [r for r in ref_ids if r]
    ref_works: list[dict] = []
    if ref_ids:
        clean = [
            (r[len("https://openalex.org/"):]
             if r.startswith("https://openalex.org/") else r)
            for r in ref_ids
        ]
        batch = client.get_works_batch(clean) if hasattr(
            client, "get_works_batch",
        ) else {"results": []}
        if isinstance(batch, dict) and "results" in batch:
            ref_works = batch.get("results") or []

    for w in ref_works:
        rcid = _cid_from_openalex_work(w)
        if not rcid:
            continue
        ext = _ids_from_openalex_work(w)
        ref_node = _ensure_node(
            project_id, rcid,
            (w.get("display_name") or rcid)[:200],
            {"year": w.get("publication_year")},
            external_ids=ext or None,
            source="openalex",
        )
        nodes_touched.add(ref_node)
        if _add_edge_if_new(project_id, from_node, ref_node, "cites"):
            edges_added += 1
        if _add_edge_if_new(project_id, ref_node, from_node, "cited-by"):
            edges_added += 1

    # ---- citers ----
    cited_by = client.get_cited_by(oa_id)
    if isinstance(cited_by, dict) and "error" in cited_by:
        return cited_by
    citer_works = (cited_by or {}).get("results") or []
    for w in citer_works:
        ccid = _cid_from_openalex_work(w)
        if not ccid:
            continue
        ext = _ids_from_openalex_work(w)
        cit_node = _ensure_node(
            project_id, ccid,
            (w.get("display_name") or ccid)[:200],
            {"year": w.get("publication_year")},
            external_ids=ext or None,
            source="openalex",
        )
        nodes_touched.add(cit_node)
        if _add_edge_if_new(project_id, cit_node, from_node, "cites"):
            edges_added += 1
        if _add_edge_if_new(project_id, from_node, cit_node, "cited-by"):
            edges_added += 1

    return {
        "edges_added": edges_added,
        "nodes_touched": len(nodes_touched),
        "skipped": 0,
        "source": "openalex",
    }


def populate_from_s2(
    paper_id: str,
    project_id: str,
    *,
    influential_only: bool = False,
    client=None,
) -> dict:
    """Fetch refs+citers from Semantic Scholar; ingest edges.

    `influential_only=True` keeps only S2 rows where the linked
    paper has `influentialCitationCount > 0`.
    """
    manifest = _load_manifest(paper_id)
    if not manifest:
        return {"error": f"no manifest for paper {paper_id}"}

    s2_id = manifest.get("s2_id")
    if not s2_id:
        doi = manifest.get("doi")
        arxiv = manifest.get("arxiv_id")
        if doi:
            s2_id = f"DOI:{doi}"
        elif arxiv:
            s2_id = f"ARXIV:{arxiv}"
        else:
            return {"error": (
                f"paper {paper_id} has no s2_id, doi, or arxiv_id "
                "in manifest"
            )}

    if client is None:
        from lib.s2_enrichment import S2Client
        client = S2Client()

    source_label = "s2-influential" if influential_only else "s2"

    from_node = _ensure_node(
        project_id, paper_id, paper_id, None,
        external_ids={
            k: v for k, v in {
                "doi": manifest.get("doi"),
                "arxiv_id": manifest.get("arxiv_id"),
                "pmid": manifest.get("pmid"),
                "s2_paper_id": manifest.get("s2_id"),
                "openalex_id": manifest.get("openalex_id"),
            }.items() if v
        } or None,
        source=source_label,
    )

    edges_added = 0
    nodes_touched: set[str] = {from_node}

    fields = (
        "title,authors,year,externalIds,influentialCitationCount"
        if influential_only
        else "title,authors,year,externalIds"
    )

    # ---- references ----
    refs_resp = client.get_paper_references(s2_id, fields=fields)
    if isinstance(refs_resp, dict) and "error" in refs_resp:
        return refs_resp
    refs_data = (refs_resp or {}).get("data") or []
    for entry in refs_data:
        cited = entry.get("citedPaper") or {}
        if influential_only:
            cnt = cited.get("influentialCitationCount") or 0
            if not cnt or int(cnt) <= 0:
                continue
        rcid = _cid_from_s2_paper(cited)
        if not rcid:
            continue
        ext = _ids_from_s2_paper(cited)
        ref_node = _ensure_node(
            project_id, rcid,
            (cited.get("title") or rcid)[:200],
            {"year": cited.get("year")},
            external_ids=ext or None,
            source=source_label,
        )
        nodes_touched.add(ref_node)
        if _add_edge_if_new(project_id, from_node, ref_node, "cites"):
            edges_added += 1
        if _add_edge_if_new(project_id, ref_node, from_node, "cited-by"):
            edges_added += 1

    # ---- citations ----
    cits_resp = client.get_paper_citations(s2_id, fields=fields)
    if isinstance(cits_resp, dict) and "error" in cits_resp:
        return cits_resp
    cits_data = (cits_resp or {}).get("data") or []
    for entry in cits_data:
        citer = entry.get("citingPaper") or {}
        if influential_only:
            cnt = citer.get("influentialCitationCount") or 0
            if not cnt or int(cnt) <= 0:
                continue
        ccid = _cid_from_s2_paper(citer)
        if not ccid:
            continue
        ext = _ids_from_s2_paper(citer)
        cit_node = _ensure_node(
            project_id, ccid,
            (citer.get("title") or ccid)[:200],
            {"year": citer.get("year")},
            external_ids=ext or None,
            source=source_label,
        )
        nodes_touched.add(cit_node)
        if _add_edge_if_new(project_id, cit_node, from_node, "cites"):
            edges_added += 1
        if _add_edge_if_new(project_id, from_node, cit_node, "cited-by"):
            edges_added += 1

    return {
        "edges_added": edges_added,
        "nodes_touched": len(nodes_touched),
        "skipped": 0,
        "source": source_label,
    }


# ---------------------------------------------------------------------- CLI


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--source", default="file",
        choices=["file", "openalex", "s2", "s2-influential"],
        help="file = legacy JSON ingest; others fetch live from backend.",
    )
    p.add_argument(
        "--input", help="JSON file (file mode only)",
    )
    p.add_argument(
        "--paper-id",
        help="paper canonical_id (live modes only)",
    )
    p.add_argument("--project-id", required=True)
    args = p.parse_args()

    if args.source == "file":
        if not args.input:
            print(json.dumps(
                {"error": "--input required when --source=file"}, indent=2,
            ))
            raise SystemExit(2)
        records = json.loads(Path(args.input).read_text())
        if not isinstance(records, list):
            print(json.dumps(
                {"error": "input must be a JSON array"}, indent=2,
            ))
            raise SystemExit(2)
        result = populate(records, args.project_id)
    else:
        if not args.paper_id:
            print(json.dumps(
                {"error": "--paper-id required for live source"}, indent=2,
            ))
            raise SystemExit(2)
        if args.source == "openalex":
            result = populate_from_openalex(args.paper_id, args.project_id)
        elif args.source == "s2":
            result = populate_from_s2(
                args.paper_id, args.project_id, influential_only=False,
            )
        else:
            result = populate_from_s2(
                args.paper_id, args.project_id, influential_only=True,
            )

    print(json.dumps(result, indent=2))
    if isinstance(result, dict) and "error" in result:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

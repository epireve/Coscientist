# retraction-mcp

Stdio MCP server wrapping Retraction Watch (via Crossref `update-to`)
and PubPeer comment lookups. Pure-stdlib networking — no extra deps
beyond the `mcp` package.

## Tools

| Tool | Args | Returns |
|---|---|---|
| `lookup_doi` | `doi: str` | Crossref retraction record |
| `batch_lookup` | `dois: list[str]`, `delay_seconds: float = 0.2` | List of per-DOI lookups |
| `pubpeer_comments` | `doi: str` | PubPeer comment metadata |

## Run as a stdio MCP server

```bash
uv run --with mcp python mcp/retraction-mcp/server.py
```

Add to `.mcp.json`:

```json
"retraction": {
  "type": "stdio",
  "command": "uv",
  "args": [
    "run", "--with", "mcp",
    "python",
    "mcp/retraction-mcp/server.py"
  ]
}
```

## Sources

- **Crossref** `https://api.crossref.org/works/<DOI>` — the
  `update-to` and `updated-by` arrays carry retraction / correction /
  expression-of-concern notices linked from the original DOI. Public,
  no key.
- **PubPeer** `https://api.pubpeer.com/v3/publications/?q=<DOI>` —
  comment count + publication URL. Public, no key.

## Returned shape — `lookup_doi`

```json
{
  "doi": "10.1038/nature12373",
  "found": true,
  "source": "crossref",
  "is_retracted": false,
  "has_correction_or_eoc": false,
  "notices": [],
  "title": "...",
  "container": "Nature",
  "year": 2013
}
```

Error path (DOI not in Crossref, network fail, etc.):

```json
{"doi": "...", "found": false, "error": "<reason>"}
```

## Caller

The `retraction-watch` skill is the primary consumer. When the user
runs `scan list` it surfaces uncovered DOIs; the orchestrator calls
`retraction.batch_lookup` to populate fresh statuses; `scan persist`
records new retractions back to the project DB.

## Limits

- Crossref: ~50 rps polite policy. Defaults to 0.2s between requests
  in `batch_lookup`.
- PubPeer: undocumented but historically 60 rpm. Tune `delay_seconds`
  upward if you hit 429.
- Neither service exposes Retraction Watch's full database; this MCP
  surfaces only what Crossref + PubPeer publish.

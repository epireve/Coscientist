# graph-query-mcp

Read-only stdio MCP over Coscientist's per-project citation /
concept / author graph. Wraps `lib/graph.py` (SQLite-adjacency
backend) with one extension: BFS shortest-path.

Read-only by design. Never mutates `graph_nodes` or `graph_edges` —
write paths still go through `lib.graph.add_node` / `add_edge` from
inside the parent project.

## Tools

| Tool | Args | Returns |
|---|---|---|
| `neighbors` | `project_id`, `node_id`, `relation=None`, `direction="out"\|"in"\|"both"` | neighbor rows |
| `walk` | `project_id`, `start_node`, `relation`, `max_hops=2` | nodes reached |
| `in_degree` | `project_id`, `node_id`, `relation=None` | int count |
| `hubs` | `project_id`, `kind`, `relation="cites"`, `top_k=10` | top-N by in-degree |
| `node_info` | `project_id`, `node_id` | single node row or `{found: false}` |
| `shortest_path` | `project_id`, `start_node`, `end_node`, `max_hops=4`, `relation=None` | path + length or `{found: false}` |

## Run as stdio MCP

```bash
uv run --with mcp python mcp/graph-query-mcp/server.py
```

## Node ID convention

Typed strings used by `lib.graph`:

| Kind | ID format |
|---|---|
| paper | `paper:<canonical_id>` |
| concept | `concept:<slug>` |
| author | `author:<s2_id>` |
| manuscript | `manuscript:<mid>` |

## Edge relations

`cites`, `cited-by`, `extends`, `refutes`, `uses`, `depends-on`,
`coauthored`, `about`, `authored-by`, `in-project`.

## Why an MCP

`lib.graph` is already callable from Python; this MCP exposes the
same primitives to non-Python agents (sub-agents in Claude Code,
external clients) via stdio JSON-RPC. The shortest-path BFS is new —
not a Python API in `lib.graph` yet, but cheap to add later.

## Kuzu migration path

When `graph_nodes` + `graph_edges` outgrow SQLite-adjacency
performance (parked roadmap item), the same six tool signatures map
1:1 onto Kuzu Cypher-style queries. The MCP surface is the
forward-compat boundary.

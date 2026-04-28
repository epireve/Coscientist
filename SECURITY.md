# Security policy

## Reporting a vulnerability

If you believe you've found a security vulnerability in Coscientist
or one of its plugins, please **do not** open a public issue.
Instead, email <i@firdaus.my> with:

- A description of the vulnerability.
- Steps to reproduce.
- Affected version (commit SHA + plugin name if applicable).
- Any proposed mitigation.

You'll receive a response within 7 days. We'll work on a fix and
coordinate disclosure timing with you.

## Scope

In scope:

- The four plugins shipped via this repository
  (`coscientist-deep-research`, `coscientist-retraction-mcp`,
  `coscientist-manuscript-mcp`, `coscientist-graph-query-mcp`)
- The `lib/`, `mcp/`, and `.claude/skills/` source code
- The CI workflows in `.github/workflows/`

Out of scope (third-party dependencies — report upstream):

- The `mcp` package itself
- Any of the external MCP servers listed in
  [`EXTERNAL_MCPS.md`](./EXTERNAL_MCPS.md) (Consensus, paper-search,
  semantic-scholar, academic, zotero, playwright, browser-use)
- Claude Code itself

## Hardening posture

What's already in place:

| Defense | Mechanism |
|---|---|
| Plugin file integrity | SHA-256 checksums per plugin (`CHECKSUMS.txt`); generate + verify via `lib/plugin_checksums.py` |
| Sandboxed code execution | `reproducibility-mcp` runs untrusted scripts inside Docker with no network, CPU/memory caps, restricted FS |
| API key isolation | Real `.mcp.json` is gitignored; `.mcp.json.example` is committed |
| Audit logging | Every PDF fetch + every Docker run logged to append-only files; rotation via `audit-rotate` |
| FK + integrity check | `lib/db_check.py` verifies coscientist DBs |
| WAL mode | Per-DB on-disk flag; reduces SQLITE_BUSY during parallel writers |
| Test isolation | Cache-leak detector catches tests writing outside `isolated_cache()` |

What's NOT defended against:

- Compromised upstream MCP servers (Consensus, etc.)
- Malicious paper PDFs (no PDF sandboxing during extraction)
- Network adversaries on `paper-acquire` HTTP fetches
- A user voluntarily running `--confirm` deletion flags

## Vulnerability disclosure timeline

- Day 0: report received, acknowledgment sent within 7 days
- Day 7–30: investigation + fix development
- Day 30+: coordinated disclosure (CVE if applicable)

## See also

- [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md)
- [`CONTRIBUTING.md`](./CONTRIBUTING.md)
- [`EXTERNAL_MCPS.md`](./EXTERNAL_MCPS.md)

# Contributing to Coscientist

Coscientist is built Lego-style: atomic skills, custom MCP servers,
and Claude Code plugins. Each piece composes through artifacts on
disk — no skill calls another skill directly.

This guide walks through how to add a new piece without breaking
the rest.

## Repository layout

```
.
├── lib/                              # pure-stdlib helpers (no LLM, no MCP)
├── .claude/skills/<name>/            # atomic skill (CLI + SKILL.md)
├── .claude/agents/<name>.md          # sub-agent persona
├── mcp/<name>-mcp/                   # source for a custom MCP server
├── plugin/<plugin-name>/             # marketplace-installable plugin
├── .claude-plugin/marketplace.json   # marketplace registry
├── tests/                            # 1600+ test classes (custom harness)
└── pyproject.toml
```

## Patterns

### Adding a new skill

1. Create `.claude/skills/<name>/SKILL.md` with frontmatter:
   ```yaml
   ---
   name: <name>
   description: One sentence on what it does.
   when_to_use: When the user says X, Y, Z; or skill X needs Y.
   ---
   ```
2. Put scripts in `.claude/skills/<name>/scripts/`. Each script:
   - Reads `--canonical-id` / `--manuscript-id` / `--run-id` /
     `--project-id` as appropriate.
   - Persists state via `lib.skill_persist` helpers (gets you
     `db_writes` audit row + `db-notify` stderr line for free).
   - Uses `lib.cache.connect_wal` for any new SQLite connection.
3. Run `uv run python -m lib.skill_index > SKILLS.md` to refresh
   the index. The CI test (`tests/test_skill_index.py`) will fail
   if you skip this.
4. Add a test under `tests/test_<name>.py` — auto-discovered by
   `tests/run_all.py` (any `class XTests(TestCase)` is picked up).

### Adding a new sub-agent

1. Create `.claude/agents/<name>.md` with YAML frontmatter
   (`name`, `description`, optional `tools`).
2. Frontmatter `name` field must match filename stem (enforced by
   `test_skill_agent_invariants.py`).
3. Reference the agent from at least one skill or doc — orphan
   detector will fail otherwise.

### Adding a custom MCP server

Three places must agree.

1. **Source**: `mcp/<name>-mcp/server.py` + README. Must:
   - Import `from mcp.server.fastmcp import FastMCP` with
     `try/except SystemExit` fallback so import-time failure
     gives a clear error.
   - Decorate every tool with `@mcp.tool()`.
   - Expose `def main()` so console scripts can target `server:main`.
2. **Plugin**: `plugin/coscientist-<name>-mcp/`:
   - `.claude-plugin/plugin.json` (name, version, description,
     license, author, homepage, keywords, requires).
   - `server/server.py` byte-equal to the source (test enforces).
   - `.mcp.json` declaring stdio server via `${CLAUDE_PLUGIN_ROOT}`.
   - `pyproject.toml` with `[project.scripts]` console-script
     pointing at `server:main`.
   - `README.md`.
   - Optional `lib/` (vendored) if the MCP needs Coscientist's
     own helpers. `tests/test_marketplace.py` enforces byte
     equality with the source `lib/`.
3. **Marketplace**: add an entry to
   `.claude-plugin/marketplace.json`. `name`, `version`, `source`,
   `description` must match `plugin.json`.
4. Run `uv run python -m lib.mcp_index > MCP_SERVERS.md`.

### Adding a new schema migration

1. Bump `ALL_VERSIONS` in `lib/migrations.py` (must remain
   contiguous; `test_migration_monotonicity.py` enforces).
2. Pick the path:
   - **SQL-only DDL**: add a `lib/migrations_sql/v<N>.sql` file +
     a `_ensure_v<N>_tables` helper.
   - **In-code transforms** (e.g. ALTER TABLE with conditional
     logic): add a `_ensure_v<N>_columns` helper.
3. Mirror new tables into `lib/sqlite_schema.sql` so fresh DBs work
   without migrations. `test_schema_parity.py` will fail otherwise.

## Test discipline

- Custom harness, not pytest. Use `from tests.harness import TestCase`.
- Test classes ending in `Tests` are auto-discovered by
  `tests/run_all.py`. No registration needed.
- Use `tests.harness.isolated_cache()` for any test that touches
  `~/.cache/coscientist/`. The cache-leak detector (runs last)
  will fail if you bypass it.
- Network tests are opt-in via `COSCIENTIST_RUN_LIVE=1` env var
  (see `tests/test_retraction_mcp_live.py` for the pattern).

## Commit + push

- Commits go to `main`. No long-lived branches.
- Every commit:
  - Author = `epireve <i@firdaus.my>` (use
    `git -c user.name='epireve' -c user.email='i@firdaus.my' commit ...`).
  - No `--no-gpg-sign` opinion either way; user runs without GPG.
  - Update ROADMAP.md `## Shipped` section with the new version
    entry. Then regenerate CHANGELOG.md:
    ```bash
    uv run python -m lib.changelog > CHANGELOG.md
    ```
  - Suite must stay green: `uv run python tests/run_all.py` →
    `0 failed`.

## Auto-generated docs

These five files are regenerated from source. Do not hand-edit:

| File | Generator | Test |
|---|---|---|
| `SKILLS.md` | `lib/skill_index.py` | `test_skill_index.py` |
| `MCP_SERVERS.md` | `lib/mcp_index.py` | `test_mcp_index.py` |
| `CHANGELOG.md` | `lib/changelog.py` | `test_changelog.py` |
| `EXTERNAL_MCPS.md` | hand-curated | `test_marketplace.py` |
| `ROADMAP.md` | hand-curated | none |

## Pre-merge checklist

- [ ] Suite green (`uv run python tests/run_all.py`)
- [ ] Auto-generated docs regenerated if their inputs changed
- [ ] ROADMAP.md updated with new version entry
- [ ] If shipping an MCP plugin: marketplace.json updated, plugin
      version bumped, server.py byte-equal between mcp/ source
      and plugin/ copy
- [ ] If shipping a migration: ALL_VERSIONS bumped, schema.sql
      mirrored

## Architecture invariants

These are enforced by tests; review before deviating:

| Invariant | Enforced by |
|---|---|
| Skill ↔ agent name parity | `test_skill_agent_invariants.py` |
| Schema parity (migrations ↔ sqlite_schema.sql) | `test_schema_parity.py` |
| Migration version contiguity | `test_migration_monotonicity.py` |
| Marketplace ↔ plugin.json parity | `test_marketplace.py` |
| Plugin server.py byte-match with source | `test_marketplace.py` |
| Cache leaks during tests | `test_cache_leak_detector.py` |
| Auto-discovery of test classes | `test_runner_discovery.py` |
| `pyproject.toml` declares `mcp` extra | `test_v0_81_infra.py` |
| Every plugin healthy via `install_check` | `test_v0_81_infra.py` |

## Questions

Open an issue at <https://github.com/epireve/coscientist/issues>.
For a structural change (new artifact kind, new state machine,
new MCP), explain *why* in the issue before opening a PR.

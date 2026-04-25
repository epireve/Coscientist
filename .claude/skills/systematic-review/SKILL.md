---
name: systematic-review
description: PRISMA-compliant systematic literature review. Protocol-first: declare scope and inclusion/exclusion criteria before searching. Then run exhaustive search, two-stage title/abstract + full-text screening, data extraction, bias assessment, and PRISMA flow diagram generation. Self-contained per-protocol SQLite DB.
when_to_use: You need a rigorous, auditable, reproducible survey of a body of literature. Use when the question demands exhaustive search (not just convenience sampling), explicit inclusion/exclusion criteria, and a transparent audit trail of every screening decision. Produces a PRISMA flow diagram and structured extraction tables ready for narrative or quantitative synthesis.
---

# systematic-review

PRISMA-compliant systematic literature review workflow. Everything is
protocol-first: you must call `init` before any other subcommand.

Each protocol lives in its own directory and lightweight SQLite DB:

```
~/.cache/coscientist/reviews/<protocol_id>/
  protocol.json     # human-readable protocol snapshot
  review.db         # per-protocol SQLite (tables: review_protocols,
                    #   screening_decisions, extraction_rows, bias_assessments)
  prisma.md         # generated PRISMA flow diagram (after `prisma` subcommand)
```

`protocol_id` is deterministic: `<slug-of-title>_<6-char-blake2s(title::question)>`.

## Protocol-first requirement

`init` MUST be called before `search`. `search` MUST be called (freezing the
protocol) before `screen`. `extract` and `bias` require an `include` full-text
decision for the paper. This enforces the PRISMA principle that the protocol
is written before evidence is examined.

## Subcommands

### init — register a new protocol

```bash
uv run python .claude/skills/systematic-review/scripts/review.py init \
  --title "Interventions for X in population Y" \
  --question "In population Y, does intervention X compared to Z affect outcome W?" \
  --inclusion '["RCT or quasi-experimental design","published 2015-2025"]' \
  --exclusion '["non-human subjects","grey literature only"]' \
  [--date-range "2015-2025"] \
  [--run-id <rid>]
```

Prints `protocol_id` to stdout. Creates the review directory and writes
`protocol.json`. Errors if `protocol_id` already exists.

### search — record search strings and freeze protocol

```bash
uv run python .claude/skills/systematic-review/scripts/review.py search \
  --protocol-id <pid> \
  --queries '["PICO query 1","database-specific query 2"]'
```

Appends queries to `review_protocols.search_strings`. Sets `frozen_at`
(protocol becomes immutable). Cannot be called after `screen` has begun.
Prints the list of paper_ids now in scope (from `papers_in_run` for the
linked run_id, or an empty list if no run_id was provided — populate via
`paper-discovery` first).

### screen — record one screening decision

```bash
uv run python .claude/skills/systematic-review/scripts/review.py screen \
  --protocol-id <pid> \
  --paper-id <canonical_id> \
  --stage <title_abstract|full_text> \
  --decision <include|exclude|uncertain> \
  [--reason "Does not meet population criterion"]
```

Records a single screening decision. Rules:
- Protocol must be frozen (`search` must have been called).
- `full_text` stage requires a prior `title_abstract` decision for the paper.
- Idempotent: re-screening the same paper+stage overwrites the previous decision.

### extract — record one data-extraction field

```bash
uv run python .claude/skills/systematic-review/scripts/review.py extract \
  --protocol-id <pid> \
  --paper-id <canonical_id> \
  --field sample_size \
  --value 142 \
  [--unit "participants"] \
  [--notes "ITT population"]
```

Accumulates rows (one per field per call). Errors if the paper has no
`include` full-text decision.

### bias — record one risk-of-bias domain

```bash
uv run python .claude/skills/systematic-review/scripts/review.py bias \
  --protocol-id <pid> \
  --paper-id <canonical_id> \
  --domain <selection|performance|detection|attrition|reporting> \
  --rating <low|unclear|high> \
  [--justification "Allocation concealment unclear"]
```

Idempotent per paper+domain (re-assessing overwrites). Domains follow the
Cochrane RoB 2.0 framework.

### prisma — generate PRISMA flow diagram

```bash
uv run python .claude/skills/systematic-review/scripts/review.py prisma \
  --protocol-id <pid>
```

Generates a Markdown PRISMA flow diagram using Unicode box-drawing characters
showing:
1. Records identified (from `search_strings` count proxy)
2. After deduplication
3. Title/abstract screened → excluded (with reason counts)
4. Full-text assessed → excluded (with reason counts)
5. Included

Writes to `~/.cache/coscientist/reviews/<protocol_id>/prisma.md`.
Prints the file path to stdout.

### status — print review progress summary

```bash
uv run python .claude/skills/systematic-review/scripts/review.py status \
  --protocol-id <pid>
```

Prints:
- Protocol metadata (title, question, date_range, frozen_at)
- Screening progress: N included/excluded/uncertain at title_abstract and full_text stages
- Extraction completeness: unique fields × papers extracted
- Bias coverage: papers assessed × domains covered
- Whether prisma.md has been generated

## PRISMA stages

| Stage | Description |
|---|---|
| Identification | Records retrieved via database searching |
| Screening | Title/abstract screen against inclusion/exclusion criteria |
| Eligibility | Full-text assessment of title/abstract-included records |
| Included | Studies meeting all criteria, entering synthesis |

## Output files

| File | Contents |
|---|---|
| `protocol.json` | Protocol snapshot: title, question, criteria, search strings, dates |
| `review.db` | SQLite with all decisions, extractions, and bias assessments |
| `prisma.md` | Unicode PRISMA flow diagram (Markdown, renderable as plain text) |

## Guarantees

- No LLM calls, no network — pure filesystem + SQLite.
- Protocol is immutable once `search` freezes it (`frozen_at` is set).
- All screening decisions are auditable with timestamps and reasons.
- `protocol_id` is deterministic: same title + question always gives the same ID.
- DB uses `PRAGMA foreign_keys = ON` and `PRAGMA journal_mode = WAL`.
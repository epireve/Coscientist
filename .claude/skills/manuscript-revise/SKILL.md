---
name: manuscript-revise
description: Respond-to-reviewers mode. Parses structured reviewer comments, generates a point-by-point response letter template and a section-by-section revision action plan, then advances the manuscript state to `revised`. The output files are scaffolds — the author fills in the actual responses; the agent can then draft the substance.
when_to_use: You have received reviewer comments back from a journal or conference and need to prepare a response letter and a plan for revising the manuscript. The manuscript must already be in the Coscientist cache (state drafted, audited, or critiqued). Run manuscript-ingest first if the manuscript is not yet cached.
---

# manuscript-revise

Respond-to-reviewers workflow. Takes a review document (structured reviewer comments)
and the current manuscript, produces a point-by-point response stub letter and a
section-by-section revision action plan.

## Subcommands

### ingest-review — parse and store reviewer comments

```bash
uv run python .claude/skills/manuscript-revise/scripts/revise.py ingest-review \
  --manuscript-id <mid> \
  --review-file path/to/review.txt
```

Or supply inline text:

```bash
uv run python .claude/skills/manuscript-revise/scripts/revise.py ingest-review \
  --manuscript-id <mid> \
  --review-text "Reviewer 1:\n\n1. The authors claim..."
```

Prints a summary: `N reviewers, M comments total`.

Writes `review.json` to `~/.cache/coscientist/manuscripts/<mid>/review.json`.

**State guard**: refuses if manuscript state is `submitted` or `published` (too late to revise via this workflow). Accepts `drafted`, `audited`, `critiqued`.

### plan — section-by-section revision action plan

```bash
uv run python .claude/skills/manuscript-revise/scripts/revise.py plan \
  --manuscript-id <mid>
```

Reads `review.json` + `source.md` + `outline.json`. Writes
`revision_notes.md` with a section-by-section action plan. Each note
cites the review comment number(s) it addresses.

Requires `review.json` to exist (run `ingest-review` first).

### respond — point-by-point response letter template

```bash
uv run python .claude/skills/manuscript-revise/scripts/revise.py respond \
  --manuscript-id <mid>
```

Reads `review.json` + `revision_notes.md`. Writes `response_letter.md`
with a stub for every reviewer comment:

```
## [REVIEWER 1, COMMENT 1]

> <original comment quoted verbatim>

[YOUR RESPONSE HERE]
```

After `respond` completes successfully the manuscript state advances to `revised`.

### status — count remaining response stubs

```bash
uv run python .claude/skills/manuscript-revise/scripts/revise.py status \
  --manuscript-id <mid>
```

Counts `[YOUR RESPONSE HERE]` placeholders remaining in `response_letter.md`.
Exit code 0 always; output: `N stubs remaining`.

## Accepted review file format

Plain-text format — the most common output from journal submission systems:

```
Reviewer 1:

1. The authors claim X but do not provide evidence...

2. The methods section lacks detail on Y...

Reviewer 2:

1. I found the introduction compelling but the evaluation is thin.
```

Supported variations:
- `Reviewer N:` or `Reviewer N` headers (with or without colon)
- Numbered comments: `1.`, `1)`, `(1)`, `[1]`
- Blank lines between comments
- Multi-paragraph comments (consecutive non-blank lines merged)

## Output layout

```
manuscripts/<manuscript_id>/
  review.json         # parsed reviewer comments
  revision_notes.md   # section-by-section action plan
  response_letter.md  # point-by-point response template
```

## State machine

| Starting state | Subcommand | Ending state |
|---|---|---|
| drafted / audited / critiqued | ingest-review | unchanged |
| any (after ingest-review) | plan | unchanged |
| any (after plan) | respond | **revised** |

Pass `--force` to `ingest-review` to override the state guard and run on
a manuscript in `drafted` or other states without an error.

## Typical workflow

```bash
# 1. Parse the review
python revise.py ingest-review --manuscript-id <mid> --review-file reviews.txt

# 2. Build revision plan (agent fills in the logic; script gives structure)
python revise.py plan --manuscript-id <mid>

# 3. Generate response letter stubs
python revise.py respond --manuscript-id <mid>

# 4. Agent (or author) fills in [YOUR RESPONSE HERE] entries

# 5. Check progress
python revise.py status --manuscript-id <mid>
```

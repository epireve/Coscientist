---
name: writing-style
description: Fingerprint your academic voice from prior manuscripts, flag style deviations in new drafts, and help keep new writing consistent with both your voice and venue norms. Pure text analysis — no LLM calls, no external deps beyond stdlib.
when_to_use: You want to keep a new manuscript consistent with your established voice, or audit a draft for stylistic drift. Also used implicitly by future `manuscript-draft` (once that skill lands).
---

# writing-style

Three scripts:

| Script | Job |
|---|---|
| `fingerprint.py` | Read N manuscripts; emit a per-project style profile (lexical + syntactic + structural) |
| `audit.py` | Full-draft deviation audit — find paragraphs/sections that drift from the profile |
| `apply.py` | Paragraph-level critique — given a profile, flag specific deviations in a paragraph |

No LLM, no heuristics that require training — everything is deterministic analysis of the text itself (regex + basic counting). This keeps it fast, cheap, and inspectable.

## Style profile schema

Written to `~/.cache/coscientist/projects/<pid>/style_profile.json`:

```json
{
  "profile_version": 1,
  "generated_at": "2026-04-24T...",
  "sample_count": 3,
  "word_count": 14823,
  "lexical": {
    "top_terms": {"attention": 82, "transformer": 47, ...},
    "hedge_density": 0.012,
    "first_person_rate": 0.18,
    "british_american": "us | uk",
    "sentence_starters": ["Here", "We", "In this", ...]
  },
  "syntactic": {
    "avg_sentence_length": 22.4,
    "sentence_length_std": 8.1,
    "passive_voice_rate": 0.14
  },
  "structural": {
    "avg_paragraph_length_sentences": 4.2,
    "signpost_phrases": ["First", "In particular", "Note that", ...]
  }
}
```

## fingerprint

```bash
uv run python .claude/skills/writing-style/scripts/fingerprint.py \
  --project-id <pid> \
  --sources path/to/paper1.md path/to/paper2.md ...
```

Reads each `.md` file, aggregates lexical/syntactic/structural stats, writes the profile, updates `projects.style_profile_path`.

## audit

```bash
uv run python .claude/skills/writing-style/scripts/audit.py \
  --manuscript-id <mid> \
  --project-id <pid>
```

Reads the manuscript's `source.md` and the project's `style_profile.json`. Emits a JSON report flagging paragraphs that deviate significantly on any measured dimension. Severity: `info`, `minor`, `major`.

## apply

```bash
# For checking a specific passage inline
echo "<paragraph text>" | uv run python .claude/skills/writing-style/scripts/apply.py \
  --project-id <pid>
```

Reads stdin, returns JSON of per-dimension deviations. Useful during drafting — not blocking.

## What this does NOT do

- Doesn't rewrite anything — pure analysis, report-only
- Doesn't evaluate *quality* — consistent-with-your-voice ≠ good writing
- Doesn't call any LLM or external service
- Doesn't enforce venue style — that's handled by `manuscript-format` (future)

## Principles enforced

From `RESEARCHER.md`: **7 (Commit to a Number — every audit finding names a numeric deviation, not vibes)**.

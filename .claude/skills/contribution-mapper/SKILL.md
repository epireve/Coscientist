---
name: contribution-mapper
description: Positions a manuscript in the research landscape. Decomposes contributions into method/domain/finding axes, finds nearest prior work via Jaccard distance, projects onto a 2D landscape (method-distance × domain-distance). Pure heuristic; LLM-free.
when_to_use: After manuscript-ingest registers a manuscript, the user wants to see where it sits relative to known prior art on three axes (method/domain/finding). Or before writing the related-work section to identify closest anchors.
---

# contribution-mapper

Coarse but mechanical landscape positioning. Three axes:

- **method**: technique tokens (transformer, rnn, mri, fmri, ...)
- **domain**: subject tokens (memory, vision, language, biology, ...)
- **finding**: result tokens (improvement, scaling, robust, fail, ...)

Per contribution × per anchor: `1 - jaccard(C.axis, A.axis)`. Lowest
total distance = closest anchor.

## How to invoke

```bash
# From a list of contribution sentences + a list of anchor papers
uv run python .claude/skills/contribution-mapper/scripts/map.py \
  --contributions /path/to/contribs.json \
  --anchors /path/to/anchors.json \
  [--write-output landscape.md]
```

`contribs.json` shape: `[{label: "C1", text: "..."}]`
`anchors.json` shape: `[{canonical_id: "...", method: [...], domain: [...], finding: [...]}]`

## What "done" looks like

- Per-contribution positioning (label, distances, closest anchor).
- 2D projection (method-distance, domain-distance) per contribution.
- ASCII landscape grid for visual gut-check.
- Markdown brief renderable via `lib.contribution_mapper.render_landscape`.

## What this skill does NOT do

- Does not search for anchors automatically (caller provides them —
  typically pulled from `papers_in_run` or Zotero).
- Does not run novelty-check (that's its own skill).
- Does not produce publication recommendations (that's `venue-match`).

## CLI flag reference (drift coverage)

- `map.py`: `--persist-db`

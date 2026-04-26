---
name: registered-reports
description: Stage 1 / Stage 2 manuscript scaffold for Registered Reports submission pathway. Stage 1 = pre-registered protocol (intro, methods, hypotheses, analysis plan); Stage 2 = full paper after data collection. Tracks state transitions stage-1-drafted → stage-1-submitted → in-principle-accepted → data-collected → stage-2-drafted → stage-2-submitted → published.
when_to_use: User says "registered report", "Stage 1 protocol", "in-principle acceptance", "RR submission". Pre-registration pathway distinct from regular submission.
---

# registered-reports

Stage 1 / Stage 2 manuscript scaffold + state tracking under `registered_reports/<rr_id>/`.

## Scripts

```
rr.py init --title "T" [--journal X] — creates Stage 1 scaffold
rr.py advance --rr-id R --to-state STATE
rr.py status --rr-id R
rr.py list
```

## States (linear)

1. `stage-1-drafted` — protocol written
2. `stage-1-submitted` — sent for review
3. `in-principle-accepted` — IPA granted
4. `data-collected` — actual data gathered
5. `stage-2-drafted` — full paper written
6. `stage-2-submitted` — final submission
7. `published`

Backwards transitions blocked. `--force` overrides.

## Stage 1 sections

introduction, hypotheses, methods, analysis_plan, sampling_plan, exclusion_criteria, deviations_from_protocol (added in Stage 2)

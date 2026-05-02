---
name: figure-agent
description: Register, audit, and caption figures for a manuscript. Checks colorblind-safe palettes using Machado 2009 deuteranopia/protanopia simulation. Stores figure manifests under manuscripts/<mid>/figures/<fig_id>/.
when_to_use: When a manuscript has figures that need accessibility auditing, caption completeness checking, or cross-reference verification. Also used by manuscript-critique to flag figure quality issues.
---

# figure-agent

Manages figure artifacts for manuscripts. All figures live under:
`~/.cache/coscientist/manuscripts/<mid>/figures/<fig_id>/manifest.json`

## Scripts

| Script | CLI | Purpose |
|---|---|---|
| `register.py` | `--mid M --fig-id F --path P --caption TEXT --label LABEL` | Register a figure with a manuscript |
| `audit.py` | `--mid M` | Audit all figures in a manuscript for caption completeness + cross-refs |
| `caption.py` | `--mid M --fig-id F --caption TEXT` | Update or set a figure caption |
| `list.py` | `--mid M [--format json\|table]` | List all figures for a manuscript |
| `check_palette.py` | `--image PATH` | Check colorblind safety of an image (PNG/SVG path or color list) |

## Colorblind simulation

Uses Machado 2009 deuteranopia + protanopia matrices applied to sRGB → linear RGB → simulate → back. Delta-E CIE76 < 40 is warning threshold.

Deuteranopia matrix (linear RGB):
```
[[0.625, 0.375, 0.0 ],
 [0.700, 0.300, 0.0 ],
 [0.0,   0.300, 0.700]]
```

Protanopia matrix (linear RGB):
```
[[0.567, 0.433, 0.0 ],
 [0.558, 0.442, 0.0 ],
 [0.0,   0.242, 0.758]]
```

## CLI flag reference (drift coverage)

- `check_palette.py`: `--colors`
- `register.py`: `--overwrite`

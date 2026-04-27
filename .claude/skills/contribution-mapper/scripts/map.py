#!/usr/bin/env python3
"""contribution-mapper CLI."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_PLUGIN_ROOT = _HERE.parents[3]
_REPO_ROOT = (
    _HERE.parents[4] if (_HERE.parents[4] / "lib").exists()
    else _PLUGIN_ROOT
)
for _p in (_REPO_ROOT, _PLUGIN_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from lib.contribution_mapper import (  # noqa: E402
    Anchor, closest_anchor, decompose_contribution,
    project_2d, render_landscape,
)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--contributions", required=True,
                   help="Path to JSON list of {label, text}")
    p.add_argument("--anchors", required=True,
                   help="Path to JSON list of {canonical_id, method, "
                        "domain, finding}")
    p.add_argument("--write-output", default=None,
                   help="If set, write landscape markdown to this path")
    args = p.parse_args()

    contribs_in = json.loads(Path(args.contributions).read_text())
    anchors_in = json.loads(Path(args.anchors).read_text())

    contributions = [
        decompose_contribution(c["label"], c["text"]) for c in contribs_in
    ]
    anchors = [Anchor.from_dict(a) for a in anchors_in]

    projections = project_2d(contributions, anchors)

    payload = {
        "n_contributions": len(contributions),
        "n_anchors": len(anchors),
        "positions": [
            {
                "label": c.label,
                "method": sorted(c.method),
                "domain": sorted(c.domain),
                "finding": sorted(c.finding),
                "method_distance": projections[i][0],
                "domain_distance": projections[i][1],
                "closest_anchor": (
                    closest_anchor(c, anchors)[0].canonical_id
                    if anchors else None
                ),
            }
            for i, c in enumerate(contributions)
        ],
    }

    if args.write_output:
        Path(args.write_output).write_text(
            render_landscape(contributions, anchors)
        )
        payload["md_path"] = args.write_output

    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()

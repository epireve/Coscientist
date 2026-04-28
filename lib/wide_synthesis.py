"""Wide Research synthesizer — per-type fan-in roll-ups.

v0.53.4. Pure stdlib. Each task_type has a dedicated reduce template:

  triage  → relevance histogram + include/review/exclude buckets +
            top-K shortlist (sorted by relevance_score)
  read    → per-paper structured digest with method/dataset/results
  rank    → Elo leaderboard from pairwise matches
  compare → cross-item feature matrix (rows=items, cols=schema fields)
  survey  → author trajectory table sorted by h-index
  screen  → PRISMA include/exclude tally + criteria-failed histogram

Synthesizer runs in fresh context. Reads result.json refs only — does
NOT inline raw sub-agent context. Output: structured dict consumable
by both CLI (csv/md writers) and downstream Deep handoff (L1 seed).
"""
from __future__ import annotations

from collections import Counter
from typing import Any


def synthesize(task_type: str, results: list[dict],
               user_query: str = "") -> dict:
    """Dispatch to per-type synthesizer.

    Args:
        task_type: triage / read / rank / compare / survey / screen
        results: output of collect_results — list of {sub_agent_id,
                  status, result, ...}
        user_query: original user prompt, preserved for the brief

    Returns:
        Structured dict. Always contains: task_type, n_total,
        n_complete, n_missing, n_error, plus type-specific fields.
    """
    completed = [r for r in results if r["status"] == "complete"
                 and "result" in r and isinstance(r["result"], dict)]
    base = {
        "task_type": task_type,
        "user_query": user_query,
        "n_total": len(results),
        "n_complete": len(completed),
        "n_missing": sum(1 for r in results if r["status"] == "missing"),
        "n_error": sum(
            1 for r in results
            if r["status"].startswith("parse_error")
        ),
    }
    fn = _SYNTH.get(task_type, _synth_generic)
    base.update(fn(completed))
    return base


def _synth_triage(completed: list[dict]) -> dict:
    """Triage: histogram by recommend bucket + top-K shortlist."""
    by_recommend: Counter = Counter()
    scored: list[dict] = []
    for r in completed:
        res = r["result"]
        rec = res.get("recommend", "review")
        by_recommend[rec] += 1
        scored.append({
            "sub_agent_id": r["sub_agent_id"],
            "canonical_id": res.get("canonical_id", ""),
            "title": res.get("title", ""),
            "year": res.get("year"),
            "relevance_score": _coerce_float(res.get("relevance_score")),
            "recommend": rec,
            "reason": res.get("reason", ""),
        })
    scored.sort(
        key=lambda x: x["relevance_score"] or 0.0, reverse=True
    )
    return {
        "by_recommend": dict(by_recommend),
        "top_shortlist": scored[:30],
        "all_scored": scored,
    }


def _synth_read(completed: list[dict]) -> dict:
    """Read: per-paper structured digest list."""
    digests = []
    for r in completed:
        res = r["result"]
        digests.append({
            "sub_agent_id": r["sub_agent_id"],
            "canonical_id": res.get("canonical_id", ""),
            "method": res.get("method", ""),
            "dataset": res.get("dataset", ""),
            "results": res.get("results", ""),
            "limitations": res.get("limitations", ""),
            "claims": res.get("claims", []),
            "figures_referenced": res.get("figures_referenced", []),
        })
    return {"digests": digests}


def _synth_rank(completed: list[dict]) -> dict:
    """Rank: tally pairwise wins per item → leaderboard."""
    wins: Counter = Counter()
    appearances: Counter = Counter()
    matches = []
    for r in completed:
        res = r["result"]
        a = res.get("item_a")
        b = res.get("item_b")
        w = res.get("winner")
        if a and b:
            appearances[a] += 1
            appearances[b] += 1
            if w in (a, b):
                wins[w] += 1
            matches.append({
                "item_a": a, "item_b": b, "winner": w,
                "reasoning": res.get("reasoning", ""),
            })
    leaderboard = sorted(
        [
            {
                "item": item,
                "wins": wins[item],
                "appearances": appearances[item],
                "win_rate": (
                    round(wins[item] / appearances[item], 3)
                    if appearances[item] else 0.0
                ),
            }
            for item in appearances
        ],
        key=lambda x: x["win_rate"],
        reverse=True,
    )
    return {"leaderboard": leaderboard, "matches": matches}


def _synth_compare(completed: list[dict]) -> dict:
    """Compare: cross-item feature matrix."""
    if not completed:
        return {"matrix": [], "schema": []}
    schema_keys: list[str] = []
    seen: set = set()
    for r in completed:
        for k in r["result"].keys():
            if k not in seen:
                seen.add(k)
                schema_keys.append(k)
    matrix = []
    for r in completed:
        row = {"sub_agent_id": r["sub_agent_id"]}
        for k in schema_keys:
            row[k] = r["result"].get(k, "")
        matrix.append(row)
    return {"matrix": matrix, "schema": schema_keys}


def _synth_survey(completed: list[dict]) -> dict:
    """Survey: author trajectory table sorted by h-index."""
    rows = []
    for r in completed:
        res = r["result"]
        rows.append({
            "sub_agent_id": r["sub_agent_id"],
            "author": res.get("author", ""),
            "h_index": _coerce_int(res.get("h_index")),
            "recent_venues": res.get("recent_venues", []),
            "top_papers": res.get("top_papers", []),
        })
    rows.sort(key=lambda x: x["h_index"] or 0, reverse=True)
    return {"authors": rows}


def _synth_screen(completed: list[dict]) -> dict:
    """Screen: include/exclude tally + criteria-failed histogram."""
    n_include = 0
    n_exclude = 0
    criteria_failed: Counter = Counter()
    items = []
    for r in completed:
        res = r["result"]
        inc = bool(res.get("include"))
        if inc:
            n_include += 1
        else:
            n_exclude += 1
        for c in res.get("criteria_failed", []) or []:
            criteria_failed[c] += 1
        items.append({
            "sub_agent_id": r["sub_agent_id"],
            "canonical_id": res.get("canonical_id", ""),
            "include": inc,
            "criteria_failed": res.get("criteria_failed", []),
        })
    return {
        "n_include": n_include,
        "n_exclude": n_exclude,
        "criteria_failed_histogram": dict(criteria_failed),
        "items": items,
    }


def _synth_generic(completed: list[dict]) -> dict:
    """Fallback: emit raw result list."""
    return {
        "results": [
            {"sub_agent_id": r["sub_agent_id"], "result": r["result"]}
            for r in completed
        ]
    }


_SYNTH = {
    "triage": _synth_triage,
    "read": _synth_read,
    "rank": _synth_rank,
    "compare": _synth_compare,
    "survey": _synth_survey,
    "screen": _synth_screen,
}


def _coerce_float(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _coerce_int(v: Any) -> int | None:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def render_brief(synthesis: dict) -> str:
    """Render synthesis dict as markdown brief."""
    t = synthesis["task_type"]
    lines = [
        f"# Wide Research synthesis — {t}",
        "",
        f"**Query**: {synthesis.get('user_query', '(none)')}",
        f"**Total items**: {synthesis['n_total']}",
        f"**Complete**: {synthesis['n_complete']}",
        f"**Missing**: {synthesis['n_missing']}",
        f"**Errors**: {synthesis['n_error']}",
        "",
    ]
    if t == "triage":
        lines += _brief_triage(synthesis)
    elif t == "read":
        lines += _brief_read(synthesis)
    elif t == "rank":
        lines += _brief_rank(synthesis)
    elif t == "compare":
        lines += _brief_compare(synthesis)
    elif t == "survey":
        lines += _brief_survey(synthesis)
    elif t == "screen":
        lines += _brief_screen(synthesis)
    return "\n".join(lines)


def _brief_triage(s: dict) -> list[str]:
    out = ["## Recommend distribution", ""]
    for k, v in s.get("by_recommend", {}).items():
        out.append(f"- **{k}**: {v}")
    out += ["", "## Top shortlist (relevance-sorted)", "",
            "| # | canonical_id | title | year | score | recommend |",
            "|---|---|---|---|---|---|"]
    for i, p in enumerate(s.get("top_shortlist", []), 1):
        out.append(
            f"| {i} | `{p['canonical_id']}` | {p['title'][:60]} | "
            f"{p['year']} | {p['relevance_score']} | {p['recommend']} |"
        )
    return out


def _brief_read(s: dict) -> list[str]:
    out = ["## Per-paper digests", ""]
    for d in s.get("digests", []):
        out += [
            f"### {d['canonical_id']}",
            f"- **Method**: {d['method']}",
            f"- **Dataset**: {d['dataset']}",
            f"- **Results**: {d['results']}",
            f"- **Limitations**: {d['limitations']}",
            "",
        ]
    return out


def _brief_rank(s: dict) -> list[str]:
    out = ["## Leaderboard", "",
           "| rank | item | wins | appearances | win rate |",
           "|---|---|---|---|---|"]
    for i, row in enumerate(s.get("leaderboard", []), 1):
        out.append(
            f"| {i} | `{row['item']}` | {row['wins']} | "
            f"{row['appearances']} | {row['win_rate']} |"
        )
    return out


def _brief_compare(s: dict) -> list[str]:
    schema = s.get("schema", [])
    if not schema:
        return ["_No comparable features extracted._"]
    out = ["## Feature matrix", "",
           "| sub_agent_id | " + " | ".join(schema) + " |",
           "|" + "---|" * (len(schema) + 1)]
    for row in s.get("matrix", []):
        cells = [f"`{row['sub_agent_id']}`"]
        for k in schema:
            cells.append(str(row.get(k, ""))[:40])
        out.append("| " + " | ".join(cells) + " |")
    return out


def _brief_survey(s: dict) -> list[str]:
    out = ["## Authors (h-index sorted)", "",
           "| author | h-index | recent venues | top papers |",
           "|---|---|---|---|"]
    for a in s.get("authors", []):
        venues = ", ".join(a.get("recent_venues", [])[:3])
        n_top = len(a.get("top_papers", []) or [])
        out.append(
            f"| {a['author']} | {a['h_index']} | {venues} | {n_top} |"
        )
    return out


def _brief_screen(s: dict) -> list[str]:
    out = [
        "## PRISMA tally",
        "",
        f"- **Include**: {s.get('n_include', 0)}",
        f"- **Exclude**: {s.get('n_exclude', 0)}",
        "",
        "## Criteria-failed histogram",
        "",
    ]
    for k, v in s.get("criteria_failed_histogram", {}).items():
        out.append(f"- `{k}`: {v}")
    return out

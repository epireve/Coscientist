"""v0.154 — thinking-trace persistence + markdown rendering.

Verdict-producing tables (`hypotheses`, `attack_findings`,
`novelty_assessments`, `publishability_verdicts`) carry a
`thinking_log_json TEXT` column that captures the deliberation
behind each verdict — what was considered, what was rejected and
why, what was finally chosen, the steelman/attack flow.

Persisted as JSON. Liberal in shape; renderer copes with partial
or empty payloads. Pure stdlib.

Expected log shape (all keys optional):
    {
      "considered": [str, ...],
      "rejected":   [{"option": str, "reason": str}, ...],
      "chose":      str,
      "rationale":  str,
      "steelman":   str,
      "attack":     str,
    }
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from lib.cache import connect_wal

# Allowlist of tables that carry `thinking_log_json`. Used to validate
# caller input — keeps the helper from being a generic UPDATE shim.
_ALLOWED_TABLES: frozenset[str] = frozenset({
    "hypotheses",
    "attack_findings",
    "novelty_assessments",
    "publishability_verdicts",
})


def record_thinking(
    run_db: Path,
    table: str,
    row_id_col: str,
    row_id: object,
    log: dict,
) -> None:
    """Persist `log` as JSON into `table.thinking_log_json` for the row
    where `row_id_col == row_id`.

    Validates `table` against the allowlist. `row_id_col` must be
    a column on that table; we don't validate it against table schema
    (caller's responsibility) but we do parameter-bind the value.
    """
    if table not in _ALLOWED_TABLES:
        raise ValueError(
            f"unknown table {table!r}; expected one of "
            f"{sorted(_ALLOWED_TABLES)}"
        )
    payload = json.dumps(log, ensure_ascii=False, sort_keys=True)
    con = connect_wal(run_db)
    try:
        with con:
            con.execute(
                f"UPDATE {table} SET thinking_log_json=? "
                f"WHERE {row_id_col}=?",
                (payload, row_id),
            )
    finally:
        con.close()


def get_thinking(
    run_db: Path,
    table: str,
    row_id_col: str,
    row_id: object,
) -> dict | None:
    """Return parsed thinking log for the matching row, or None
    when the row is missing or the column is NULL/invalid JSON.
    """
    if table not in _ALLOWED_TABLES:
        raise ValueError(
            f"unknown table {table!r}; expected one of "
            f"{sorted(_ALLOWED_TABLES)}"
        )
    con = connect_wal(run_db)
    try:
        row = con.execute(
            f"SELECT thinking_log_json FROM {table} "
            f"WHERE {row_id_col}=?",
            (row_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        # Column missing on older DBs that haven't been migrated.
        return None
    finally:
        con.close()
    if row is None or row[0] is None:
        return None
    try:
        out = json.loads(row[0])
    except (TypeError, ValueError):
        return None
    return out if isinstance(out, dict) else None


def format_thinking_md(log: dict) -> str:
    """Render a thinking log as markdown. Liberal in shape: any of the
    canonical keys is rendered when present, anything else dumped as
    a `key: value` line under a "Other" subsection.

    Empty / non-dict input returns an empty string.
    """
    if not isinstance(log, dict) or not log:
        return ""

    lines: list[str] = []

    considered = log.get("considered")
    if considered:
        lines.append("**Considered:**")
        if isinstance(considered, list):
            for opt in considered:
                lines.append(f"- {opt}")
        else:
            lines.append(f"- {considered}")
        lines.append("")

    rejected = log.get("rejected")
    if rejected:
        lines.append("**Rejected:**")
        if isinstance(rejected, list):
            for entry in rejected:
                if isinstance(entry, dict):
                    opt = entry.get("option", "?")
                    reason = entry.get("reason", "")
                    lines.append(f"- {opt} — {reason}")
                else:
                    lines.append(f"- {entry}")
        else:
            lines.append(f"- {rejected}")
        lines.append("")

    chose = log.get("chose")
    if chose:
        lines.append(f"**Chose:** {chose}")
        lines.append("")

    rationale = log.get("rationale")
    if rationale:
        lines.append(f"**Rationale:** {rationale}")
        lines.append("")

    steelman = log.get("steelman")
    if steelman:
        lines.append(f"**Steelman:** {steelman}")
        lines.append("")

    attack = log.get("attack")
    if attack:
        lines.append(f"**Attack:** {attack}")
        lines.append("")

    canonical = {"considered", "rejected", "chose",
                 "rationale", "steelman", "attack"}
    extras = {k: v for k, v in log.items()
              if k not in canonical and v not in (None, "", [], {})}
    if extras:
        lines.append("**Other:**")
        for k in sorted(extras):
            lines.append(f"- {k}: {extras[k]}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n" if lines else ""


# Per-table identity-column hints for the renderer.
_TABLE_KEYS: tuple[tuple[str, str, str], ...] = (
    # (table, primary identifier column, label-template)
    ("hypotheses",              "hyp_id",       "hypothesis"),
    ("attack_findings",         "finding_id",   "attack-finding"),
    ("novelty_assessments",     "assessment_id", "novelty-assessment"),
    ("publishability_verdicts", "verdict_id",   "publishability-verdict"),
)


def collect_for_run(run_db: Path, run_id: str | None) -> list[dict]:
    """Walk the four verdict tables and return every row whose
    thinking_log_json is non-NULL (filtered to `run_id` when given).

    Each entry: {"table", "id_col", "row_id", "log"}. Tables missing
    the column on older DBs are silently skipped.
    """
    out: list[dict] = []
    con = connect_wal(run_db)
    try:
        for tbl, id_col, _label in _TABLE_KEYS:
            # Probe column presence — older DBs may not have it.
            cols = {row[1] for row in con.execute(
                f"PRAGMA table_info({tbl})"
            )}
            if "thinking_log_json" not in cols:
                continue
            sql = (
                f"SELECT {id_col}, thinking_log_json FROM {tbl} "
                f"WHERE thinking_log_json IS NOT NULL"
            )
            params: tuple = ()
            if run_id and "run_id" in cols:
                sql += " AND run_id=?"
                params = (run_id,)
            try:
                rows = con.execute(sql, params).fetchall()
            except sqlite3.OperationalError:
                continue
            for rid, blob in rows:
                try:
                    log = json.loads(blob)
                except (TypeError, ValueError):
                    continue
                if not isinstance(log, dict):
                    continue
                out.append({
                    "table": tbl,
                    "id_col": id_col,
                    "row_id": rid,
                    "log": log,
                })
    finally:
        con.close()
    return out


def render_thinking_section(run_db: Path,
                            run_id: str | None) -> str:
    """Markdown section with thinking traces for a run. Empty string
    when no traces are present (so callers can append unconditionally).
    """
    entries = collect_for_run(run_db, run_id)
    if not entries:
        return ""
    lines = ["", "## Thinking traces (v0.154)", ""]
    for e in entries:
        lines.append(
            f"### `{e['table']}` · {e['id_col']}=`{e['row_id']}`"
        )
        lines.append("")
        body = format_thinking_md(e["log"])
        if body:
            lines.append(body.rstrip())
        lines.append("")
    return "\n".join(lines) + "\n"

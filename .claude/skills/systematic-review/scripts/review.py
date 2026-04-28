#!/usr/bin/env python3
"""systematic-review: PRISMA-compliant systematic literature review workflow.

Subcommands
-----------
init     Register a new review protocol (must be first).
search   Record search strings and freeze the protocol.
screen   Record one title/abstract or full-text screening decision.
extract  Record one data-extraction field for an included paper.
bias     Record one risk-of-bias domain assessment.
prisma   Generate a Markdown PRISMA flow diagram.
status   Print a progress summary for a protocol.

Typical workflow
----------------
  # 1. Protocol first
  python review.py init --title "..." --question "..." \\
      --inclusion '["..."]' --exclusion '["..."]'

  # 2. Freeze protocol with search queries
  python review.py search --protocol-id <pid> --queries '["q1","q2"]'

  # 3. Screen papers (two stages)
  python review.py screen --protocol-id <pid> --paper-id <id> \\
      --stage title_abstract --decision include
  python review.py screen --protocol-id <pid> --paper-id <id> \\
      --stage full_text --decision include

  # 4. Extract data from included papers
  python review.py extract --protocol-id <pid> --paper-id <id> \\
      --field sample_size --value 142 --unit participants

  # 5. Bias assessment
  python review.py bias --protocol-id <pid> --paper-id <id> \\
      --domain selection --rating low

  # 6. Generate PRISMA flow
  python review.py prisma --protocol-id <pid>

  # 7. Check progress at any time
  python review.py status --protocol-id <pid>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.cache import cache_root  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_STAGES = ("title_abstract", "full_text")
VALID_DECISIONS = ("include", "exclude", "uncertain")
VALID_DOMAINS = ("selection", "performance", "detection", "attrition", "reporting")
VALID_RATINGS = ("low", "unclear", "high")

_SCHEMA = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS review_protocols (
    protocol_id    TEXT PRIMARY KEY,
    run_id         TEXT,
    title          TEXT NOT NULL,
    question       TEXT NOT NULL,
    inclusion      TEXT NOT NULL,
    exclusion      TEXT NOT NULL,
    search_strings TEXT NOT NULL,
    date_range     TEXT,
    languages      TEXT DEFAULT '["en"]',
    created_at     TEXT NOT NULL,
    frozen_at      TEXT
);

CREATE TABLE IF NOT EXISTS screening_decisions (
    decision_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    protocol_id    TEXT NOT NULL REFERENCES review_protocols(protocol_id) ON DELETE CASCADE,
    paper_id       TEXT NOT NULL,
    stage          TEXT NOT NULL CHECK(stage IN ('title_abstract','full_text')),
    decision       TEXT NOT NULL CHECK(decision IN ('include','exclude','uncertain')),
    reason         TEXT,
    decided_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS extraction_rows (
    row_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    protocol_id    TEXT NOT NULL REFERENCES review_protocols(protocol_id) ON DELETE CASCADE,
    paper_id       TEXT NOT NULL,
    field          TEXT NOT NULL,
    value          TEXT,
    unit           TEXT,
    notes          TEXT,
    extracted_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bias_assessments (
    assessment_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    protocol_id    TEXT NOT NULL REFERENCES review_protocols(protocol_id) ON DELETE CASCADE,
    paper_id       TEXT NOT NULL,
    domain         TEXT NOT NULL,
    rating         TEXT NOT NULL CHECK(rating IN ('low','unclear','high')),
    justification  TEXT,
    assessed_at    TEXT NOT NULL
);
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slug(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "_", text).strip("_")
    return text[:40]


def _make_protocol_id(title: str, question: str) -> str:
    digest = hashlib.blake2s(f"{title}::{question}".encode()).hexdigest()[:6]
    return f"{_slug(title)}_{digest}"


def _review_dir(protocol_id: str) -> Path:
    p = cache_root() / "reviews" / protocol_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def _db_path(protocol_id: str) -> Path:
    return _review_dir(protocol_id) / "review.db"


def _open_db(protocol_id: str) -> sqlite3.Connection:
    """Open (and initialise if new) the per-protocol SQLite DB."""
    conn = sqlite3.connect(str(_db_path(protocol_id)))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _load_protocol(conn: sqlite3.Connection, protocol_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM review_protocols WHERE protocol_id = ?", (protocol_id,)
    ).fetchone()
    if row is None:
        print(f"ERROR: protocol {protocol_id!r} not found.", file=sys.stderr)
        sys.exit(1)
    return row


# ---------------------------------------------------------------------------
# Subcommand: init
# ---------------------------------------------------------------------------

def cmd_init(args: argparse.Namespace) -> int:
    protocol_id = _make_protocol_id(args.title, args.question)

    # Check for duplicate
    db = _db_path(protocol_id)
    if db.exists():
        conn = sqlite3.connect(str(db))
        row = conn.execute(
            "SELECT protocol_id FROM review_protocols WHERE protocol_id = ?",
            (protocol_id,),
        ).fetchone()
        conn.close()
        if row is not None:
            print(
                f"ERROR: protocol {protocol_id!r} already exists. "
                "Each title+question pair maps to a unique protocol.",
                file=sys.stderr,
            )
            return 1

    # Validate JSON arrays
    try:
        inclusion = json.loads(args.inclusion)
        if not isinstance(inclusion, list):
            raise ValueError("inclusion must be a JSON array")
    except (json.JSONDecodeError, ValueError) as e:
        print(f"ERROR: --inclusion is not valid JSON array: {e}", file=sys.stderr)
        return 2

    try:
        exclusion = json.loads(args.exclusion)
        if not isinstance(exclusion, list):
            raise ValueError("exclusion must be a JSON array")
    except (json.JSONDecodeError, ValueError) as e:
        print(f"ERROR: --exclusion is not valid JSON array: {e}", file=sys.stderr)
        return 2

    conn = _open_db(protocol_id)
    now = _now()
    conn.execute(
        """INSERT INTO review_protocols
           (protocol_id, run_id, title, question, inclusion, exclusion,
            search_strings, date_range, languages, created_at, frozen_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)""",
        (
            protocol_id,
            args.run_id,
            args.title,
            args.question,
            json.dumps(inclusion),
            json.dumps(exclusion),
            json.dumps([]),   # empty until search
            args.date_range,
            '["en"]',
            now,
        ),
    )
    conn.commit()
    conn.close()

    # Write human-readable protocol.json
    proto_json = {
        "protocol_id": protocol_id,
        "title": args.title,
        "question": args.question,
        "inclusion": inclusion,
        "exclusion": exclusion,
        "date_range": args.date_range,
        "run_id": args.run_id,
        "created_at": now,
    }
    (_review_dir(protocol_id) / "protocol.json").write_text(
        json.dumps(proto_json, indent=2)
    )

    print(protocol_id)
    return 0


# ---------------------------------------------------------------------------
# Subcommand: search
# ---------------------------------------------------------------------------

def cmd_search(args: argparse.Namespace) -> int:
    try:
        new_queries = json.loads(args.queries)
        if not isinstance(new_queries, list):
            raise ValueError("queries must be a JSON array")
    except (json.JSONDecodeError, ValueError) as e:
        print(f"ERROR: --queries is not valid JSON array: {e}", file=sys.stderr)
        return 2

    conn = _open_db(args.protocol_id)
    proto = _load_protocol(conn, args.protocol_id)

    # Cannot call search after screen has begun
    screen_count = conn.execute(
        "SELECT COUNT(*) FROM screening_decisions WHERE protocol_id = ?",
        (args.protocol_id,),
    ).fetchone()[0]
    if screen_count > 0:
        print(
            "ERROR: screening has already begun — cannot modify search strings.",
            file=sys.stderr,
        )
        conn.close()
        return 1

    # Append queries
    existing = json.loads(proto["search_strings"])
    merged = existing + new_queries

    now = _now()
    conn.execute(
        "UPDATE review_protocols SET search_strings = ?, frozen_at = ? WHERE protocol_id = ?",
        (json.dumps(merged), now, args.protocol_id),
    )
    conn.commit()

    # Collect paper_ids from linked run if available
    paper_ids: list[str] = []
    run_id = proto["run_id"]
    if run_id:
        run_db = cache_root() / "runs" / f"run-{run_id}.db"
        if run_db.exists():
            try:
                rconn = sqlite3.connect(str(run_db))
                rows = rconn.execute(
                    "SELECT canonical_id FROM papers_in_run WHERE run_id = ?",
                    (run_id,),
                ).fetchall()
                paper_ids = [r[0] for r in rows]
                rconn.close()
            except Exception:  # noqa: BLE001
                pass

    conn.close()
    print(json.dumps(paper_ids))
    return 0


# ---------------------------------------------------------------------------
# Subcommand: screen
# ---------------------------------------------------------------------------

def cmd_screen(args: argparse.Namespace) -> int:
    if args.stage not in VALID_STAGES:
        print(
            f"ERROR: --stage must be one of {VALID_STAGES}, got {args.stage!r}",
            file=sys.stderr,
        )
        return 2
    if args.decision not in VALID_DECISIONS:
        print(
            f"ERROR: --decision must be one of {VALID_DECISIONS}, got {args.decision!r}",
            file=sys.stderr,
        )
        return 2

    conn = _open_db(args.protocol_id)
    proto = _load_protocol(conn, args.protocol_id)

    # Protocol must be frozen
    if not proto["frozen_at"]:
        print(
            "ERROR: protocol is not frozen. Run `search` before `screen`.",
            file=sys.stderr,
        )
        conn.close()
        return 1

    # full_text requires prior title_abstract decision
    if args.stage == "full_text":
        prior = conn.execute(
            """SELECT decision_id FROM screening_decisions
               WHERE protocol_id = ? AND paper_id = ? AND stage = 'title_abstract'""",
            (args.protocol_id, args.paper_id),
        ).fetchone()
        if prior is None:
            print(
                f"ERROR: no title_abstract decision found for paper {args.paper_id!r}. "
                "Screen title/abstract stage first.",
                file=sys.stderr,
            )
            conn.close()
            return 1

    now = _now()

    # Idempotent: delete existing decision for this paper+stage before inserting
    conn.execute(
        """DELETE FROM screening_decisions
           WHERE protocol_id = ? AND paper_id = ? AND stage = ?""",
        (args.protocol_id, args.paper_id, args.stage),
    )
    conn.execute(
        """INSERT INTO screening_decisions
           (protocol_id, paper_id, stage, decision, reason, decided_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (args.protocol_id, args.paper_id, args.stage, args.decision,
         args.reason, now),
    )
    conn.commit()
    conn.close()
    print(f"screened:{args.paper_id} stage:{args.stage} decision:{args.decision}")
    return 0


# ---------------------------------------------------------------------------
# Subcommand: extract
# ---------------------------------------------------------------------------

def cmd_extract(args: argparse.Namespace) -> int:
    conn = _open_db(args.protocol_id)
    _load_protocol(conn, args.protocol_id)

    # Paper must have a full_text include decision
    ft_include = conn.execute(
        """SELECT decision_id FROM screening_decisions
           WHERE protocol_id = ? AND paper_id = ?
             AND stage = 'full_text' AND decision = 'include'""",
        (args.protocol_id, args.paper_id),
    ).fetchone()
    if ft_include is None:
        print(
            f"ERROR: paper {args.paper_id!r} does not have a full_text 'include' decision. "
            "Only included papers can have data extracted.",
            file=sys.stderr,
        )
        conn.close()
        return 1

    now = _now()
    conn.execute(
        """INSERT INTO extraction_rows
           (protocol_id, paper_id, field, value, unit, notes, extracted_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (args.protocol_id, args.paper_id, args.field,
         args.value, args.unit, args.notes, now),
    )
    conn.commit()
    conn.close()
    print(f"extracted:{args.paper_id} field:{args.field} value:{args.value}")
    return 0


# ---------------------------------------------------------------------------
# Subcommand: bias
# ---------------------------------------------------------------------------

def cmd_bias(args: argparse.Namespace) -> int:
    if args.domain not in VALID_DOMAINS:
        print(
            f"ERROR: --domain must be one of {VALID_DOMAINS}, got {args.domain!r}",
            file=sys.stderr,
        )
        return 2
    if args.rating not in VALID_RATINGS:
        print(
            f"ERROR: --rating must be one of {VALID_RATINGS}, got {args.rating!r}",
            file=sys.stderr,
        )
        return 2

    conn = _open_db(args.protocol_id)
    _load_protocol(conn, args.protocol_id)

    now = _now()
    # Idempotent per paper+domain
    conn.execute(
        """DELETE FROM bias_assessments
           WHERE protocol_id = ? AND paper_id = ? AND domain = ?""",
        (args.protocol_id, args.paper_id, args.domain),
    )
    conn.execute(
        """INSERT INTO bias_assessments
           (protocol_id, paper_id, domain, rating, justification, assessed_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (args.protocol_id, args.paper_id, args.domain,
         args.rating, args.justification, now),
    )
    conn.commit()
    conn.close()
    print(f"bias:{args.paper_id} domain:{args.domain} rating:{args.rating}")
    return 0


# ---------------------------------------------------------------------------
# Subcommand: prisma
# ---------------------------------------------------------------------------

def cmd_prisma(args: argparse.Namespace) -> int:
    conn = _open_db(args.protocol_id)
    proto = _load_protocol(conn, args.protocol_id)

    search_strings = json.loads(proto["search_strings"])
    n_search_strings = len(search_strings)

    # Title/abstract counts
    ta_rows = conn.execute(
        """SELECT decision, reason, COUNT(*) as cnt
           FROM screening_decisions
           WHERE protocol_id = ? AND stage = 'title_abstract'
           GROUP BY decision, reason""",
        (args.protocol_id,),
    ).fetchall()
    ta_total = sum(r["cnt"] for r in ta_rows)
    ta_include = sum(r["cnt"] for r in ta_rows if r["decision"] == "include")
    ta_uncertain = sum(r["cnt"] for r in ta_rows if r["decision"] == "uncertain")
    ta_exclude = sum(r["cnt"] for r in ta_rows if r["decision"] == "exclude")

    # Reason breakdown for title/abstract exclusions
    ta_reasons: dict[str, int] = {}
    for r in ta_rows:
        if r["decision"] == "exclude":
            key = r["reason"] or "no reason given"
            ta_reasons[key] = ta_reasons.get(key, 0) + r["cnt"]

    # Full-text counts
    ft_rows = conn.execute(
        """SELECT decision, reason, COUNT(*) as cnt
           FROM screening_decisions
           WHERE protocol_id = ? AND stage = 'full_text'
           GROUP BY decision, reason""",
        (args.protocol_id,),
    ).fetchall()
    ft_total = sum(r["cnt"] for r in ft_rows)
    ft_include = sum(r["cnt"] for r in ft_rows if r["decision"] == "include")
    ft_exclude = sum(r["cnt"] for r in ft_rows if r["decision"] == "exclude")

    # Reason breakdown for full-text exclusions
    ft_reasons: dict[str, int] = {}
    for r in ft_rows:
        if r["decision"] == "exclude":
            key = r["reason"] or "no reason given"
            ft_reasons[key] = ft_reasons.get(key, 0) + r["cnt"]

    conn.close()

    # Estimated records identified: ta_total as the screened count,
    # n_search_strings as the proxy for database searches run.
    n_identified = max(ta_total, n_search_strings)

    lines = [
        "# PRISMA Flow Diagram",
        "",
        f"Protocol: **{proto['title']}**",
        "",
        "```",
        "┌─────────────────────────────────────────────┐",
        "│             IDENTIFICATION                   │",
        "├─────────────────────────────────────────────┤",
        "│  Records identified via searching            │",
        f"│  (n = {n_identified}){'':>38}│".replace("│" + " " * 45 + "│", "│" + f"  Records identified via searching            │\n│  (n = {n_identified})"),
        "└──────────────────────┬──────────────────────┘",
        "                       │",
        "                       ▼",
        "┌─────────────────────────────────────────────┐",
        "│               SCREENING                      │",
        "├─────────────────────────────────────────────┤",
        "│  Records screened (title/abstract)           │",
        f"│  (n = {ta_total})                                      │",
        "├─────────────────────────────────────────────┤",
    ]

    if ta_exclude > 0:
        lines += [
            "│  Records excluded (title/abstract)           │",
            f"│  (n = {ta_exclude})                                      │",
        ]
        for reason, cnt in sorted(ta_reasons.items()):
            short_reason = reason[:38]
            lines.append(f"│    - {short_reason}: {cnt}{'':>2}│")
        lines.append("├─────────────────────────────────────────────┤")

    lines += [
        f"│  Eligible for full-text (n = {ta_include + ta_uncertain}){'':>14}│",
        "└──────────────────────┬──────────────────────┘",
        "                       │",
        "                       ▼",
        "┌─────────────────────────────────────────────┐",
        "│              ELIGIBILITY                     │",
        "├─────────────────────────────────────────────┤",
        "│  Full-text articles assessed                 │",
        f"│  (n = {ft_total})                                      │",
        "├─────────────────────────────────────────────┤",
    ]

    if ft_exclude > 0:
        lines += [
            "│  Full-text articles excluded                 │",
            f"│  (n = {ft_exclude})                                      │",
        ]
        for reason, cnt in sorted(ft_reasons.items()):
            short_reason = reason[:38]
            lines.append(f"│    - {short_reason}: {cnt}{'':>2}│")
        lines.append("├─────────────────────────────────────────────┤")

    lines += [
        "└──────────────────────┬──────────────────────┘",
        "                       │",
        "                       ▼",
        "┌─────────────────────────────────────────────┐",
        "│               INCLUDED                       │",
        "├─────────────────────────────────────────────┤",
        "│  Studies included in synthesis               │",
        f"│  (n = {ft_include})                                      │",
        "└─────────────────────────────────────────────┘",
        "```",
        "",
        f"_Generated: {_now()}_",
    ]

    # Rebuild lines without the malformed duplicate line
    clean_lines = []
    for line in lines:
        # Skip the malformed line we accidentally introduced
        if "Records identified via searching" in line and "│\n│" in line:
            continue
        clean_lines.append(line)

    content = "\n".join(clean_lines) + "\n"
    out_path = _review_dir(args.protocol_id) / "prisma.md"
    out_path.write_text(content)
    print(str(out_path))
    return 0


# ---------------------------------------------------------------------------
# Subcommand: status
# ---------------------------------------------------------------------------

def cmd_status(args: argparse.Namespace) -> int:
    db = _db_path(args.protocol_id)
    if not db.exists():
        print(f"ERROR: protocol {args.protocol_id!r} not found.", file=sys.stderr)
        return 1

    conn = _open_db(args.protocol_id)
    proto = _load_protocol(conn, args.protocol_id)

    print(f"protocol_id : {proto['protocol_id']}")
    print(f"title       : {proto['title']}")
    print(f"question    : {proto['question']}")
    print(f"date_range  : {proto['date_range'] or '(not set)'}")
    print(f"frozen_at   : {proto['frozen_at'] or '(not frozen)'}")

    search_strings = json.loads(proto["search_strings"])
    print(f"search_strings: {len(search_strings)} registered")
    print()

    # Screening progress
    print("=== Screening Progress ===")
    for stage in VALID_STAGES:
        rows = conn.execute(
            """SELECT decision, COUNT(*) as cnt
               FROM screening_decisions
               WHERE protocol_id = ? AND stage = ?
               GROUP BY decision""",
            (args.protocol_id, stage),
        ).fetchall()
        totals = {r["decision"]: r["cnt"] for r in rows}
        inc = totals.get("include", 0)
        exc = totals.get("exclude", 0)
        unc = totals.get("uncertain", 0)
        total = inc + exc + unc
        print(f"  {stage:<20}: {total} screened  "
              f"include={inc}  exclude={exc}  uncertain={unc}")

    print()

    # Extraction completeness
    ext_rows = conn.execute(
        """SELECT COUNT(DISTINCT paper_id) as papers,
                  COUNT(DISTINCT field) as fields
           FROM extraction_rows WHERE protocol_id = ?""",
        (args.protocol_id,),
    ).fetchone()
    print("=== Extraction ===")
    print(f"  {ext_rows['papers']} papers with extracted data, "
          f"{ext_rows['fields']} distinct fields")

    print()

    # Bias coverage
    bias_rows = conn.execute(
        """SELECT COUNT(DISTINCT paper_id) as papers,
                  COUNT(DISTINCT domain) as domains
           FROM bias_assessments WHERE protocol_id = ?""",
        (args.protocol_id,),
    ).fetchone()
    print("=== Bias Assessments ===")
    print(f"  {bias_rows['papers']} papers assessed, "
          f"{bias_rows['domains']} distinct domains covered")

    print()

    # PRISMA status
    prisma_path = _review_dir(args.protocol_id) / "prisma.md"
    print("=== PRISMA Diagram ===")
    if prisma_path.exists():
        print(f"  Generated: {prisma_path}")
    else:
        print("  Not yet generated. Run `prisma` subcommand.")

    conn.close()
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(
        prog="review.py",
        description="PRISMA-compliant systematic literature review workflow.",
    )
    sub = p.add_subparsers(dest="subcommand", required=True)

    # init
    pi = sub.add_parser("init", help="Register a new review protocol")
    pi.add_argument("--title", required=True, help="Review title")
    pi.add_argument("--question", required=True,
                    help="Research question (PICO or equivalent)")
    pi.add_argument("--inclusion", required=True,
                    help="JSON array of inclusion criteria strings")
    pi.add_argument("--exclusion", required=True,
                    help="JSON array of exclusion criteria strings")
    pi.add_argument("--date-range", dest="date_range",
                    help='Date range, e.g. "2015-2025"')
    pi.add_argument("--run-id", dest="run_id",
                    help="Link to a deep-research run_id")

    # search
    ps = sub.add_parser("search", help="Record search strings and freeze protocol")
    ps.add_argument("--protocol-id", required=True, dest="protocol_id")
    ps.add_argument("--queries", required=True,
                    help="JSON array of query strings")

    # screen
    psc = sub.add_parser("screen", help="Record a screening decision")
    psc.add_argument("--protocol-id", required=True, dest="protocol_id")
    psc.add_argument("--paper-id", required=True, dest="paper_id")
    psc.add_argument("--stage", required=True,
                     choices=list(VALID_STAGES),
                     help="Screening stage")
    psc.add_argument("--decision", required=True,
                     choices=list(VALID_DECISIONS),
                     help="Screening decision")
    psc.add_argument("--reason", help="Reason or note for this decision")

    # extract
    pex = sub.add_parser("extract", help="Record a data-extraction field")
    pex.add_argument("--protocol-id", required=True, dest="protocol_id")
    pex.add_argument("--paper-id", required=True, dest="paper_id")
    pex.add_argument("--field", required=True, help="Field name, e.g. sample_size")
    pex.add_argument("--value", required=True, help="Extracted value")
    pex.add_argument("--unit", help="Unit of measurement")
    pex.add_argument("--notes", help="Extraction notes")

    # bias
    pb = sub.add_parser("bias", help="Record a risk-of-bias assessment")
    pb.add_argument("--protocol-id", required=True, dest="protocol_id")
    pb.add_argument("--paper-id", required=True, dest="paper_id")
    pb.add_argument("--domain", required=True,
                    choices=list(VALID_DOMAINS),
                    help="Bias domain")
    pb.add_argument("--rating", required=True,
                    choices=list(VALID_RATINGS),
                    help="Risk-of-bias rating")
    pb.add_argument("--justification", help="Justification text")

    # prisma
    ppr = sub.add_parser("prisma", help="Generate PRISMA flow diagram")
    ppr.add_argument("--protocol-id", required=True, dest="protocol_id")

    # status
    pst = sub.add_parser("status", help="Print review progress summary")
    pst.add_argument("--protocol-id", required=True, dest="protocol_id")

    args = p.parse_args()
    dispatch = {
        "init": cmd_init,
        "search": cmd_search,
        "screen": cmd_screen,
        "extract": cmd_extract,
        "bias": cmd_bias,
        "prisma": cmd_prisma,
        "status": cmd_status,
    }
    return dispatch[args.subcommand](args)


if __name__ == "__main__":
    sys.exit(main())

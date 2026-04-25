"""v0.13 — multi-DB transaction primitive.

Several skills write to two SQLite DBs in one logical operation
(e.g., manuscript-audit gate writes to run DB + project DB). If one
write succeeds and the other fails, partial state results.

This context manager opens both DBs in DEFERRED mode, BEGINs each
explicitly, runs the user block, then COMMITs both — or ROLLBACKs
both on any exception. It's not a true distributed-2PC; it's
"best-effort atomic" — if commit-1 succeeds and commit-2 fails (rare
without disk failure), the system is still inconsistent. Good enough
for personal-research workloads.

Usage:
    from lib.transaction import multi_db_tx
    with multi_db_tx([run_db_path, project_db_path]) as cons:
        run_con, proj_con = cons
        run_con.execute("INSERT INTO claims …")
        proj_con.execute("INSERT INTO claims …")
        # both commit on success; both rollback on raise
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def multi_db_tx(db_paths: list[Path],
                isolation_level: str = "DEFERRED") -> Iterator[list[sqlite3.Connection]]:
    """Open all DBs and BEGIN; commit all on clean exit, rollback all on error.

    Connections are passed to the caller in the same order as `db_paths`.
    Caller does not need to call .commit() — that happens here.
    """
    cons: list[sqlite3.Connection] = []
    try:
        for path in db_paths:
            con = sqlite3.connect(path)
            con.row_factory = sqlite3.Row
            con.isolation_level = None  # we manage BEGIN/COMMIT explicitly
            con.execute(f"BEGIN {isolation_level}")
            cons.append(con)

        yield cons

        # All blocks completed; commit each in order.
        for con in cons:
            con.execute("COMMIT")
    except Exception:
        # Rollback every connection we opened
        for con in cons:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
        raise
    finally:
        for con in cons:
            try:
                con.close()
            except sqlite3.Error:
                pass

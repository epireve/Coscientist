"""v0.10 citation key collision + disambiguation tests.

Covers:
- disambiguate_entry_keys auto-suffixes collisions (wang2020a, wang2020b)
- Unique keys pass through unchanged
- manuscript_references gets disambiguated_key column populated correctly
- validate_citations detects `ambiguous-citation` when in-text key has ≥2 bib matches
- validate_citations accepts disambiguated_key as a precise resolve
- collision_groups surfaced in validation report
- audit gate accepts `ambiguous-citation` kind
"""

from tests import _shim  # noqa: F401

import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests

_ROOT = Path(__file__).resolve().parent.parent
SCHEMA = (_ROOT / "lib" / "sqlite_schema.sql").read_text()

INGEST = _ROOT / ".claude/skills/manuscript-ingest/scripts/ingest.py"
VALIDATE = _ROOT / ".claude/skills/manuscript-ingest/scripts/validate_citations.py"
AUDIT_GATE = _ROOT / ".claude/skills/manuscript-audit/scripts/gate.py"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], capture_output=True, text=True)


def _run_with_input(script: Path, input_json, *args: str) -> subprocess.CompletedProcess:
    tmp = _ROOT / "tests" / "_tmp_input.json"
    tmp.write_text(json.dumps(input_json))
    return _run(str(script), "--input", str(tmp), *args)


def _seed_project(cache_dir: Path, pid: str = "v010_proj") -> str:
    p = cache_dir / "projects" / pid
    p.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p / "project.db")
    con.executescript(SCHEMA)
    con.execute(
        "INSERT INTO projects (project_id, name, created_at) VALUES (?, ?, ?)",
        (pid, "Collision test", "2026-04-24T00:00:00Z"),
    )
    con.commit()
    con.close()
    return pid


def _load_ingest_mod():
    path = _ROOT / ".claude/skills/manuscript-ingest/scripts/ingest.py"
    spec = importlib.util.spec_from_file_location("ingest_v10", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------- disambiguate_entry_keys unit ----------------

class DisambiguationUnitTests(TestCase):
    def test_unique_keys_pass_through(self):
        mod = _load_ingest_mod()
        entries = [
            {"entry_key": "smith2020", "ordinal": 1, "raw_text": "Smith 2020"},
            {"entry_key": "jones2019", "ordinal": 2, "raw_text": "Jones 2019"},
        ]
        out = mod.disambiguate_entry_keys(entries)
        keys = {e["disambiguated_key"] for e in out}
        self.assertEqual(keys, {"smith2020", "jones2019"})

    def test_two_way_collision(self):
        mod = _load_ingest_mod()
        entries = [
            {"entry_key": "wang2020", "ordinal": 3, "raw_text": "Wang (2020) paper A"},
            {"entry_key": "wang2020", "ordinal": 7, "raw_text": "Wang (2020) paper B"},
        ]
        out = mod.disambiguate_entry_keys(entries)
        dkeys = {e["disambiguated_key"] for e in out}
        self.assertEqual(dkeys, {"wang2020a", "wang2020b"})
        # Earlier ordinal gets 'a'
        by_ord = {e["ordinal"]: e["disambiguated_key"] for e in out}
        self.assertEqual(by_ord[3], "wang2020a")
        self.assertEqual(by_ord[7], "wang2020b")

    def test_three_way_collision(self):
        mod = _load_ingest_mod()
        entries = [
            {"entry_key": "li2021", "ordinal": 1, "raw_text": "Li 2021 A"},
            {"entry_key": "li2021", "ordinal": 5, "raw_text": "Li 2021 B"},
            {"entry_key": "li2021", "ordinal": 2, "raw_text": "Li 2021 C"},
        ]
        out = mod.disambiguate_entry_keys(entries)
        by_ord = {e["ordinal"]: e["disambiguated_key"] for e in out}
        # Ordered by ordinal: 1→a, 2→b, 5→c
        self.assertEqual(by_ord[1], "li2021a")
        self.assertEqual(by_ord[2], "li2021b")
        self.assertEqual(by_ord[5], "li2021c")

    def test_none_entry_key_untouched(self):
        mod = _load_ingest_mod()
        entries = [
            {"entry_key": None, "ordinal": 1, "raw_text": "Unparseable entry"},
            {"entry_key": "smith2020", "ordinal": 2, "raw_text": "Smith 2020"},
        ]
        out = mod.disambiguate_entry_keys(entries)
        by_ord = {e["ordinal"]: e["disambiguated_key"] for e in out}
        self.assertEqual(by_ord[1], None)
        self.assertEqual(by_ord[2], "smith2020")

    def test_collision_groups_helper(self):
        mod = _load_ingest_mod()
        entries = [
            {"entry_key": "smith2020", "ordinal": 1, "raw_text": "Smith 2020"},
            {"entry_key": "wang2020", "ordinal": 2, "raw_text": "Wang 2020 A"},
            {"entry_key": "wang2020", "ordinal": 3, "raw_text": "Wang 2020 B"},
        ]
        groups = mod.collision_groups(entries)
        self.assertIn("wang2020", groups)
        self.assertNotIn("smith2020", groups)
        self.assertEqual(len(groups["wang2020"]), 2)


# ---------------- ingest persistence ----------------

class IngestDisambiguationTests(TestCase):
    def test_ingest_populates_disambiguated_key_for_collisions(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir)
            src = cache_dir / "ms.md"
            src.write_text(
                "# Intro\n\nFoo.\n\n"
                "# References\n\n"
                "- Wang, X. (2020). First Wang paper. Journal A.\n"
                "- Wang, X. (2020). Second Wang paper. Journal B.\n"
                "- Smith, J. (2019). Unique. Conf.\n"
            )
            r = _run(str(INGEST), "--source", str(src), "--title", "T",
                     "--project-id", pid)
            assert r.returncode == 0, f"stderr={r.stderr}"
            mid = r.stdout.strip()

            db = cache_dir / "projects" / pid / "project.db"
            con = sqlite3.connect(db)
            rows = con.execute(
                "SELECT ordinal, entry_key, disambiguated_key FROM manuscript_references "
                "WHERE manuscript_id=? ORDER BY ordinal", (mid,)
            ).fetchall()
            con.close()

            by_ord = {r[0]: (r[1], r[2]) for r in rows}
            # ordinals 1, 2, 3
            self.assertEqual(by_ord[1], ("wang2020", "wang2020a"))
            self.assertEqual(by_ord[2], ("wang2020", "wang2020b"))
            self.assertEqual(by_ord[3], ("smith2019", "smith2019"))


# ---------------- validate_citations ----------------

def _setup(cache_dir: Path, md: str, pid: str = "val_proj") -> tuple[str, str]:
    _seed_project(cache_dir, pid)
    src = cache_dir / "ms.md"
    src.write_text(md)
    r = _run(str(INGEST), "--source", str(src), "--title", "V",
             "--project-id", pid)
    assert r.returncode == 0, f"stderr={r.stderr}"
    return r.stdout.strip(), pid


class AmbiguousCitationTests(TestCase):
    def test_ambiguous_when_bib_has_collision_and_intext_uses_plain_key(self):
        with isolated_cache() as cache_dir:
            mid, pid = _setup(cache_dir, (
                "# Intro\n\nCite \\cite{wang2020} here.\n\n"
                "# References\n\n"
                "- Wang, X. (2020). Paper A. Journal.\n"
                "- Wang, X. (2020). Paper B. Conf.\n"
            ))
            _run(str(VALIDATE), "--manuscript-id", mid, "--project-id", pid)
            report = json.loads(
                (cache_dir / "manuscripts" / mid / "validation_report.json").read_text()
            )
            self.assertEqual(report["summary"]["ambiguous_citations"], 1)
            amb = report["ambiguous_citations"][0]
            self.assertEqual(amb["citation_key"], "wang2020")
            self.assertEqual(len(amb["candidates"]), 2)
            dkeys = {c["disambiguated_key"] for c in amb["candidates"]}
            self.assertEqual(dkeys, {"wang2020a", "wang2020b"})

    def test_disambiguated_key_resolves_cleanly(self):
        """Author writes \\cite{wang2020a} — matches exactly one entry."""
        with isolated_cache() as cache_dir:
            mid, pid = _setup(cache_dir, (
                "# Intro\n\nCite \\cite{wang2020a} here.\n\n"
                "# References\n\n"
                "- Wang, X. (2020). Paper A. Journal.\n"
                "- Wang, X. (2020). Paper B. Conf.\n"
            ))
            _run(str(VALIDATE), "--manuscript-id", mid, "--project-id", pid)
            report = json.loads(
                (cache_dir / "manuscripts" / mid / "validation_report.json").read_text()
            )
            self.assertEqual(report["summary"]["ambiguous_citations"], 0)
            self.assertEqual(report["summary"]["dangling_citations"], 0)

    def test_collision_groups_surfaced_even_without_in_text_ambiguity(self):
        """Bib has Wang-Wang collision but author only cites wang2020a →
        no ambiguous finding, but collision_groups still reported."""
        with isolated_cache() as cache_dir:
            mid, pid = _setup(cache_dir, (
                "# Intro\n\nCite \\cite{wang2020a} here.\n\n"
                "# References\n\n"
                "- Wang, X. (2020). Paper A. Journal.\n"
                "- Wang, X. (2020). Paper B. Conf.\n"
            ))
            _run(str(VALIDATE), "--manuscript-id", mid, "--project-id", pid)
            report = json.loads(
                (cache_dir / "manuscripts" / mid / "validation_report.json").read_text()
            )
            self.assertEqual(report["summary"]["collision_groups"], 1)
            self.assertEqual(report["collision_groups"][0]["entry_key"], "wang2020")

    def test_fail_on_major_triggers_on_ambiguous(self):
        with isolated_cache() as cache_dir:
            mid, pid = _setup(cache_dir, (
                "# Intro\n\nCite \\cite{wang2020}.\n\n"
                "# References\n\n"
                "- Wang, X. (2020). Paper A. Journal.\n"
                "- Wang, X. (2020). Paper B. Conf.\n"
            ))
            r = _run(str(VALIDATE), "--manuscript-id", mid, "--project-id", pid,
                     "--fail-on-major")
            self.assertEqual(r.returncode, 2)

    def test_ambiguous_lands_in_manuscript_audit_findings(self):
        with isolated_cache() as cache_dir:
            mid, pid = _setup(cache_dir, (
                "# Intro\n\nCite \\cite{wang2020}.\n\n"
                "# References\n\n"
                "- Wang, X. (2020). Paper A.\n"
                "- Wang, X. (2020). Paper B.\n"
            ))
            _run(str(VALIDATE), "--manuscript-id", mid, "--project-id", pid)
            db = cache_dir / "projects" / pid / "project.db"
            con = sqlite3.connect(db)
            rows = con.execute(
                "SELECT kind FROM manuscript_audit_findings "
                "WHERE manuscript_id=? AND claim_id LIKE 'citation-validator:%'",
                (mid,),
            ).fetchall()
            con.close()
            kinds = {r[0] for r in rows}
            self.assertIn("ambiguous-citation", kinds)


# ---------------- audit gate kind ----------------

class AuditGateAmbiguousKindTests(TestCase):
    def test_gate_accepts_ambiguous_citation_kind(self):
        with isolated_cache():
            report = {
                "manuscript_id": "ms_amb",
                "claims": [{
                    "claim_id": "c-1",
                    "text": "Wang shows \\cite{wang2020}.",
                    "location": "§1",
                    "cited_sources": ["wang_2020_a_abc"],
                    "findings": [{
                        "kind": "ambiguous-citation",
                        "severity": "major",
                        "evidence": "wang2020 matches two bib entries.",
                    }],
                }],
            }
            r = _run_with_input(AUDIT_GATE, report, "--manuscript-id", "ms_amb")
            assert r.returncode == 0, f"stderr={r.stderr}"


# ---------------- schema ----------------

class DisambiguatedKeyColumnTests(TestCase):
    def test_column_present(self):
        con = sqlite3.connect(":memory:")
        con.executescript(SCHEMA)
        cols = {r[1] for r in con.execute("PRAGMA table_info(manuscript_references)")}
        self.assertIn("disambiguated_key", cols)

    def test_index_present(self):
        con = sqlite3.connect(":memory:")
        con.executescript(SCHEMA)
        idx = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )}
        self.assertIn("idx_msrefs_disamb", idx)


if __name__ == "__main__":
    sys.exit(run_tests(
        DisambiguationUnitTests,
        IngestDisambiguationTests,
        AmbiguousCitationTests,
        AuditGateAmbiguousKindTests,
        DisambiguatedKeyColumnTests,
    ))

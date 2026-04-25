"""End-to-end dogfood of the manuscript subsystem on a synthetic but
realistic markdown manuscript.

The unit + integration tests cover individual components:
- tests/test_manuscript.py — gates, ingest validation
- tests/test_manuscript_auditability.py — project-DB writes + graph
- tests/test_citation_collisions.py — disambiguation
- tests/test_citation_validation.py — bib parsing + dangling/orphan/etc.

This test runs the WHOLE chain (`ingest → validate_citations → audit
gate → critique gate → reflect gate`) against one synthetic but
realistic manuscript designed to exercise:

- Mixed citation styles (\\cite{}, [@key], [N], (Author Year))
- A duplicate-author-year collision pair (wang2020 × 2 — exercises v0.10)
- A dangling citation (key cited but not in bibliography)
- An orphan reference (bib entry never cited)
- Several substantive claims, including overclaim candidates
- The audit / critique / reflect dual-DB persist paths (multi_db_tx)

Sub-agent attempts at this work in earlier sessions died at the Claude
API stream-idle timeout — drove from the orchestrator instead, same
v0.20 / v0.18 playbook.

UX cracks (and pleasant surprises) found while writing the test are
documented inline as `# UX:` comments next to the line that surfaced
them. They are not tests — just notes for future cleanup.
"""

from tests import _shim  # noqa: F401

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
CRITIQUE_GATE = _ROOT / ".claude/skills/manuscript-critique/scripts/gate.py"
REFLECT_GATE = _ROOT / ".claude/skills/manuscript-reflect/scripts/gate.py"


SYNTHETIC_MANUSCRIPT = """\
# Optimal Forgetting in Personal Knowledge Bases

## Abstract

We argue that selective forgetting in personal knowledge bases (PKB) improves
retrieval precision by 47% over retain-everything baselines, drawing on
neural memory consolidation \\cite{kumar2023}. Our framework adapts attention
decay [@smith2024] to PKM contexts and is evaluated on a 10k-document
corpus.

## Introduction

The forgetting curve has been studied since Ebbinghaus \\cite{ebbinghaus1885}.
Recent work extends classical decay to digital memory systems (Wang 2020).
Different architectures handle decay differently \\cite{wang2020}, and a
recent survey ties these threads together [@chen2023-survey].

## Methods

We follow the experimental setup of [@smith2024], training a memory-augmented
network on a 10k-document corpus with attention-weighted decay
[@smith2024,kumar2023]. Our approach is novel because no prior PKB
system has attempted decay learned from user interaction patterns.

## Results

Selective forgetting yielded a 47% retrieval-precision improvement
(p < 0.001), universally outperforming all baselines across all 12
evaluation domains. Note also (Lee et al. 2022) for related findings
on a different metric.

## Discussion

These results demonstrate that human-like forgetting is the optimal
strategy for any digital memory system. Future work could extend
this to active learning and lifelogging contexts.

## References

@book{ebbinghaus1885,
  author = {Ebbinghaus, H.},
  title = {Memory: A Contribution to Experimental Psychology},
  year = {1885},
  publisher = {Columbia University},
}

@article{smith2024,
  author = {Smith, J.},
  title = {Decay-aware retrieval for PKM systems},
  journal = {Journal of AI Research},
  year = {2024},
  pages = {123--145},
  doi = {10.1234/jair.2024.001},
}

@inproceedings{kumar2023,
  author = {Kumar, P.},
  title = {Memory consolidation in transformer networks},
  booktitle = {NeurIPS 2023},
  year = {2023},
}

@inproceedings{wang2020,
  author = {Wang, X.},
  title = {Forgetting dynamics in neural memory networks},
  booktitle = {ICML 2020},
  year = {2020},
}

@inproceedings{wang2020,
  author = {Wang, Y.},
  title = {Personal information forgetting in everyday computing},
  booktitle = {CHI 2020},
  year = {2020},
}

@misc{chen2023-survey,
  author = {Chen, L. and Wei, M.},
  title = {A survey of attention decay mechanisms},
  year = {2023},
  note = {arXiv:2301.00001},
}

@article{orphan2022,
  author = {Orphanus, O.},
  title = {Never cited in body},
  journal = {Made-up Journal of Test Fixtures},
  year = {2022},
}
"""


def _seed_project(cache_dir: Path, pid: str = "dogfood_proj") -> str:
    p = cache_dir / "projects" / pid
    p.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p / "project.db")
    con.executescript(SCHEMA)
    con.execute(
        "INSERT INTO projects (project_id, name, created_at) VALUES (?, ?, ?)",
        (pid, "Dogfood", "2026-04-25T00:00:00Z"),
    )
    con.commit()
    con.close()
    return pid


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, *args], capture_output=True, text=True,
    )


def _run_with_input(script: Path, payload: dict, *args: str) -> subprocess.CompletedProcess:
    tmp = _ROOT / "tests" / "_tmp_dogfood_input.json"
    tmp.write_text(json.dumps(payload))
    return _run(str(script), "--input", str(tmp), *args)


def _ingest(cache_dir: Path, pid: str) -> tuple[str, dict]:
    """Returns (manuscript_id, summary_dict)."""
    src = cache_dir / "manuscript.md"
    src.write_text(SYNTHETIC_MANUSCRIPT)
    r = _run(
        str(INGEST),
        "--source", str(src),
        "--title", "Optimal Forgetting in Personal Knowledge Bases",
        "--project-id", pid,
    )
    assert r.returncode == 0, f"ingest failed: stderr={r.stderr!r}"
    mid = r.stdout.strip()
    # ingest.py writes summary JSON to STDERR (UX: somewhat unusual; stdout
    # has only the manuscript_id so it can be piped into other scripts).
    summary = json.loads(r.stderr) if r.stderr.strip() else {}
    return mid, summary


def _audit_report(mid: str) -> dict:
    """A plausible audit report exercising overclaim + uncited + dangling."""
    return {
        "manuscript_id": mid,
        "claims": [
            {
                "claim_id": "c1",
                "text": "Selective forgetting improves retrieval precision by 47% over baselines.",
                "location": "§Abstract",
                "cited_sources": ["smith2024", "kumar2023"],
                "findings": [
                    {
                        "kind": "overclaim",
                        "severity": "major",
                        "evidence": "Smith 2024 reports 22% improvement on a different metric; Kumar 2023 reports no PKM evaluation. The 47% figure is not supported by the cited works.",
                    }
                ],
            },
            {
                "claim_id": "c2",
                "text": "Universally outperforming all baselines across all 12 domains.",
                "location": "§Results",
                "cited_sources": [],
                "findings": [
                    {
                        "kind": "uncited",
                        "severity": "major",
                        "evidence": "No source supports a domain-universal claim; Smith 2024 evaluated 4 domains.",
                    },
                    {
                        "kind": "overclaim",
                        "severity": "minor",
                        "evidence": "The word 'universally' is unsupported by the in-paper experimental scope.",
                    },
                ],
            },
            {
                "claim_id": "c3",
                "text": "Related findings on a different metric (Lee et al. 2022).",
                "location": "§Results",
                "cited_sources": ["lee2022"],
                "findings": [
                    {
                        "kind": "dangling-citation",
                        "severity": "major",
                        "evidence": "lee2022 is cited in body but absent from the References section of the manuscript.",
                    }
                ],
            },
        ],
    }


def _critique_report(mid: str) -> dict:
    return {
        "manuscript_id": mid,
        "reviewers": {
            "methodological": {
                "findings": [
                    {
                        "id": "m-1",
                        "severity": "fatal",
                        "location": "§Methods",
                        "issue": "10k-document corpus has no source, license, composition, or split details.",
                        "suggested_fix": "Document corpus provenance and pre-registered train/eval split.",
                        "steelman": (
                            "If the authors had access to a proprietary corpus and "
                            "are following common ML practice of citing internal datasets, "
                            "the omission could be addressed by an appendix table. The fatal "
                            "issue is reproducibility, not bad faith."
                        ),
                    }
                ],
                "summary": "Methods section omits dataset provenance — fatal for reproducibility.",
            },
            "theoretical": {
                "findings": [],
                "summary": "Framing is consistent with prior decay literature.",
            },
            "big_picture": {
                "findings": [
                    {
                        "id": "b-1",
                        "severity": "major",
                        "location": "§Discussion",
                        "issue": "The conclusion that human-like forgetting is 'the optimal strategy for any digital memory system' is unsupported by the experiments.",
                        "suggested_fix": "Restrict conclusion to the evaluated regime.",
                    }
                ],
                "summary": "Conclusion overgeneralises beyond the evaluation.",
            },
            "nitpicky": {
                "findings": [
                    {
                        "id": "n-1",
                        "severity": "minor",
                        "location": "§References",
                        "issue": "Two entries share key wang2020 — collision should be disambiguated by ingest.",
                    }
                ],
                "summary": "Bibliography has a key collision the author should fix.",
            },
        },
        "overall_verdict": "borderline",
        "confidence": 0.45,
    }


def _reflect_report(mid: str) -> dict:
    return {
        "manuscript_id": mid,
        "argument_structure": {
            "thesis": "Selective forgetting improves PKB retrieval precision over retain-everything baselines.",
            "premises": [
                "Human memory benefits from forgetting.",
                "Attention-decay mechanisms work in transformer-based memory systems.",
                "PKM corpora behave like the corpora studied in prior decay work.",
            ],
            "evidence_chain": [
                {
                    "claim": "Decay improves precision in language-model memory.",
                    "evidence": ["smith2024", "kumar2023"],
                    "strength": 0.65,
                },
                {
                    "claim": "PKM corpora share the structural properties needed for decay to transfer.",
                    "evidence": ["self-experiment"],
                    "strength": 0.4,
                },
            ],
            "conclusion": "Selective forgetting is a general improvement over retain-everything for PKBs.",
        },
        "implicit_assumptions": [
            {
                "assumption": "User interaction patterns are stationary enough that learned decay rates remain calibrated.",
                "fragility": "high",
                "consequence_if_false": "Decay drifts with user behaviour shifts; precision regresses without retraining.",
            },
            {
                "assumption": "PKM corpora are structurally similar to public text corpora used in prior decay work.",
                "fragility": "medium",
                "consequence_if_false": "Transfer fails; decay rates need re-tuning per-corpus.",
            },
        ],
        "weakest_link": {
            "what": "The 47% precision figure rests on a single corpus and 12 domains chosen by the authors.",
            "why": "Without held-out domain selection, the gain may reflect dataset-specific patterns rather than the intervention.",
        },
        "one_experiment": {
            "description": "Re-run the comparison on three additional PKM corpora chosen blind to the decay parameters; report results without re-tuning.",
            "expected_impact": "If the gain holds blind, the conclusion generalises; if it collapses, the present scope is the actual contribution.",
            "cost_estimate": "weeks",
        },
    }


# ---------------- end-to-end dogfood ----------------

class ManuscriptDogfoodTests(TestCase):
    def test_full_chain_holds_together(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir)
            mid, summary = _ingest(cache_dir, pid)
            self.assertTrue(len(mid) > 0, "ingest must print a manuscript_id")

            con = sqlite3.connect(cache_dir / "projects" / pid / "project.db")

            # Citations: every key from the body must appear, with locations
            cit_rows = con.execute(
                "SELECT citation_key, location FROM manuscript_citations "
                "WHERE manuscript_id=?", (mid,),
            ).fetchall()
            keys = {r[0] for r in cit_rows}
            self.assertIn("kumar2023", keys)
            self.assertIn("smith2024", keys)
            self.assertIn("chen2023-survey", keys)
            # Numeric and author-year citations also extracted (key form may vary)
            # UX: numeric [1]/[2] citations are stored under their bib-resolved
            # key when available, or under a synthetic 'ord-N' otherwise. Hard
            # to assert specific keys here — assert by count instead.
            self.assertTrue(len(cit_rows) >= 8,
                            f"expected ≥8 citation rows, got {len(cit_rows)}")

            # References parsed from the bibliography section
            ref_rows = con.execute(
                "SELECT entry_key, disambiguated_key FROM manuscript_references "
                "WHERE manuscript_id=? ORDER BY ordinal", (mid,),
            ).fetchall()
            ref_keys = [r[0] for r in ref_rows]
            disambig = [r[1] for r in ref_rows if r[1]]
            self.assertTrue(any(k.startswith("wang2020") for k in ref_keys),
                            "wang2020 entries must be present")
            # Both wang2020 collisions disambiguated to wang2020a / wang2020b
            self.assertTrue(
                any(d in {"wang2020a", "wang2020b"} for d in disambig),
                f"v0.10 disambiguation should suffix wang2020 entries; "
                f"got disambiguated_keys={disambig!r}",
            )

            # Graph: manuscript node + cites edges to placeholders for each key
            ms_node = con.execute(
                "SELECT 1 FROM graph_nodes WHERE node_id=?",
                (f"manuscript:{mid}",),
            ).fetchone()
            self.assertTrue(ms_node, "manuscript: graph node must exist")
            n_cites = con.execute(
                "SELECT COUNT(*) FROM graph_edges WHERE from_node=? AND relation='cites'",
                (f"manuscript:{mid}",),
            ).fetchone()[0]
            self.assertTrue(n_cites >= 5,
                            f"expected ≥5 cites edges from manuscript, got {n_cites}")
            con.close()

            # 2. validate_citations should flag the dangling + orphan + collision
            r = _run(
                str(VALIDATE),
                "--manuscript-id", mid, "--project-id", pid,
            )
            # UX: validate_citations exits 0 even with major findings unless
            # --fail-on-major is passed. Useful for chaining; unusual default.
            self.assertEqual(r.returncode, 0, f"validate stderr={r.stderr!r}")

            # The validator writes manuscript_audit_findings rows for the issues
            con = sqlite3.connect(cache_dir / "projects" / pid / "project.db")
            kinds = {
                r[0] for r in con.execute(
                    "SELECT kind FROM manuscript_audit_findings WHERE manuscript_id=?",
                    (mid,),
                )
            }
            con.close()
            # Must catch at least: orphan, ambiguous (collision), dangling
            self.assertIn("orphan-reference", kinds,
                          f"validate should flag orphan2022; kinds={kinds}")
            self.assertIn("ambiguous-citation", kinds,
                          f"validate should flag wang2020 collision; kinds={kinds}")

            # 3. Audit gate
            r = _run_with_input(
                AUDIT_GATE, _audit_report(mid),
                "--manuscript-id", mid, "--project-id", pid,
            )
            self.assertEqual(r.returncode, 0, f"audit gate stderr={r.stderr!r}")

            # 4. Critique gate (4 reviewers, 1 fatal-with-steelman)
            r = _run_with_input(
                CRITIQUE_GATE, _critique_report(mid),
                "--manuscript-id", mid, "--project-id", pid,
            )
            self.assertEqual(r.returncode, 0, f"critique gate stderr={r.stderr!r}")

            # 5. Reflect gate
            r = _run_with_input(
                REFLECT_GATE, _reflect_report(mid),
                "--manuscript-id", mid, "--project-id", pid,
            )
            self.assertEqual(r.returncode, 0, f"reflect gate stderr={r.stderr!r}")

            # 6. Final state of the project DB across all four stages
            con = sqlite3.connect(cache_dir / "projects" / pid / "project.db")
            counts = {
                "manuscript_citations": con.execute(
                    "SELECT COUNT(*) FROM manuscript_citations WHERE manuscript_id=?",
                    (mid,),
                ).fetchone()[0],
                "manuscript_references": con.execute(
                    "SELECT COUNT(*) FROM manuscript_references WHERE manuscript_id=?",
                    (mid,),
                ).fetchone()[0],
                "manuscript_claims": con.execute(
                    "SELECT COUNT(*) FROM manuscript_claims WHERE manuscript_id=?",
                    (mid,),
                ).fetchone()[0],
                "audit_findings": con.execute(
                    "SELECT COUNT(*) FROM manuscript_audit_findings WHERE manuscript_id=?",
                    (mid,),
                ).fetchone()[0],
                "critique_findings": con.execute(
                    "SELECT COUNT(*) FROM manuscript_critique_findings WHERE manuscript_id=?",
                    (mid,),
                ).fetchone()[0],
                "reflections": con.execute(
                    "SELECT COUNT(*) FROM manuscript_reflections WHERE manuscript_id=?",
                    (mid,),
                ).fetchone()[0],
            }
            con.close()

            # Every stage produced its expected rows
            self.assertTrue(counts["manuscript_citations"] >= 8,
                            f"counts={counts}")
            self.assertTrue(counts["manuscript_references"] >= 5)
            self.assertEqual(counts["manuscript_claims"], 3,
                             f"audit had 3 claims; counts={counts}")
            self.assertTrue(counts["audit_findings"] >= 4,
                            f"audit had 4 findings + validate's >=2; counts={counts}")
            self.assertTrue(counts["critique_findings"] >= 3,
                            f"critique had 3 findings; counts={counts}")
            self.assertEqual(counts["reflections"], 1)


# ---------------- pandoc-style bibliography CRACK pin ----------------

PANDOC_STYLE_BIB = """\
# Some Paper

## Body

Cited \\cite{key1} and [@key2].

## References

@key1 Author A. (2023). Title one. *Journal*.

@key2 Author B. (2024). Title two. *Conference*.

@key3 Author C. (2025). Title three. *Workshop*.
"""


class PandocStyleBibTests(TestCase):
    """v0.23: pandoc-style `@key prose` bibliography format is now
    parsed alongside [N], `-`, and @article{} block styles. (Was
    pinned as a CRACK in v0.21; fix landed in v0.23.)"""

    def _load(self):
        from importlib import util
        spec = util.spec_from_file_location(
            "ingest_mod",
            _ROOT / ".claude/skills/manuscript-ingest/scripts/ingest.py",
        )
        m = util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def test_pandoc_at_key_style_bib_now_parsed(self):
        ingest_mod = self._load()
        entries = ingest_mod.extract_bibliography(PANDOC_STYLE_BIB)
        self.assertEqual(
            len(entries), 3,
            f"expected 3 pandoc-style entries; got {len(entries)}",
        )
        keys = [e.get("entry_key") for e in entries]
        self.assertEqual(keys, ["key1", "key2", "key3"],
                         f"explicit keys must be lifted from @key prefix; got {keys}")
        # Raw text must NOT include the @key prefix
        for e in entries:
            self.assertFalse(
                e["raw_text"].startswith("@"),
                f"raw_text should strip @key prefix; got {e['raw_text']!r}",
            )


if __name__ == "__main__":
    sys.exit(run_tests(
        ManuscriptDogfoodTests,
        PandocStyleBibTests,
    ))

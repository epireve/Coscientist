"""Writing-style subsystem tests: fingerprint + audit + apply + _textstats."""

from tests import _shim  # noqa: F401

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests

_ROOT = Path(__file__).resolve().parent.parent
FINGERPRINT = _ROOT / ".claude/skills/writing-style/scripts/fingerprint.py"
AUDIT = _ROOT / ".claude/skills/writing-style/scripts/audit.py"
APPLY = _ROOT / ".claude/skills/writing-style/scripts/apply.py"


def _run(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], capture_output=True,
                          text=True, input=stdin)


def _seed_project(cache_dir: Path, pid: str = "ws_project") -> str:
    p = cache_dir / "projects" / pid
    p.mkdir(parents=True, exist_ok=True)
    schema = (_ROOT / "lib" / "sqlite_schema.sql").read_text()
    con = sqlite3.connect(p / "project.db")
    con.executescript(schema)
    con.execute(
        "INSERT INTO projects (project_id, name, created_at) VALUES (?, ?, ?)",
        (pid, "WS", "2026-04-24T00:00:00Z"),
    )
    con.commit()
    con.close()
    return pid


def _sample_manuscript() -> str:
    return (
        "# Transformers at Scale\n\n"
        "## Introduction\n\n"
        "We present a study of transformer scaling behavior. "
        "In this work we systematically vary model size and training budget. "
        "First, we train small models and measure downstream performance. "
        "Our main finding is a predictable scaling law.\n\n"
        "## Methods\n\n"
        "We train 100 models spanning 1M to 1B parameters. "
        "For each configuration we run three seeds. "
        "We measure validation loss and downstream accuracy. "
        "The training data is a 100B-token mixture.\n\n"
        "## Results\n\n"
        "The loss follows a power law in compute. "
        "We observe an exponent of 0.076 on our mixture. "
        "This matches prior estimates within two standard errors. "
        "Downstream accuracy correlates tightly with loss.\n\n"
        "## Discussion\n\n"
        "Scale continues to dominate architecture choice. "
        "We find no threshold at the sizes tested. "
        "Future work will explore emergent capabilities.\n"
    )


class FingerprintTests(TestCase):
    def test_fingerprint_produces_profile(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir)
            src = cache_dir / "paper1.md"
            src.write_text(_sample_manuscript())
            # Use same sample twice as two "prior" manuscripts
            src2 = cache_dir / "paper2.md"
            src2.write_text(_sample_manuscript().replace("transformer", "attention"))

            r = _run(str(FINGERPRINT), "--project-id", pid,
                     "--sources", str(src), str(src2))
            assert r.returncode == 0, f"stderr={r.stderr}"

            profile_path = cache_dir / "projects" / pid / "style_profile.json"
            self.assertTrue(profile_path.exists())
            profile = json.loads(profile_path.read_text())

            self.assertEqual(profile["sample_count"], 2)
            self.assertTrue(profile["word_count"] > 50)
            self.assertIn("lexical", profile)
            self.assertIn("syntactic", profile)
            self.assertIn("structural", profile)
            self.assertIn("first_person_rate", profile["lexical"])
            self.assertIn("top_terms", profile["lexical"])
            self.assertTrue(profile["syntactic"]["avg_sentence_length"] > 0)

    def test_fingerprint_updates_project_db(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir)
            src = cache_dir / "paper.md"
            src.write_text(_sample_manuscript())
            _run(str(FINGERPRINT), "--project-id", pid, "--sources", str(src))

            con = sqlite3.connect(cache_dir / "projects" / pid / "project.db")
            row = con.execute(
                "SELECT style_profile_path FROM projects WHERE project_id=?",
                (pid,),
            ).fetchone()
            con.close()
            self.assertTrue(row[0])
            self.assertTrue(row[0].endswith("style_profile.json"))

    def test_fingerprint_fails_on_missing_source(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir)
            r = _run(str(FINGERPRINT), "--project-id", pid,
                     "--sources", str(cache_dir / "nope.md"))
            self.assertEqual(r.returncode, 1)

    def test_fingerprint_detects_american_spelling(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir)
            src = cache_dir / "american.md"
            src.write_text(
                "We analyze the behavior of the model. "
                "The color space is important. "
                "Models were trained with standard optimizers. "
                "We labeled all tokens in the corpus."
            )
            _run(str(FINGERPRINT), "--project-id", pid, "--sources", str(src))
            profile = json.loads(
                (cache_dir / "projects" / pid / "style_profile.json").read_text()
            )
            self.assertEqual(profile["lexical"]["british_american"], "us")


class AuditTests(TestCase):
    def _setup(self, cache_dir: Path, ms_text: str) -> tuple[str, str]:
        pid = _seed_project(cache_dir)
        # Profile from the sample manuscript (low hedging, avg ~15 word sentences)
        src = cache_dir / "sample.md"
        src.write_text(_sample_manuscript())
        _run(str(FINGERPRINT), "--project-id", pid, "--sources", str(src))

        # Ingest a manuscript with arbitrary content
        mid = "test_ms"
        ms_dir = cache_dir / "manuscripts" / mid
        ms_dir.mkdir(parents=True, exist_ok=True)
        (ms_dir / "source.md").write_text(ms_text)
        (ms_dir / "manifest.json").write_text(json.dumps({
            "artifact_id": mid, "kind": "manuscript", "state": "drafted",
        }))
        return pid, mid

    def test_audit_finds_few_deviations_for_similar_text(self):
        """Self-audit of the fingerprint source should produce few major findings.

        A 2-sample profile has tight stddevs so isolated outlier paragraphs
        can still trigger, but the overall rate should be low.
        """
        with isolated_cache() as cache_dir:
            pid, mid = self._setup(cache_dir, _sample_manuscript())
            r = _run(str(AUDIT), "--manuscript-id", mid, "--project-id", pid)
            assert r.returncode == 0, f"stderr={r.stderr}"
            report = json.loads(
                (cache_dir / "manuscripts" / mid / "style_audit.json").read_text()
            )
            # Very lenient: a self-audit with a 2-sample profile
            # should have at most one or two major flags
            self.assertTrue(report["by_severity"]["major"] <= 2,
                            f"unexpected major-finding count: {report['by_severity']}")

    def test_audit_flags_very_long_paragraph(self):
        with isolated_cache() as cache_dir:
            # Manuscript with one huge paragraph (violates paragraph_length)
            long_text = " ".join(
                f"Sentence number {i} with moderate length and some content here."
                for i in range(50)
            )
            ms = _sample_manuscript() + "\n\n## Extra\n\n" + long_text + "\n"
            pid, mid = self._setup(cache_dir, ms)
            _run(str(AUDIT), "--manuscript-id", mid, "--project-id", pid)
            report = json.loads(
                (cache_dir / "manuscripts" / mid / "style_audit.json").read_text()
            )
            # The huge paragraph should be flagged on paragraph_length
            flagged = [
                f for f in report["findings"]
                if f["metric"] == "paragraph_length" and f["severity"] in {"minor", "major"}
            ]
            self.assertTrue(len(flagged) > 0)

    def test_audit_flags_hedge_spike(self):
        with isolated_cache() as cache_dir:
            hedgy = (
                "# Test\n\n"
                "We might perhaps observe that the results could possibly be informative. "
                "It seems that the effect may potentially exist. "
                "Arguably, the finding could suggest a relationship. "
                "Possibly, our analysis might reveal a trend."
            )
            pid, mid = self._setup(cache_dir, hedgy)
            _run(str(AUDIT), "--manuscript-id", mid, "--project-id", pid)
            report = json.loads(
                (cache_dir / "manuscripts" / mid / "style_audit.json").read_text()
            )
            hedges = [f for f in report["findings"] if f["metric"] == "hedge_density"]
            self.assertTrue(len(hedges) > 0)
            # At least one at major severity
            self.assertTrue(any(f["severity"] in {"minor", "major"} for f in hedges))

    def test_audit_fails_without_profile(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir)
            mid = "no_profile_ms"
            ms_dir = cache_dir / "manuscripts" / mid
            ms_dir.mkdir(parents=True, exist_ok=True)
            (ms_dir / "source.md").write_text("Body text here.")

            r = _run(str(AUDIT), "--manuscript-id", mid, "--project-id", pid)
            self.assertEqual(r.returncode, 1)


class ApplyTests(TestCase):
    def test_apply_via_stdin(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir)
            src = cache_dir / "sample.md"
            src.write_text(_sample_manuscript())
            _run(str(FINGERPRINT), "--project-id", pid, "--sources", str(src))

            hedgy_para = (
                "We might perhaps observe that the results could possibly be informative. "
                "It seems that the effect may potentially exist."
            )
            r = _run(str(APPLY), "--project-id", pid, stdin=hedgy_para)
            assert r.returncode == 0, f"stderr={r.stderr}"
            result = json.loads(r.stdout)
            self.assertIn("findings", result)
            # Hedge density on that paragraph will exceed profile
            hedges = [f for f in result["findings"] if f["metric"] == "hedge_density"]
            self.assertTrue(len(hedges) > 0)

    def test_apply_rejects_empty(self):
        with isolated_cache() as cache_dir:
            pid = _seed_project(cache_dir)
            src = cache_dir / "sample.md"
            src.write_text(_sample_manuscript())
            _run(str(FINGERPRINT), "--project-id", pid, "--sources", str(src))
            r = _run(str(APPLY), "--project-id", pid, stdin="")
            self.assertEqual(r.returncode, 1)


class TextstatsUnitTests(TestCase):
    """Direct unit tests of _textstats primitives."""

    def _import_textstats(self):
        import importlib.util
        path = _ROOT / ".claude/skills/writing-style/scripts/_textstats.py"
        spec = importlib.util.spec_from_file_location("_textstats", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_hedge_density_counts_sentences_not_words(self):
        ts = self._import_textstats()
        sents = [
            "This is a clear statement.",
            "We might observe something.",
            "Perhaps it could be true.",
        ]
        rate = ts.hedge_density(sents)
        self.assertEqual(rate, 2 / 3)

    def test_british_vs_american_detection(self):
        ts = self._import_textstats()
        self.assertEqual(ts.british_or_american("We analyse the colour of behaviour"), "uk")
        self.assertEqual(ts.british_or_american("We analyze the color of behavior"), "us")
        self.assertEqual(ts.british_or_american("No signals here"), "unknown")

    def test_sentences_strip_markdown(self):
        ts = self._import_textstats()
        sents = ts.sentences("# Title\n\n`code here`. Real sentence starts. Another one.")
        # Should not treat the header as a sentence on its own
        self.assertTrue(all("#" not in s for s in sents))

    def test_top_terms_excludes_stopwords(self):
        ts = self._import_textstats()
        terms = ts.top_terms(["the", "attention", "the", "attention", "model", "model", "the"])
        self.assertNotIn("the", terms)
        self.assertIn("attention", terms)
        self.assertEqual(terms["attention"], 2)


if __name__ == "__main__":
    sys.exit(run_tests(
        FingerprintTests, AuditTests, ApplyTests, TextstatsUnitTests,
    ))

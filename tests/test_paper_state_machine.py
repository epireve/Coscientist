"""Dry-run harness for the per-paper state machine.

Mirrors `test_deep_research_pipeline.py`'s coverage of the run-pipeline
state machine, but for the per-paper lifecycle:

    discovered → triaged → acquired → extracted → read → cited

We drive `paper-triage/scripts/record.py`, `paper-acquire/scripts/record.py`,
and `paper-acquire/scripts/gate.py` via subprocess and assert what they
do to the manifest, the audit log, and (where applicable) refuse to do.

Coverage:
- discovered: a fresh PaperArtifact has state=discovered with no triage
- triaged: paper-triage with --sufficient=false advances state and sets
  triage.sufficient=false (the only path that paper-acquire is allowed
  to consume)
- triaged: paper-triage with --sufficient=true on a paper with NO
  abstract/tldr/claims errors out — guardrail in record_one
- triaged: paper-triage with --sufficient=true on a paper WITH metadata
  advances state and records sufficient=true
- gate.py: refuses an untriaged paper (exit 2)
- gate.py: refuses a sufficient=true paper (exit 3)
- gate.py: passes a sufficient=false paper (exit 0)
- acquire: tiny file (<200 bytes) rejected (v0.12.1 integrity check)
- acquire: HTML payload of sufficient size rejected by magic-bytes
- acquire: real %PDF prefix ≥200 bytes succeeds, advances state to
  acquired, appends to audit.log with all expected fields
- audit log: --failed appends a JSON line with action=failed and does
  NOT advance state
- monotonicity: documents what happens on triage of an already-acquired
  paper (currently overwrites state — captured, not asserted "correct")
- argparse edge cases: missing --canonical-id without --batch errors
"""

from tests import _shim  # noqa: F401

import json
import os
import subprocess
import sys
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests

_ROOT = Path(__file__).resolve().parent.parent
TRIAGE = _ROOT / ".claude/skills/paper-triage/scripts/record.py"
ACQUIRE = _ROOT / ".claude/skills/paper-acquire/scripts/record.py"
GATE = _ROOT / ".claude/skills/paper-acquire/scripts/gate.py"


# ---------------- subprocess helpers ----------------

def _run(script: Path, *args: str) -> subprocess.CompletedProcess:
    """Run a CLI script as a subprocess; pass through COSCIENTIST_CACHE_DIR."""
    env = os.environ.copy()
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True, text=True, env=env,
    )


def _seed_paper(cid: str, *, with_metadata: bool = False) -> None:
    """Create a paper artifact stub. Optionally seed metadata so triage
    can mark sufficient=true."""
    from lib.paper_artifact import Metadata, PaperArtifact

    art = PaperArtifact(cid)
    art.save_manifest(art.load_manifest())  # initialize manifest.json
    if with_metadata:
        art.save_metadata(Metadata(
            title="Stub Paper",
            authors=["Anon"],
            year=2025,
            abstract="A non-empty abstract so triage will accept sufficient=true.",
        ))


def _load_manifest(cid: str):
    from lib.paper_artifact import PaperArtifact
    return PaperArtifact(cid).load_manifest()


def _audit_lines(cache_dir: Path) -> list[dict]:
    log = cache_dir / "audit.log"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines() if line.strip()]


def _write_pdf(path: Path, *, size: int = 4096) -> Path:
    """Write a minimally-valid %PDF-prefixed file of `size` bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    head = b"%PDF-1.4\n"
    body = b"x" * (size - len(head))
    path.write_bytes(head + body)
    return path


def _write_html(path: Path, *, size: int = 4096) -> Path:
    """Write an HTML payload (paywall-redirect style) of `size` bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    head = b"<!DOCTYPE html><html><body>Sign in to download</body></html>\n"
    body = b" " * max(0, size - len(head))
    path.write_bytes(head + body)
    return path


# ---------------- discovered → triaged ----------------

class DiscoveredStateTests(TestCase):
    def test_fresh_artifact_is_discovered(self):
        with isolated_cache():
            from lib.paper_artifact import State
            cid = "anon_2025_fresh_aaaaaa"
            _seed_paper(cid)
            m = _load_manifest(cid)
            self.assertEqual(m.state, State.discovered)
            self.assertTrue(m.triage is None,
                            "fresh manifest must have triage=None")

    def test_triage_sufficient_false_advances_state(self):
        with isolated_cache():
            from lib.paper_artifact import State
            cid = "anon_2025_tfalse_bbbbbb"
            _seed_paper(cid)

            r = _run(TRIAGE, "--canonical-id", cid,
                     "--sufficient", "false",
                     "--rationale", "need full text")
            self.assertEqual(r.returncode, 0, f"triage failed: {r.stderr}")

            m = _load_manifest(cid)
            self.assertEqual(m.state, State.triaged)
            self.assertEqual(m.triage["sufficient"], False)
            self.assertEqual(m.triage["rationale"], "need full text")
            self.assertIn("at", m.triage)

    def test_triage_sufficient_true_without_metadata_errors(self):
        """Existing guardrail: cannot mark sufficient=true with no
        abstract/tldr/claims to back the verdict."""
        with isolated_cache():
            from lib.paper_artifact import State
            cid = "anon_2025_ttrue_nometa_cccccc"
            _seed_paper(cid)  # NO metadata

            r = _run(TRIAGE, "--canonical-id", cid,
                     "--sufficient", "true",
                     "--rationale", "looks fine")
            self.assertTrue(r.returncode != 0,
                            "must refuse sufficient=true without metadata")
            self.assertIn("cannot mark sufficient=true", r.stderr)

            # State must NOT have advanced — still discovered
            m = _load_manifest(cid)
            self.assertEqual(m.state, State.discovered,
                             "failed triage must not mutate state")
            self.assertTrue(m.triage is None)

    def test_triage_sufficient_true_with_metadata_advances(self):
        with isolated_cache():
            from lib.paper_artifact import State
            cid = "anon_2025_ttrue_meta_dddddd"
            _seed_paper(cid, with_metadata=True)

            r = _run(TRIAGE, "--canonical-id", cid,
                     "--sufficient", "true",
                     "--rationale", "abstract is enough")
            self.assertEqual(r.returncode, 0, f"triage failed: {r.stderr}")

            m = _load_manifest(cid)
            self.assertEqual(m.state, State.triaged)
            self.assertEqual(m.triage["sufficient"], True)


# ---------------- paper-acquire gate enforcement ----------------

class AcquireGateTests(TestCase):
    def test_gate_refuses_untriaged(self):
        with isolated_cache():
            cid = "anon_2025_untriaged_eeeeee"
            _seed_paper(cid)
            r = _run(GATE, "--canonical-id", cid)
            self.assertEqual(r.returncode, 2,
                             f"untriaged must exit 2; got {r.returncode}")
            self.assertIn("no triage verdict", r.stderr)

    def test_gate_refuses_sufficient_true(self):
        with isolated_cache():
            cid = "anon_2025_suff_true_ffffff"
            _seed_paper(cid, with_metadata=True)
            r = _run(TRIAGE, "--canonical-id", cid,
                     "--sufficient", "true", "--rationale", "ok")
            self.assertEqual(r.returncode, 0, r.stderr)

            r = _run(GATE, "--canonical-id", cid)
            self.assertEqual(r.returncode, 3,
                             f"sufficient=true must exit 3; got {r.returncode}")
            self.assertIn("fetch forbidden", r.stderr)

    def test_gate_passes_sufficient_false(self):
        with isolated_cache():
            cid = "anon_2025_suff_false_111111"
            _seed_paper(cid)
            r = _run(TRIAGE, "--canonical-id", cid,
                     "--sufficient", "false", "--rationale", "need pdf")
            self.assertEqual(r.returncode, 0, r.stderr)

            r = _run(GATE, "--canonical-id", cid)
            self.assertEqual(r.returncode, 0,
                             f"sufficient=false must exit 0; got rc={r.returncode}"
                             f" stderr={r.stderr}")


# ---------------- paper-acquire integrity checks ----------------

class AcquireIntegrityTests(TestCase):
    def test_too_small_file_rejected(self):
        """v0.12.1 integrity check: <200 bytes is refused."""
        with isolated_cache() as cache_dir:
            from lib.paper_artifact import State
            cid = "anon_2025_tiny_222222"
            _seed_paper(cid)
            _run(TRIAGE, "--canonical-id", cid, "--sufficient", "false",
                 "--rationale", "fetch")

            tiny = cache_dir / "downloads" / "tiny.pdf"
            tiny.parent.mkdir(parents=True, exist_ok=True)
            tiny.write_bytes(b"%PDF-1.4\nshort")  # ~14 bytes

            r = _run(ACQUIRE, "--canonical-id", cid,
                     "--source", "oa-fallback",
                     "--pdf-path", str(tiny))
            self.assertTrue(r.returncode != 0,
                            "tiny file must be rejected")
            self.assertIn("too small", r.stderr)

            m = _load_manifest(cid)
            self.assertEqual(m.state, State.triaged,
                             "rejected acquire must not advance state")

    def test_html_payload_rejected_by_magic_bytes(self):
        """A 4KB HTML page (paywall redirect) must be refused — wrong
        magic bytes."""
        with isolated_cache() as cache_dir:
            from lib.paper_artifact import State
            cid = "anon_2025_html_333333"
            _seed_paper(cid)
            _run(TRIAGE, "--canonical-id", cid, "--sufficient", "false",
                 "--rationale", "fetch")

            html = _write_html(cache_dir / "downloads" / "paywall.pdf",
                               size=4096)

            r = _run(ACQUIRE, "--canonical-id", cid,
                     "--source", "oa-fallback",
                     "--pdf-path", str(html))
            self.assertTrue(r.returncode != 0)
            self.assertIn("not a PDF", r.stderr)

            m = _load_manifest(cid)
            self.assertEqual(m.state, State.triaged)

    def test_valid_pdf_succeeds_and_advances_state(self):
        with isolated_cache() as cache_dir:
            from lib.paper_artifact import State
            cid = "anon_2025_valid_444444"
            _seed_paper(cid)
            _run(TRIAGE, "--canonical-id", cid, "--sufficient", "false",
                 "--rationale", "fetch")

            pdf = _write_pdf(cache_dir / "downloads" / "real.pdf", size=4096)

            r = _run(ACQUIRE, "--canonical-id", cid,
                     "--source", "arxiv",
                     "--pdf-path", str(pdf))
            self.assertEqual(r.returncode, 0, f"acquire failed: {r.stderr}")

            m = _load_manifest(cid)
            self.assertEqual(m.state, State.acquired)
            # raw/<source>.pdf was written
            from lib.paper_artifact import PaperArtifact
            art = PaperArtifact(cid)
            self.assertTrue(art.has_raw_pdf(),
                            "raw/<source>.pdf should exist after acquire")
            primary = art.primary_pdf()
            self.assertTrue(primary is not None and primary.exists())

            # sources_tried recorded the success
            self.assertEqual(len(m.sources_tried), 1)
            self.assertEqual(m.sources_tried[0]["source"], "arxiv")
            self.assertEqual(m.sources_tried[0]["outcome"], "ok")


# ---------------- audit log ----------------

class AuditLogTests(TestCase):
    def test_successful_acquire_appends_audit_line(self):
        with isolated_cache() as cache_dir:
            cid = "anon_2025_audit_ok_555555"
            _seed_paper(cid)
            _run(TRIAGE, "--canonical-id", cid, "--sufficient", "false",
                 "--rationale", "fetch")

            pdf = _write_pdf(cache_dir / "downloads" / "ok.pdf", size=2048)
            r = _run(ACQUIRE, "--canonical-id", cid,
                     "--source", "oa-fallback",
                     "--pdf-path", str(pdf))
            self.assertEqual(r.returncode, 0, r.stderr)

            lines = _audit_lines(cache_dir)
            self.assertEqual(len(lines), 1, f"expected 1 audit line, got {lines!r}")
            entry = lines[0]
            for k in ("at", "canonical_id", "source", "action", "pdf", "bytes"):
                self.assertIn(k, entry, f"audit entry missing {k}: {entry!r}")
            self.assertEqual(entry["canonical_id"], cid)
            self.assertEqual(entry["source"], "oa-fallback")
            self.assertEqual(entry["action"], "fetched")
            self.assertEqual(entry["bytes"], 2048)

    def test_failed_acquire_appends_audit_line_and_keeps_state(self):
        """--failed must append a JSON line with action=failed and NOT
        advance state."""
        with isolated_cache() as cache_dir:
            from lib.paper_artifact import State
            cid = "anon_2025_audit_fail_666666"
            _seed_paper(cid)
            _run(TRIAGE, "--canonical-id", cid, "--sufficient", "false",
                 "--rationale", "fetch")

            r = _run(ACQUIRE, "--canonical-id", cid,
                     "--source", "institutional",
                     "--failed",
                     "--detail", "401 unauthorized")
            self.assertEqual(r.returncode, 0,
                             f"--failed must succeed (recording is the point); "
                             f"got rc={r.returncode} stderr={r.stderr}")

            lines = _audit_lines(cache_dir)
            self.assertEqual(len(lines), 1)
            entry = lines[0]
            self.assertEqual(entry["action"], "failed")
            self.assertEqual(entry["source"], "institutional")
            self.assertEqual(entry["detail"], "401 unauthorized")
            self.assertNotIn("pdf", entry,
                             "failed entries should not have a 'pdf' field")

            m = _load_manifest(cid)
            self.assertEqual(m.state, State.triaged,
                             "failed acquire must not advance state")
            self.assertEqual(len(m.sources_tried), 1)
            self.assertEqual(m.sources_tried[0]["outcome"], "failed")

    def test_rejected_pdf_still_writes_no_audit_line(self):
        """When integrity check fails, record.py raises SystemExit BEFORE
        appending to the audit log. Documents this — if it ever changes
        we want to know."""
        with isolated_cache() as cache_dir:
            cid = "anon_2025_rejected_777777"
            _seed_paper(cid)
            _run(TRIAGE, "--canonical-id", cid, "--sufficient", "false",
                 "--rationale", "fetch")

            tiny = cache_dir / "downloads" / "tiny.pdf"
            tiny.parent.mkdir(parents=True, exist_ok=True)
            tiny.write_bytes(b"%PDF-1.4\nx")

            r = _run(ACQUIRE, "--canonical-id", cid,
                     "--source", "oa-fallback",
                     "--pdf-path", str(tiny))
            self.assertTrue(r.returncode != 0)

            # CRACK (documented, not fixed): integrity rejection currently
            # writes nothing to the audit log — no record of the
            # publisher having served us junk. The audit log is meant to
            # be append-only for ALL fetch attempts; rejected payloads
            # are still attempts. If you decide failed integrity should
            # produce a `action=rejected` line, this assertion will fail
            # and you'll need to flip it.
            lines = _audit_lines(cache_dir)
            self.assertEqual(
                len(lines), 0,
                "current behavior: integrity-rejected fetch leaves no audit trail",
            )


# ---------------- state monotonicity (current behavior) ----------------

class StateMonotonicityTests(TestCase):
    def test_triage_after_acquire_overwrites_state_back_to_triaged(self):
        """Document current behavior: re-running triage on an already
        acquired paper rolls state BACK to triaged. record_one writes
        manifest.state = State.triaged unconditionally — no monotonicity
        check.

        # CRACK (documented, not fixed): paper-triage record_one has no
        # check that the current state is `discovered` or earlier. A
        # second triage call after acquire (e.g. an orchestrator bug that
        # re-loops over the shortlist) silently demotes the paper. The
        # manifest.triage block is also overwritten. If this is intended
        # as idempotency, it's surprising; if not, record_one should
        # refuse when state is acquired/extracted/read/cited.
        """
        with isolated_cache() as cache_dir:
            from lib.paper_artifact import State
            cid = "anon_2025_remix_888888"
            _seed_paper(cid)
            _run(TRIAGE, "--canonical-id", cid, "--sufficient", "false",
                 "--rationale", "first")

            pdf = _write_pdf(cache_dir / "downloads" / "x.pdf", size=1024)
            r = _run(ACQUIRE, "--canonical-id", cid,
                     "--source", "arxiv", "--pdf-path", str(pdf))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(_load_manifest(cid).state, State.acquired)

            # Re-triage this acquired paper — currently allowed
            r = _run(TRIAGE, "--canonical-id", cid, "--sufficient", "false",
                     "--rationale", "second")
            self.assertEqual(r.returncode, 0,
                             f"current behavior: re-triage allowed; got {r.stderr}")

            m = _load_manifest(cid)
            self.assertEqual(m.state, State.triaged,
                             "current behavior: re-triage demoted state")
            self.assertEqual(m.triage["rationale"], "second",
                             "current behavior: triage block overwritten")


# ---------------- argparse edge cases ----------------

class CliEdgeCaseTests(TestCase):
    def test_triage_without_canonical_id_or_batch_errors(self):
        with isolated_cache():
            r = _run(TRIAGE, "--sufficient", "false")
            self.assertTrue(r.returncode != 0)
            # Either argparse-level error or the explicit SystemExit message
            combined = (r.stderr + r.stdout).lower()
            self.assertTrue(
                "--canonical-id" in combined or "--batch" in combined,
                f"expected hint about --canonical-id/--batch in: {combined!r}",
            )

    def test_acquire_success_without_pdf_path_errors(self):
        with isolated_cache():
            cid = "anon_2025_no_pdf_path_999999"
            _seed_paper(cid)
            _run(TRIAGE, "--canonical-id", cid, "--sufficient", "false",
                 "--rationale", "fetch")
            r = _run(ACQUIRE, "--canonical-id", cid, "--source", "arxiv")
            self.assertTrue(r.returncode != 0)
            self.assertIn("pdf-path required", r.stderr)

    def test_acquire_success_with_missing_file_errors(self):
        with isolated_cache():
            cid = "anon_2025_no_file_aaaaa1"
            _seed_paper(cid)
            _run(TRIAGE, "--canonical-id", cid, "--sufficient", "false",
                 "--rationale", "fetch")
            r = _run(ACQUIRE, "--canonical-id", cid,
                     "--source", "arxiv",
                     "--pdf-path", "/tmp/this-file-does-not-exist-xyzzy.pdf")
            self.assertTrue(r.returncode != 0)
            self.assertIn("pdf not found", r.stderr)


if __name__ == "__main__":
    sys.exit(run_tests(
        DiscoveredStateTests,
        AcquireGateTests,
        AcquireIntegrityTests,
        AuditLogTests,
        StateMonotonicityTests,
        CliEdgeCaseTests,
    ))

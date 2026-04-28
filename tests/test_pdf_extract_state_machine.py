"""Dry-run harness for the pdf-extract state machine.

Mirrors `tests/test_paper_state_machine.py` and `tests/test_deep_research_pipeline.py`
patterns. Drives `pdf-extract/scripts/extract.py` via subprocess and asserts
its pre-conditions, idempotency, and dependency reporting.

Docling is NOT installed in this runtime, which is a feature for these
tests: it lets us cleanly verify the "docling not installed" failure
mode and the pre-extract guards (no-PDF, already-extracted) without
accidentally producing real extractions.

Cracks documented (as code-review observations rather than executable
failures, since exercising them requires docling installed):

- CRACK A: extract.py has no `state == acquired` guard. It only checks
  whether a PDF exists in raw/. A paper at state=discovered with a PDF
  somehow in raw/ would extract anyway — there's no audit-log entry
  refusing the unsanctioned advance. See extract.py:120-122.
- CRACK B: extract.py does not magic-byte-check the PDF before passing
  it to docling (paper-acquire/record.py does this on its way in;
  extract.py trusts the file). A garbage file in raw/ produces an
  opaque docling error rather than a clear "not a PDF" message.
- CRACK C: extract.py does not acquire an artifact_lock before mutating
  the artifact (writing content.md, figures/, extraction.log, advancing
  state). Concurrent extract runs against the same paper would race —
  unlike paper-acquire/record.py which uses lib.lockfile.artifact_lock.
"""

import json
import subprocess
import sys
from pathlib import Path

from tests import _shim  # noqa: F401
from tests.harness import TestCase, isolated_cache, run_tests

_ROOT = Path(__file__).resolve().parent.parent
EXTRACT = _ROOT / ".claude/skills/pdf-extract/scripts/extract.py"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(EXTRACT), *args],
        capture_output=True, text=True,
    )


def _seed_paper(cid: str, state: str = "discovered") -> "PaperArtifact":  # type: ignore  # noqa: F821
    """Seed a paper with manifest + metadata. State defaults to discovered;
    pass state='acquired' for tests that exercise post-acquire paths
    (e.g. extract behavior after the v0.23 state guard)."""
    from lib.paper_artifact import Metadata, PaperArtifact, State
    art = PaperArtifact(cid)
    m = art.load_manifest()
    if state != "discovered":
        m.state = getattr(State, state)
    art.save_manifest(m)
    if art.load_metadata() is None:
        art.save_metadata(Metadata(title=f"Test paper {cid}"))
    return art


def _write_pdf(path: Path, size: int = 1024) -> Path:
    """Write a syntactically-valid (header-wise) PDF of approx `size` bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = b"%PDF-1.4\n" + b"%\xe2\xe3\xcf\xd3\n"  # plausible header
    payload += b"1 0 obj\n<<>>\nendobj\n" * max(1, (size - len(payload)) // 30)
    payload += b"\n%%EOF\n"
    path.write_bytes(payload[:size] if len(payload) > size else payload)
    return path


# ---------------- pre-extract guards ----------------

class PreExtractGuardTests(TestCase):
    def test_extract_without_pdf_in_raw_errors(self):
        """A paper at state=acquired (gate-passed) but with raw/ empty
        errors with 'no PDF'. v0.23: this is the no-pdf-after-acquire
        edge case — the state guard passed but the file is missing."""
        with isolated_cache():
            cid = "anon_2025_nopdf_111111"
            _seed_paper(cid, state="acquired")
            r = _run("--canonical-id", cid)
            self.assertTrue(r.returncode != 0,
                            "extract must refuse when no PDF exists")
            self.assertIn("no PDF", r.stderr,
                          f"expected 'no PDF' in stderr; got: {r.stderr!r}")

    def test_extract_unknown_canonical_id_hits_state_guard(self):
        """An entirely unknown cid: fresh paper defaults to state=discovered.
        v0.23: the state guard fires before the no-PDF check."""
        with isolated_cache():
            r = _run("--canonical-id", "anon_2025_notreal_222222")
            self.assertTrue(r.returncode != 0)
            self.assertIn("refusing to extract", r.stderr)

    def test_extract_invalid_engine_value_rejected_by_argparse(self):
        with isolated_cache():
            cid = "anon_2025_argparse_333333"
            _seed_paper(cid)
            r = _run("--canonical-id", cid, "--engine", "ocr-magic")
            self.assertTrue(r.returncode != 0)
            self.assertIn("invalid choice", r.stderr.lower())


# ---------------- docling-not-installed branch ----------------

class DoclingMissingTests(TestCase):
    """Docling is not installed in this runtime. The script should fail
    cleanly with an actionable message rather than crash with an opaque
    ImportError stack trace."""

    def test_docling_missing_errors_cleanly_on_default_engine(self):
        with isolated_cache() as cache_dir:
            cid = "anon_2025_doclingmiss_444444"
            art = _seed_paper(cid, state="acquired")
            _write_pdf(art.raw_dir / "arxiv.pdf", size=1024)

            r = _run("--canonical-id", cid)
            # Two acceptable outcomes when docling is absent:
            #   (a) script exits non-zero with a docling-related message, or
            #   (b) auto-mode falls back to vision and records the fallback
            #       in extraction.log (rc=0, but the log proves docling
            #       didn't actually run).
            stderr = r.stderr.lower()
            log_file = art.root / "extraction.log"
            log = json.loads(log_file.read_text()) if log_file.exists() else {}
            failed_cleanly = (
                r.returncode != 0 and (
                    "docling" in stderr or "pymupdf" in stderr or "fallback" in stderr
                )
            )
            fell_back = (
                r.returncode == 0 and (
                    log.get("fallback") == "vision"
                    or "docling_error" in log
                )
            )
            self.assertTrue(
                failed_cleanly or fell_back,
                f"expected clean failure or recorded vision fallback; "
                f"rc={r.returncode}, stderr={r.stderr!r}, log={log!r}",
            )

    def test_explicit_engine_docling_surfaces_the_missing_dep(self):
        with isolated_cache() as cache_dir:
            cid = "anon_2025_doclingexplicit_555555"
            art = _seed_paper(cid, state="acquired")
            _write_pdf(art.raw_dir / "arxiv.pdf", size=1024)

            r = _run("--canonical-id", cid, "--engine", "docling")
            self.assertTrue(r.returncode != 0)
            # With --engine docling, the docling ImportError is the first
            # thing to fail; no fallback masks it.
            self.assertIn("docling", r.stderr.lower())


# ---------------- idempotency ----------------

class IdempotencyTests(TestCase):
    def test_already_extracted_short_circuits(self):
        """A paper at state=extracted with content.md is a no-op without
        --force. v0.23 keeps this friendly UX (state=extracted is allowed
        to enter; has_full_text() short-circuits before doing any work)."""
        with isolated_cache() as cache_dir:
            cid = "anon_2025_alreadyext_666666"
            art = _seed_paper(cid, state="extracted")
            _write_pdf(art.raw_dir / "arxiv.pdf", size=1024)
            # Pre-write content.md so has_full_text() returns True
            art.content_path.write_text("# already extracted\n\nbody " * 50)

            r = _run("--canonical-id", cid)
            self.assertEqual(
                r.returncode, 0,
                f"already-extracted noop must succeed: {r.stderr!r}",
            )
            self.assertIn("already extracted", r.stdout)

    def test_force_bypasses_already_extracted_skip(self):
        """--force must NOT short-circuit on existing content.md. Without
        docling installed it'll error out attempting the real extract,
        which is itself the proof the skip was bypassed."""
        with isolated_cache() as cache_dir:
            cid = "anon_2025_forcerun_777777"
            art = _seed_paper(cid, state="extracted")
            _write_pdf(art.raw_dir / "arxiv.pdf", size=1024)
            art.content_path.write_text("# stale\n\nbody " * 50)

            r = _run("--canonical-id", cid, "--force")
            # With docling missing, the real extract fails. That non-zero
            # exit + the absence of "already extracted" in stdout is the
            # signal that --force did its job.
            self.assertNotIn(
                "already extracted", r.stdout,
                "--force must NOT print the already-extracted skip line",
            )


# ---------------- argparse / CLI edges ----------------

class CliEdgeTests(TestCase):
    def test_extract_requires_canonical_id(self):
        r = _run()
        self.assertTrue(r.returncode != 0)
        self.assertIn("--canonical-id", r.stderr)

    def test_extract_help_lists_force_and_engine(self):
        r = _run("--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("--force", r.stdout)
        self.assertIn("--engine", r.stdout)
        self.assertIn("docling", r.stdout)
        self.assertIn("vision", r.stdout)


# ---------------- crack documentation (source-grep, not behavior) ----------------

class V023FixesTests(TestCase):
    """v0.23 fixed the three v0.20 CRACKs. These tests assert the FIXES
    are in place via source-grep; behavioral tests below exercise them."""

    def _src(self) -> str:
        return EXTRACT.read_text()

    def test_state_acquired_guard_present(self):
        """v0.23: extract refuses on upstream states (discovered/triaged)
        and on read/cited unless --force. acquired and extracted pass through."""
        src = self._src()
        self.assertIn("_STATES_TOO_EARLY", src,
                      "extract.py must declare which states are too-early")
        self.assertIn("_STATES_TOO_LATE", src,
                      "extract.py must declare which states are too-late")
        self.assertIn("refusing to extract", src)

    def test_pdf_integrity_check_present(self):
        """v0.23: magic-byte + min-size check before passing to docling."""
        src = self._src()
        self.assertIn("%PDF-", src,
                      "extract.py must magic-byte-check the PDF")
        self.assertIn("_MIN_PDF_BYTES", src)

    def test_artifact_lock_present(self):
        """v0.23: artifact_lock wraps the artifact mutation block."""
        src = self._src()
        self.assertIn("artifact_lock", src)
        self.assertIn("from lib.lockfile import artifact_lock", src)


class V023BehavioralTests(TestCase):
    """End-to-end exercises of the v0.23 fixes."""

    def test_extract_refuses_when_state_is_discovered(self):
        """A paper at state=discovered with a PDF in raw/ now refuses
        rather than silently extracting (CRACK A from v0.20)."""
        with isolated_cache() as cache_dir:
            cid = "anon_2025_unsanctioned_aaaaaa"
            art = _seed_paper(cid)
            # Manually drop a PDF in raw/ without going through paper-acquire
            _write_pdf(art.raw_dir / "manual.pdf", size=1024)

            r = _run("--canonical-id", cid)
            self.assertTrue(r.returncode != 0)
            self.assertIn("refusing to extract", r.stderr)
            self.assertIn("discovered", r.stderr)

    def test_extract_rejects_html_payload_at_extract_time(self):
        """A paper at state=acquired with a non-PDF in raw/ (e.g. someone
        replaced the file post-acquire) is now rejected before docling
        is even invoked (CRACK B from v0.20)."""
        with isolated_cache() as cache_dir:
            from lib.paper_artifact import State
            cid = "anon_2025_replaced_bbbbbb"
            art = _seed_paper(cid)
            # Advance state to acquired without going through record.py
            m = art.load_manifest()
            m.state = State.acquired
            art.save_manifest(m)
            # Drop an HTML payload as if a publisher replaced the PDF
            html = b"<!DOCTYPE html><html>" + b"login wall " * 50 + b"</html>"
            (art.raw_dir / "arxiv.pdf").write_bytes(html)

            r = _run("--canonical-id", cid)
            self.assertTrue(r.returncode != 0)
            self.assertIn("not a PDF", r.stderr)

    def test_extract_rejects_too_small_payload_at_extract_time(self):
        with isolated_cache() as cache_dir:
            from lib.paper_artifact import State
            cid = "anon_2025_tinyrepl_cccccc"
            art = _seed_paper(cid)
            m = art.load_manifest()
            m.state = State.acquired
            art.save_manifest(m)
            (art.raw_dir / "arxiv.pdf").write_bytes(b"%PDF-1.4\nx")

            r = _run("--canonical-id", cid)
            self.assertTrue(r.returncode != 0)
            self.assertIn("too small", r.stderr)


if __name__ == "__main__":
    sys.exit(run_tests(
        PreExtractGuardTests,
        DoclingMissingTests,
        IdempotencyTests,
        CliEdgeTests,
        V023FixesTests,
        V023BehavioralTests,
    ))

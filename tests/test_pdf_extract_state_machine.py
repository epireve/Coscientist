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

from tests import _shim  # noqa: F401

import json
import subprocess
import sys
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests

_ROOT = Path(__file__).resolve().parent.parent
EXTRACT = _ROOT / ".claude/skills/pdf-extract/scripts/extract.py"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(EXTRACT), *args],
        capture_output=True, text=True,
    )


def _seed_paper(cid: str) -> "PaperArtifact":  # type: ignore  # noqa: F821
    """Seed a paper with manifest + metadata. State stays at discovered."""
    from lib.paper_artifact import Metadata, PaperArtifact
    art = PaperArtifact(cid)
    art.save_manifest(art.load_manifest())
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
        """A paper with state=discovered (no raw/*.pdf) cannot be extracted."""
        with isolated_cache():
            cid = "anon_2025_nopdf_111111"
            _seed_paper(cid)
            r = _run("--canonical-id", cid)
            self.assertTrue(r.returncode != 0,
                            "extract must refuse when no PDF exists")
            self.assertIn("no PDF", r.stderr,
                          f"expected 'no PDF' in stderr; got: {r.stderr!r}")

    def test_extract_unknown_canonical_id_errors_cleanly(self):
        """An entirely unknown cid: PaperArtifact creates the dir on the fly,
        but no PDF is there, so the same 'no PDF' branch fires."""
        with isolated_cache():
            r = _run("--canonical-id", "anon_2025_notreal_222222")
            self.assertTrue(r.returncode != 0)
            self.assertIn("no PDF", r.stderr)

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
            art = _seed_paper(cid)
            _write_pdf(art.raw_dir / "arxiv.pdf", size=1024)

            r = _run("--canonical-id", cid)
            self.assertTrue(r.returncode != 0,
                            "extract must fail when docling missing")
            # Either docling error message or vision fallback failure.
            # The script prefers "docling not installed" but auto mode
            # may try vision fallback first; accept either signal.
            stderr = r.stderr.lower()
            self.assertTrue(
                "docling" in stderr or "pymupdf" in stderr or "fallback" in stderr,
                f"expected docling/pymupdf-related error; got: {r.stderr!r}",
            )

    def test_explicit_engine_docling_surfaces_the_missing_dep(self):
        with isolated_cache() as cache_dir:
            cid = "anon_2025_doclingexplicit_555555"
            art = _seed_paper(cid)
            _write_pdf(art.raw_dir / "arxiv.pdf", size=1024)

            r = _run("--canonical-id", cid, "--engine", "docling")
            self.assertTrue(r.returncode != 0)
            # With --engine docling, the docling ImportError is the first
            # thing to fail; no fallback masks it.
            self.assertIn("docling", r.stderr.lower())


# ---------------- idempotency ----------------

class IdempotencyTests(TestCase):
    def test_already_extracted_short_circuits(self):
        """If content.md exists and is non-empty, extract is a no-op
        without --force. The caller learns nothing was redone."""
        with isolated_cache() as cache_dir:
            cid = "anon_2025_alreadyext_666666"
            art = _seed_paper(cid)
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
            art = _seed_paper(cid)
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

class CrackDocumentationTests(TestCase):
    """These tests assert that the *current* extract.py source has the
    properties we identified as cracks. If any of these tests start
    failing, it means someone fixed the crack — flip the assertion."""

    def _src(self) -> str:
        return EXTRACT.read_text()

    def test_CRACK_A_no_state_acquired_guard(self):
        """No `state == acquired` check before extracting. extract.py only
        guards against missing PDF, not against running on a paper that
        hasn't been formally acquired (e.g. someone dropped a file in
        raw/ manually)."""
        src = self._src()
        # A real guard would look something like:
        #   if manifest.state != State.acquired
        self.assertNotIn(
            "State.acquired", src,
            "if extract.py now has a state guard, flip this CRACK test",
        )

    def test_CRACK_B_no_pdf_integrity_check(self):
        """No magic-byte / size check on the PDF before passing to docling
        (compare paper-acquire/record.py which has b'%PDF-' check + size>=200)."""
        src = self._src()
        self.assertNotIn(b"%PDF-".decode(), src,
                         "if extract.py now magic-byte-checks the PDF, flip this CRACK test")

    def test_CRACK_C_no_artifact_lock(self):
        """No artifact_lock around extract operations. Concurrent extracts
        on the same paper can race — unlike paper-acquire/record.py which
        wraps mutations in `with artifact_lock(art.root, timeout=30.0)`."""
        src = self._src()
        self.assertNotIn(
            "artifact_lock", src,
            "if extract.py now uses artifact_lock, flip this CRACK test",
        )


if __name__ == "__main__":
    sys.exit(run_tests(
        PreExtractGuardTests,
        DoclingMissingTests,
        IdempotencyTests,
        CliEdgeTests,
        CrackDocumentationTests,
    ))

"""Tests for Phase 2 remaining: dmp-generator, ethics-irb, registered-reports, zenodo-deposit (prepare-only)."""
from __future__ import annotations

import importlib.util as _ilu
import json
import os
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

from tests.harness import CoscientistTestCase, isolated_cache  # noqa


def _load(skill, file):
    spec = _ilu.spec_from_file_location(
        file,
        _REPO_ROOT / f".claude/skills/{skill}/scripts/{file}.py",
    )
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ───── dmp-generator ─────

class DmpGeneratorTests(CoscientistTestCase):
    def test_funders_has_four(self):
        mod = _load("dmp-generator", "dmp")
        self.assertEqual(set(mod.FUNDERS), {"nih", "nsf", "wellcome", "erc"})

    def test_get_template_default(self):
        mod = _load("dmp-generator", "dmp")
        t = mod.get_template("nih", None)
        self.assertEqual(t["mechanism"], "R01")

    def test_get_template_invalid_funder_raises(self):
        mod = _load("dmp-generator", "dmp")
        try:
            mod.get_template("gates", None)
            self.assertFalse(True, "should have raised")
        except ValueError:
            pass

    def test_init_creates_files(self):
        with isolated_cache() as cache:
            mod = _load("dmp-generator", "dmp")
            import argparse
            import contextlib
            import io
            args = argparse.Namespace(
                title="My DMP", funder="nih", mechanism=None, force=False
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_init(args)
            r = json.loads(buf.getvalue())
            d = cache / "dmps" / r["dmp_id"]
            self.assertTrue((d / "manifest.json").exists())
            self.assertTrue((d / "outline.json").exists())
            self.assertTrue((d / "source.md").exists())

    def test_section_updates(self):
        with isolated_cache() as cache:
            mod = _load("dmp-generator", "dmp")
            import argparse
            import contextlib
            import io
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_init(argparse.Namespace(
                    title="My DMP", funder="nih", mechanism=None, force=False
                ))
            did = json.loads(buf.getvalue())["dmp_id"]
            buf2 = io.StringIO()
            with contextlib.redirect_stdout(buf2):
                mod.cmd_section(argparse.Namespace(
                    dmp_id=did, section="data_type",
                    content="Tabular data; 200 GB."
                ))
            r = json.loads(buf2.getvalue())
            self.assertEqual(r["status"], "drafted")
            self.assertGreater(r["word_count"], 0)

    def test_status_after_section(self):
        with isolated_cache():
            mod = _load("dmp-generator", "dmp")
            import argparse
            import contextlib
            import io
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_init(argparse.Namespace(
                    title="DMP S", funder="nsf", mechanism=None, force=False
                ))
            did = json.loads(buf.getvalue())["dmp_id"]
            buf2 = io.StringIO()
            with contextlib.redirect_stdout(buf2):
                mod.cmd_section(argparse.Namespace(
                    dmp_id=did, section="data_description",
                    content="Description text."
                ))
            buf3 = io.StringIO()
            with contextlib.redirect_stdout(buf3):
                mod.cmd_status(argparse.Namespace(dmp_id=did))
            self.assertEqual(json.loads(buf3.getvalue())["sections_drafted"], 1)


# ───── ethics-irb ─────

class EthicsIrbTests(CoscientistTestCase):
    def test_irb_init_exempt(self):
        with isolated_cache():
            mod = _load("ethics-irb", "ethics")
            import argparse
            import contextlib
            import io
            args = argparse.Namespace(
                title="Survey Study", review_level="exempt",
                has_vulnerable_pop=False, force=False
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_irb_init(args)
            r = json.loads(buf.getvalue())
            self.assertEqual(r["review_level"], "exempt")
            self.assertEqual(r["n_sections"], 3)

    def test_irb_init_full_board_more_sections(self):
        with isolated_cache():
            mod = _load("ethics-irb", "ethics")
            import argparse
            import contextlib
            import io
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_irb_init(argparse.Namespace(
                    title="Trial", review_level="full-board",
                    has_vulnerable_pop=True, force=False
                ))
            r = json.loads(buf.getvalue())
            self.assertGreater(r["n_sections"], 5)

    def test_irb_section(self):
        with isolated_cache():
            mod = _load("ethics-irb", "ethics")
            import argparse
            import contextlib
            import io
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_irb_init(argparse.Namespace(
                    title="X", review_level="exempt",
                    has_vulnerable_pop=False, force=False
                ))
            aid = json.loads(buf.getvalue())["application_id"]
            buf2 = io.StringIO()
            with contextlib.redirect_stdout(buf2):
                mod.cmd_irb_section(argparse.Namespace(
                    application_id=aid, section="study_description",
                    content="Brief description."
                ))
            self.assertEqual(json.loads(buf2.getvalue())["status"], "drafted")

    def test_coi_add_and_list(self):
        with isolated_cache():
            mod = _load("ethics-irb", "ethics")
            import argparse
            import contextlib
            import io
            for entity, type_ in [("Acme Pharma", "consulting"), ("Beta Corp", "stock")]:
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    mod.cmd_coi_add(argparse.Namespace(
                        project_id="p1", entity=entity, type=type_, value="5000"
                    ))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_coi_list(argparse.Namespace(project_id="p1"))
            r = json.loads(buf.getvalue())
            self.assertEqual(r["total"], 2)

    def test_coi_invalid_type_raises(self):
        with isolated_cache():
            mod = _load("ethics-irb", "ethics")
            import argparse
            with self.assertRaises(SystemExit):
                mod.cmd_coi_add(argparse.Namespace(
                    project_id="p1", entity="X", type="bribe", value=""
                ))

    def test_coi_remove(self):
        with isolated_cache():
            mod = _load("ethics-irb", "ethics")
            import argparse
            import contextlib
            import io
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_coi_add(argparse.Namespace(
                    project_id="p1", entity="Acme", type="funding", value="1000"
                ))
            added_id = json.loads(buf.getvalue())["added_id"]
            buf2 = io.StringIO()
            with contextlib.redirect_stdout(buf2):
                mod.cmd_coi_remove(argparse.Namespace(
                    project_id="p1", entry_id=added_id
                ))
            self.assertEqual(json.loads(buf2.getvalue())["total_count"], 0)


# ───── registered-reports ─────

class RegisteredReportsTests(CoscientistTestCase):
    def test_init_creates(self):
        with isolated_cache() as cache:
            mod = _load("registered-reports", "rr")
            import argparse
            import contextlib
            import io
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_init(argparse.Namespace(
                    title="My RR", journal="Cortex", force=False
                ))
            r = json.loads(buf.getvalue())
            self.assertEqual(r["state"], "stage-1-drafted")
            self.assertTrue((cache / "registered_reports" / r["rr_id"] / "manifest.json").exists())

    def test_advance_forward(self):
        with isolated_cache():
            mod = _load("registered-reports", "rr")
            import argparse
            import contextlib
            import io
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_init(argparse.Namespace(title="RR1", journal=None, force=False))
            rid = json.loads(buf.getvalue())["rr_id"]
            for state in ["stage-1-submitted", "in-principle-accepted",
                          "data-collected", "stage-2-drafted"]:
                buf2 = io.StringIO()
                with contextlib.redirect_stdout(buf2):
                    mod.cmd_advance(argparse.Namespace(
                        rr_id=rid, to_state=state, force=False
                    ))
                self.assertEqual(json.loads(buf2.getvalue())["state"], state)

    def test_advance_backward_blocked(self):
        with isolated_cache():
            mod = _load("registered-reports", "rr")
            import argparse
            import contextlib
            import io
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_init(argparse.Namespace(title="RR2", journal=None, force=False))
            rid = json.loads(buf.getvalue())["rr_id"]
            mod.cmd_advance(argparse.Namespace(
                rr_id=rid, to_state="stage-1-submitted", force=False
            ))
            with self.assertRaises(SystemExit):
                mod.cmd_advance(argparse.Namespace(
                    rr_id=rid, to_state="stage-1-drafted", force=False
                ))

    def test_advance_invalid_state_raises(self):
        with isolated_cache():
            mod = _load("registered-reports", "rr")
            import argparse
            import contextlib
            import io
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_init(argparse.Namespace(title="RR3", journal=None, force=False))
            rid = json.loads(buf.getvalue())["rr_id"]
            with self.assertRaises(SystemExit):
                mod.cmd_advance(argparse.Namespace(
                    rr_id=rid, to_state="nonexistent", force=False
                ))

    def test_history_recorded(self):
        with isolated_cache():
            mod = _load("registered-reports", "rr")
            import argparse
            import contextlib
            import io
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.cmd_init(argparse.Namespace(title="RR4", journal=None, force=False))
            rid = json.loads(buf.getvalue())["rr_id"]
            mod.cmd_advance(argparse.Namespace(
                rr_id=rid, to_state="stage-1-submitted", force=False
            ))
            buf2 = io.StringIO()
            with contextlib.redirect_stdout(buf2):
                mod.cmd_status(argparse.Namespace(rr_id=rid))
            r = json.loads(buf2.getvalue())
            self.assertEqual(len(r["history"]), 2)


# ───── zenodo-deposit (prepare-only, no real network) ─────

class ZenodoPrepareTests(CoscientistTestCase):
    def _setup_dataset(self, cache, mod_ds):
        import argparse
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "data.csv"
            f.write_text("col1,col2\n1,2\n")
            args = argparse.Namespace(
                title="Test Set", description="A test dataset",
                license="CC-BY-4.0", source_url=None, doi=None,
                paths=[str(f)], project_id=None, force=False,
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod_ds.cmd_register(args)
            did = json.loads(buf.getvalue())["dataset_id"]
            buf2 = io.StringIO()
            with contextlib.redirect_stdout(buf2):
                mod_ds.cmd_hash(argparse.Namespace(
                    dataset_id=did, algorithm="sha256", force_large=False
                ))
            return did

    def test_prepare_emits_metadata(self):
        with isolated_cache() as cache:
            mod_ds = _load("dataset-agent", "register")
            mod_zen = _load("zenodo-deposit", "deposit")
            did = self._setup_dataset(cache, mod_ds)
            import argparse
            import contextlib
            import io
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod_zen.cmd_prepare(argparse.Namespace(dataset_id=did))
            r = json.loads(buf.getvalue())
            self.assertTrue(r["ready_to_upload"])
            self.assertEqual(r["validation_errors"], [])
            self.assertIn("metadata", r)
            self.assertEqual(r["metadata"]["metadata"]["upload_type"], "dataset")

    def test_prepare_missing_hashes_flagged(self):
        with isolated_cache() as cache:
            mod_ds = _load("dataset-agent", "register")
            mod_zen = _load("zenodo-deposit", "deposit")
            import argparse
            import contextlib
            import io
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod_ds.cmd_register(argparse.Namespace(
                    title="No Hash", description="x", license="MIT",
                    source_url=None, doi=None, paths=[], project_id=None, force=False,
                ))
            did = json.loads(buf.getvalue())["dataset_id"]
            buf2 = io.StringIO()
            with contextlib.redirect_stdout(buf2):
                mod_zen.cmd_prepare(argparse.Namespace(dataset_id=did))
            r = json.loads(buf2.getvalue())
            self.assertFalse(r["ready_to_upload"])
            self.assertTrue(any("hash" in e for e in r["validation_errors"]))

    def test_upload_no_token_raises(self):
        with isolated_cache() as cache:
            mod_ds = _load("dataset-agent", "register")
            mod_zen = _load("zenodo-deposit", "deposit")
            did = self._setup_dataset(cache, mod_ds)
            old_token = os.environ.pop("ZENODO_TOKEN", None)
            try:
                import argparse
                with self.assertRaises(SystemExit):
                    mod_zen.cmd_upload(argparse.Namespace(
                        dataset_id=did, sandbox=False
                    ))
            finally:
                if old_token:
                    os.environ["ZENODO_TOKEN"] = old_token

    def test_status_after_prepare(self):
        with isolated_cache() as cache:
            mod_ds = _load("dataset-agent", "register")
            mod_zen = _load("zenodo-deposit", "deposit")
            did = self._setup_dataset(cache, mod_ds)
            import argparse
            import contextlib
            import io
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod_zen.cmd_status(argparse.Namespace(dataset_id=did))
            r = json.loads(buf.getvalue())
            self.assertEqual(r["state"], "registered")
            self.assertFalse(r["has_zenodo_response"])

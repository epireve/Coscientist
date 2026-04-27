"""v0.56 — self-play debate tests."""

from tests import _shim  # noqa: F401

import sys
from pathlib import Path

from tests.harness import TestCase, run_tests

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from lib.debate import (  # noqa: E402
    DebateSpec, EvidenceAnchor, JudgeRuling, Position, Scores,
    decide_verdict, render_brief, render_con_prompt,
    render_judge_prompt, render_pro_prompt, score_falsifiability,
    score_groundedness, score_position, score_responsiveness,
    score_specificity,
)


def _spec() -> DebateSpec:
    return DebateSpec(
        topic="novelty",
        target_id="vaswani_2017_attention",
        target_claim="The paper introduces a novel attention-only architecture",
        min_anchors_per_side=3,
    )


def _anchor(cid: str) -> EvidenceAnchor:
    return EvidenceAnchor(
        canonical_id=cid,
        claim_quote="x",
        why_relevant="y",
    )


# ---------- specificity ----------

class SpecificityTests(TestCase):
    def test_empty_text_zero(self):
        self.assertEqual(score_specificity(""), 0.0)

    def test_concrete_signals_score_high(self):
        s = score_specificity(
            "Experiment 1 shows accuracy 95% with n=200 samples; "
            "see figure 3 and table 2."
        )
        self.assertTrue(s >= 0.75)

    def test_hedge_phrases_penalized(self):
        s_low = score_specificity(
            "It might broadly seem to be somewhat interesting; "
            "perhaps results may indicate something."
        )
        self.assertEqual(s_low, 0.0)

    def test_concrete_beats_hedge(self):
        s_concrete = score_specificity(
            "Experiment 2 with n=500 shows p<0.01 across ablation."
        )
        s_hedge = score_specificity(
            "It may seem that perhaps somewhat results appear."
        )
        self.assertTrue(s_concrete > s_hedge)


# ---------- groundedness ----------

class GroundednessTests(TestCase):
    def test_no_anchors_zero(self):
        self.assertEqual(score_groundedness([], {"a"}), 0.0)

    def test_no_validation_returns_neutral(self):
        s = score_groundedness([_anchor("a"), _anchor("b")], None)
        self.assertEqual(s, 0.5)

    def test_all_valid_full_score(self):
        valid = {"a", "b", "c"}
        s = score_groundedness(
            [_anchor("a"), _anchor("b"), _anchor("c")], valid,
            min_anchors=3,
        )
        self.assertEqual(s, 1.0)

    def test_partial_valid_partial_score(self):
        valid = {"a"}
        s = score_groundedness(
            [_anchor("a"), _anchor("b"), _anchor("c")], valid,
            min_anchors=3,
        )
        # 1/3 valid, full count met → ~0.33
        self.assertTrue(0.3 <= s <= 0.4)

    def test_below_min_anchors_penalized(self):
        valid = {"a"}
        s_few = score_groundedness(
            [_anchor("a")], valid, min_anchors=3,
        )
        s_full = score_groundedness(
            [_anchor("a"), _anchor("a"), _anchor("a")], valid,
            min_anchors=3,
        )
        self.assertTrue(s_few < s_full)


# ---------- responsiveness ----------

class ResponsivenessTests(TestCase):
    def test_empty_rebuttal_zero(self):
        self.assertEqual(score_responsiveness("", "other content"), 0.0)

    def test_high_overlap_high_score(self):
        other = "transformer attention mechanism scales with parameters"
        rebut = "The transformer attention claim is countered by parameters scaling not at all"
        s = score_responsiveness(rebut, other)
        self.assertTrue(s >= 0.5)

    def test_no_overlap_zero(self):
        s = score_responsiveness(
            "completely different unrelated stuff",
            "transformer attention mechanism scales",
        )
        self.assertTrue(s <= 0.2)


# ---------- falsifiability ----------

class FalsifiabilityTests(TestCase):
    def test_no_trigger_zero(self):
        self.assertEqual(score_falsifiability("just a generic statement"), 0.0)

    def test_kill_criterion_phrase_scores(self):
        s = score_falsifiability(
            "Our verdict would flip if we observed null results in "
            "the kill criterion experiment."
        )
        self.assertTrue(s >= 0.5)


# ---------- decide_verdict ----------

class DecideVerdictTests(TestCase):
    def _scores(self, x: float) -> Scores:
        return Scores(x, x, x, x)

    def test_pro_wins_when_higher(self):
        v, d = decide_verdict(self._scores(0.8), self._scores(0.5))
        self.assertEqual(v, "pro")
        self.assertTrue(d > 0)

    def test_con_wins_when_higher(self):
        v, _ = decide_verdict(self._scores(0.4), self._scores(0.7))
        self.assertEqual(v, "con")

    def test_draw_within_threshold(self):
        v, _ = decide_verdict(self._scores(0.51), self._scores(0.50))
        self.assertEqual(v, "draw")


# ---------- score_position integration ----------

class ScorePositionTests(TestCase):
    def test_strong_position_scores_well(self):
        valid = {"c1", "c2", "c3"}
        pos = Position(
            side="pro",
            statement=(
                "Experiment 1 shows accuracy 95% with n=300; ablation "
                "in figure 2 shows the proposed method outperforms baseline. "
                "Our verdict would flip if we observed null results."
            ),
            evidence_anchors=[_anchor("c1"), _anchor("c2"), _anchor("c3")],
            rebuttal_to_other=(
                "Their counterclaim about transformer parameters fails "
                "because the experiment used 1B parameters not 100M."
            ),
        )
        scores = score_position(
            pos,
            other_statement="transformer parameters scaling",
            valid_canonical_ids=valid,
        )
        self.assertEqual(scores.evidence_groundedness, 1.0)
        self.assertTrue(scores.argument_specificity >= 0.5)
        self.assertTrue(scores.falsifiability >= 0.5)

    def test_weak_position_scores_low(self):
        pos = Position(
            side="con",
            statement=(
                "It seems perhaps somewhat that broadly the work may "
                "be interestingly novel."
            ),
            evidence_anchors=[],
            rebuttal_to_other="",
        )
        scores = score_position(
            pos, valid_canonical_ids={"x"}, min_anchors=3,
        )
        self.assertEqual(scores.evidence_groundedness, 0.0)
        self.assertEqual(scores.argument_specificity, 0.0)
        self.assertEqual(scores.rebuttal_responsiveness, 0.0)
        self.assertEqual(scores.falsifiability, 0.0)


# ---------- prompt rendering ----------

class PromptTests(TestCase):
    def test_pro_prompt_has_target_and_role(self):
        out = render_pro_prompt(_spec())
        self.assertIn("PRO side", out)
        self.assertIn("vaswani_2017_attention", out)
        self.assertIn("evidence_anchors", out)
        self.assertIn("at least 3", out)

    def test_con_prompt_argues_against(self):
        out = render_con_prompt(_spec())
        self.assertIn("CON side", out)
        self.assertIn("not novel", out.lower())

    def test_topic_specific_phrasing(self):
        s = DebateSpec(
            topic="publishability",
            target_id="m1", target_claim="X",
        )
        pro = render_pro_prompt(s)
        self.assertIn("publishable", pro.lower())
        s2 = DebateSpec(topic="red-team", target_id="m1", target_claim="X")
        con = render_con_prompt(s2)
        self.assertIn("fatal", con.lower())

    def test_judge_prompt_includes_both_positions(self):
        spec = _spec()
        pro = Position(side="pro", statement="PRO statement here",
                       evidence_anchors=[_anchor("c1")])
        con = Position(side="con", statement="CON statement here",
                       evidence_anchors=[_anchor("c2")])
        out = render_judge_prompt(spec, pro, con)
        self.assertIn("PRO statement here", out)
        self.assertIn("CON statement here", out)
        self.assertIn("verdict", out)
        self.assertIn("kill_criterion", out)


# ---------- transcript rendering ----------

class RenderBriefTests(TestCase):
    def test_brief_renders_all_sections(self):
        spec = _spec()
        pro = Position(
            side="pro", statement="Pro stmt",
            evidence_anchors=[_anchor("c1"), _anchor("c2")],
        )
        con = Position(
            side="con", statement="Con stmt",
            evidence_anchors=[_anchor("c3")],
        )
        ruling = JudgeRuling(
            verdict="pro", reasoning="PRO had stronger evidence.",
            kill_criterion="If a 2018 paper made the same claim",
            pro_scores=Scores(0.9, 0.8, 0.7, 0.6),
            con_scores=Scores(0.5, 0.4, 0.3, 0.5),
            delta=0.325,
        )
        out = render_brief(spec, pro, con, ruling)
        for needle in ("Debate", "PRO", "CON", "Judge reasoning",
                       "Verdict", "kill criterion".lower()):
            self.assertIn(needle, out if needle != "kill criterion" else out.lower())

    def test_brief_shows_verdict(self):
        spec = _spec()
        pro = Position(side="pro", statement="x")
        con = Position(side="con", statement="y")
        ruling = JudgeRuling(
            verdict="draw", reasoning="r", kill_criterion="k",
            pro_scores=Scores(0.5, 0.5, 0.5, 0.5),
            con_scores=Scores(0.5, 0.5, 0.5, 0.5),
            delta=0.0,
        )
        out = render_brief(spec, pro, con, ruling)
        self.assertIn("`draw`", out)


# ---------- Position serialization ----------

class PositionSerializationTests(TestCase):
    def test_round_trip(self):
        pos = Position(
            side="pro", statement="x",
            evidence_anchors=[_anchor("c1"), _anchor("c2")],
            rebuttal_to_other="r",
        )
        d = pos.to_dict()
        pos2 = Position.from_dict(d)
        self.assertEqual(pos2.side, "pro")
        self.assertEqual(pos2.statement, "x")
        self.assertEqual(len(pos2.evidence_anchors), 2)
        self.assertEqual(pos2.evidence_anchors[0].canonical_id, "c1")
        self.assertEqual(pos2.rebuttal_to_other, "r")


if __name__ == "__main__":
    sys.exit(run_tests(
        SpecificityTests, GroundednessTests, ResponsivenessTests,
        FalsifiabilityTests, DecideVerdictTests, ScorePositionTests,
        PromptTests, RenderBriefTests, PositionSerializationTests,
    ))

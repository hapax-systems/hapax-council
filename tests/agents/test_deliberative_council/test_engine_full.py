from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from agents.deliberative_council.engine import (
    _run_phase2,
    _run_phase3,
    _run_phase4,
    deliberate,
)
from agents.deliberative_council.models import (
    AdversarialExchange,
    ConvergenceStatus,
    CouncilConfig,
    CouncilInput,
    CouncilMode,
    EvidenceMatrix,
    EvidenceMatrixAxis,
    PhaseOneResult,
)
from agents.deliberative_council.rubrics import EpistemicQualityRubric

# These tests exercise the phase 2-5 convergence mechanics, not the quorum /
# family-diversity gate (which has dedicated pins in test_council_fail_loud.py).
# A 2-3 member panel is below the principled floor and would REFUSE before
# phase 2, so deliberate() tests pass a quorum-1 config to isolate convergence.
# cc-task cctv-council-perfect-health-faillloud-convergence.
_QUORUM_OFF = {"min_valid_members": 1, "min_valid_families": 1}


def _make_phase1_results(
    scores_by_model: dict[str, dict[str, int]],
) -> list[PhaseOneResult]:
    return [
        PhaseOneResult(
            model_alias=alias,
            scores=scores,
            rationale={k: f"rationale for {k}" for k in scores},
            research_findings=[f"{alias} found evidence"],
        )
        for alias, scores in scores_by_model.items()
    ]


class TestPhase2EvidenceMatrix:
    @pytest.mark.asyncio
    async def test_phase2_evidence_matrix_structure(self) -> None:
        phase1_results = _make_phase1_results(
            {
                "opus": {"claim_evidence_alignment": 1, "hedge_calibration": 4},
                "balanced": {"claim_evidence_alignment": 5, "hedge_calibration": 4},
            }
        )

        matrix_response = json.dumps(
            {
                "axes": {
                    "claim_evidence_alignment": {
                        "least_inconsistent_score": 3,
                        "summary": "Evidence splits between high and low",
                    }
                }
            }
        )

        async def _mock_call(member, prompt):
            return matrix_response, [], ""

        with patch("agents.deliberative_council.engine._call_member", side_effect=_mock_call):
            config = CouncilConfig(model_aliases=("opus", "balanced"))
            rubric = EpistemicQualityRubric()
            matrix = await _run_phase2(phase1_results, rubric, config, text="test")

        assert matrix is not None
        assert "claim_evidence_alignment" in matrix.axes
        assert matrix.axes["claim_evidence_alignment"].least_inconsistent_score == 3
        assert matrix.built_by == "opus"

    @pytest.mark.asyncio
    async def test_phase2_returns_none_when_all_converged(self) -> None:
        phase1_results = _make_phase1_results(
            {
                "opus": {"a": 4, "b": 3},
                "balanced": {"a": 4, "b": 3},
            }
        )

        async def _mock_call(member, prompt):
            raise RuntimeError("Should not be called when no axes are contested")

        with patch("agents.deliberative_council.engine._call_member", side_effect=_mock_call):
            config = CouncilConfig(model_aliases=("opus", "balanced"))
            rubric = EpistemicQualityRubric()
            matrix = await _run_phase2(phase1_results, rubric, config, text="test")

        assert matrix is None


class TestPhase3Adversarial:
    @pytest.mark.asyncio
    async def test_phase3_adversarial_targets_highest_vs_lowest(self) -> None:
        phase1_results = _make_phase1_results(
            {
                "opus": {"a": 5, "b": 3},
                "balanced": {"a": 1, "b": 3},
                "local-fast": {"a": 3, "b": 3},
            }
        )

        challenge_response = json.dumps(
            {"revised_score": 4, "response": "The low scorer missed key evidence."}
        )

        async def _mock_call(member, prompt):
            return challenge_response, [], ""

        evidence_matrix = EvidenceMatrix(
            axes={"a": EvidenceMatrixAxis(axis="a", least_inconsistent_score=3)},
            built_by="opus",
        )

        with patch("agents.deliberative_council.engine._call_member", side_effect=_mock_call):
            config = CouncilConfig(model_aliases=("opus", "balanced", "local-fast"))
            rubric = EpistemicQualityRubric()
            exchanges = await _run_phase3(
                phase1_results, evidence_matrix, rubric, config, text="test"
            )

        assert len(exchanges) == 1
        assert exchanges[0].axis == "a"
        assert exchanges[0].high_scorer == "opus"
        assert exchanges[0].high_score == 5
        assert exchanges[0].low_scorer == "balanced"
        assert exchanges[0].low_score == 1

    @pytest.mark.asyncio
    async def test_phase3_skips_converged_axes(self) -> None:
        phase1_results = _make_phase1_results(
            {
                "opus": {"a": 4, "b": 4},
                "balanced": {"a": 4, "b": 4},
            }
        )

        async def _mock_call(member, prompt):
            raise RuntimeError("Should not be called for converged axes")

        with patch("agents.deliberative_council.engine._call_member", side_effect=_mock_call):
            config = CouncilConfig(model_aliases=("opus", "balanced"))
            rubric = EpistemicQualityRubric()
            exchanges = await _run_phase3(phase1_results, None, rubric, config, text="test")

        assert len(exchanges) == 0


class TestPhase4Revision:
    @pytest.mark.asyncio
    async def test_phase4_private_revision(self) -> None:
        phase1_results = _make_phase1_results(
            {
                "opus": {"a": 5},
                "balanced": {"a": 1},
            }
        )

        evidence_matrix = EvidenceMatrix(
            axes={"a": EvidenceMatrixAxis(axis="a", least_inconsistent_score=3)},
            built_by="opus",
        )
        exchanges = [
            AdversarialExchange(
                axis="a",
                high_scorer="opus",
                high_score=5,
                low_scorer="balanced",
                low_score=1,
                challenge_text="test challenge",
                response_text="test response",
            )
        ]

        async def _mock_call(member, prompt):
            return (
                json.dumps(
                    {
                        "revised_scores": {"a": 3},
                        "revision_rationale": {"a": "adjusted after evidence"},
                        "changed_axes": ["a"],
                    }
                ),
                [],
                "",
            )

        with patch("agents.deliberative_council.engine._call_member", side_effect=_mock_call):
            config = CouncilConfig(model_aliases=("opus", "balanced"))
            rubric = EpistemicQualityRubric()
            revised = await _run_phase4(phase1_results, evidence_matrix, exchanges, rubric, config)

        assert len(revised) == 2
        assert all(r.scores["a"] == 3 for r in revised)

    @pytest.mark.asyncio
    async def test_phase4_noop_when_no_exchanges(self) -> None:
        phase1_results = _make_phase1_results(
            {
                "opus": {"a": 4},
                "balanced": {"a": 4},
            }
        )

        config = CouncilConfig(model_aliases=("opus", "balanced"))
        rubric = EpistemicQualityRubric()
        revised = await _run_phase4(phase1_results, None, [], rubric, config)

        assert revised is phase1_results

    @pytest.mark.asyncio
    async def test_phase4_falls_back_on_parse_failure(self) -> None:
        phase1_results = _make_phase1_results({"opus": {"a": 5}})
        exchanges = [
            AdversarialExchange(
                axis="a",
                high_scorer="opus",
                high_score=5,
                low_scorer="balanced",
                low_score=1,
                challenge_text="test",
                response_text="test",
            )
        ]

        async def _mock_call(member, prompt):
            return "not json", [], ""

        with patch("agents.deliberative_council.engine._call_member", side_effect=_mock_call):
            config = CouncilConfig(model_aliases=("opus",))
            rubric = EpistemicQualityRubric()
            revised = await _run_phase4(phase1_results, None, exchanges, rubric, config)

        assert len(revised) == 1
        assert revised[0].scores["a"] == 5


class TestPhase5Convergence:
    @pytest.mark.asyncio
    async def test_phase5_converged_output(self) -> None:
        divergent_p1 = _make_phase1_results(
            {"opus": {"a": 1}, "balanced": {"a": 5}, "local-fast": {"a": 3}}
        )
        converged_p4 = _make_phase1_results(
            {"opus": {"a": 4}, "balanced": {"a": 4}, "local-fast": {"a": 4}}
        )

        with (
            patch("agents.deliberative_council.engine.run_phase1", return_value=divergent_p1),
            patch("agents.deliberative_council.engine._run_phase2", return_value=None),
            patch("agents.deliberative_council.engine._run_phase3", return_value=[]),
            patch("agents.deliberative_council.engine._run_phase4", return_value=converged_p4),
        ):
            config = CouncilConfig(model_aliases=("opus", "balanced", "local-fast"), **_QUORUM_OFF)
            inp = CouncilInput(text="test", source_ref="ref.md")
            rubric = EpistemicQualityRubric()
            verdict = await deliberate(inp, CouncilMode.DISCONFIRMATION, rubric, config)

        assert verdict.convergence_status == ConvergenceStatus.CONVERGED
        assert verdict.scores["a"] == 4

    @pytest.mark.asyncio
    async def test_phase5_contested_output(self) -> None:
        divergent_p1 = _make_phase1_results(
            {"opus": {"a": 1}, "balanced": {"a": 5}, "local-fast": {"a": 3}}
        )
        # [2, 3, 4] → IQR = 2.0 → CONTESTED
        contested_p4 = _make_phase1_results(
            {"opus": {"a": 2}, "balanced": {"a": 3}, "local-fast": {"a": 4}}
        )

        with (
            patch("agents.deliberative_council.engine.run_phase1", return_value=divergent_p1),
            patch("agents.deliberative_council.engine._run_phase2", return_value=None),
            patch("agents.deliberative_council.engine._run_phase3", return_value=[]),
            patch("agents.deliberative_council.engine._run_phase4", return_value=contested_p4),
        ):
            config = CouncilConfig(model_aliases=("opus", "balanced", "local-fast"), **_QUORUM_OFF)
            inp = CouncilInput(text="test", source_ref="ref.md")
            rubric = EpistemicQualityRubric()
            verdict = await deliberate(inp, CouncilMode.DISCONFIRMATION, rubric, config)

        assert verdict.convergence_status == ConvergenceStatus.CONTESTED

    @pytest.mark.asyncio
    async def test_phase5_hung_output(self) -> None:
        divergent_p1 = _make_phase1_results(
            {"opus": {"a": 1}, "balanced": {"a": 5}, "local-fast": {"a": 3}}
        )
        # [1, 3, 5] → IQR = 4.0 → HUNG
        hung_p4 = _make_phase1_results(
            {"opus": {"a": 1}, "balanced": {"a": 3}, "local-fast": {"a": 5}}
        )

        with (
            patch("agents.deliberative_council.engine.run_phase1", return_value=divergent_p1),
            patch("agents.deliberative_council.engine._run_phase2", return_value=None),
            patch("agents.deliberative_council.engine._run_phase3", return_value=[]),
            patch("agents.deliberative_council.engine._run_phase4", return_value=hung_p4),
        ):
            config = CouncilConfig(model_aliases=("opus", "balanced", "local-fast"), **_QUORUM_OFF)
            inp = CouncilInput(text="test", source_ref="ref.md")
            rubric = EpistemicQualityRubric()
            verdict = await deliberate(inp, CouncilMode.DISCONFIRMATION, rubric, config)

        assert verdict.convergence_status == ConvergenceStatus.HUNG
        assert verdict.scores["a"] is None


class TestFullDeliberation:
    @pytest.mark.asyncio
    async def test_full_5phase_on_known_bad_record(self) -> None:
        phase1_results = [
            PhaseOneResult(
                model_alias="opus",
                scores={"claim_evidence_alignment": 1, "hedge_calibration": 1},
                rationale={
                    "claim_evidence_alignment": "no evidence",
                    "hedge_calibration": "false certainty",
                },
                research_findings=["No sources found"],
            ),
            PhaseOneResult(
                model_alias="balanced",
                scores={"claim_evidence_alignment": 4, "hedge_calibration": 3},
                rationale={
                    "claim_evidence_alignment": "weak evidence",
                    "hedge_calibration": "some hedging",
                },
                research_findings=["Claims unverifiable"],
            ),
        ]

        matrix_json = json.dumps(
            {
                "axes": {
                    "claim_evidence_alignment": {
                        "least_inconsistent_score": 1,
                        "summary": "No supporting evidence",
                    },
                    "hedge_calibration": {
                        "least_inconsistent_score": 1,
                        "summary": "False certainty",
                    },
                }
            }
        )

        revision_json = json.dumps(
            {
                "revised_scores": {"claim_evidence_alignment": 1, "hedge_calibration": 1},
                "revision_rationale": {
                    "claim_evidence_alignment": "confirmed: no evidence",
                    "hedge_calibration": "overconfident claims",
                },
                "changed_axes": ["hedge_calibration"],
            }
        )

        async def _mock_call(member, prompt):
            lower = prompt.lower()
            if "competing hypotheses" in lower:
                return matrix_json, [], ""
            if "adversarial" in lower:
                return json.dumps({"revised_score": 1, "response": "Confirmed low."}), [], ""
            if "revising" in lower:
                return revision_json, [], ""
            return "{}", [], ""

        with (
            patch("agents.deliberative_council.engine.run_phase1", return_value=phase1_results),
            patch("agents.deliberative_council.engine._call_member", side_effect=_mock_call),
        ):
            config = CouncilConfig(model_aliases=("opus", "balanced"), **_QUORUM_OFF)
            inp = CouncilInput(
                text="This system is production-ready and fully tested.",
                source_ref="suspicious-claim.md",
            )
            rubric = EpistemicQualityRubric()
            verdict = await deliberate(inp, CouncilMode.DISCONFIRMATION, rubric, config)

        for axis, score in verdict.scores.items():
            if score is not None:
                assert score <= 2, f"{axis} should be low but was {score}"

        assert verdict.receipt.get("shortcircuited") is False
        assert 5 in verdict.receipt.get("phases_completed", [])

    @pytest.mark.asyncio
    async def test_receipt_includes_all_phase_transcripts(self) -> None:
        divergent_p1 = _make_phase1_results({"opus": {"a": 1}, "balanced": {"a": 5}})

        evidence_matrix = EvidenceMatrix(
            axes={"a": EvidenceMatrixAxis(axis="a", least_inconsistent_score=3)},
            built_by="opus",
        )
        exchanges = [
            AdversarialExchange(
                axis="a",
                high_scorer="balanced",
                high_score=5,
                low_scorer="opus",
                low_score=1,
                challenge_text="test",
                response_text="test response",
            )
        ]
        revised_p4 = _make_phase1_results({"opus": {"a": 3}, "balanced": {"a": 3}})

        with (
            patch("agents.deliberative_council.engine.run_phase1", return_value=divergent_p1),
            patch("agents.deliberative_council.engine._run_phase2", return_value=evidence_matrix),
            patch("agents.deliberative_council.engine._run_phase3", return_value=exchanges),
            patch("agents.deliberative_council.engine._run_phase4", return_value=revised_p4),
        ):
            config = CouncilConfig(model_aliases=("opus", "balanced"), **_QUORUM_OFF)
            inp = CouncilInput(text="test", source_ref="ref.md")
            rubric = EpistemicQualityRubric()
            verdict = await deliberate(inp, CouncilMode.DISCONFIRMATION, rubric, config)

        receipt = verdict.receipt
        assert receipt["shortcircuited"] is False
        assert receipt["phases_completed"] == [1, 2, 3, 4, 5]
        assert "phase1_transcript" in receipt
        assert "phase2_transcript" in receipt
        assert receipt["phase2_transcript"]["built_by"] == "opus"
        assert "a" in receipt["phase2_transcript"]["contested_axes"]
        assert "phase3_transcript" in receipt
        assert len(receipt["phase3_transcript"]) == 1
        assert receipt["phase3_transcript"][0]["high_scorer"] == "balanced"
        assert "phase4_transcript" in receipt
        assert len(receipt["phase4_transcript"]) == 2
        assert "phase5_convergence" in receipt
        assert receipt["phase5_convergence"]["a"]["status"] == "converged"
        # AC #4: the FULL deliberation receipt (not just the short-circuit one)
        # must record served models + a ruler_substituted signal, so a silent
        # served-model swap is auditable on the normal convergence path too.
        assert receipt["served_models"] == [r.served_model for r in divergent_p1]
        assert isinstance(receipt["ruler_substituted"], bool)

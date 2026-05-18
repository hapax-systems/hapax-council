from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from agents.deliberative_council.engine import _parse_phase1_output, deliberate, run_phase1
from agents.deliberative_council.models import (
    ConvergenceStatus,
    CouncilConfig,
    CouncilInput,
    CouncilMode,
    PhaseOneResult,
)
from agents.deliberative_council.rubrics import EpistemicQualityRubric


class TestParsePhase1Output:
    def test_valid_json(self) -> None:
        raw = json.dumps(
            {
                "scores": {"claim_evidence_alignment": 4, "hedge_calibration": 3},
                "rationale": {"claim_evidence_alignment": "good"},
                "research_findings": ["checked file"],
            }
        )
        result = _parse_phase1_output("opus", raw)
        assert result.scores["claim_evidence_alignment"] == 4
        assert result.model_alias == "opus"

    def test_json_in_code_block(self) -> None:
        raw = (
            "Here is my evaluation:\n```json\n"
            + json.dumps(
                {
                    "scores": {"a": 3},
                    "rationale": {"a": "ok"},
                    "research_findings": [],
                }
            )
            + "\n```"
        )
        result = _parse_phase1_output("balanced", raw)
        assert result.scores["a"] == 3

    def test_invalid_json_graceful(self) -> None:
        result = _parse_phase1_output("local-fast", "not json at all")
        assert result.scores == {}
        assert result.model_alias == "local-fast"


class TestRunPhase1:
    @pytest.mark.asyncio
    async def test_returns_results_per_model(self) -> None:
        mock_output = json.dumps(
            {
                "scores": {"claim_evidence_alignment": 4},
                "rationale": {"claim_evidence_alignment": "good"},
                "research_findings": [],
            }
        )

        async def _mock_call(member, prompt):
            return mock_output, []

        with patch("agents.deliberative_council.engine._call_member", side_effect=_mock_call):
            config = CouncilConfig(model_aliases=("opus", "balanced"))
            inp = CouncilInput(text="test claim", source_ref="test.md")
            rubric = EpistemicQualityRubric()
            results = await run_phase1(inp, rubric, config)

        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_handles_model_failure(self) -> None:
        call_count = 0

        async def _mock_call(member, prompt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise TimeoutError("model timeout")
            return json.dumps(
                {
                    "scores": {"a": 3},
                    "rationale": {"a": "ok"},
                    "research_findings": [],
                }
            ), []

        with patch("agents.deliberative_council.engine._call_member", side_effect=_mock_call):
            config = CouncilConfig(model_aliases=("opus", "balanced"))
            inp = CouncilInput(text="test", source_ref="test.md")
            rubric = EpistemicQualityRubric()
            results = await run_phase1(inp, rubric, config)

        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_phase1_parallel_calls(self) -> None:
        call_log: list[str] = []

        async def _mock_call(member, prompt):
            call_log.append(prompt[:10])
            return json.dumps({"scores": {"a": 3}, "rationale": {}, "research_findings": []}), []

        with patch("agents.deliberative_council.engine._call_member", side_effect=_mock_call):
            config = CouncilConfig(model_aliases=("opus", "balanced", "local-fast"))
            inp = CouncilInput(text="test", source_ref="ref.md")
            rubric = EpistemicQualityRubric()
            results = await run_phase1(inp, rubric, config)

        assert len(results) == 3
        assert len(call_log) == 6  # investigate + score per model

    @pytest.mark.asyncio
    async def test_phase1_randomized_axis_order(self) -> None:
        from agents.deliberative_council.prompts import phase1_prompt

        rubric = EpistemicQualityRubric()
        prompt_seed0 = phase1_prompt(rubric, "text", "ref.md", seed=0)
        prompt_seed1 = phase1_prompt(rubric, "text", "ref.md", seed=1)

        assert prompt_seed0 != prompt_seed1

    @pytest.mark.asyncio
    async def test_shortcircuit_unanimous(self) -> None:
        unanimous_results = [
            PhaseOneResult(model_alias="opus", scores={"a": 4}, rationale={}, research_findings=[]),
            PhaseOneResult(
                model_alias="balanced", scores={"a": 4}, rationale={}, research_findings=[]
            ),
            PhaseOneResult(
                model_alias="local-fast", scores={"a": 4}, rationale={}, research_findings=[]
            ),
        ]

        with patch("agents.deliberative_council.engine.run_phase1", return_value=unanimous_results):
            config = CouncilConfig(model_aliases=("opus", "balanced", "local-fast"))
            inp = CouncilInput(text="test", source_ref="ref.md")
            rubric = EpistemicQualityRubric()
            verdict = await deliberate(inp, CouncilMode.DISCONFIRMATION, rubric, config)

        assert verdict.receipt.get("shortcircuited") is True
        assert verdict.convergence_status == ConvergenceStatus.CONVERGED

    @pytest.mark.asyncio
    async def test_shortcircuit_skips_when_iqr_high(self) -> None:
        high_iqr_results = [
            PhaseOneResult(model_alias="opus", scores={"a": 1}, rationale={}, research_findings=[]),
            PhaseOneResult(
                model_alias="balanced", scores={"a": 5}, rationale={}, research_findings=[]
            ),
        ]

        with (
            patch("agents.deliberative_council.engine.run_phase1", return_value=high_iqr_results),
            patch("agents.deliberative_council.engine._run_phase2", return_value=None) as p2,
            patch("agents.deliberative_council.engine._run_phase3", return_value=[]),
            patch("agents.deliberative_council.engine._run_phase4", return_value=None),
        ):
            config = CouncilConfig(model_aliases=("opus", "balanced"))
            inp = CouncilInput(text="test", source_ref="ref.md")
            rubric = EpistemicQualityRubric()
            verdict = await deliberate(inp, CouncilMode.DISCONFIRMATION, rubric, config)

        assert verdict.receipt.get("shortcircuited") is False
        p2.assert_called_once()

    @pytest.mark.asyncio
    async def test_phase1_handles_model_failure_gracefully(self) -> None:
        call_count = 0

        async def _mock_call(member, prompt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("network failure")
            return json.dumps({"scores": {"a": 3}, "rationale": {}, "research_findings": []}), []

        with patch("agents.deliberative_council.engine._call_member", side_effect=_mock_call):
            config = CouncilConfig(model_aliases=("opus", "balanced"))
            inp = CouncilInput(text="test", source_ref="ref.md")
            rubric = EpistemicQualityRubric()
            results = await run_phase1(inp, rubric, config)

        assert len(results) == 1
        assert results[0].model_alias == "balanced"

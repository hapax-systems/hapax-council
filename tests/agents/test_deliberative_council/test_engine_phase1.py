from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from agents.deliberative_council.engine import _parse_phase1_output, run_phase1
from agents.deliberative_council.models import CouncilConfig, CouncilInput
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

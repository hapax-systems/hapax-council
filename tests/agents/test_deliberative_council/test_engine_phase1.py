from __future__ import annotations

from unittest.mock import patch

import pytest
from pydantic_ai.messages import CachePoint

from agents.deliberative_council.engine import deliberate, run_phase1
from agents.deliberative_council.models import (
    ConvergenceStatus,
    CouncilConfig,
    CouncilInput,
    CouncilMode,
    Phase1Output,
    PhaseOneResult,
)
from agents.deliberative_council.rubrics import EpistemicQualityRubric

# Phase 1 scoring is now provider-enforced structured output: the engine calls
# ``_call_member(score_member, prompt, output_type=NativeOutput(Phase1Output), ...)``
# and expects a ``Phase1Output`` back (no permissive ``_parse_phase1_output``).
# The investigate (research) call sets no output_type and returns text. Mocks
# below mirror that: text for the investigate call, a Phase1Output for scoring.
# A panel below the quorum / family floor would REFUSE before phases 2-5, so the
# deliberate() tests here use a quorum-1 config to isolate the convergence
# mechanics (the quorum gate has its own pins in test_council_fail_loud.py).
# cc-task cctv-council-perfect-health-faillloud-convergence.

_QUORUM_OFF = {"min_valid_members": 1, "min_valid_families": 1}


def _phase1_mock(score: Phase1Output | Exception):
    async def _mock(member, prompt, *, output_type=None, usage_limits=None):
        if output_type is None:  # investigate (research) call
            return "researched the claim", [], ""
        if isinstance(score, Exception):
            raise score
        return score, [], ""

    return _mock


class TestRunPhase1:
    @pytest.mark.asyncio
    async def test_returns_results_per_model(self) -> None:
        mock = _phase1_mock(
            Phase1Output(scores={"claim_evidence_alignment": 4}, rationale={}, research_findings=[])
        )
        with patch("agents.deliberative_council.engine._call_member", side_effect=mock):
            config = CouncilConfig(model_aliases=("opus", "balanced"))
            inp = CouncilInput(text="test claim", source_ref="test.md")
            results = await run_phase1(inp, EpistemicQualityRubric(), config)

        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_handles_model_failure(self) -> None:
        # The structured scoring call raises for exactly one member; the other
        # emits a valid Phase1Output. Survivors-only, the failure excluded.
        score_calls = 0

        async def _mock_call(member, prompt, *, output_type=None, usage_limits=None):
            nonlocal score_calls
            if output_type is None:
                return "researched", [], ""
            score_calls += 1
            if score_calls == 1:
                raise TimeoutError("model timeout")
            return Phase1Output(scores={"a": 3}, rationale={}, research_findings=[]), [], ""

        with patch("agents.deliberative_council.engine._call_member", side_effect=_mock_call):
            config = CouncilConfig(model_aliases=("opus", "balanced"))
            inp = CouncilInput(text="test", source_ref="test.md")
            results = await run_phase1(inp, EpistemicQualityRubric(), config)

        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_phase1_two_calls_per_model(self) -> None:
        call_log: list[object] = []

        async def _mock_call(member, prompt, *, output_type=None, usage_limits=None):
            call_log.append(prompt)
            if output_type is None:
                return "researched", [], ""
            return Phase1Output(scores={"a": 3}, rationale={}, research_findings=[]), [], ""

        with patch("agents.deliberative_council.engine._call_member", side_effect=_mock_call):
            config = CouncilConfig(model_aliases=("opus", "balanced", "local-fast"))
            inp = CouncilInput(text="test", source_ref="ref.md")
            results = await run_phase1(inp, EpistemicQualityRubric(), config)

        assert len(results) == 3
        assert len(call_log) == 6  # investigate + structured score per model

    @pytest.mark.asyncio
    async def test_phase1_score_prompt_is_dynamic_only_cache_via_system_prompt(self) -> None:
        # R1b (cctv-prompt-caching-quality-neutral-20260607): the stable rubric
        # prefix (role + instructions + axes) moved into ``Agent(system_prompt=)``
        # so it sits at the conversation prefix for provider cache reuse across
        # every member call. The score USER message is therefore a plain string
        # carrying ONLY the per-input dynamic content — for ALL families. The
        # cache_control breakpoint is injected at the LiteLLM gateway for capable
        # families (R1), and the per-alias cache *policy* stays family-aware in
        # the verdict receipt (``cache_policy_for_alias``).
        from agents.deliberative_council.members import cache_policy_for_alias

        prompts: list[object] = []

        async def _mock_call(member, prompt, *, output_type=None, usage_limits=None):
            prompts.append(prompt)
            if output_type is None:
                return "researched", [], ""
            return Phase1Output(scores={"a": 3}, rationale={}, research_findings=[]), [], ""

        with patch("agents.deliberative_council.engine._call_member", side_effect=_mock_call):
            config = CouncilConfig(model_aliases=("opus", "local-fast"))
            inp = CouncilInput(text="test", source_ref="ref.md")
            await run_phase1(inp, EpistemicQualityRubric(), config)

        # Each _run_one runs investigate then score back-to-back (the mock never
        # suspends), so prompts == [opus_inv, opus_score, local_inv, local_score].
        opus_score_prompt = prompts[1]
        local_score_prompt = prompts[3]

        # No per-call CachePoint object any more: the score prompt is a plain
        # string of dynamic input only, identical in shape across families.
        for score_prompt in (opus_score_prompt, local_score_prompt):
            assert isinstance(score_prompt, str)
            assert "Your Prior Research Findings" in score_prompt
            assert "ref.md" in score_prompt
            # The stable rubric axes are NOT duplicated into the user message.
            assert "Rubric Axes" not in score_prompt

        # Family-aware cache policy is preserved for the receipt: the Anthropic
        # member advertises a provider cache breakpoint, the local one does not.
        assert cache_policy_for_alias("opus")["cache_control"] is True
        assert cache_policy_for_alias("local-fast")["cache_control"] is False

    @pytest.mark.asyncio
    async def test_phase1_randomized_axis_order(self) -> None:
        from agents.deliberative_council.prompts import phase1_prompt

        rubric = EpistemicQualityRubric()
        prompt_seed0 = phase1_prompt(rubric, "text", "ref.md", seed=0)
        prompt_seed1 = phase1_prompt(rubric, "text", "ref.md", seed=1)

        assert prompt_seed0 != prompt_seed1

    def test_phase1_prompt_parts_cache_stable_prefix_only(self) -> None:
        from agents.deliberative_council.prompts import phase1_prompt_parts

        rubric = EpistemicQualityRubric()
        prompt = phase1_prompt_parts(
            rubric,
            "dynamic claim text",
            "claim-source.md",
            seed=0,
            cache_ttl="5m",
        )

        assert not isinstance(prompt, str)
        assert isinstance(prompt[1], CachePoint)
        assert prompt[1].ttl == "5m"
        assert "Rubric Axes" in prompt[0]
        assert "dynamic claim text" not in prompt[0]
        assert "dynamic claim text" in prompt[2]
        assert "claim-source.md" in prompt[2]

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
            config = CouncilConfig(model_aliases=("opus", "balanced", "local-fast"), **_QUORUM_OFF)
            inp = CouncilInput(text="test", source_ref="ref.md")
            verdict = await deliberate(
                inp, CouncilMode.DISCONFIRMATION, EpistemicQualityRubric(), config
            )

        assert verdict.receipt.get("shortcircuited") is True
        assert verdict.convergence_status == ConvergenceStatus.CONVERGED
        assert verdict.receipt["cache_policy"]["opus"]["cache_control"] is True
        assert verdict.receipt["cache_policy"]["local-fast"]["cache_control"] is False
        # The health receipt is recorded even on the shortcircuit path.
        assert verdict.receipt["council_health"]["members_valid"] == 3

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
            config = CouncilConfig(model_aliases=("opus", "balanced"), **_QUORUM_OFF)
            inp = CouncilInput(text="test", source_ref="ref.md")
            verdict = await deliberate(
                inp, CouncilMode.DISCONFIRMATION, EpistemicQualityRubric(), config
            )

        assert verdict.receipt.get("shortcircuited") is False
        p2.assert_called_once()

    @pytest.mark.asyncio
    async def test_phase1_handles_model_failure_gracefully(self) -> None:
        score_calls = 0

        async def _mock_call(member, prompt, *, output_type=None, usage_limits=None):
            nonlocal score_calls
            if output_type is None:
                return "researched", [], ""
            score_calls += 1
            if score_calls == 1:
                raise RuntimeError("network failure")
            return Phase1Output(scores={"a": 3}, rationale={}, research_findings=[]), [], ""

        with patch("agents.deliberative_council.engine._call_member", side_effect=_mock_call):
            config = CouncilConfig(model_aliases=("opus", "balanced"))
            inp = CouncilInput(text="test", source_ref="ref.md")
            results = await run_phase1(inp, EpistemicQualityRubric(), config)

        assert len(results) == 1
        assert results[0].model_alias in {"opus", "balanced"}

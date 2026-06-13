"""Regression pins for deliberative-council member routing + degradation.

Context: cc-task ``segment-prep-council-model-alias-reliability-20260607``.

The GATE-1 segment-prep run (2026-06-07) reported the council degrading with
``Phase 1 failure for gemini-3-pro / mistral-large / balanced / web-research``.
Root cause analysis showed every council alias *already* resolves to a valid
LiteLLM ``:4000`` route (``gemini-3-pro`` -> ``gemini-pro`` since 2026-05-24),
so the live failures were transient infrastructure (proxy unavailability /
timeouts), not an alias bug. These tests pin two invariants going forward:

1. Every council member alias resolves to a served LiteLLM route, so a future
   edit that adds an alias without a matching route (-> HTTP 400 "Invalid
   model name" -> silent member drop) fails CI instead of production.
2. Phase-1 member failures are recorded transparently in the verdict receipt
   (``failed_members``) rather than silently dropped, so a degraded panel is
   visible to the downstream substance gate.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

from agents.deliberative_council.engine import deliberate, run_phase1
from agents.deliberative_council.models import (
    ConvergenceStatus,
    CouncilConfig,
    CouncilInput,
    CouncilMode,
    MemberFailure,
    Phase1Output,
)
from agents.deliberative_council.rubrics import EpistemicQualityRubric
from shared.config import MODELS

# Valid LiteLLM :4000 route names — the ``model_name`` entries served by the
# proxy. SSOT: ``~/llm-stack/litellm-config.yaml``. A council member whose
# resolved route is NOT served triggers LiteLLM HTTP 400 "Invalid model name",
# silently dropping that member from the panel.
VALID_LITELLM_ROUTES = frozenset(
    {
        "claude-sonnet-4-6",
        "claude-opus-4-8",
        "claude-opus-4-7",
        "claude-haiku",
        "balanced",
        "fast",
        "claude-sonnet",
        "claude-opus",
        "gemini-pro",
        "gemini-flash",
        "web-scout",
        "web-research",
        "web-reason",
        "web-deep",
        "mistral-large",
        "local-fast",
        "coding",
        "reasoning",
        "appendix-fast",
    }
)

_LITELLM_CONFIG = Path.home() / "llm-stack" / "litellm-config.yaml"
_MODEL_NAME_RE = re.compile(r"^\s*-?\s*model_name:\s*(\S+)", re.MULTILINE)


def _resolved_council_routes() -> dict[str, str]:
    """Map each configured council alias -> its resolved LiteLLM route name."""
    config = CouncilConfig()
    return {alias: MODELS.get(alias, alias) for alias in config.model_aliases}


class TestCouncilMemberRoutes:
    def test_every_council_alias_resolves_to_valid_route(self) -> None:
        offenders = {
            alias: route
            for alias, route in _resolved_council_routes().items()
            if route not in VALID_LITELLM_ROUTES
        }
        assert not offenders, (
            "Every deliberative-council member alias must resolve to a valid "
            f"LiteLLM :4000 route (SSOT: {_LITELLM_CONFIG}). These do not: "
            f"{offenders}. Add the alias to shared.config.MODELS pointing at a "
            "served route, or add the route to the proxy."
        )

    def test_gemini_member_resolves_to_served_gemini_route(self) -> None:
        # The exact drift flagged by GATE-1: the council's `gemini-3-pro`
        # alias must map to the served `gemini-pro` route, never pass through
        # to the unserved literal `gemini-3-pro`.
        assert MODELS.get("gemini-3-pro") == "gemini-pro"

    def test_council_routes_served_by_live_litellm_config(self) -> None:
        # When the LiteLLM config is on disk (operator machine), cross-check
        # that the council's resolved routes are actually served — catches a
        # MODELS value repointed to a renamed/retired route. Skipped in CI,
        # where the config is absent.
        if not _LITELLM_CONFIG.exists():
            import pytest

            pytest.skip(f"LiteLLM config not present: {_LITELLM_CONFIG}")
        served = set(_MODEL_NAME_RE.findall(_LITELLM_CONFIG.read_text(encoding="utf-8")))
        unserved = {
            alias: route
            for alias, route in _resolved_council_routes().items()
            if route not in served
        }
        assert not unserved, (
            f"Council routes not served by live LiteLLM config {_LITELLM_CONFIG}: {unserved}"
        )


class TestPhase1FailureTransparency:
    async def test_run_phase1_records_failures_into_out_param(self) -> None:
        # The structured scoring call (output_type set) raises for exactly one
        # member; the rest emit a valid Phase1Output. The failed member is
        # recorded and excluded — survivors-only, no fail-open, no retry.
        score_calls = 0

        async def _mock_call(member, prompt, *, output_type=None, usage_limits=None):
            nonlocal score_calls
            if output_type is None:  # the investigate (research) call
                return "researched the claim", []
            score_calls += 1
            if score_calls == 1:
                raise TimeoutError("simulated member timeout")
            return Phase1Output(scores={"a": 3}, rationale={"a": "ok"}, research_findings=[]), []

        failures: list[MemberFailure] = []
        with patch("agents.deliberative_council.engine._call_member", side_effect=_mock_call):
            config = CouncilConfig(model_aliases=("opus", "balanced"))
            inp = CouncilInput(text="t", source_ref="ref.md")
            results = await run_phase1(inp, EpistemicQualityRubric(), config, failures_out=failures)

        # Survivors-only behaviour preserved (no fail-open / no retry).
        assert len(results) == 1
        assert len(failures) == 1
        assert failures[0].model_alias in {"opus", "balanced"}
        assert "TimeoutError" in failures[0].reason

    async def test_run_phase1_without_out_param_is_unchanged(self) -> None:
        async def _mock_call(member, prompt, *, output_type=None, usage_limits=None):
            raise RuntimeError("boom")

        with patch("agents.deliberative_council.engine._call_member", side_effect=_mock_call):
            config = CouncilConfig(model_aliases=("opus",))
            inp = CouncilInput(text="t", source_ref="ref.md")
            results = await run_phase1(inp, EpistemicQualityRubric(), config)

        # No out-param supplied -> failures still dropped, no recording, no raise.
        assert results == []

    async def test_research_budget_hit_member_still_scores(self) -> None:
        # GRACEFUL research-cap handling (DASEIN re-rooting): a member that exhausts
        # the research budget (UsageLimitExceeded) is NOT discarded — it proceeds to
        # scoring with truncated research and survives into the panel. Discarding
        # over-grounders collapsed members_valid in the 2026-06-13 seg-prep incident.
        from pydantic_ai.exceptions import UsageLimitExceeded

        async def _mock_call(member, prompt, *, output_type=None, usage_limits=None):
            if output_type is None:  # research call — exhausts the budget
                raise UsageLimitExceeded("simulated research budget exhausted")
            return Phase1Output(scores={"a": 3}, rationale={"a": "ok"}, research_findings=[]), []

        failures: list[MemberFailure] = []
        with patch("agents.deliberative_council.engine._call_member", side_effect=_mock_call):
            config = CouncilConfig(model_aliases=("opus", "balanced"))
            inp = CouncilInput(text="t", source_ref="ref.md")
            results = await run_phase1(inp, EpistemicQualityRubric(), config, failures_out=failures)

        assert len(results) == 2  # both survive — research-cap is graceful, not a discard
        assert failures == []

    async def test_research_timeout_member_still_scores(self) -> None:
        # TimeoutError in the research phase is also graceful (scores anyway).
        async def _mock_call(member, prompt, *, output_type=None, usage_limits=None):
            if output_type is None:
                raise TimeoutError("simulated research timeout")
            return Phase1Output(scores={"a": 3}, rationale={"a": "ok"}, research_findings=[]), []

        failures: list[MemberFailure] = []
        with patch("agents.deliberative_council.engine._call_member", side_effect=_mock_call):
            config = CouncilConfig(model_aliases=("opus",))
            inp = CouncilInput(text="t", source_ref="ref.md")
            results = await run_phase1(inp, EpistemicQualityRubric(), config, failures_out=failures)

        assert len(results) == 1
        assert failures == []

    async def test_scoring_failure_still_discards(self) -> None:
        # The graceful path is research-ONLY; a SCORING failure still discards the
        # member (no fail-open) — the survivors-only invariant is preserved.
        async def _mock_call(member, prompt, *, output_type=None, usage_limits=None):
            if output_type is None:
                return "researched", []
            raise TimeoutError("scoring failed")

        failures: list[MemberFailure] = []
        with patch("agents.deliberative_council.engine._call_member", side_effect=_mock_call):
            config = CouncilConfig(model_aliases=("opus",))
            inp = CouncilInput(text="t", source_ref="ref.md")
            results = await run_phase1(inp, EpistemicQualityRubric(), config, failures_out=failures)

        assert results == []
        assert len(failures) == 1
        assert "TimeoutError" in failures[0].reason

    async def test_deliberate_receipt_names_failed_members(self) -> None:
        # Whole panel fails -> REFUSED verdict (typed "broke", NOT HUNG which
        # means genuine disagreement) whose receipt names every failure, so a
        # fully-degraded council is never reported as silent consensus.
        async def _mock_call(member, prompt, *, output_type=None, usage_limits=None):
            raise TimeoutError("litellm unavailable")

        with patch("agents.deliberative_council.engine._call_member", side_effect=_mock_call):
            config = CouncilConfig(model_aliases=("opus", "balanced", "gemini-3-pro"))
            inp = CouncilInput(text="t", source_ref="ref.md")
            verdict = await deliberate(
                inp, CouncilMode.DISCONFIRMATION, EpistemicQualityRubric(), config
            )

        assert verdict.convergence_status == ConvergenceStatus.REFUSED
        assert verdict.receipt["refusal_reason"] == "all_models_failed"
        failed = verdict.receipt.get("failed_members", [])
        assert {f["model_alias"] for f in failed} == {"opus", "balanced", "gemini-3-pro"}
        assert all("TimeoutError" in f["reason"] for f in failed)


class TestSegPrepGateUnblocks:
    """Pins for the 2026-06-13 seg-prep GATE-1 unblocks (task
    seg-prep-gate-code-unblocks-20260613). The live seg-prep journal
    (2026-06-11 23:39) proved healthy members need 9-11 research tool calls;
    the prior cap of 8 forced members_valid=1/6 -> 0 segments released."""

    def test_research_budget_covers_observed_member_need(self) -> None:
        from agents.deliberative_council.engine import _RESEARCH_LIMITS

        # Observed live maximum was 11 (mistral); the budget must clear it.
        assert _RESEARCH_LIMITS.tool_calls_limit >= 12, (
            "research tool_calls_limit must cover the observed 11-call member "
            "need + headroom (seg-prep GATE-1 blocker, 2026-06-11 journal)"
        )
        assert _RESEARCH_LIMITS.request_limit >= 8

    def test_appendix_fast_alias_resolves_to_served_route(self) -> None:
        # The appendix-served grounding route is in VALID_LITELLM_ROUTES; the
        # MODELS alias must exist so agents can select it explicitly rather
        # than only via the local-fast proxy fallback.
        assert MODELS.get("appendix-fast") == "appendix-fast"
        assert MODELS["appendix-fast"] in VALID_LITELLM_ROUTES

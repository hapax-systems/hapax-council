"""Degrade-to-available: council coherence must NOT refuse when cloud members fail
with provider-side errors (UsageLimitExceeded, ContentFilterError).

cc-task seg-prep-council-coherence-degrade-not-refuse-20260613.

Exit predicate: a test that injects ContentFilterError/UsageLimitExceeded for the
cloud aliases and asserts a non-refused release with members_valid >= 1 (the
resident Command-R always participates).
"""

from __future__ import annotations

from unittest.mock import patch

from agents.deliberative_council.engine import (
    PROVIDER_EXCUSED_REASONS,
    _assess_health,
    deliberate,
)
from agents.deliberative_council.models import (
    ConvergenceStatus,
    CouncilConfig,
    CouncilInput,
    CouncilMode,
    MemberFailure,
    PhaseOneResult,
)
from agents.deliberative_council.rubrics import EpistemicQualityRubric


def _result(alias: str, scores: dict[str, int]) -> PhaseOneResult:
    return PhaseOneResult(model_alias=alias, scores=scores, rationale={})


def _input() -> CouncilInput:
    return CouncilInput(text="test text", source_ref="test.md", source_context="ctx")


# ── _assess_health unit tests ─────────────────────────────────────────────────


class TestAssessHealthDegradation:
    """_assess_health must lower the effective quorum floor when members fail
    with provider-side (excused) errors."""

    FULL_PANEL = ("opus", "balanced", "gemini-3-pro", "local-fast", "web-research", "mistral-large")

    def test_four_excused_one_resident_surviving_is_not_below_quorum(self) -> None:
        """4 cloud members fail with ContentFilterError, only local-fast and
        web-research survive.  Effective floor drops from 4 to 1 (member) and
        4 to 1 (family).  2 survivors >= 1 → NOT below quorum."""
        config = CouncilConfig(model_aliases=self.FULL_PANEL)
        results = [
            _result("local-fast", {"a": 4}),
            _result("web-research", {"a": 3}),
        ]
        failed = [
            MemberFailure(model_alias="opus", reason="ContentFilterError"),
            MemberFailure(model_alias="balanced", reason="ContentFilterError"),
            MemberFailure(model_alias="gemini-3-pro", reason="UsageLimitExceeded"),
            MemberFailure(model_alias="mistral-large", reason="UsageLimitExceeded"),
        ]
        health = _assess_health(results, failed, config)
        assert health.below_quorum is False
        assert health.members_valid == 2
        assert health.excused_failures == 4
        # Effective floor should be max(1, 4-4) = 1.
        assert health.quorum_floor_members == 1
        assert health.quorum_floor_families == 1

    def test_only_resident_surviving_is_not_below_quorum(self) -> None:
        """ALL cloud members fail with provider errors.  Only the resident
        Command-R (local-fast) survives.  valid=1 >= effective floor 1 → OK."""
        config = CouncilConfig(model_aliases=self.FULL_PANEL)
        results = [_result("local-fast", {"a": 4})]
        failed = [
            MemberFailure(model_alias="opus", reason="ContentFilterError"),
            MemberFailure(model_alias="balanced", reason="ContentFilterError"),
            MemberFailure(model_alias="gemini-3-pro", reason="UsageLimitExceeded"),
            MemberFailure(model_alias="web-research", reason="RateLimitError"),
            MemberFailure(model_alias="mistral-large", reason="UsageLimitExceeded"),
        ]
        health = _assess_health(results, failed, config)
        assert health.below_quorum is False
        assert health.members_valid == 1
        assert health.excused_failures == 5

    def test_non_excused_failures_still_refuse(self) -> None:
        """Non-provider failures (TimeoutError, EmptyScores) are NOT excused
        and still count against the quorum floor."""
        config = CouncilConfig(model_aliases=self.FULL_PANEL)
        results = [_result("local-fast", {"a": 4})]
        failed = [
            MemberFailure(model_alias="opus", reason="TimeoutError"),
            MemberFailure(model_alias="balanced", reason="EmptyScores"),
            MemberFailure(model_alias="gemini-3-pro", reason="TimeoutError"),
            MemberFailure(model_alias="web-research", reason="ConnectionError"),
            MemberFailure(model_alias="mistral-large", reason="TimeoutError"),
        ]
        health = _assess_health(results, failed, config)
        # No excused failures → floor stays at 4/4. 1 valid < 4 → below quorum.
        assert health.below_quorum is True
        assert health.excused_failures == 0

    def test_mixed_excused_and_non_excused(self) -> None:
        """Mix of excused and non-excused failures.  Per-member floor drops by
        excused member count, but per-family excusal requires ALL of a family's
        failed members to be provider-excused."""
        config = CouncilConfig(model_aliases=self.FULL_PANEL)
        results = [
            _result("local-fast", {"a": 4}),
            _result("web-research", {"a": 3}),
        ]
        failed = [
            MemberFailure(model_alias="opus", reason="ContentFilterError"),  # excused member
            MemberFailure(model_alias="balanced", reason="TimeoutError"),  # NOT excused
            MemberFailure(
                model_alias="gemini-3-pro", reason="UsageLimitExceeded"
            ),  # excused member
            MemberFailure(model_alias="mistral-large", reason="EmptyScores"),  # NOT excused
        ]
        health = _assess_health(results, failed, config)
        # 2 excused MEMBERS → effective member floor = max(1, 4-2) = 2.
        # 2 valid >= 2 → OK on member count.
        assert health.excused_failures == 2
        assert health.quorum_floor_members == 2
        # BUT family-level excusal requires ALL of a family's failures to be
        # provider-excused.  anthropic: opus(provider)+balanced(timeout) → mixed → NOT
        # excused.  mistral: mistral-large(EmptyScores) → non-provider → NOT excused.
        # Only google is excused (gemini-3-pro all-provider).
        # families_valid = {cohere, perplexity} = 2.
        # effective family floor = max(1, 4-1) = 3.  2 < 3 → below quorum.
        assert health.quorum_floor_families == 3
        assert health.below_quorum is True

    def test_excused_family_not_double_counted_when_survivor_exists(self) -> None:
        """If one anthropic member (balanced) fails with ContentFilterError but
        the other (opus) survives, the anthropic family is NOT excused — it's
        already covered by the survivor."""
        config = CouncilConfig(model_aliases=self.FULL_PANEL)
        results = [
            _result("opus", {"a": 4}),
            _result("local-fast", {"a": 4}),
            _result("web-research", {"a": 3}),
            _result("mistral-large", {"a": 4}),
        ]
        failed = [
            MemberFailure(model_alias="balanced", reason="ContentFilterError"),  # excused
            MemberFailure(model_alias="gemini-3-pro", reason="UsageLimitExceeded"),  # excused
        ]
        health = _assess_health(results, failed, config)
        assert health.excused_failures == 2
        # anthropic is still covered by opus, so only google family is excused.
        # families_valid = {anthropic, cohere, perplexity, mistral} = 4
        # excused_family_count = {google} - {anthropic, cohere, perplexity, mistral} = {google} = 1
        # effective family floor = max(1, 4-1) = 3.  4 >= 3 → OK.
        assert health.families_valid == 4
        assert health.below_quorum is False

    def test_floor_never_drops_below_one(self) -> None:
        """Even with many excused failures, the floor never goes below 1."""
        config = CouncilConfig(
            model_aliases=("local-fast",),
            min_valid_members=1,
            min_valid_families=1,
        )
        results = []  # even resident failed!
        failed = [
            MemberFailure(model_alias="local-fast", reason="ContentFilterError"),
        ]
        health = _assess_health(results, failed, config)
        # Floor = max(1, 1-1) = 1.  0 valid < 1 → below quorum.
        assert health.quorum_floor_members == 1
        assert health.below_quorum is True

    def test_mixed_failure_family_is_not_excused(self) -> None:
        """A family with NO survivor whose failures are MIXED (one provider-excused,
        one real timeout) must NOT be excused — the real failure means the family
        degradation is genuine, not just a provider outage.

        Contrast with test_four_excused_one_resident_surviving_is_not_below_quorum
        where ALL of each absent family's failures are provider-excused.

        This is the critical fix from the review-team BLOCK on PR #4116:
        opus:ContentFilterError + balanced:TimeoutError → anthropic family is NOT
        excused → family floor stays at 4 → families_valid=3 < 4 → REFUSED."""
        config = CouncilConfig(model_aliases=self.FULL_PANEL)
        # 3 survivors from 3 families (google, cohere, perplexity).
        results = [
            _result("gemini-3-pro", {"a": 4}),
            _result("local-fast", {"a": 4}),
            _result("web-research", {"a": 3}),
        ]
        failed = [
            # Anthropic family: one excused, one NOT → family NOT excused.
            MemberFailure(model_alias="opus", reason="ContentFilterError"),
            MemberFailure(model_alias="balanced", reason="TimeoutError"),
            # Mistral family: all excused → family IS excused.
            MemberFailure(model_alias="mistral-large", reason="UsageLimitExceeded"),
        ]
        health = _assess_health(results, failed, config)
        # Per-member: 2 excused (opus + mistral-large), effective member floor = max(1, 4-2) = 2.
        # 3 valid >= 2 → OK on members.
        assert health.excused_failures == 2
        assert health.quorum_floor_members == 2
        # Per-family: only mistral is excused (all its failures are provider-side).
        # anthropic is NOT excused (balanced failed with TimeoutError, a real error).
        # families_valid = {google, cohere, perplexity} = 3.
        # effective family floor = max(1, 4-1) = 3.  3 >= 3 → just barely OK.
        assert health.families_valid == 3
        assert health.quorum_floor_families == 3
        assert health.below_quorum is False

    def test_mixed_failure_family_causes_refused_when_below_floor(self) -> None:
        """Same scenario as above but with fewer survivors: the non-excused
        anthropic family pushes families_valid below the effective floor → REFUSED.

        This proves the fix works end-to-end: without the fix, the anthropic
        family would be wrongly excused and the verdict would pass."""
        config = CouncilConfig(model_aliases=self.FULL_PANEL)
        # Only 2 survivors from 2 families (cohere, perplexity).
        results = [
            _result("local-fast", {"a": 4}),
            _result("web-research", {"a": 3}),
        ]
        failed = [
            # Anthropic: mixed → NOT excused.
            MemberFailure(model_alias="opus", reason="ContentFilterError"),
            MemberFailure(model_alias="balanced", reason="TimeoutError"),
            # Google: all provider → excused.
            MemberFailure(model_alias="gemini-3-pro", reason="UsageLimitExceeded"),
            # Mistral: all provider → excused.
            MemberFailure(model_alias="mistral-large", reason="ContentFilterError"),
        ]
        health = _assess_health(results, failed, config)
        # Per-member: 3 excused, effective member floor = max(1, 4-3) = 1. 2 >= 1 → OK.
        assert health.excused_failures == 3
        # Per-family: google + mistral excused (2), anthropic NOT excused.
        # families_valid = {cohere, perplexity} = 2.
        # effective family floor = max(1, 4-2) = 2.  2 >= 2 → OK on family too.
        assert health.families_valid == 2
        assert health.quorum_floor_families == 2
        assert health.below_quorum is False


# ── deliberate() integration tests ───────────────────────────────────────────


class TestDeliberateDegradeToAvailable:
    """deliberate() must produce a non-REFUSED verdict when cloud members fail
    with provider-side errors and the resident Command-R survives."""

    @staticmethod
    def _patch_phase1(results: list[PhaseOneResult], failed_aliases: list[tuple[str, str]]):
        async def _fake(inp, rubric, config, *, failures_out=None):  # noqa: ANN001
            if failures_out is not None:
                failures_out.extend(
                    MemberFailure(model_alias=a, reason=r) for a, r in failed_aliases
                )
            return results

        return patch("agents.deliberative_council.engine.run_phase1", side_effect=_fake)

    async def test_cloud_content_filter_resident_survives_not_refused(self) -> None:
        """Exit predicate: 2+ cloud members injected-failing with
        ContentFilterError/UsageLimitExceeded, resident (local-fast) survives,
        verdict is NOT refused."""
        results = [
            _result("local-fast", {"a": 4, "b": 3}),
            _result("web-research", {"a": 3, "b": 4}),
        ]
        cloud_failures = [
            ("opus", "UsageLimitExceeded"),
            ("balanced", "ContentFilterError"),
            ("gemini-3-pro", "UsageLimitExceeded"),
            ("mistral-large", "ContentFilterError"),
        ]
        with self._patch_phase1(results, cloud_failures):
            verdict = await deliberate(
                _input(), CouncilMode.DISCONFIRMATION, EpistemicQualityRubric()
            )
        assert verdict.convergence_status != ConvergenceStatus.REFUSED
        health = verdict.receipt["council_health"]
        assert health["members_valid"] >= 1
        assert health["excused_failures"] == 4
        assert health["below_quorum"] is False
        # Quality floor is NOT lowered — scores must still meet per-axis thresholds.
        assert verdict.scores  # non-empty scores

    async def test_all_cloud_fail_resident_only_not_refused(self) -> None:
        """Even if ALL cloud members fail with provider errors, the resident
        Command-R alone produces a non-refused verdict."""
        # Single-member panel will have min_axis_values=2 constraint, so we need
        # to use a config that lowers that for this extreme case.
        results = [_result("local-fast", {"a": 4, "b": 3})]
        cloud_failures = [
            ("opus", "UsageLimitExceeded"),
            ("balanced", "ContentFilterError"),
            ("gemini-3-pro", "UsageLimitExceeded"),
            ("web-research", "RateLimitError"),
            ("mistral-large", "ContentFilterError"),
        ]
        config = CouncilConfig(min_axis_values=1)  # allow single-member axis
        with self._patch_phase1(results, cloud_failures):
            verdict = await deliberate(
                _input(), CouncilMode.DISCONFIRMATION, EpistemicQualityRubric(), config
            )
        assert verdict.convergence_status != ConvergenceStatus.REFUSED
        assert verdict.receipt["council_health"]["members_valid"] == 1
        assert verdict.receipt["council_health"]["excused_failures"] == 5

    async def test_non_excused_failures_still_refuse_through_deliberate(self) -> None:
        """Non-provider failures must still REFUSE — the degrade-to-available
        only applies to provider-side errors."""
        results = [_result("local-fast", {"a": 4})]
        non_excused = [
            ("opus", "TimeoutError"),
            ("balanced", "EmptyScores"),
            ("gemini-3-pro", "TimeoutError"),
            ("web-research", "ConnectionError"),
            ("mistral-large", "TimeoutError"),
        ]
        with self._patch_phase1(results, non_excused):
            verdict = await deliberate(
                _input(), CouncilMode.DISCONFIRMATION, EpistemicQualityRubric()
            )
        assert verdict.convergence_status == ConvergenceStatus.REFUSED


# ── PROVIDER_EXCUSED_REASONS set coverage ─────────────────────────────────────


class TestProviderExcusedReasons:
    def test_expected_reasons_present(self) -> None:
        assert "UsageLimitExceeded" in PROVIDER_EXCUSED_REASONS
        assert "ContentFilterError" in PROVIDER_EXCUSED_REASONS
        assert "RateLimitError" in PROVIDER_EXCUSED_REASONS

    def test_timeout_is_not_excused(self) -> None:
        assert "TimeoutError" not in PROVIDER_EXCUSED_REASONS

    def test_empty_scores_is_not_excused(self) -> None:
        assert "EmptyScores" not in PROVIDER_EXCUSED_REASONS

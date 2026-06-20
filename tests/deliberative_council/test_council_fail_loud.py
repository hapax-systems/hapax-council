"""Fail-loud architecture pins for the deliberative council.

cc-task cctv-council-perfect-health-faillloud-convergence-20260607.

These pin the architectural contract change from "produce a verdict at all
costs" to "refuse LOUDLY when it cannot be trusted":

- a member that cannot emit a valid structured score is a recorded FAILURE,
  excluded from BOTH the numerator and the survivor count (never a phantom
  abstainer with empty scores);
- a lone surviving score on an axis is NOT auto-CONVERGED
  (``compute_iqr`` of a single value is 0.0 — that must not read as consensus);
- a panel below the principled quorum / family-diversity floor returns
  ConvergenceStatus.REFUSED, NEVER CONVERGED;
- a fully-failed panel returns REFUSED (typed "broke"), distinct from HUNG
  (typed "genuine disagreement");
- the disconfirmation consumer routes REFUSED / HUNG-with-empty-scores to
  degraded so council_disconfirmation_passed fails LOUD.

No shared fixtures (per task Step 4): each test builds its own inputs.
"""

from __future__ import annotations

from unittest.mock import patch

from agents.deliberative_council.aggregation import aggregate_scores
from agents.deliberative_council.engine import _assess_health, deliberate, run_phase1
from agents.deliberative_council.members import served_model_family
from agents.deliberative_council.models import (
    ConvergenceStatus,
    CouncilConfig,
    CouncilInput,
    CouncilMode,
    CouncilVerdict,
    MemberFailure,
    NarrativeVerdictStatus,
    Phase1Output,
    PhaseOneResult,
)
from agents.deliberative_council.rubrics import CoherenceRubric, EpistemicQualityRubric
from shared.segment_disconfirmation import apply_council_verdicts
from shared.segment_narrative_critique import _convert_to_narrative_verdict, _empty_verdict


def _result(alias: str, scores: dict[str, int]) -> PhaseOneResult:
    return PhaseOneResult(model_alias=alias, scores=scores, rationale={})


def _counting_mock(calls: dict[str, int], score_scores: dict[str, int]):
    """A _call_member side-effect that counts investigate (output_type=None) vs
    scoring (output_type set) calls, so the requires_research gate is observable."""

    async def _mock(member, prompt, *, output_type=None, usage_limits=None):
        if output_type is not None:
            calls["score"] = calls.get("score", 0) + 1
            return Phase1Output(scores=score_scores, rationale={}, research_findings=[]), [], ""
        calls["investigate"] = calls.get("investigate", 0) + 1
        return "researched the claim", [], ""

    return _mock


class TestRequiresResearchGating:
    """The ``requires_research`` flag gates the Phase-1 investigate pass. Judgment
    rubrics (CoherenceRubric, requires_research=False) must SKIP research and
    still score — proving there is no UnboundLocalError on the no-research path
    where ``research_member`` is never assigned (gemini-1/claude-1, PR #4133)."""

    async def test_judgment_rubric_skips_research_and_still_scores(self) -> None:
        calls: dict[str, int] = {}
        mock = _counting_mock(calls, {"opening_pressure": 5})
        with patch("agents.deliberative_council.engine._call_member", side_effect=mock):
            config = CouncilConfig(model_aliases=("opus",))
            results = await run_phase1(
                CouncilInput(text="a composed segment", source_ref="coherence:p1"),
                CoherenceRubric(),
                config,
            )
        assert calls.get("investigate", 0) == 0  # research pass SKIPPED
        assert calls.get("score", 0) == 1  # scoring still ran (no UnboundLocalError)
        assert len(results) == 1

    async def test_research_rubric_runs_investigate(self) -> None:
        calls: dict[str, int] = {}
        mock = _counting_mock(calls, {"epistemic_rigor": 4})
        with patch("agents.deliberative_council.engine._call_member", side_effect=mock):
            config = CouncilConfig(model_aliases=("opus",))
            results = await run_phase1(
                CouncilInput(text="a claim", source_ref="r.md"),
                EpistemicQualityRubric(),
                config,
            )
        assert calls.get("investigate", 0) == 1  # research pass RAN
        assert calls.get("score", 0) == 1
        assert len(results) == 1


def _scoring_mock(score_return):
    """Build a _call_member side-effect: investigate→text, scoring→score_return.

    ``score_return`` is either a Phase1Output to return for the scoring call or
    an Exception instance to raise.
    """

    async def _mock(member, prompt, *, output_type=None, usage_limits=None):
        if output_type is not None:  # the structured scoring call
            if isinstance(score_return, Exception):
                raise score_return
            return score_return, [], ""
        return "researched the claim", [], ""  # the investigate call

    return _mock


class TestAggregationCoverageQuorum:
    def test_lone_axis_score_is_not_auto_converged(self) -> None:
        # Only ONE member scored this axis. IQR of a single value is 0.0, which
        # previously read as CONVERGED — a lone survivor masquerading as consensus.
        agg = aggregate_scores([_result("opus", {"axis_a": 4})], min_values=2)
        assert agg["axis_a"].status == ConvergenceStatus.REFUSED
        assert agg["axis_a"].score is None

    def test_full_coverage_agreement_converges(self) -> None:
        results = [
            _result("opus", {"axis_a": 4}),
            _result("gemini-3-pro", {"axis_a": 4}),
            _result("local-fast", {"axis_a": 5}),
            _result("mistral-large", {"axis_a": 4}),
        ]
        agg = aggregate_scores(results, min_values=2)
        assert agg["axis_a"].status == ConvergenceStatus.CONVERGED
        assert agg["axis_a"].score == 4

    def test_below_coverage_axis_refused_even_when_values_agree(self) -> None:
        # Two members would agree, but the per-axis coverage floor is 3 here:
        # insufficient independent coverage to certify convergence.
        results = [_result("opus", {"axis_a": 4}), _result("gemini-3-pro", {"axis_a": 4})]
        agg = aggregate_scores(results, min_values=3)
        assert agg["axis_a"].status == ConvergenceStatus.REFUSED


class TestStructuredPhase1NoPhantom:
    async def test_empty_scores_is_recorded_failure_and_excluded(self) -> None:
        # Provider-enforced structure succeeds but yields NO usable scores. That
        # is a LOUD failure, never a phantom abstainer that shrinks the denominator.
        failures: list[MemberFailure] = []
        mock = _scoring_mock(Phase1Output(scores={}, rationale={}, research_findings=[]))
        with patch("agents.deliberative_council.engine._call_member", side_effect=mock):
            config = CouncilConfig(model_aliases=("opus",))
            results = await run_phase1(
                CouncilInput(text="t", source_ref="r.md"),
                EpistemicQualityRubric(),
                config,
                failures_out=failures,
            )
        assert results == []
        assert len(failures) == 1
        assert failures[0].model_alias == "opus"
        assert failures[0].reason == "EmptyScores"

    async def test_scoring_exception_is_recorded_failure_and_excluded(self) -> None:
        # The structured scoring call raises (e.g. timeout / validation with
        # retries=0). The member is recorded and excluded — never silently dropped.
        failures: list[MemberFailure] = []
        mock = _scoring_mock(TimeoutError("scoring timed out"))
        with patch("agents.deliberative_council.engine._call_member", side_effect=mock):
            config = CouncilConfig(model_aliases=("opus",))
            results = await run_phase1(
                CouncilInput(text="t", source_ref="r.md"),
                EpistemicQualityRubric(),
                config,
                failures_out=failures,
            )
        assert results == []
        assert len(failures) == 1
        assert failures[0].reason == "TimeoutError"

    async def test_valid_structured_scores_survive(self) -> None:
        failures: list[MemberFailure] = []
        mock = _scoring_mock(
            Phase1Output(scores={"axis_a": 4}, rationale={"axis_a": "ok"}, research_findings=["f"])
        )
        with patch("agents.deliberative_council.engine._call_member", side_effect=mock):
            config = CouncilConfig(model_aliases=("opus",))
            results = await run_phase1(
                CouncilInput(text="t", source_ref="r.md"),
                EpistemicQualityRubric(),
                config,
                failures_out=failures,
            )
        assert failures == []
        assert len(results) == 1
        assert results[0].scores == {"axis_a": 4}

    def test_phase1_output_rejects_out_of_range_scores(self) -> None:
        import pytest
        from pydantic import ValidationError

        Phase1Output(scores={"axis_a": 5})  # in range OK
        with pytest.raises(ValidationError):
            Phase1Output(scores={"axis_a": 6})
        with pytest.raises(ValidationError):
            Phase1Output(scores={"axis_a": 0})


class TestDeliberateQuorumGate:
    """deliberate() applies a principled quorum + family-diversity floor and
    types a broken panel as REFUSED (never CONVERGED / never silent HUNG)."""

    @staticmethod
    def _patch_phase1(results: list[PhaseOneResult], failed_aliases: list[str]):
        async def _fake(inp, rubric, config, *, failures_out=None):  # noqa: ANN001
            if failures_out is not None:
                failures_out.extend(
                    MemberFailure(model_alias=a, reason="TimeoutError") for a in failed_aliases
                )
            return results

        return patch("agents.deliberative_council.engine.run_phase1", side_effect=_fake)

    @staticmethod
    def _input() -> CouncilInput:
        return CouncilInput(text="t", source_ref="r.md", source_context="ctx")

    async def test_all_failed_panel_is_refused_not_hung(self) -> None:
        with self._patch_phase1(
            [],
            ["opus", "balanced", "gemini-3-pro", "local-fast", "web-research", "mistral-large"],
        ):
            verdict = await deliberate(
                self._input(), CouncilMode.DISCONFIRMATION, EpistemicQualityRubric()
            )
        assert verdict.convergence_status == ConvergenceStatus.REFUSED
        assert verdict.receipt["refusal_reason"] == "all_models_failed"
        assert verdict.receipt["council_health"]["members_valid"] == 0
        assert {f["model_alias"] for f in verdict.receipt["failed_members"]} == {
            "opus",
            "balanced",
            "gemini-3-pro",
            "local-fast",
            "web-research",
            "mistral-large",
        }

    async def test_below_family_floor_is_refused(self) -> None:
        # Two valid members, but BOTH are the anthropic family → families_valid=1.
        results = [
            _result("opus", {"a": 4}),
            _result("balanced", {"a": 4}),
        ]
        with self._patch_phase1(
            results, ["gemini-3-pro", "local-fast", "web-research", "mistral-large"]
        ):
            verdict = await deliberate(
                self._input(), CouncilMode.DISCONFIRMATION, EpistemicQualityRubric()
            )
        assert verdict.convergence_status == ConvergenceStatus.REFUSED
        health = verdict.receipt["council_health"]
        assert health["members_valid"] == 2
        assert health["families_valid"] == 1
        assert health["below_quorum"] is True

    async def test_healthy_panel_converges_and_records_health(self) -> None:
        results = [
            _result("opus", {"a": 4}),
            _result("gemini-3-pro", {"a": 4}),
            _result("local-fast", {"a": 4}),
            _result("web-research", {"a": 4}),
            _result("mistral-large", {"a": 4}),
        ]
        with self._patch_phase1(results, ["balanced"]):
            verdict = await deliberate(
                self._input(), CouncilMode.DISCONFIRMATION, EpistemicQualityRubric()
            )
        assert verdict.convergence_status == ConvergenceStatus.CONVERGED
        health = verdict.receipt["council_health"]
        assert health["members_valid"] == 5
        assert health["families_valid"] == 5
        assert health["below_quorum"] is False

    async def test_under_covered_axis_folds_overall_to_refused(self) -> None:
        # Panel passes the panel-level quorum (5 members / 5 families) but axis "b"
        # was scored by only ONE member — insufficient coverage → overall REFUSED,
        # never collapsed to CONVERGED by a fall-through else.
        results = [
            _result("opus", {"a": 4, "b": 3}),
            _result("gemini-3-pro", {"a": 4}),
            _result("local-fast", {"a": 4}),
            _result("web-research", {"a": 4}),
            _result("mistral-large", {"a": 4}),
        ]
        with self._patch_phase1(results, []):
            verdict = await deliberate(
                self._input(), CouncilMode.DISCONFIRMATION, EpistemicQualityRubric()
            )
        assert verdict.convergence_status == ConvergenceStatus.REFUSED


class TestDisconfirmationConsumerFailLoud:
    """apply_council_verdicts routes REFUSED and HUNG-with-empty-scores to
    degraded — closing the fail-open where a fully-timed-out panel (returned, not
    raised) fell to else->contested and reported council_disconfirmation_passed."""

    @staticmethod
    def _claim() -> CouncilInput:
        return CouncilInput(text="c", source_ref="s.md", metadata={"claim_id": "claim:1"})

    @staticmethod
    def _verdict(status: ConvergenceStatus, scores: dict[str, int | None]) -> CouncilVerdict:
        return CouncilVerdict(
            scores=scores,
            confidence_bands={},
            convergence_status=status,
            disagreement_log=[],
            research_findings=[],
            evidence_matrix=None,
            receipt={},
        )

    @staticmethod
    def _apply(verdict: CouncilVerdict) -> dict:
        return apply_council_verdicts(
            [(TestDisconfirmationConsumerFailLoud._claim(), verdict)],
            source_consequence_map=[],
            claim_map=[{"claim_id": "claim:1", "grounds": ["s.md"]}],
        )

    def test_hung_with_empty_scores_is_degraded_not_contested_pass(self) -> None:
        # All members timed out -> HUNG, scores={}, returned-not-raised, no
        # council_unavailable flag. This must degrade, never contested-pass.
        result = self._apply(self._verdict(ConvergenceStatus.HUNG, {}))
        assert result["council_disconfirmation_passed"] is False
        assert result["council_degraded"] is True
        assert "claim:1" in result["degraded_claims"]
        assert "claim:1" not in result["contested_claims"]

    def test_refused_panel_is_degraded(self) -> None:
        result = self._apply(self._verdict(ConvergenceStatus.REFUSED, {}))
        assert result["council_disconfirmation_passed"] is False
        assert result["council_degraded"] is True
        assert "claim:1" in result["degraded_claims"]

    def test_all_none_scores_is_degraded(self) -> None:
        result = self._apply(self._verdict(ConvergenceStatus.HUNG, {"a": None, "b": None}))
        assert result["council_degraded"] is True
        assert "claim:1" in result["degraded_claims"]

    def test_genuine_hung_with_real_scores_stays_contested(self) -> None:
        # Real disagreement (HUNG WITH scores) is NOT a panel failure — it stays
        # contested so genuine disagreement keeps its meaning.
        result = self._apply(self._verdict(ConvergenceStatus.HUNG, {"a": 4, "b": 2}))
        assert "claim:1" in result["contested_claims"]
        assert "claim:1" not in result["degraded_claims"]


class TestNarrativeCritiqueFailLoud:
    """The narrative critique must NOT fail-open to BROADCAST_READY when the
    council refused, broke, or was unavailable — even with a high mean score."""

    @staticmethod
    def _verdict(status: ConvergenceStatus, scores: dict[str, int | None]) -> CouncilVerdict:
        return CouncilVerdict(
            scores=scores,
            confidence_bands={},
            convergence_status=status,
            disagreement_log=[],
            research_findings=[],
            evidence_matrix=None,
            receipt={},
        )

    def test_refused_council_is_not_broadcast_ready(self) -> None:
        # High mean, but a REFUSED panel cannot certify broadcast readiness.
        verdict = self._verdict(
            ConvergenceStatus.REFUSED,
            {
                "focalization_integrity": 5,
                "information_gap_integrity": 5,
                "escalation_architecture": 5,
            },
        )
        nv = _convert_to_narrative_verdict(verdict, "prog:1")
        assert nv.verdict_status != NarrativeVerdictStatus.BROADCAST_READY

    def test_empty_scores_council_is_not_broadcast_ready(self) -> None:
        nv = _convert_to_narrative_verdict(self._verdict(ConvergenceStatus.HUNG, {}), "prog:1")
        assert nv.verdict_status != NarrativeVerdictStatus.BROADCAST_READY

    def test_unavailable_council_empty_verdict_is_not_broadcast_ready(self) -> None:
        nv = _empty_verdict("council_unavailable: boom")
        assert nv.verdict_status != NarrativeVerdictStatus.BROADCAST_READY
        assert nv.convergence_status == ConvergenceStatus.REFUSED

    def test_healthy_high_quality_panel_still_broadcast_ready(self) -> None:
        # Guardrail: the fail-loud change must NOT block a genuinely healthy,
        # high-quality CONVERGED panel from being BROADCAST_READY.
        verdict = self._verdict(
            ConvergenceStatus.CONVERGED,
            {
                "focalization_integrity": 4,
                "information_gap_integrity": 4,
                "escalation_architecture": 4,
                "promise_delivery_ratio": 4,
            },
        )
        nv = _convert_to_narrative_verdict(verdict, "prog:1")
        assert nv.verdict_status == NarrativeVerdictStatus.BROADCAST_READY


class TestModeConsumersFailClosedOnRefused:
    """The intake + disconfirmation MODE verdict derivations must fail CLOSED on a
    REFUSED panel — never SURVIVED / READY_TO_PLAN even if partial fold scores
    would clear the floor (the new REFUSED status must not fall through)."""

    def test_disconfirmation_refused_is_insufficient_evidence(self) -> None:
        from agents.deliberative_council.modes.disconfirmation import (
            DisconfirmationVerdict,
            derive_verdict,
        )

        verdict = CouncilVerdict(
            scores={"a": 5, "b": 5},  # all-high would otherwise read as SURVIVED
            confidence_bands={},
            convergence_status=ConvergenceStatus.REFUSED,
            disagreement_log=[],
            research_findings=[],
            evidence_matrix=None,
            receipt={},
        )
        assert derive_verdict(verdict) == DisconfirmationVerdict.INSUFFICIENT_EVIDENCE

    def test_intake_refused_is_needs_hardening(self) -> None:
        from agents.deliberative_council.modes.intake import IntakeVerdict, derive_verdict

        # all-high scores would otherwise read READY_TO_PLAN.
        verdict = derive_verdict({"a": 5, "b": 5}, ConvergenceStatus.REFUSED)
        assert verdict == IntakeVerdict.NEEDS_HARDENING


class TestCouncilDegradationMetric:
    def test_record_increments_or_noops(self) -> None:
        from agents.deliberative_council.metrics import (
            panel_degraded_value,
            record_panel_degraded,
        )

        before = panel_degraded_value("cohere", "coherence_unavailable")
        record_panel_degraded("cohere", "coherence_unavailable")
        after = panel_degraded_value("cohere", "coherence_unavailable")
        if before is None:
            # prometheus_client unavailable -> documented no-op contract.
            assert after is None
        else:
            assert after == before + 1.0


def _result_served(alias: str, served_model: str) -> PhaseOneResult:
    return PhaseOneResult(
        model_alias=alias, scores={"a": 4}, rationale={}, served_model=served_model
    )


class TestServedModelFamilyLabeling:
    """Family-diversity is counted by the SERVED model, so a gateway fail-over (e.g.
    balanced->gemini-pro on an Anthropic credit cap) cannot satisfy the quorum's diversity
    floor with a phantom-anthropic gemini. cc-task 20260619-eval-council-served-model-labeling."""

    def test_served_model_family_mapper(self) -> None:
        assert served_model_family("claude-sonnet-4-6") == "anthropic"
        assert served_model_family("gemini-3.1-pro-preview") == "google"
        assert served_model_family("command-r-08-2024-exl3-4.0bpw") == "cohere"
        assert served_model_family("compassverifier-7b") == "cohere"
        assert served_model_family("mistral-large-latest") == "mistral"
        assert served_model_family("sonar-pro") == "perplexity"
        # Cap-resilient diversity families admitted 2026-06-20 (cloud, no GPU conflict).
        assert served_model_family("deepseek/deepseek-chat-v3.1") == "deepseek"
        assert served_model_family("glm-5.2") == "zhipu"
        assert served_model_family("") == "unknown"
        assert served_model_family("some-unknown-model") == "unknown"

    def test_default_roster_seats_diversity_families(self) -> None:
        """The SCED ruler default roster seats deepseek + glm so it can hit
        family-quorum without anthropic (cap-resilient diversity)."""
        from agents.deliberative_council.models import CouncilConfig

        aliases = CouncilConfig().model_aliases
        assert "deepseek" in aliases
        assert "glm" in aliases
        # served families the roster can produce span >= 6 distinct families
        fams = {
            served_model_family(m)
            for m in (
                "claude-4.6-sonnet",
                "gemini-3.1-pro",
                "command-r-08-2024",
                "mistral-large",
                "sonar-pro",
                "deepseek/deepseek-chat",
                "glm-5.2",
            )
        }
        assert {
            "anthropic",
            "google",
            "cohere",
            "mistral",
            "perplexity",
            "deepseek",
            "zhipu",
        } <= fams

    def test_anthropic_cap_failover_counted_by_served_family_stays_valid(self) -> None:
        # Anthropic-only cap: both anthropic seats fall over to gemini. Honest count = 4 families
        # (google, cohere, perplexity, mistral) — still meets the floor, so the panel produces a
        # valid DEGRADED verdict on its surviving redundancy and flags the 2 substitutions.
        results = [
            _result_served("opus", "gemini-3.1-pro-preview"),  # anthropic -> google
            _result_served("balanced", "gemini-3.1-pro-preview"),  # anthropic -> google
            _result_served("gemini-3-pro", "gemini-3.1-pro-preview"),
            _result_served("local-fast", "command-r-08-2024-exl3-4.0bpw"),
            _result_served("web-research", "sonar-pro"),
            _result_served("mistral-large", "mistral-large-latest"),
        ]
        health = _assess_health(results, [], CouncilConfig())
        assert health.families_valid == 4  # honest (NOT the fooled 5)
        assert health.served_substitutions == 2
        assert health.below_quorum is False  # 4 >= 4 floor -> valid degraded verdict

    def test_served_collapse_below_floor_refuses_where_alias_count_is_fooled(self) -> None:
        # Anthropic AND perplexity seats fall over to gemini -> served families collapse to 3
        # (google, cohere, mistral) -> below the 4-family floor -> honest refusal. Counting by the
        # REQUESTED alias would see 5 families and wrongly pass a contaminated panel.
        results = [
            _result_served("opus", "gemini-3.1-pro-preview"),  # anthropic -> google
            _result_served("balanced", "gemini-3.1-pro-preview"),  # anthropic -> google
            _result_served("gemini-3-pro", "gemini-3.1-pro-preview"),
            _result_served("web-research", "gemini-3.1-pro-preview"),  # perplexity -> google
            _result_served("local-fast", "command-r-08-2024-exl3-4.0bpw"),
            _result_served("mistral-large", "mistral-large-latest"),
        ]
        health = _assess_health(results, [], CouncilConfig())
        assert health.families_valid == 3  # google, cohere, mistral
        assert health.served_substitutions == 3  # opus, balanced, web-research
        assert health.below_quorum is True  # honest refusal (alias-count would be a fooled 5)

    def test_served_unknown_falls_back_to_requested_family_no_regression(self) -> None:
        # All-up path: served_model empty/unrecognized -> count by the requested alias, identical
        # to pre-change behavior. 5 families, no substitutions, valid.
        results = [
            _result_served("opus", ""),
            _result_served("balanced", ""),
            _result_served("gemini-3-pro", ""),
            _result_served("local-fast", ""),
            _result_served("web-research", ""),
            _result_served("mistral-large", ""),
        ]
        health = _assess_health(results, [], CouncilConfig())
        assert health.families_valid == 5
        assert health.served_substitutions == 0
        assert health.below_quorum is False

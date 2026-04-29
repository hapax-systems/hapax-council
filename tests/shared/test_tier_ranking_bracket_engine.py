"""Tests for tier/ranking/bracket engine helper models."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import ValidationError

from shared.tier_ranking_bracket_engine import (
    BOUNDARY_SURFACES,
    CandidateRecord,
    CandidateSetRecord,
    CriterionRecord,
    FinalDecisionRecord,
    InconsistencyRecord,
    PairwiseComparisonRecord,
    RankRecord,
    TieBreakRecord,
    TierRecord,
    build_run_store_events,
    can_feed_grounding_evaluator,
    emit_deterministic_boundaries,
    final_decision_is_evidence_bound,
)


def _candidate(candidate_id: str) -> CandidateRecord:
    return CandidateRecord(
        candidate_id=candidate_id,
        label=candidate_id.replace("_", " "),
        source_refs=(f"source:{candidate_id}",),
        evidence_refs=(f"evidence:{candidate_id}",),
        evidence_envelope_refs=(f"ee:{candidate_id}",),
        wcs_refs=(f"wcs:{candidate_id}",),
        rights_refs=(f"rights:{candidate_id}",),
    )


def _criterion() -> CriterionRecord:
    return CriterionRecord(
        criterion_id="criterion_evidence_fit",
        label="Evidence fit",
        description="Matches declared evidence without expanding scope.",
        direction="higher_better",
        weight=1.0,
        scope_limit="Current evidence window only.",
        evidence_refs=("evidence:criterion",),
        wcs_refs=("wcs:criterion",),
    )


def _candidate_set() -> CandidateSetRecord:
    return CandidateSetRecord(
        candidate_set_id="candidate_set_a",
        title="Evidence-fit candidates",
        scope_limit="Two declared candidates only.",
        candidates=(_candidate("candidate_a"), _candidate("candidate_b")),
        criteria=(_criterion(),),
        evidence_refs=("evidence:candidate-set",),
        wcs_refs=("wcs:candidate-set",),
    )


def _comparison(outcome: str = "left") -> PairwiseComparisonRecord:
    return PairwiseComparisonRecord(
        comparison_id="comparison_a_b",
        left_candidate_id="candidate_a",
        right_candidate_id="candidate_b",
        criterion_ids=("criterion_evidence_fit",),
        outcome=outcome,
        rationale="Candidate A has stronger declared evidence for this bounded criterion.",
        evidence_refs=("evidence:comparison",),
        evidence_envelope_refs=("ee:comparison",),
        wcs_refs=("wcs:comparison",),
        uncertainty_ref="uncertainty:comparison",
    )


def _ranks() -> tuple[RankRecord, RankRecord]:
    return (
        RankRecord(
            rank_id="rank_candidate_a",
            candidate_id="candidate_a",
            ordinal=1,
            tier_id="tier_a",
            comparison_refs=("comparison_a_b",),
            criterion_ids=("criterion_evidence_fit",),
            evidence_refs=("evidence:rank-a",),
            evidence_envelope_refs=("ee:rank-a",),
            wcs_refs=("wcs:rank-a",),
            uncertainty_ref="uncertainty:comparison",
            score=0.82,
            scope_limit="Current evidence window only.",
        ),
        RankRecord(
            rank_id="rank_candidate_b",
            candidate_id="candidate_b",
            ordinal=2,
            tier_id="tier_b",
            comparison_refs=("comparison_a_b",),
            criterion_ids=("criterion_evidence_fit",),
            evidence_refs=("evidence:rank-b",),
            evidence_envelope_refs=("ee:rank-b",),
            wcs_refs=("wcs:rank-b",),
            uncertainty_ref="uncertainty:comparison",
            score=0.55,
            scope_limit="Current evidence window only.",
        ),
    )


def _tiers() -> tuple[TierRecord, TierRecord]:
    return (
        TierRecord(
            tier_id="tier_a",
            label="A",
            ordinal=1,
            rank_refs=("rank_candidate_a",),
            criteria_summary="Highest evidence fit in declared scope.",
            evidence_refs=("evidence:tier-a",),
            wcs_refs=("wcs:tier-a",),
            uncertainty_ref="uncertainty:comparison",
        ),
        TierRecord(
            tier_id="tier_b",
            label="B",
            ordinal=2,
            rank_refs=("rank_candidate_b",),
            criteria_summary="Lower evidence fit in declared scope.",
            evidence_refs=("evidence:tier-b",),
            wcs_refs=("wcs:tier-b",),
            uncertainty_ref="uncertainty:comparison",
        ),
    )


def _decision(**updates: object) -> FinalDecisionRecord:
    payload: dict[str, object] = {
        "decision_id": "trb_decision_a",
        "run_id": "run_a",
        "programme_id": "programme_a",
        "format_id": "tier_list",
        "selected_at": datetime(2026, 4, 29, 13, tzinfo=UTC),
        "candidate_set": _candidate_set(),
        "comparisons": (_comparison(),),
        "ranks": _ranks(),
        "tiers": _tiers(),
        "tie_breaks": (),
        "bracket": None,
        "reversals": (),
        "inconsistencies": (),
        "evaluator_refs": ("fge:decision-a",),
        "run_store_refs": ("run-store:run-a",),
        "evidence_refs": ("evidence:decision",),
        "evidence_envelope_refs": ("ee:decision",),
        "wcs_refs": ("wcs:decision",),
        "uncertainty_ref": "uncertainty:decision",
        "requested_public_private_mode": "dry_run",
        "public_private_mode": "dry_run",
        "output_eligibility": "dry_run",
        "public_claim_allowed": False,
    }
    payload.update(updates)
    return FinalDecisionRecord(**payload)


def test_final_decision_preserves_evidence_wcs_and_no_verdict_policy() -> None:
    decision = _decision()

    assert final_decision_is_evidence_bound(decision) is True
    assert can_feed_grounding_evaluator(decision) is True
    assert decision.no_expert_verdict_policy.criteria_bounded_outputs_only is True
    assert decision.no_expert_verdict_policy.authoritative_verdict_allowed is False
    assert decision.no_expert_verdict_policy.domain_truth_adjudication_allowed is False


def test_missing_evidence_refs_fail_validation() -> None:
    try:
        PairwiseComparisonRecord(
            comparison_id="comparison_missing_evidence",
            left_candidate_id="candidate_a",
            right_candidate_id="candidate_b",
            criterion_ids=("criterion_evidence_fit",),
            outcome="left",
            rationale="No evidence should fail closed.",
            evidence_refs=(),
            evidence_envelope_refs=("ee:comparison",),
            wcs_refs=("wcs:comparison",),
            uncertainty_ref="uncertainty:comparison",
        )
    except ValidationError as exc:
        assert "comparison.evidence_refs" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("comparison without evidence refs should fail validation")


def test_private_and_dry_run_decisions_cannot_allow_public_claims() -> None:
    for mode in ("private", "dry_run"):
        try:
            _decision(
                requested_public_private_mode=mode,
                public_private_mode=mode,
                output_eligibility=mode,
                public_claim_allowed=True,
            )
        except ValidationError as exc:
            assert "cannot allow public claims" in str(exc)
        else:  # pragma: no cover - assertion guard
            raise AssertionError("private/dry-run decision should not allow public claims")


def test_open_inconsistency_blocks_public_claims_and_evaluator_feed() -> None:
    inconsistency = InconsistencyRecord(
        inconsistency_id="inconsistency_missing_evidence",
        kind="missing_evidence",
        detected_at=datetime(2026, 4, 29, 13, tzinfo=UTC),
        comparison_refs=("comparison_a_b",),
        rank_refs=("rank_candidate_a",),
        criterion_ids=("criterion_evidence_fit",),
        explanation="Declared evidence is missing for this rank.",
        evidence_refs=("evidence:inconsistency",),
        wcs_refs=("wcs:inconsistency",),
        resolution_state="open",
    )

    dry_run = _decision(inconsistencies=(inconsistency,))
    assert can_feed_grounding_evaluator(dry_run) is False

    try:
        _decision(
            requested_public_private_mode="public_archive",
            public_private_mode="public_archive",
            output_eligibility="public_ready",
            public_claim_allowed=True,
            inconsistencies=(inconsistency,),
        )
    except ValidationError as exc:
        assert "open inconsistencies" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("public claim should be blocked by open inconsistency")


def test_tie_breaks_require_evidence_except_no_tiebreak() -> None:
    no_tie_break = TieBreakRecord(
        tie_break_id="tie_no_break",
        applies_to_rank_ids=("rank_candidate_a", "rank_candidate_b"),
        method="no_tiebreak",
        rationale="The declared evidence does not support a tie-break.",
        evidence_refs=(),
        evidence_envelope_refs=(),
        wcs_refs=(),
        uncertainty_ref="uncertainty:tie",
    )
    assert no_tie_break.method == "no_tiebreak"

    try:
        TieBreakRecord(
            tie_break_id="tie_missing_evidence",
            applies_to_rank_ids=("rank_candidate_a", "rank_candidate_b"),
            method="criterion_priority",
            rationale="Criterion priority needs evidence.",
            evidence_refs=(),
            evidence_envelope_refs=("ee:tie",),
            wcs_refs=("wcs:tie",),
            uncertainty_ref="uncertainty:tie",
        )
    except ValidationError as exc:
        assert "tie_break.evidence_refs" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("evidence-bearing tie-break without evidence should fail")


def test_deterministic_boundaries_cover_all_downstream_surfaces() -> None:
    decision = _decision()
    boundaries = emit_deterministic_boundaries(decision)

    assert tuple(boundary.sequence for boundary in boundaries) == (1, 2, 3, 4, 5)
    assert len(boundaries) == len(BOUNDARY_SURFACES)
    assert {boundary.duplicate_key.split(":")[-2] for boundary in boundaries} == set(
        BOUNDARY_SURFACES
    )
    assert boundaries[0].cuepoint_chapter_distinction == "vod_chapter_boundary"
    assert boundaries[1].cuepoint_chapter_distinction == "live_cuepoint_candidate"
    assert all(boundary.mapping_state == "internal_only" for boundary in boundaries)
    assert all("dry_run_mode" in boundary.unavailable_reasons for boundary in boundaries)

    public_decision = _decision(
        requested_public_private_mode="public_archive",
        public_private_mode="public_archive",
        output_eligibility="public_ready",
        public_claim_allowed=True,
    )
    public_boundaries = emit_deterministic_boundaries(
        public_decision,
        public_event_mapping_refs={
            "chapter": "rvpe:chapter",
            "shorts": "rvpe:shorts",
            "replay_card": "rvpe:replay-card",
            "dataset": "rvpe:dataset",
            "zine": "rvpe:zine",
        },
    )
    assert all(
        boundary.mapping_state == "research_vehicle_linked" for boundary in public_boundaries
    )
    assert all(not boundary.unavailable_reasons for boundary in public_boundaries)


def test_run_store_projection_uses_append_only_refs_without_public_payloads() -> None:
    decision = _decision()
    boundaries = emit_deterministic_boundaries(decision)
    events = build_run_store_events(
        decision,
        boundaries,
        occurred_at=datetime(2026, 4, 29, 13, tzinfo=UTC),
    )

    assert [event.sequence for event in events] == [0, 1, 2, 3]
    assert [event.event_type for event in events] == [
        "evidence_attached",
        "boundary_emitted",
        "claim_recorded",
        "conversion_held",
    ]
    assert all(event.append_only for event in events)
    assert events[1].boundary_event_refs == tuple(boundary.boundary_id for boundary in boundaries)
    assert events[2].payload_refs == (decision.decision_id,)
    assert all(event.evidence_refs == decision.evidence_refs for event in events)

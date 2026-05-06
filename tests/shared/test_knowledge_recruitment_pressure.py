from __future__ import annotations

import json

from shared.impingement import render_impingement_text
from shared.knowledge_recruitment_pressure import (
    AUTHORITY_BOUNDARIES,
    KNOWLEDGE_RECRUITMENT_CLAIM_TYPE,
    LOCAL_EVALUATOR_PROVIDER_ID,
    FreshnessNeed,
    KnowledgeGapSignal,
    KnowledgeStakes,
    build_knowledge_recruitment_decision,
    build_knowledge_recruitment_impingement,
)


def test_low_confidence_open_world_gap_requires_source_acquisition() -> None:
    signal = KnowledgeGapSignal(
        gap_id="segment-bit-form-001",
        domain="livestream_segment_quality",
        task_summary="Make a baseball arbitration explainer work as a live segment.",
        uncertainty_summary="Internal know-how is thin about what makes this format compelling.",
        internal_confidence=0.31,
        stakes=KnowledgeStakes.HIGH,
        freshness_need=FreshnessNeed.OPEN_WORLD,
        public_claim_intended=True,
    )

    decision = build_knowledge_recruitment_decision(signal)

    assert decision.should_recruit is True
    assert decision.claim_type == KNOWLEDGE_RECRUITMENT_CLAIM_TYPE
    assert decision.source_acquisition_required is True
    assert decision.source_acquiring_provider_ids
    assert LOCAL_EVALUATOR_PROVIDER_ID not in decision.source_acquiring_provider_ids
    assert LOCAL_EVALUATOR_PROVIDER_ID not in decision.source_conditioned_provider_ids
    assert "internal_confidence_below_threshold" in decision.trigger_reasons
    assert "open_world_freshness_needed" in decision.trigger_reasons
    assert decision.blockers == ()
    assert set(AUTHORITY_BOUNDARIES) == set(decision.authority_boundaries)


def test_supplied_evidence_gap_can_use_command_r_only_as_evaluator() -> None:
    signal = KnowledgeGapSignal(
        gap_id="local-layout-note-001",
        domain="layout_decision",
        task_summary="Evaluate whether a supplied layout note supports a segment move.",
        uncertainty_summary="The available note may be stale or incomplete.",
        internal_confidence=0.55,
        stakes=KnowledgeStakes.MEDIUM,
        freshness_need=FreshnessNeed.STABLE_BACKGROUND,
        existing_evidence_refs=("vault:layout-note",),
    )

    decision = build_knowledge_recruitment_decision(signal)

    assert decision.should_recruit is True
    assert decision.source_acquisition_required is False
    assert decision.local_evaluator_provider_id == LOCAL_EVALUATOR_PROVIDER_ID
    assert LOCAL_EVALUATOR_PROVIDER_ID in decision.source_conditioned_provider_ids
    assert LOCAL_EVALUATOR_PROVIDER_ID not in decision.source_acquiring_provider_ids
    assert "source_items" in decision.required_receipt_fields
    assert "raw_source_hashes" in decision.required_receipt_fields
    assert decision.blockers == ()


def test_private_payload_refs_count_as_supplied_evidence_for_local_evaluation() -> None:
    signal = KnowledgeGapSignal(
        gap_id="private-layout-note-001",
        domain="layout_decision",
        task_summary="Evaluate a private local note before changing a plan.",
        uncertainty_summary="The private note may be enough, but it has not been evaluated.",
        internal_confidence=0.45,
        stakes=KnowledgeStakes.MEDIUM,
        freshness_need=FreshnessNeed.STABLE_BACKGROUND,
        private_payload_refs=("vault-private:layout-note-excerpt",),
    )

    decision = build_knowledge_recruitment_decision(signal)
    impingement = build_knowledge_recruitment_impingement(signal, decision, now=100.0)

    assert decision.should_recruit is True
    assert decision.source_acquisition_required is False
    assert decision.local_evaluator_provider_id == LOCAL_EVALUATOR_PROVIDER_ID
    assert "vault-private:layout-note-excerpt" in impingement.content["evidence_refs"]
    assert impingement.content["private_payload_refs"] == ["vault-private:layout-note-excerpt"]
    assert impingement.context["egress_payload_refs"] == ["vault-private:layout-note-excerpt"]


def test_high_confidence_low_stakes_uncertainty_does_not_force_recruitment() -> None:
    signal = KnowledgeGapSignal(
        gap_id="routine-style-001",
        domain="private_brainstorm",
        task_summary="Choose wording for an internal note.",
        uncertainty_summary="There is ordinary residual uncertainty, but no known gap.",
        internal_confidence=0.91,
        stakes=KnowledgeStakes.LOW,
        freshness_need=FreshnessNeed.NONE,
        public_claim_intended=False,
    )

    decision = build_knowledge_recruitment_decision(signal)

    assert decision.should_recruit is False
    assert decision.trigger_reasons == ()
    assert decision.source_acquisition_required is False


def test_impingement_carries_blockers_for_fail_closed_consumers(tmp_path) -> None:
    registry = tmp_path / "grounding-providers.json"
    registry.write_text(json.dumps({"providers": []}), encoding="utf-8")
    signal = KnowledgeGapSignal(
        gap_id="blocked-source-route-001",
        domain="current_claim",
        task_summary="Check a current public claim.",
        uncertainty_summary="The claim needs fresh source acquisition.",
        internal_confidence=0.2,
        stakes=KnowledgeStakes.HIGH,
        freshness_need=FreshnessNeed.CURRENT,
        public_claim_intended=True,
    )

    decision = build_knowledge_recruitment_decision(signal, provider_registry_path=registry)
    impingement = build_knowledge_recruitment_impingement(signal, decision, now=100.0)

    assert decision.blockers == ("source_acquisition_route_missing",)
    assert impingement.content["action_tendency"] == "withhold"
    assert impingement.content["speech_act_candidate"] == "knowledge_recruitment_blocked"
    assert impingement.content["blockers"] == ["source_acquisition_route_missing"]
    assert impingement.context["blockers"] == ["source_acquisition_route_missing"]


def test_impingement_renders_guidance_as_prior_not_authority() -> None:
    signal = KnowledgeGapSignal(
        gap_id="maintenance-001",
        domain="system_maintenance",
        task_summary="Plan a recovery procedure for a service class.",
        uncertainty_summary="The local plan lacks enough operational detail.",
        internal_confidence=0.42,
        stakes=KnowledgeStakes.HIGH,
        freshness_need=FreshnessNeed.CURRENT,
        existing_evidence_refs=("runbook:partial",),
    )
    decision = build_knowledge_recruitment_decision(signal)

    impingement = build_knowledge_recruitment_impingement(signal, decision, now=100.0)

    assert impingement.source == "knowledge.recruitment"
    assert impingement.timestamp == 100.0
    assert impingement.strength > 0.8
    assert impingement.content["action_tendency"] == "route_attention"
    assert impingement.content["learning_policy"] == "recruited_guidance_is_prior_not_authority"
    assert "no_script_or_static_default_authority" in impingement.content["authority_boundaries"]
    assert "runbook:partial" in impingement.content["evidence_refs"]
    rendered = render_impingement_text(impingement)
    assert "knowledge gap" in rendered.lower()
    assert "evidence refs" in rendered

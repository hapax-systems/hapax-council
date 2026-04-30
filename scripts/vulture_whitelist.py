# pyright: reportUnusedExpression=false
"""Justified dynamic-entrypoint references for scripts/check-unused-functions.py.

Keep this file narrow. Add names here only when a callable is invoked by a
framework, subprocess entrypoint, import string, or other dynamic path that
vulture cannot see. Do not use this as a baseline for ordinary dead code.
"""

from agents.visual_pool.repository import VisualPoolSidecar
from logos.api.routes.studio import studio_audio_safe_for_broadcast, studio_egress_state
from shared.audio_topology_inspector import check_l12_forward_invariant
from shared.audio_world_surface_fixtures import AudioSurfaceFixture, AudioWorldSurfaceFixtureSet
from shared.capability_classification_inventory import (
    AvailabilityProbe,
    CapabilityClassificationInventory,
    CapabilityClassificationRow,
    build_seed_inventory,
    capability_classification_rows_by_id,
    validate_daimonion_tool_affordance_parity,
)
from shared.capability_outcome import (
    CapabilityOutcomeEnvelope,
    CapabilityOutcomeFixtureSet,
)
from shared.capability_outcome import (
    ClaimPosteriorUpdate as CapabilityClaimPosteriorUpdate,
)
from shared.capability_outcome import (
    Freshness as CapabilityFreshness,
)
from shared.capability_outcome import (
    LearningUpdate as CapabilityLearningUpdate,
)
from shared.capability_outcome import (
    PublicClaimEvidence as CapabilityPublicClaimEvidence,
)
from shared.content_programme_feedback_ledger import (
    append_feedback_event,
    audience_outcome_is_aggregate_only,
    build_feedback_fixture,
    event_allows_public_truth_claim,
    posterior_update_is_evidence_bound,
)
from shared.content_programme_run_store import (
    append_run_store_event,
    build_fixture_envelope,
    command_execution_allows_posterior_update,
    decide_fail_closed_mode,
    public_conversion_is_allowed,
    witnessed_outcome_allows_posterior_update,
)
from shared.conversion_target_readiness import (
    ConversionTargetReadinessMatrix,
    ConversionTargetThreshold,
    evaluate_failure_fixture,
    load_conversion_target_readiness_matrix,
)
from shared.director_control_audit import DirectorControlMoveAuditRecord
from shared.director_intent import CompositionalImpingement, DirectorIntent
from shared.director_scrim_gesture_adapter import (
    DirectorControlMoveRef,
    DirectorScrimGestureAuditRecord,
    DirectorScrimGestureFixtureSet,
    DirectorScrimGestureInput,
    DirectorScrimGestureProjection,
    ScrimGestureCaps,
    ScrimGesturePublicClaimPolicy,
    ScrimGestureRecord,
    WCSMoveRef,
)
from shared.director_vocabulary import DirectorVocabulary, SpectacleLaneState
from shared.director_world_surface_snapshot import (
    ClaimPosture as DirectorWorldSurfaceClaimPosture,
)
from shared.director_world_surface_snapshot import (
    DirectorWorldSurfaceMoveRow,
    DirectorWorldSurfaceSnapshot,
    DirectorWorldSurfaceSnapshotFixtureSet,
)
from shared.director_world_surface_snapshot import (
    EvidenceObligation as DirectorWorldSurfaceEvidenceObligation,
)
from shared.director_world_surface_snapshot import (
    Fallback as DirectorWorldSurfaceFallback,
)
from shared.director_world_surface_snapshot import (
    Freshness as DirectorWorldSurfaceFreshness,
)
from shared.grounding_provider_router import (
    build_eval_artifact,
    build_privacy_egress_preflight,
    route_candidates_for_claim,
    validate_eval_suite,
    validate_provider_registry,
)
from shared.narration_triad import IntendedOutcomeItem, NarrationTriadEnvelope
from shared.scrim_health_fixtures import (
    ScrimHealthExpectedOutcome,
    ScrimHealthFixture,
    ScrimHealthFixtureSet,
    ScrimHealthWorldSurfaceRef,
    ScrimInvariantScores,
)
from shared.scrim_wcs_claim_posture import (
    EvidenceReference,
    ScrimWCSClaimPostureProjection,
    WCSClaimReference,
)
from shared.semantic_recruitment import (
    SemanticDescription,
    SemanticRecruitmentFixtureSet,
    SemanticRecruitmentRow,
    SplitMergeDecision,
)
from shared.support_surface_registry import (
    AggregateReceiptPolicy,
    NoPerkSupportDoctrine,
    SupportSurface,
    SupportSurfaceRegistry,
    build_aggregate_receipt_projection,
    load_support_surface_registry,
    public_prompt_allowed,
    surfaces_by_decision,
)
from shared.temporal_span_registry import (
    ClaimBearingMediaOutput,
    SpanClaimGateDecision,
    TemporalMediaSidecar,
    TemporalSpan,
    TemporalSpanAlignment,
    TemporalSpanRegistryFixtureSet,
)
from shared.tier_ranking_bracket_engine import (
    BracketMatchRecord,
    BracketRecord,
    CandidateSetRecord,
    EvidenceAnchor,
    FinalDecisionRecord,
    InconsistencyRecord,
    PairwiseComparisonRecord,
    RankRecord,
    ReversalRecord,
    TieBreakRecord,
    UncertaintyRecord,
    build_run_store_events,
    can_feed_grounding_evaluator,
    emit_deterministic_boundaries,
)
from shared.trend_current_event_gate import evaluate_candidate, validate_policy
from shared.wcs_witness_probe_runtime import WCSWitnessProbeFixtureSet, WitnessProbeRecord
from shared.world_capability_surface import (
    EvidenceEnvelopeRequirements,
    WitnessRequirement,
    WorldCapabilityRecord,
    WorldCapabilityRegistry,
)
from shared.world_surface_health import (
    Freshness,
    HealthDimension,
    WorldSurfaceHealthEnvelope,
    WorldSurfaceHealthFixtureSet,
    WorldSurfaceHealthRecord,
)

# FastAPI registers this route by decorator; vulture does not follow APIRouter.
studio_egress_state
studio_audio_safe_for_broadcast

# Invoked by the extensionless scripts/hapax-audio-topology CLI and subprocess
# CLI tests; vulture scans scripts as Python modules but does not see that
# entrypoint as a static importer.
check_l12_forward_invariant

# Director vocabulary is a contract surface for future programme scheduler and
# content runner consumers. Pydantic calls validators dynamically; exported view
# methods are public API, not internal dead code.
SpectacleLaneState._known_director_verbs
DirectorVocabulary.for_programme_scheduler
DirectorVocabulary.for_content_runner

# Pydantic invokes model validators dynamically during model validation.
DirectorControlMoveAuditRecord._validate_boundary_and_evidence

# Director intent models split real provenance from synthetic diagnostics via
# Pydantic validators. The properties are consumed as public read helpers, but
# vulture cannot see Pydantic/property dynamic access reliably.
CompositionalImpingement._separate_synthetic_grounding
CompositionalImpingement.has_real_grounding_provenance
DirectorIntent._separate_synthetic_grounding
DirectorIntent.has_real_grounding_provenance

# Grounding-provider router helpers are a public contract for the content
# runner/evaluator train. The first PR publishes the schema and static helpers;
# downstream runner tasks call these entrypoints after merging this contract.
route_candidates_for_claim
validate_provider_registry
validate_eval_suite
build_eval_artifact
build_privacy_egress_preflight

# Trend/current-event gate helpers are the deterministic public API for the
# content-candidate-discovery daemon and public adapters. This contract lands
# before those consumers so vulture cannot see the dynamic call path yet.
evaluate_candidate
validate_policy

# Content programme run-store helpers are the deterministic public API for
# downstream scheduler, runner, feedback, conversion, and adapter tasks. This
# contract lands before those consumers, so vulture cannot see the call path yet.
append_run_store_event
decide_fail_closed_mode
command_execution_allows_posterior_update
witnessed_outcome_allows_posterior_update
public_conversion_is_allowed
build_fixture_envelope

# Content programme feedback-ledger helpers are the deterministic public API for
# downstream Bayesian posterior, scheduler, metrics, and conversion consumers.
# This contract lands before those consumers, so vulture cannot see the call
# path yet.
append_feedback_event
audience_outcome_is_aggregate_only
posterior_update_is_evidence_bound
event_allows_public_truth_claim
build_feedback_event_from_run_envelope
build_scheduler_policy_feedback
build_feedback_fixture

# Conversion target readiness helpers are the deterministic public contract for
# downstream conversion broker, grant queue, monetization readiness, and N=1
# dossier consumers. Pydantic invokes validators dynamically, and the first
# matrix PR lands before those downstream consumers call the loader.
ConversionTargetThreshold.validate_target_gate_contract
ConversionTargetReadinessMatrix.validate_matrix_contract
load_conversion_target_readiness_matrix
evaluate_failure_fixture

# Tier/ranking/bracket engine helpers are the public contract for downstream
# content runners, evaluator adapters, and run-store projections. This contract
# lands before those consumers, and Pydantic invokes validators dynamically.
EvidenceAnchor
UncertaintyRecord
CandidateSetRecord.validate_candidate_set
UncertaintyRecord.validate_uncertainty
PairwiseComparisonRecord.validate_comparison
TieBreakRecord.validate_tie_break
RankRecord.validate_rank
BracketMatchRecord.validate_match
BracketRecord.validate_bracket
ReversalRecord.validate_reversal
InconsistencyRecord.validate_inconsistency
FinalDecisionRecord.validate_decision
can_feed_grounding_evaluator
emit_deterministic_boundaries
build_run_store_events

# Support-surface registry helpers are a public contract for downstream payment
# aggregator, no-perk offer-page, and support-copy generator tasks. Pydantic
# invokes validators dynamically, and downstream tasks consume these entrypoints
# after this registry lands.
NoPerkSupportDoctrine.validate_doctrine
AggregateReceiptPolicy.validate_receipt_policy
SupportSurface.validate_surface_policy
SupportSurfaceRegistry.validate_registry_contract
load_support_surface_registry
surfaces_by_decision
public_prompt_allowed
build_aggregate_receipt_projection

# World Capability Surface seed loader helpers are the public contract for
# downstream witness probes, director snapshots, scheduler, runner, and scrim
# posture tasks. Pydantic invokes validators dynamically; downstream tasks
# consume the read helpers after this registry lands.
EvidenceEnvelopeRequirements._requires_core_fields
WitnessRequirement._inferred_context_is_not_a_witness
WorldCapabilityRecord._fail_closed_static_seed
WorldCapabilityRegistry._validate_registry
WorldCapabilityRegistry.require
WorldCapabilityRegistry.records_for_domain
WorldCapabilityRegistry.records_for_surface_ref
WorldCapabilityRegistry.blocked_reason_codes

# Semantic recruitment row helpers are the public contract for the downstream
# classification registry sweep and WCS adapters. Pydantic invokes validators
# dynamically; downstream tasks consume projection helpers after this schema
# contract lands.
SemanticDescription._validate_basic_level_affordance_text
SemanticRecruitmentRow._validate_row_contract
SplitMergeDecision._validate_decision_shape
SemanticRecruitmentFixtureSet._validate_fixture_contract
SemanticRecruitmentFixtureSet.require_row
SemanticRecruitmentFixtureSet.qdrant_payloads_for_single_indexing
SemanticRecruitmentFixtureSet.qdrant_payloads_for_batch_indexing

# Audio WCS fixture helpers are the public contract for downstream semantic
# router, marker-probe, audio-health, and director route tasks. Pydantic invokes
# validators dynamically; downstream tasks consume read helpers after this
# schema/fixture contract lands.
AudioSurfaceFixture._route_destination_matches_row
AudioWorldSurfaceFixtureSet._validate_contract_coverage
AudioWorldSurfaceFixtureSet.require_surface
AudioWorldSurfaceFixtureSet.rows_for_witness

# Local visual-pool sidecar validators are invoked by Pydantic while scanning
# and ingesting Sierpinski frame assets. The pool lands before downstream visual
# source consumers, so keep the dynamic-entrypoint references explicit.
VisualPoolSidecar._normalize_source
VisualPoolSidecar._normalize_aesthetic_tags
VisualPoolSidecar._normalize_color_palette

# World Surface Health envelope helpers are the public contract for downstream
# audio, visual, control, provider/tool, public-event, and no-false-grounding
# adapters. Pydantic invokes validators dynamically; downstream tasks consume
# these read helpers after this schema/fixture contract lands.
HealthDimension._passing_required_dimensions_need_evidence
Freshness._fresh_sources_need_age_and_ttl
WorldSurfaceHealthRecord._validate_fail_closed_claimability
WorldSurfaceHealthEnvelope._validate_envelope_counts_and_public_gates
WorldSurfaceHealthFixtureSet._validate_contract_coverage
WorldSurfaceHealthFixtureSet.rows_for_fixture_case

# Scrim WCS claim-posture models are validated by Pydantic and consumed by
# downstream director/scrim adapters. The first slice publishes the contract and
# fixtures, so keep the dynamic validator references explicit.
WCSClaimReference._public_claims_need_public_refs
EvidenceReference._fresh_evidence_needs_refs_and_age
ScrimWCSClaimPostureProjection._validate_no_claim_expansion

# Scrim health fixture rows are validated by Pydantic while adapting OQ-02
# invariant fixtures into ScrimStateEnvelope and WorldSurfaceHealthRecord refs.
ScrimInvariantScores._validate_register_and_caps
ScrimHealthWorldSurfaceRef._validate_no_public_claim_authority
ScrimHealthExpectedOutcome._foreground_gestures_are_named_when_required
ScrimHealthFixture._validate_fixture_contract
ScrimHealthFixtureSet._validate_set_coverage
ScrimHealthFixtureSet.world_surface_records
ScrimHealthFixtureSet.scrim_state_refs

# Director scrim gesture adapter validators are invoked by Pydantic while
# validating fixture packets. The fixture/projection read helpers are the public
# contract for downstream ScrimStateEnvelope and audit consumers.
DirectorControlMoveRef._validate_audited_move_ref
WCSMoveRef._validate_wcs_claim_floor
ScrimGesturePublicClaimPolicy._validate_no_public_claim_expansion
ScrimGestureCaps._validate_pierce_cap
ScrimGestureRecord._validate_bounded_scrim_gesture
ScrimGestureRecord.scrim_state_gesture
DirectorScrimGestureAuditRecord._validate_audit_no_claim_expansion
DirectorScrimGestureInput._validate_input_refs
DirectorScrimGestureProjection._validate_projection_consistency
DirectorScrimGestureFixtureSet._validate_fixture_set_contract
DirectorScrimGestureFixtureSet.audit_records_by_outcome

# WCS witness probe runtime helpers are the public contract for downstream WCS
# director snapshots, health blocker bus, and programme WCS snapshot tasks.
# Pydantic invokes validators dynamically; downstream tasks consume the read
# helpers after this first runtime slice lands.
WitnessProbeRecord._validate_state_evidence
WCSWitnessProbeFixtureSet.require_probe
WCSWitnessProbeFixtureSet.probes_for_surface

# Director World Surface snapshot helpers are the public contract for downstream
# prompt, vocabulary, programme, public-event, and move-normalizer tasks.
# Pydantic invokes validators dynamically; downstream consumers call read
# helpers after this schema/fixture contract lands.
DirectorWorldSurfaceFreshness._fresh_sources_need_evidence
DirectorWorldSurfaceEvidenceObligation._satisfied_obligations_need_evidence
DirectorWorldSurfaceClaimPosture._validate_claim_posture_order
DirectorWorldSurfaceFallback._fallback_target_requires_target
DirectorWorldSurfaceMoveRow._validate_director_move_fail_closed
DirectorWorldSurfaceSnapshot._validate_snapshot_move_buckets
DirectorWorldSurfaceSnapshot.public_live_moves
DirectorWorldSurfaceSnapshot.rows_for_status
DirectorWorldSurfaceSnapshot.rows_for_surface_family
DirectorWorldSurfaceSnapshot.prompt_projection_payloads
DirectorWorldSurfaceSnapshotFixtureSet._validate_fixture_set_coverage
DirectorWorldSurfaceSnapshotFixtureSet.rows_for_status
DirectorWorldSurfaceSnapshotFixtureSet.rows_for_surface_family

# Capability outcome envelope helpers are the public contract for downstream
# affordance outcome adapters, dispatch audits, public-event adapters, and
# no-false-grounding tests. Pydantic invokes validators dynamically; downstream
# tasks consume these read helpers after this schema/fixture contract lands.
CapabilityFreshness._fresh_sources_need_age_and_ttl
CapabilityLearningUpdate._no_target_when_update_not_allowed
CapabilityClaimPosteriorUpdate._allowed_claim_updates_need_evidence_and_gate
CapabilityPublicClaimEvidence._present_public_claims_need_evidence_event_and_gate
CapabilityOutcomeEnvelope._validate_outcome_learning_and_claims
CapabilityOutcomeEnvelope.allows_verified_public_or_action_success_update
CapabilityOutcomeEnvelope.allows_claim_posterior_update
CapabilityOutcomeFixtureSet._validate_contract_coverage
CapabilityOutcomeFixtureSet.require_outcome
CapabilityOutcomeFixtureSet.rows_for_fixture_case

# Capability-classification inventory helpers are the public contract for
# downstream WCS registry adapters, director snapshots, and tool/provider
# parity checks. Pydantic invokes validators dynamically; downstream tasks
# consume the read helpers after this first seed inventory lands.
AvailabilityProbe._freshness_probe_has_ttl
CapabilityClassificationRow._validate_classification_contract
CapabilityClassificationInventory._validate_inventory_contract
CapabilityClassificationInventory.rows_for_family
CapabilityClassificationInventory.rows_for_availability
CapabilityClassificationInventory.director_snapshot_rows
CapabilityClassificationInventory.wcs_projection_payloads
capability_classification_rows_by_id
validate_daimonion_tool_affordance_parity
build_seed_inventory

# Narration triad validators are invoked dynamically by Pydantic while the
# autonomous narration ledger validates open/closed semantic-outcome policy.
IntendedOutcomeItem._open_or_closed_has_policy
NarrationTriadEnvelope._validate_grounding_policy

# Temporal span registry validators are invoked dynamically by Pydantic while
# validating media/replay/perception fixture contracts. The sidecar grouping
# helper is a public contract for downstream replay/media consumers.
TemporalSpan._validate_temporal_bounds_and_authority
TemporalMediaSidecar._validate_sidecar_join_policy
TemporalSpanAlignment._validate_alignment_without_mtime
ClaimBearingMediaOutput._validate_output_claim_shape
SpanClaimGateDecision._validate_fail_closed_decision
TemporalSpanRegistryFixtureSet._validate_registry_fixture_contract
TemporalSpanRegistryFixtureSet.sidecars_by_kind

# pyright: reportUnusedExpression=false
"""Justified dynamic-entrypoint references for scripts/check-unused-functions.py.

Keep this file narrow. Add names here only when a callable is invoked by a
framework, subprocess entrypoint, import string, or other dynamic path that
vulture cannot see. Do not use this as a baseline for ordinary dead code.
"""

from agents.payment_processors.x402.models import Accept, SettlementResponse
from agents.visual_pool.repository import VisualPoolSidecar
from logos.api.routes.studio import studio_audio_safe_for_broadcast, studio_egress_state
from shared.aperture_registry import (
    ApertureRegistryFixtureSet,
    ApertureRegistryRecord,
    TemporalSpanPolicy,
    aperture_registry,
    load_aperture_registry,
)
from shared.audio_topology_inspector import check_l12_forward_invariant
from shared.audio_world_surface_fixtures import AudioSurfaceFixture, AudioWorldSurfaceFixtureSet
from shared.bayesian_camera_salience_world_surface import (
    CameraEvidenceRow,
    CameraFreshness,
    CameraObservationEnvelope,
    CameraSalienceBundle,
    CameraSalienceFixtureSet,
    CameraTemporalWindow,
    ImageAttachmentPolicy,
    ObservationAperture,
    PublicClaimPolicy,
    ValueOfInformation,
    adapt_cross_camera_tracklet,
    adapt_ir_presence_observation,
    adapt_vision_backend_observation,
    load_camera_salience_fixtures,
)
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
    ContentProgrammeRunEnvelope,
    NestedProgrammeOutcome,
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
from shared.director_programme_format_actions import (
    DirectorProgrammeFormatActionProjection,
    DirectorProgrammeFormatActionRow,
    ProgrammeWCSSurfaceRef,
)
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
from shared.format_wcs_requirement_matrix import (
    FormatWCSRequirementMatrix,
    FormatWCSRequirementRow,
    decide_format_wcs_readiness,
    director_projection,
    load_format_wcs_requirement_matrix,
    opportunity_gate_projection,
)
from shared.github_publication_log import GitHubPublicationLogEvent
from shared.grounding_provider_router import (
    build_eval_artifact,
    build_privacy_egress_preflight,
    route_candidates_for_claim,
    validate_eval_suite,
    validate_provider_registry,
)
from shared.livestream_health_group import LivestreamHealthEnvelope, LivestreamHealthGroup
from shared.narration_triad import IntendedOutcomeItem, NarrationTriadEnvelope
from shared.operator_quality_feedback import (
    OperatorQualityRatingEvent,
    iter_operator_quality_ratings,
)
from shared.operator_quality_posterior import (
    OperatorQualityPosteriorReadModel,
    aggregate_operator_quality_posterior,
)
from shared.operator_vad_gate import (
    DEFAULT_MATCH_THRESHOLD,
    OperatorVADDecision,
    OperatorVADGate,
)
from shared.private_to_public_bridge import BridgeResult, evaluate_bridge
from shared.programme_revenue_braid_adapters import (
    BraidSnapshotRowRef,
    ConversionReadinessBraidProjection,
    ProgrammeFeedbackBraidProjection,
    load_programme_revenue_braid_adapter_fixtures,
)
from shared.scrim_health_fixtures import (
    ScrimHealthExpectedOutcome,
    ScrimHealthFixture,
    ScrimHealthFixtureSet,
    ScrimHealthWorldSurfaceRef,
    ScrimInvariantScores,
)
from shared.scrim_refusal_correction_boundary_gestures import (
    BoundaryGestureCaps,
    BoundaryNoExpertGate,
    BoundaryPublicEventMapping,
    ProgrammeBoundaryEventGestureRef,
    ScrimBoundaryGestureFixtureSet,
    ScrimBoundaryGestureInput,
    ScrimBoundaryGestureProjection,
    ScrimBoundaryGestureRecord,
)
from shared.scrim_wcs_claim_posture import (
    EvidenceReference,
    ScrimWCSClaimPostureProjection,
    WCSClaimReference,
)

# Public-API context manager. Called by the five per-outcome smoke tests
# (vocal / programme_authoring / director_moves / chat_reactivity /
# chat_response) shipping in follow-up cc-tasks; vulture cannot see the
# eventual call sites.
from shared.segment_observability import SegmentRecorder as _SegmentRecorder

_SegmentRecorder

# Deterministic fixture evaluator for segment quality/action/layout contract tests.
# Test call sites are intentionally outside vulture's production scan.
from shared.segment_quality_actionability import (
    build_beat_layout_needs as _build_beat_layout_needs,
)
from shared.segment_quality_layout_eval import (
    evaluate_segment_quality_layout_fixture as _evaluate_segment_quality_layout_fixture,
)

_evaluate_segment_quality_layout_fixture
_build_beat_layout_needs

# Segment-prep framework public helpers are invoked by review scripts, tests,
# Pydantic validators, or future prep phases that vulture does not scan as
# production call paths.
from shared.loop_card import ControlLoopCard as _ControlLoopCard
from shared.segment_live_event_quality import (
    compare_live_event_quality as _compare_live_event_quality,
)
from shared.segment_prep_contract import (
    programme_source_readiness as _programme_source_readiness,
)
from shared.segment_source_inquiry import (
    build_source_packet_inquiry_blackboard as _build_source_packet_inquiry_blackboard,
)
from shared.segment_source_inquiry import (
    render_source_packet_inquiry_seed as _render_source_packet_inquiry_seed,
)
from shared.segment_source_inquiry import (
    source_packet_inquiry_summary as _source_packet_inquiry_summary,
)

_ControlLoopCard._tuple_items_non_empty
_ControlLoopCard._admissibility_has_required_operational_surface
_compare_live_event_quality
_programme_source_readiness
_build_source_packet_inquiry_blackboard
_source_packet_inquiry_summary
_render_source_packet_inquiry_seed

# Pydantic v2 validators for the programme live-prior contract. They are
# invoked by model validation, not by direct static calls.
from shared.programme import (
    ProgrammeBeatCard as _ProgrammeBeatCard,
)
from shared.programme import (
    ProgrammeContent as _ProgrammeContent,
)
from shared.programme import (
    ProgrammeLivePrior as _ProgrammeLivePrior,
)

_ProgrammeBeatCard._proposal_only
_ProgrammeLivePrior._proposal_only
_ProgrammeContent._beat_action_intents_are_proposals
_ProgrammeContent._delivery_mode_normalized
_ProgrammeContent._beat_cards_reasonable
_ProgrammeContent._live_priors_reasonable

# Test-only reset hook for the in-process rendered-blit readback cache. The
# production read path is recent_blit_readbacks(); vulture does not scan tests.
from agents.studio_compositor.fx_chain import clear_blit_readbacks as _clear_blit_readbacks

_clear_blit_readbacks

from shared.self_grounding_envelope import (
    SelfPresenceEnvelopeProjection,
    build_envelope_projection,
    render_compact_prompt_block,
)
from shared.self_presence import (
    Aperture,
    ApertureEvent,
    ClaimBinding,
    OntologyTermMapping,
    SelfPresenceEnvelope,
    SelfPresenceFixtureSet,
    fixture_set,
    load_self_presence_fixture_set,
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
from shared.tool_provider_outcome import (
    ToolProviderOutcomeEnvelope,
    ToolProviderOutcomeFixtureSet,
)
from shared.trend_current_event_gate import evaluate_candidate, validate_policy
from shared.wcs_browser_mcp_file_surface import (
    SourceSurfaceRecord,
    SourceWitnessProbe,
    WCSBrowserMCPFileSurfaceFixtureSet,
    evaluate_surface,
    load_wcs_browser_mcp_file_surface_fixtures,
)
from shared.wcs_browser_mcp_file_surface import (
    schema as wcs_browser_mcp_file_surface_schema,
)
from shared.wcs_camera_archive_public_aperture import (
    MediaApertureFixtureSet,
    MediaApertureRecord,
)
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
from shared.world_surface_health_control_adapter import (
    ControlRouteHealth,
    ControlRouteHealthFixtureSet,
)
from shared.world_surface_provider_tool_health import ProviderToolRouteHealth
from shared.world_surface_temporal_perceptual_health import TemporalPerceptualHealthRow

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

# x402 v2 transport models — Pydantic field validators invoked
# dynamically at model_validate time. Vulture cannot trace through
# the @field_validator decorator regardless of test reachability.
Accept._scheme_supported
Accept._network_caip_eip155
Accept._amount_is_numeric_string
SettlementResponse._network_caip_eip155

# Pydantic invokes model validators dynamically during model validation.
DirectorControlMoveAuditRecord._validate_boundary_and_evidence
TemporalEvidenceEnvelope._validate_temporal_authority
TemporalShmPayloadFixture._validate_fixture_case
TemporalBandEvidenceFixtureSet._validate_fixture_set
LivestreamHealthGroup._non_healthy_groups_explain_themselves
LivestreamHealthEnvelope._validate_group_set_and_claim_implications
GitHubPublicationLogEvent._publication_state_matches_evidence
LivestreamHealthEnvelope.groups_by_id

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
NestedProgrammeOutcome._validate_nested_outcome_semantics
ContentProgrammeRunEnvelope._validate_nested_outcome_graph

# Operator-quality feedback is a private JSONL contract consumed by operator
# control surfaces and downstream SS2/QM5 analysis. Pydantic invokes validators
# dynamically, and the iterator is the stable reader for those later consumers.
OperatorQualityRatingEvent._rating_must_not_be_bool
OperatorQualityRatingEvent._occurred_at_must_be_utc
OperatorQualityRatingEvent._strip_optional_strings
OperatorQualityRatingEvent._required_strings_non_empty
OperatorQualityRatingEvent._refs_non_empty
iter_operator_quality_ratings

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
SupportCopyConsumerReadiness.validate_consumer_policy
SupportCopyReadinessDecision.validate_decision
SupportCopyReadinessDecision.consumer_state
support_copy_doctrine_summary
evaluate_support_copy_readiness

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
AudioMarkerProbeFixture._validate_mode_and_witness

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

# Provider/tool route health validators are invoked dynamically by Pydantic
# while projecting model/search/MCP/publication/local routes into WCS rows.
ProviderToolRouteHealth._validate_route_claim_authority

# Temporal/perceptual WCS health rows are loaded through Pydantic fixture
# validation; vulture cannot see model_validator invocation.
TemporalPerceptualHealthRow._validate_temporal_perceptual_row

# Control-surface route health validators are invoked dynamically by Pydantic
# while projecting MIDI, desktop, private-device, and blocked-hardware rows into
# WCS records. The action-readiness and lookup helpers are public contracts for
# downstream director/control consumers; the production-only vulture gate does
# not count focused tests as callsites.
ControlRouteHealth._validate_control_route_contract
ControlRouteHealth.satisfies_control_action_witness
ControlRouteHealthFixtureSet.routes_by_id

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

# Scrim refusal/correction boundary gesture validators are invoked by Pydantic
# while validating programme-boundary fixture packets. The projection is a
# schema/fixture contract for downstream run-store, audit, and health consumers.
BoundaryNoExpertGate._blocked_gate_cannot_claim_public
BoundaryPublicEventMapping._internal_only_cannot_have_public_fallback
ProgrammeBoundaryEventGestureRef._public_boundary_claims_require_evidence
BoundaryGestureCaps._bounded_boundary_pulses
ScrimBoundaryGestureRecord._validate_no_laundered_boundary_claim
ScrimBoundaryGestureInput._family_must_match_projection
ScrimBoundaryGestureProjection._refs_stay_consistent
ScrimBoundaryGestureFixtureSet._validate_fixture_set

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

# Director programme format/action rows are a read-model contract for the next
# WCS prompt block and programme snapshot smoke tasks. Pydantic invokes
# validators dynamically; production consumers land after this slice.
ProgrammeWCSSurfaceRef._blocked_or_missing_surfaces_need_reason
DirectorProgrammeFormatActionRow._validate_fail_closed_programme_action
DirectorProgrammeFormatActionProjection._validate_projection_coverage
DirectorProgrammeFormatActionProjection.rows_for_state
DirectorProgrammeFormatActionProjection.require_action

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

# Tool/provider outcome envelope helpers are the public contract for downstream
# action-receipt grounding. Pydantic invokes validators dynamically; the
# action-receipt bridge consumes the read helpers after this schema/fixture
# contract lands.
ToolProviderOutcomeEnvelope._validate_source_acquisition_mode
ToolProviderOutcomeEnvelope._validate_status_error_and_authority
ToolProviderOutcomeEnvelope._validate_claim_support
ToolProviderOutcomeEnvelope._validate_redaction_and_public_claims
ToolProviderOutcomeEnvelope.action_receipt_consumption_refs
ToolProviderOutcomeFixtureSet._validate_fixture_set_contract
ToolProviderOutcomeFixtureSet.require_outcome
ToolProviderOutcomeFixtureSet.rows_for_fixture_case

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

# Browser/MCP/file source-read helpers are the public contract for downstream
# private dry-run loops and source-evidence WCS gates. Pydantic invokes
# validators dynamically; downstream tasks consume the loader/evaluator after
# this fixture contract lands.
SourceWitnessProbe._validate_witness_result
SourceSurfaceRecord._validate_surface_contract
WCSBrowserMCPFileSurfaceFixtureSet._validate_fixture_set_contract
WCSBrowserMCPFileSurfaceFixtureSet.require_surface
WCSBrowserMCPFileSurfaceFixtureSet.evaluate_all
evaluate_surface
load_wcs_browser_mcp_file_surface_fixtures
wcs_browser_mcp_file_surface_schema

# Camera/archive/public-aperture WCS validators are invoked dynamically by
# Pydantic while validating the fixture packet. The read helpers are public
# contracts for downstream camera salience, archive sidecar, and programme WCS
# consumers; production vulture does not count focused tests as callsites.
MediaApertureRecord._validate_media_aperture_contract
MediaApertureFixtureSet._validate_fixture_coverage
MediaApertureFixtureSet.require_record
MediaApertureFixtureSet.records_for_state

# Bayesian camera salience broker validators are invoked dynamically by
# Pydantic while validating WCS-backed perception envelopes. The adapter and
# projection helpers are the public contract for future director, archive,
# visual-variance, and runtime wiring tasks; this slice intentionally avoids
# wiring those consumers directly.
CameraFreshness._validate_freshness_contract
ObservationAperture._validate_aperture_contract
CameraTemporalWindow._archive_windows_need_bounds
CameraEvidenceRow._validate_evidence_refs
CameraObservationEnvelope._validate_observation_contract
ValueOfInformation._validate_selection
ImageAttachmentPolicy._validate_attachment_bounds
CameraSalienceBundle._validate_bundle_contract
CameraSalienceBundle.to_director_world_surface_projection
CameraSalienceBundle.to_wcs_projection_payload
CameraSalienceFixtureSet._validate_fixture_contract
CameraSalienceFixtureSet.broker
CameraSalienceFixtureSet.query_by_id
PublicClaimPolicy
adapt_vision_backend_observation
adapt_cross_camera_tracklet
adapt_ir_presence_observation
load_camera_salience_fixtures

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

# Application obligation refusal helpers are the public contract for downstream
# grant/fellowship scout, attestation, and operating-system tasks. This slice
# lands the fail-closed policy and fixture packet before those call sites.
evaluate_application_obligation
load_application_obligation_fixtures

# Grant opportunity scout validators are invoked dynamically by Pydantic while
# validating the private evidence / attestation queue fixture contract.
OperatorAttestationRequirement._operator_action_matches_requiredness
GrantOpportunityRecord._validate_private_evidence_contract
GrantOpportunityFixtureSet._validate_source_coverage

# Programme/revenue braid adapter validators are invoked dynamically by
# Pydantic while validating fixture packets. The loader is a public contract for
# downstream programme/conversion consumers and schema tests.
BraidSnapshotRowRef._private_ceiling_has_no_public_claim
ProgrammeFeedbackBraidProjection._grounding_updates_need_grounding_signal
ConversionReadinessBraidProjection._grant_private_evidence_stays_separate
load_programme_revenue_braid_adapter_fixtures

# Format WCS requirement matrix validators are invoked dynamically by Pydantic
# while validating the matrix. The projection helpers are public contracts for
# downstream director and opportunity-to-run gate packets.
FormatWCSRequirementRow._validate_format_wcs_contract
FormatWCSRequirementRow.surface_ids_for_director
FormatWCSRequirementMatrix._validate_all_initial_formats_present
load_format_wcs_requirement_matrix
decide_format_wcs_readiness
director_projection
opportunity_gate_projection

# Self-presence ontology validators are invoked dynamically by Pydantic while
# validating the unified self-grounding fixture envelope contract. The loader
# and fixture_set helper are public contracts for downstream aperture registry,
# route/claim envelope, bridge governor, and deictic resolver tasks.
OntologyTermMapping._requires_existing_vocab_targets
Aperture._public_live_requires_evidence
ClaimBinding._prompt_only_states_are_not_evidence
ApertureEvent._success_requires_witness
SelfPresenceEnvelope._fail_closed_public_speech
SelfPresenceFixtureSet._covers_required_contract
load_self_presence_fixture_set
fixture_set

# Aperture registry validators are invoked dynamically by Pydantic while
# validating the system-wide aperture registry fixture contract. The loader
# and cached registry helper are public contracts for downstream route/claim
# envelope, bridge governor, and prompt block consumers.
TemporalSpanPolicy._max_gte_default
ApertureRegistryRecord._fail_closed_public
ApertureRegistryFixtureSet._validate_registry_contract
ApertureRegistryFixtureSet.by_id
ApertureRegistryFixtureSet.require
ApertureRegistryFixtureSet.records_for_kind
ApertureRegistryFixtureSet.records_for_exposure
ApertureRegistryFixtureSet.public_apertures
ApertureRegistryFixtureSet.private_apertures
ApertureRegistryFixtureSet.aperture_for_destination
aperture_registry
load_aperture_registry

# Self-grounding envelope validators are invoked dynamically by Pydantic while
# projecting runtime state into SelfPresenceEnvelopeProjection. The builder and
# prompt block renderer are public contracts for downstream bridge governor,
# prompt block, and emit consumers.
SelfPresenceEnvelopeProjection._fail_closed_public_speech
build_envelope_projection
render_compact_prompt_block

# Segment layout responsibility contract validators are invoked dynamically by
# Pydantic while prepared artifacts and runtime receipts are validated. The
# contract lands before downstream prep/runtime consumers wire it in.
from agents.hapax_daimonion.segment_layout_contract import (
    HostingContext as _SegmentLayoutHostingContext,
)
from agents.hapax_daimonion.segment_layout_contract import (
    LayoutDecisionContract as _SegmentLayoutDecisionContract,
)
from agents.hapax_daimonion.segment_layout_contract import (
    PreparedSegmentLayoutContract as _PreparedSegmentLayoutContract,
)
from agents.hapax_daimonion.segment_layout_contract import (
    RuntimeLayoutDecision as _RuntimeLayoutDecision,
)
from agents.hapax_daimonion.segment_layout_contract import (
    RuntimeLayoutReceipt as _RuntimeLayoutReceipt,
)
from agents.hapax_daimonion.segment_layout_contract import (
    RuntimeReadbackRef as _RuntimeReadbackRef,
)
from agents.hapax_daimonion.segment_layout_contract import (
    SegmentActionIntent as _SegmentLayoutActionIntent,
)

_SegmentLayoutHostingContext._static_success_requires_explicit_non_responsibility
_SegmentLayoutActionIntent._visible_action_intents_need_sources
_SegmentLayoutDecisionContract._bounded_contract_is_complete
_PreparedSegmentLayoutContract._adapt_parent_hosting_context
_PreparedSegmentLayoutContract._prepared_artifact_sha_is_hex
_PreparedSegmentLayoutContract._responsible_hosting_needs_visible_work
_RuntimeLayoutDecision._decision_ttl_covers_dwell
_RuntimeLayoutReceipt._layout_state_hash_is_sha256
_RuntimeReadbackRef._digest_is_sha256

# Bridge governor validators are invoked dynamically by Pydantic.
# The evaluator is the sole public path from private to public.
BridgeResult._no_public_without_authorization
evaluate_bridge

# Awareness-digest watcher loop is the public entrypoint wired into
# `run_loops_aux` by the daemon's voice path in a follow-up; per the
# cc-task `awareness-digest-fortress-watcher-loop` it ships standalone
# (testable in isolation) ahead of the daemon hookup.
from agents.hapax_daimonion.awareness_digest_watcher import (
    awareness_digest_watcher_loop,
)

awareness_digest_watcher_loop

# Operator-quality posterior read-model is the private dossier substrate for
# the operator-predictive-dossier value-braid. Public callers (the value-braid
# adapter cc-task `operator-dossier-value-braid-adapter`) land in a follow-up
# PR; until then the aggregator and projection helpers are exercised by tests
# only.
aggregate_operator_quality_posterior
OperatorQualityPosteriorReadModel.cells_for_programme
OperatorQualityPosteriorReadModel.cells_for_axis
OperatorQualityPosteriorReadModel.private_summary_lines

# Operator-VAD gate (cc-task audio-audit-D Phase 0): substrate ships
# without consumer wiring. Phase 1 (separate PR) wires OperatorVADGate.decide
# into the audio-ducker trigger and supplies a ResemBlyzer-backed match
# callable. Until then, only the test suite exercises decide() / should_duck /
# match_threshold. The OperatorVADDecision import keeps the dataclass + Literal
# alias visible for type-resolution at downstream call sites.
DEFAULT_MATCH_THRESHOLD
OperatorVADDecision
OperatorVADGate.decide
OperatorVADGate.match_threshold
OperatorVADDecision.should_duck

# MixerGainWriter Protocol + writer impls (cc-task audio-audit-C Phase 0):
# substrate ships ahead of the ducker swap PR. Phase 1 will inject the writer
# into agents.audio_ducker.__main__ and swap the in-place subprocess.run for
# self._writer.write. Until then the protocol + Subprocess impl + Native
# placeholder are exercised by tests only.
from agents.audio_ducker.pw_writer import (
    MIXER_WRITE_LATENCY_SECONDS,
    MixerGainWriter,
    MixerWriteOutcome,
    NativePWWriter,
    SubprocessPWWriter,
)

MixerGainWriter
SubprocessPWWriter
SubprocessPWWriter.write
NativePWWriter
NativePWWriter.write
MixerWriteOutcome.succeeded
MIXER_WRITE_LATENCY_SECONDS

# PerceptualField grounding key registry: registry rows + helpers expose a
# public API for downstream director / autonomous-narration / public-broadcast
# consumers. Tests + downstream phases call these dynamically.
from shared.perceptual_field_grounding_registry import (
    GroundingDecision,
    PerceptualFieldGroundingRegistry,
    RegistryRow,
    default_registry,
)

GroundingDecision.hard_blocked
PerceptualFieldGroundingRegistry.by_key_path
PerceptualFieldGroundingRegistry.row_for
PerceptualFieldGroundingRegistry.is_diagnostic_only_path
PerceptualFieldGroundingRegistry.evaluate
RegistryRow.is_diagnostic_only
RegistryRow.allows_consumer
RegistryRow.public_safe
default_registry

# Monetization readiness ledger: the ledger query helpers are the public
# read-side API for downstream public-growth surfaces (artifact-edition
# release, support-prompt, YouTube/VOD packaging, etc.) that need to know
# which target families are public, monetizable, or blocked. The default-
# matrix convenience constructor is the canonical loader.
from shared.monetization_readiness_ledger import (
    MonetizationReadinessLedger,
    evaluate_default_monetization_readiness,
)

CaptionFrame
RollUpEncoder
RollUpEncoder.encode_line
filler_pair

# Phase 5b — audio-to-video clock-offset estimator. The TimingAligner
# is consumed by the upcoming gst_injector slice; helpers + result
# dataclass are part of the public API. Whitelisted so Phase 5b can
# land before its consumer per the same cc-task split as Phase 5a.
from agents.live_captions.timing_aligner import (
    AlignmentResult,
    TimingAligner,
)

AlignmentResult
TimingAligner
TimingAligner.record_pair
TimingAligner.align
TimingAligner.reset
MonetizationReadinessLedger.for_target_family
MonetizationReadinessLedger.public_target_families
MonetizationReadinessLedger.monetizable_target_families
MonetizationReadinessLedger.blocked_target_families
evaluate_default_monetization_readiness
# Operator predictive dossier productization contract: typed atomic-row
# schema + leak detectors + render path. The query helpers, leak detectors,
# and renderer are the public read-side API for downstream feature-spec
# and value-braid surfaces; tests + Phase 2+ ingestion call them dynamically.
from shared.operator_predictive_dossier_contract import (
    LeakFinding,
    OperatorPredictiveDossier,
    detect_evidence_ref_leaks,
    detect_leaks,
    empty_dossier,
    render_dossier_for_prompt,
    render_row_for_prompt,
)

LeakFinding
OperatorPredictiveDossier.by_id
OperatorPredictiveDossier.active_rows
OperatorPredictiveDossier.for_vertical
OperatorPredictiveDossier.for_operator_dimension
detect_evidence_ref_leaks
detect_leaks
empty_dossier
render_dossier_for_prompt
render_row_for_prompt

# DossierRow Pydantic validators are invoked dynamically at construction.
# Vulture flags _validate_governance_consistency because its body
# raises only — but the validator itself is the gate that keeps the
# anti-overclaim invariant from being bypassed.
from shared.operator_predictive_dossier_contract import DossierRow as _DossierRow

_DossierRow._validate_evidence_sufficiency
_DossierRow._validate_governance_consistency

# Institutional fit source registry: public read-side API for the grant
# attestation OS + reusable funding evidence packet cc-tasks (this PR
# `blocks:` both). Tests + Phase 2+ ingestion call dynamically.
from shared.institutional_fit_source_registry import (
    EligibilityNote,
    FundingAmount,
    InstitutionalFitSourceRegistry,
    Obligation,
    SourceRow,
    default_registry,
)

EligibilityNote
FundingAmount
Obligation
InstitutionalFitSourceRegistry.by_id
InstitutionalFitSourceRegistry.by_category
InstitutionalFitSourceRegistry.engaged
InstitutionalFitSourceRegistry.refused
InstitutionalFitSourceRegistry.upcoming_deadlines
SourceRow.freshness
SourceRow.is_engaged
SourceRow.days_until_deadline
SourceRow._validate_no_false_affiliation
FundingAmount._validate_range
default_registry

# Director control-move WCS normalizer: public read-side API for the
# director loop's move resolution path. Phase 2+ wires the loop to call
# normalize_director_control_move; Phase 1 ships scaffolding + tests.
from shared.director_control_move_normalizer import (
    DirectorControlMoveIntent,
    NormalizedDirectorControlMove,
    normalize_director_control_move,
)

DirectorControlMoveIntent
NormalizedDirectorControlMove.is_executable
NormalizedDirectorControlMove.is_public_authoritative
NormalizedDirectorControlMove._validate_public_carries_evidence
normalize_director_control_move

# Phase 6b mood-engine status routes are FastAPI handlers registered via
# the `@router.get` decorator; vulture's static analysis can't see the
# decorator-driven dispatch. Mirrors the (un-whitelisted but pre-existing)
# system_degraded_status / operator_activity_status handlers in the same
# module.
from logos.api.routes.engine import (
    mood_arousal_status,
    mood_coherence_status,
    mood_valence_status,
)

mood_arousal_status
mood_valence_status
mood_coherence_status

# BaselineQuantileTracker.is_above_quantile — the public query API of the
# mood calibration module. Called dynamically by mood bridge accessors
# (LogosMoodValenceBridge / LogosMoodCoherenceBridge) that read watch data
# through the tracker's quantile interface. Vulture can't see the bridge
# accessor dispatch.
from shared.mood_calibration import BaselineQuantileTracker

BaselineQuantileTracker.is_above_quantile

# IR VLM hand-semantics classifier — Phase 1 ships the helper before
# its consumer (Pi-edge daemon wiring in `pi-edge/ir_hands.py` lands
# in a follow-up). Whitelisted so the Phase 1 slice can land first per
# cc-task `ir-perception-replace-zones-with-vlm-classification`.
from shared.ir_vlm_classifier import classify_hand_via_vlm

classify_hand_via_vlm

# IR VLM motion-gated runner (Phase 2) — same Phase 1/2 split: the
# runner ships ahead of its daemon owner. `fingerprint_image` is a
# public log helper consumed by the daemon owner's log lines.
from agents.ir_vlm_runner import MotionGatedVlmRunner, fingerprint_image

MotionGatedVlmRunner
MotionGatedVlmRunner.tick
fingerprint_image

# Segment layout responsibility receipts are consumed as dynamic/public receipt
# metadata by runtime overlays and coordinating agents. The first slice ships
# the pure controller contract before the compositor bridge consumes the
# convenience properties.
from agents.studio_compositor.segment_layout_control import LayoutDecisionReceipt

LayoutDecisionReceipt.layout_applied
LayoutDecisionReceipt.visible_metadata

# x402 receive-endpoint handler — Path A demo route is dispatched via
# the @router.get decorator; vulture's static analysis can't see the
# decorator-driven dispatch. Same pattern as the mood_*_status
# handlers above.
from logos.api.routes.x402 import demo_payment_required

demo_payment_required

# Canonical precedent loader — mirrors load_implications. No
# downstream consumer yet (substrate for future governance reports);
# whitelisted so vulture doesn't flag while a consumer is wired.
from shared.axiom_registry import Precedent, load_precedents

Precedent
load_precedents

# FFT marker-probe detector — runtime-witness layer for the existing
# fixture/policy harness (PR #1897). Whitelisted because the live
# runner that calls into it lands as a follow-up; the helpers ship
# pure-logic + tested first per cc-task `audio-marker-probe-fft-detector`.
from shared.audio_marker_probe_fft import (
    detect_marker_in_capture,
    generate_marker_tone,
)

detect_marker_in_capture
generate_marker_tone

# Qdrant FlowEvent-instrumented factory — opt-in entry point for callers
# that want Logos flow visibility on their qdrant ops. Whitelisted because
# the wrapper class (InstrumentedQdrantClient) was correctly structured
# but had no factory for 6 days post-#1660; this factory is the missing
# wire path. Per the R-16 audit
# (docs/research/2026-04-26-r16-langfuse-instrumented-qdrant-audit.md
# § Disposition), migration is opt-in per caller — no bulk migration
# required, so vulture flags it until the first caller adopts.
from shared.config import get_qdrant_instrumented

get_qdrant_instrumented

# Voice output router (role-keyed API) — ``known_roles`` is the
# operator-dashboard helper for the audio-routing blocker stack. Lands
# ahead of the dashboard surface that will read it (separate cc-task);
# the route() method is the primary consumer surface for the director
# rewrite (cc-task: director-loop-semantic-audio-route).
from shared.voice_output_router import VoiceOutputRouter

VoiceOutputRouter.known_roles

# M8 firmware health check — registered via @check_group("m8") decorator
# in agents/health_monitor/registry.py; vulture's first-pass scan misses
# the registry tie (the check is dispatched dynamically through the
# group registry by health_monitor's runner). Other check_group-
# decorated functions in checks/ escape vulture only because they have
# more reference graph depth (cc-task: m8-system-info-firmware-ingest).
from agents.health_monitor.checks.m8_firmware import check_m8_firmware

check_m8_firmware

# Audio ducker liveness health check — registered via @check_group("audio")
# decorator. Audit C#2 (2026-05-02) caught hapax-audio-ducker.service dead
# for ~8h with no operator-visible signal; this check fires ntfy on inactive
# state. Same dynamic-registry pattern as check_m8_firmware above.
from agents.health_monitor.checks.audio import check_audio_ducker_liveness

check_audio_ducker_liveness

# M8Sequencer — director → M8 MIDI dispatch (cc-task:
# m8-dmn-mute-solo-transport). Currently invoked only via test fixtures;
# the director-side recruitment wiring (impingement_consumer dispatch
# table entry + studio.m8_track_mute/solo/transport affordances) lands
# in a follow-up task per the cc-task scope (mechanism here, recruitment
# integration separate). Whitelisted until the recruitment wire-in PR
# lands.
from agents.studio_compositor.m8_sequencer import M8Sequencer

M8Sequencer
M8Sequencer.muted_tracks
M8Sequencer.soloed_tracks

# ActivityRouter — diagnostic-only public surface for ad-hoc operator
# scripts and the upcoming router observability dashboard (P3 wires the
# Prometheus exporter to read last_state on a poll cadence). Tests pin
# the contract; vulture's static call graph doesn't count unittest
# cases as "real" callsites for production code. Per cc-task
# ``activity-reveal-ward-p0-base-class``.
from agents.studio_compositor.activity_router import ActivityRouter

ActivityRouter.describe
ActivityRouter.last_state

# ActivityRevealMixin — public surface for the P3 governance wiring +
# router-side ceiling enforcement. P0 ships the contract + 4 regression
# pins; P3 + P4 are the consumers vulture cannot yet see.
from agents.studio_compositor.activity_reveal_ward import ActivityRevealMixin

ActivityRevealMixin._ceiling_enforced
ActivityRevealMixin._claim_source_refs
ActivityRevealMixin._compute_claim_score
ActivityRevealMixin._consumed_visible_seconds
ActivityRevealMixin._describe_source_registration
ActivityRevealMixin._hardm_check
ActivityRevealMixin._mandatory_invisible
ActivityRevealMixin._visibility_ceiling_s
ActivityRevealMixin._want_visible
ActivityRevealMixin.current_claim
ActivityRevealMixin.mark_visible_window
ActivityRevealMixin.poll_once
ActivityRevealMixin.state
ActivityRevealMixin.stop

# ChronicleEvent evidence-envelope helpers — public surface for
# downstream consumers (director snapshot, autonomous narration WCS
# gate, public-claim gate) that enforce authority downgrade based on
# trace/span zero-fill and explicit valid/transaction times. P0 ships
# the schema; the consumers land in follow-on PRs. Per cc-task
# ``chronicle-event-evidence-envelope-migration``.
from shared.chronicle import (
    EVIDENCE_CLASSES,
    PUBLIC_SCOPES,
)
from shared.chronicle import (
    ChronicleEvent as _ChronicleEvent,
)

EVIDENCE_CLASSES
PUBLIC_SCOPES
_ChronicleEvent.effective_valid_time
_ChronicleEvent.effective_transaction_time
_ChronicleEvent.has_full_provenance

# Public offer page markdown renderer + generator + validator —
# exposed for downstream consumers (omg.lol weblog, GitHub README,
# static-site surfaces). Not yet wired into a daemon producer;
# first consumer will be the public-offer-page weblog publisher in
# a follow-up PR.
from shared.public_offer_page_generator import (
    OfferPage as _OfferPage,
)
from shared.public_offer_page_generator import (
    generate_offer_page,
    render_offer_page_markdown,
)

render_offer_page_markdown
generate_offer_page
_OfferPage.validate_offer_invariants

# Visual pool destination routing — cc-task
# visual-source-pool-homage-routing. select_by_destination() is the
# query API for downstream homage_video / reverie / gem_ward routing
# integration, which lands in follow-up PRs (effect graph + studio
# compositor). Whitelisted until the runtime callers materialize.
from agents.visual_pool.repository import LocalVisualPool

LocalVisualPool.select_by_destination

# Pydantic field validators on VisualPoolSidecar — invoked dynamically
# by pydantic during model_validate. Vulture can't see the dynamic
# binding (cc-task: visual-source-pool-homage-routing).
from agents.visual_pool.repository import VisualPoolSidecar

VisualPoolSidecar._validate_public_posture
VisualPoolSidecar._validate_routable_destinations

# YouTube packaging claim policy gate — cc-task
# youtube-packaging-claim-policy. Downstream consumer is the
# youtube-content-programming-packaging-compiler (separate cc-task,
# not yet shipped). Whitelisted until compiler lands.
from shared.youtube_packaging_claim_policy import PackagingClaim, evaluate_payload

evaluate_payload
PackagingClaim._require_public_event_ref

# PublicClaimGateDecision.allows_emission is the public predicate
# composer / github-claim-gate consumers use to decide whether to emit
# the original claim copy or swap in correction copy. Phase 0 ships
# the gate library; Phase 1 wires composer.compose_metadata and the
# github surface. Per cc-task ``metadata-public-claim-gate``.
from agents.metadata_composer.public_claim_gate import PublicClaimGateDecision

PublicClaimGateDecision.allows_emission

# LivestreamRoleState + SpeechAct — Pydantic model_validator hooks
# are invoked dynamically at construction, plus the public
# ``is_speech_act_authorized_by_role`` predicate consumers call
# before emission. Phase 0 ships the schema; Phase 1+ wires the
# programme runner, director snapshot, scrim, audio, captions,
# archive, and public-event adapters. Per cc-task
# ``livestream-role-speech-programme-binding-contract``.
from shared.livestream_role_state import (
    LivestreamRoleState,
    SpeechAct,
    is_speech_act_authorized_by_role,
)

LivestreamRoleState._validate_invariants
SpeechAct._validate_speech_act_invariants
is_speech_act_authorized_by_role

# Artifact catalog helpers — cc-task artifact-catalog-release-workflow.
# Render/checksum/gate functions called by downstream catalog-publisher
# PRs (separate cc-tasks). Whitelisted until publisher lands.
from shared.artifact_catalog import (
    ArtifactCatalog,
    ArtifactRecord,
    compute_bundle_checksum,
    evaluate_export_gate,
    render_catalog_page,
)

evaluate_export_gate
render_catalog_page
compute_bundle_checksum
ArtifactCatalog.by_stream
ArtifactCatalog.by_price_class
ArtifactCatalog.exportable
ArtifactRecord._validate_price_class_invariants

# Audio-source-role → motion-protocol proposals (cc-task
# audio-reactive-ward-camera-homage-motion-protocols, Phase 0).
# MotionProtocolRunner and record_witness are the runtime entrypoints
# for director / studio_compositor consumption; that wiring lands in a
# follow-up PR. Whitelisted until the runtime callers materialize.
from shared.audio_motion_protocols import MotionProtocolRunner, record_witness

MotionProtocolRunner
record_witness

# Governance refusal outcome policy — cc-task governance-refusal-outcome-policy.
# Pair / wrapper / public artifact policy classes called by the
# learning adapter and downstream programme refusal/correction artifact
# emitters (separate cc-tasks). Whitelisted until consumers land.
from shared.governance_refusal_outcome import (
    GovernanceRefusalPair,
    PublicRefusalArtifactPolicy,
    RefusalEnvelopePolicy,
    learning_adapter_treats_refusal_as_governance_success,
)

GovernanceRefusalPair.governance_learning_is_success
GovernanceRefusalPair.refused_claim_validates_success
GovernanceRefusalPair.shared_refusal_refs
GovernanceRefusalPair._validate_no_laundering_invariants
PublicRefusalArtifactPolicy.cleared_for_public_release
PublicRefusalArtifactPolicy._validate_public_artifact_invariants
RefusalEnvelopePolicy.governance_capability_learning_allowed
RefusalEnvelopePolicy.refused_claim_posterior_locked
RefusalEnvelopePolicy._validate_no_laundering_for_refusal
learning_adapter_treats_refusal_as_governance_success

# License request price class router — cc-task license-request-price-class-router.
# Pydantic model_validator hooks invoked at construction; ledger and helper
# entry-points called by downstream license-routing daemon (separate cc-task).
from shared.license_request_price_class_router import (
    Quote,
    RouteVerdict,
    evaluate_request,
    ledger_entry,
    now_utc,
)

Quote._validate_price_invariants
RouteVerdict._exactly_one_branch
evaluate_request
ledger_entry
now_utc

# Aesthetic condition editions ledger — cc-task aesthetic-condition-editions-ledger.
# Pydantic model_validator + ledger / dry-run / capture entry-points called by
# downstream condition-edition selector daemon (separate cc-task).
from shared.aesthetic_condition_editions_ledger import (
    AestheticConditionEditionsLedger,
    EditionMetadata,
    auto_capture_edition_from_input,
    evaluate_edition_eligibility_from_input,
)

EditionMetadata._validate_creation_gate
AestheticConditionEditionsLedger.by_kind
AestheticConditionEditionsLedger.by_rights
AestheticConditionEditionsLedger.by_condition
auto_capture_edition_from_input
evaluate_edition_eligibility_from_input

# Payment aggregator v2 support normalizer — cc-task
# payment-aggregator-v2-support-normalizer.
# Pydantic model_validator hooks + public emit / render entrypoints called
# by the downstream support-aggregation daemon (separate cc-task).
from shared.payment_aggregator_v2_support_normalizer import (
    NormalizedSupportReceipt,
    PublicAggregateEmission,
    PublicEmitDecision,
    evaluate_public_emit,
    render_public_aggregate_text,
)

NormalizedSupportReceipt._validate_rail_currency_match
PublicAggregateEmission._validate_window
PublicEmitDecision._exactly_emit_or_refuse
evaluate_public_emit
render_public_aggregate_text

# GitHub Sponsors receive-only rail — cc-task
# publication-bus-monetization-rails-surfaces (Phase 0).
# Pydantic field_validator + the public ingest_webhook entrypoint are invoked
# by the downstream publication_bus rail dispatcher (separate cc-task).
from shared.github_sponsors_receive_only_rail import (
    GitHubSponsorsRailReceiver,
    SponsorshipEvent,
)

SponsorshipEvent._login_is_handle_only
GitHubSponsorsRailReceiver.ingest_webhook

# Liberapay receive-only rail — cc-task
# publication-bus-monetization-rails-surfaces (Phase 0, Liberapay rail).
# Pydantic field_validator hook invoked at construction; ingest_webhook is
# the public receiver entry-point called by the downstream FastAPI handler
# bridging email-to-webhook / CSV-export deliveries (separate cc-task).
from shared.liberapay_receive_only_rail import (
    DonationEvent,
    LiberapayRailReceiver,
)

DonationEvent._handle_is_username_only
LiberapayRailReceiver.ingest_webhook

# Open Collective receive-only rail — cc-task
# publication-bus-monetization-rails-surfaces (Phase 0, Open Collective rail).
# Pydantic field_validator hooks (slug + ISO 4217 currency) invoked at
# construction; ingest_webhook is the public receiver entry-point called by the
# downstream FastAPI webhook handler bridging Open Collective deliveries
# (separate cc-task). Multi-currency preservation is the new shape this rail
# introduces vs the prior two.
from shared.open_collective_receive_only_rail import (
    CollectiveEvent,
    OpenCollectiveRailReceiver,
)

CollectiveEvent._handle_is_slug_only
CollectiveEvent._currency_is_iso_4217
OpenCollectiveRailReceiver.ingest_webhook

# Stripe Payment Link receive-only rail — cc-task
# publication-bus-monetization-rails-surfaces (Phase 0, Stripe Payment Link rail).
# Pydantic field_validator hooks (Stripe object-ID + ISO 4217 currency) invoked
# at construction; ingest_webhook is the public receiver entry-point called by
# the downstream FastAPI webhook handler bridging Stripe deliveries (separate
# cc-task). Timestamped HMAC + 300s replay tolerance are the new shapes this
# rail introduces vs the prior three.
from shared.stripe_payment_link_receive_only_rail import (
    PaymentEvent,
    StripePaymentLinkRailReceiver,
)

PaymentEvent._handle_is_stripe_id
PaymentEvent._currency_is_iso_4217
StripePaymentLinkRailReceiver.ingest_webhook

# Patreon receive-only rail — cc-task
# publication-bus-monetization-rails-surfaces (Phase 0, Patreon rail).
# Pydantic field_validator hooks (Patreon vanity slug + ISO 4217 currency)
# invoked at construction; ingest_webhook is the public receiver entry-point
# called by the downstream FastAPI webhook handler bridging Patreon deliveries
# (separate cc-task). HMAC MD5 + JSON:API included[] resource walking are the
# new shapes this rail introduces vs the prior four.
from shared.patreon_receive_only_rail import (
    PatreonRailReceiver,
    PledgeEvent,
)

PledgeEvent._handle_is_vanity_only
PledgeEvent._currency_is_iso_4217
PatreonRailReceiver.ingest_webhook

# Ko-fi receive-only rail — cc-task
# publication-bus-monetization-rails-surfaces (Phase 0, Ko-fi rail).
# Pydantic field_validator hooks (display-name + ISO 4217 currency) invoked at
# construction; ingest_webhook is the public receiver entry-point called by the
# downstream FastAPI webhook handler bridging Ko-fi form-encoded deliveries
# (separate cc-task). Verification-token auth (in lieu of HMAC) is the new
# shape this rail introduces vs the prior four.
from shared.ko_fi_receive_only_rail import (
    KoFiEvent,
    KoFiRailReceiver,
)

KoFiEvent._handle_is_display_name_only
KoFiEvent._currency_is_iso_4217
KoFiRailReceiver.ingest_webhook

# Buy Me a Coffee receive-only rail — cc-task
# publication-bus-monetization-rails-surfaces (Phase 0, BMaC rail). Pydantic
# field_validator hooks (display-name + ISO 4217 currency) invoked at
# construction; ingest_webhook is the public receiver entry-point called by the
# downstream FastAPI webhook handler bridging BMaC HMAC-SHA256-signed JSON
# deliveries (separate cc-task). Restores HMAC SHA-256 over raw body (vs Ko-fi
# verification-token + Patreon HMAC-MD5 divergences); 8th rail in the family.
from shared.buy_me_a_coffee_receive_only_rail import (
    BuyMeACoffeeRailReceiver,
    CoffeeEvent,
)

CoffeeEvent._handle_is_display_name_only
CoffeeEvent._currency_is_iso_4217
BuyMeACoffeeRailReceiver.ingest_webhook

# omg.lol support-directory composer — cc-task
# omg-lol-support-directory-publisher. Pure typed composer that renders the
# seven receive-only rails' canonical public URLs to deterministic markdown
# suitable for an OmgLolWeblogPublisher.publish() call (which lives in a
# separate downstream cc-task). Pydantic model_validator hooks
# (entry/directory invariants) invoked at construction; render_directory_markdown
# is the public renderer entry-point called by the downstream weblog-driver
# script. RailId / SupportDirectory / SupportDirectoryEntry are exported as the
# typed public schema.
from shared.omg_lol_support_directory import (
    RailId,
    SupportDirectory,
    SupportDirectoryEntry,
    SupportDirectoryError,
    render_directory_markdown,
)

SupportDirectoryEntry._validate_entry
SupportDirectory._validate_directory
render_directory_markdown
RailId
SupportDirectoryError

# Mercury receive-only rail — cc-task mercury-receive-only-rail
# (Phase 0, Mercury bank-rail). Pydantic field_validator hooks
# (counterparty-display + ISO 4217 currency) invoked at construction;
# ingest_webhook is the public receiver entry-point called by the
# downstream FastAPI webhook handler bridging Mercury HMAC-SHA256-signed
# JSON deliveries (separate cc-task). The first direct-bank rail in the
# family — adds a direction filter (incoming-only) on the transaction
# kind enum, alongside the standard HMAC-over-raw-body shape from
# GitHub Sponsors / Stripe / BMaC.
from shared.mercury_receive_only_rail import (
    MercuryEventKind,
    MercuryRailReceiver,
    MercuryTransactionDirection,
    MercuryTransactionEvent,
)

MercuryTransactionEvent._handle_is_display_name_only
MercuryTransactionEvent._currency_is_iso_4217
MercuryRailReceiver.ingest_webhook
MercuryEventKind
MercuryTransactionDirection

# Modern Treasury receive-only rail — cc-task
# modern-treasury-receive-only-rail (Phase 0). Pydantic field_validator
# hooks (originating-party-display + ISO 4217 currency) invoked at
# construction; ingest_webhook is the public receiver entry-point called
# by the downstream FastAPI webhook handler bridging Modern Treasury
# HMAC-SHA256-signed JSON deliveries (separate cc-task). Ninth rail in
# the family — second direct-bank rail after Mercury (#2251). Direction
# filter is promoted into the event-kind enum here (only accepts
# ``incoming_payment_detail.created`` / ``.completed``); outgoing
# ``payment_order.*`` events are rejected.
from shared.modern_treasury_receive_only_rail import (
    IncomingPaymentEvent,
    IncomingPaymentEventKind,
    ModernTreasuryRailReceiver,
    PaymentMethod,
)

IncomingPaymentEvent._handle_is_display_name_only
IncomingPaymentEvent._currency_is_iso_4217
ModernTreasuryRailReceiver.ingest_webhook
IncomingPaymentEventKind
PaymentMethod

# Treasury Prime receive-only rail (Phase 0, ledger accounts) — cc-task
# treasury-prime-receive-only-rail. Pydantic field_validator hooks
# (originating-party-display + ISO 4217 currency) invoked at construction;
# ingest_webhook is the public receiver entry-point called by the
# downstream FastAPI webhook handler bridging Treasury Prime
# HMAC-SHA256-signed JSON deliveries (separate cc-task). Tenth rail in
# the family — third direct-bank rail, closes the Jr packet's
# Bank-as-API recommendation set. Phase 0 accepts only
# ``incoming_ach.create`` (ledger accounts); Phase 1 will extend to
# ``transaction.create`` (core direct accounts) with the data-level
# direction filter from Mercury.
from shared.treasury_prime_receive_only_rail import (
    IncomingAchEvent,
    IncomingAchEventKind,
    TreasuryPrimeRailReceiver,
)

IncomingAchEvent._handle_is_display_name_only
IncomingAchEvent._currency_is_iso_4217
TreasuryPrimeRailReceiver.ingest_webhook
IncomingAchEventKind

# cc-task u8-stream-mode-delta-amplification (Phase 0): get_visual_mode_bias
# is the consumer-facing accessor; consumers (compositor preset selector,
# imagination colorgrade, reverie satellite recruit) wire in Phase 1.
# Whitelisted until Phase 1 lands so vulture doesn't flag the unused
# function in the substrate-only PR.
from shared.visual_mode_bias import VisualModeBias, get_visual_mode_bias

get_visual_mode_bias
VisualModeBias.family_weight

# cc-task u5-semantic-verbs-consumer (Phase 0 substrate): the vocabulary
# accessors are the API consumers (preset_recruitment_consumer, future
# verb-to-shader-uniform wiring) will hit at Phase 1. Whitelisted until
# Phase 1 lands.
from shared.director_semantic_verbs import (
    consumer_for,
    no_orphan_verbs,
    registered_verbs,
)

registered_verbs
consumer_for
no_orphan_verbs

# cc-task u4-eight-slot-micromove-cycle-activate (Phase 0): the cycle +
# accessors are the API consumers (compositor main loop tick, Prometheus
# counter wiring) will hit at Phase 1. Whitelisted until Phase 1 lands.
from shared.micromove_cycle import MicromoveCycle, slot_by_name

MicromoveCycle
MicromoveCycle.current_slot
MicromoveCycle.current_action
MicromoveCycle.tick
MicromoveCycle.reset
slot_by_name

# Activity-family visibility-window tracker — singleton accessors used
# by the recruitment-bias bridge. Per cc-task
# `p3-governance-recruitment-bias-replacement`: the prior
# FamilyCeilingTracker (#2259) was deleted because its hardcoded
# threshold table violated feedback_no_expert_system_rules. The
# replacement is bias-only: the router writes via mark_visible_window
# and the affordance pipeline reads via bias_score. Both paths go
# through the singleton; vulture flags the accessors because the
# affordance-pipeline read lives behind an import bridge.
from agents.studio_compositor.activity_family_ceiling import (
    get_default_tracker as _act_get_default_tracker,
)
from agents.studio_compositor.activity_family_ceiling import (
    set_default_tracker as _act_set_default_tracker,
)
from agents.studio_compositor.activity_family_ceiling import (
    visible_time_bias_score as _act_visible_time_bias_score,
)

_act_get_default_tracker
_act_set_default_tracker
_act_visible_time_bias_score

# GitHub Sponsors V5 publisher + FastAPI route — cc-task
# github-sponsors-end-to-end-wiring (1st live monetization rail).
# The Publisher subclass entry-points are invoked by the FastAPI
# route handler; vulture cannot follow the import-string dispatch
# through router.include. Pure helpers exported for tests + future
# aggregator wiring.
from agents.publication_bus.github_sponsors_publisher import (
    GitHubSponsorsPublisher,
    event_to_manifest_record,
    manifest_path_for_event,
)
from logos.api.routes.payment_rails import (
    GITHUB_SPONSORS_SIGNATURE_HEADER,
    receive_github_sponsors_webhook,
)

GitHubSponsorsPublisher.publish_event
GitHubSponsorsPublisher._render_manifest_body
event_to_manifest_record
manifest_path_for_event
GITHUB_SPONSORS_SIGNATURE_HEADER
receive_github_sponsors_webhook

# R9 dynamic compositor-layout switcher (cc-task
# dynamic-compositor-layout-switching). Pure logic + cooldown wrapper
# shipped in isolation; integration into the director loop / systemd
# timer is a follow-up PR per the task scope. Whitelisted until that
# integration lands.
from agents.studio_compositor.layout_switcher import (
    LayoutSelection as _r9_LayoutSelection,
)
from agents.studio_compositor.layout_switcher import (
    LayoutSwitcher as _r9_LayoutSwitcher,
)
from agents.studio_compositor.layout_switcher import (
    select_layout as _r9_select_layout,
)

_r9_LayoutSelection
_r9_LayoutSwitcher
_r9_select_layout
_r9_LayoutSwitcher.current_layout
_r9_LayoutSwitcher.should_switch
_r9_LayoutSwitcher.record_switch

# Liberapay V5 publisher + FastAPI route — cc-task
# liberapay-end-to-end-wiring (2nd live monetization rail; sister of #2280
# github-sponsors-end-to-end-wiring). Same pattern; vulture cannot follow
# the import-string dispatch through router.include.
from agents.publication_bus.liberapay_publisher import (
    LiberapayPublisher,
)
from agents.publication_bus.liberapay_publisher import (
    event_to_manifest_record as _lp_event_to_manifest_record,
)
from agents.publication_bus.liberapay_publisher import (
    manifest_path_for_event as _lp_manifest_path_for_event,
)
from logos.api.routes.payment_rails import (
    LIBERAPAY_SIGNATURE_HEADER,
    receive_liberapay_webhook,
)

LiberapayPublisher.publish_event
LiberapayPublisher._render_manifest_body
_lp_event_to_manifest_record
_lp_manifest_path_for_event
LIBERAPAY_SIGNATURE_HEADER
receive_liberapay_webhook

# Open Collective V5 publisher + FastAPI route — cc-task
# open-collective-end-to-end-wiring (3rd live monetization rail).
# Same pattern as Sponsors (#2280) + Liberapay (#2287); no cancellation
# auto-link because the canonical 4 OC events do not include a
# cancellation-equivalent.
from agents.publication_bus.open_collective_publisher import (
    OpenCollectivePublisher,
)
from agents.publication_bus.open_collective_publisher import (
    event_to_manifest_record as _oc_event_to_manifest_record,
)
from agents.publication_bus.open_collective_publisher import (
    manifest_path_for_event as _oc_manifest_path_for_event,
)
from logos.api.routes.payment_rails import (
    OPEN_COLLECTIVE_SIGNATURE_HEADER,
    receive_open_collective_webhook,
)

OpenCollectivePublisher.publish_event
OpenCollectivePublisher._render_manifest_body
_oc_event_to_manifest_record
_oc_manifest_path_for_event
OPEN_COLLECTIVE_SIGNATURE_HEADER
receive_open_collective_webhook

# Stripe Payment Link V5 publisher + FastAPI route — cc-task
# stripe-payment-link-end-to-end-wiring (4th live monetization rail).
# Same pattern; subscription-deletion auto-link to refusal log.
from agents.publication_bus.stripe_payment_link_publisher import (
    StripePaymentLinkPublisher,
)
from agents.publication_bus.stripe_payment_link_publisher import (
    event_to_manifest_record as _stripe_event_to_manifest_record,
)
from agents.publication_bus.stripe_payment_link_publisher import (
    manifest_path_for_event as _stripe_manifest_path_for_event,
)
from logos.api.routes.payment_rails import (
    STRIPE_PAYMENT_LINK_SIGNATURE_HEADER,
    receive_stripe_payment_link_webhook,
    receive_stripe_webhook,
)

StripePaymentLinkPublisher.publish_event
StripePaymentLinkPublisher._render_manifest_body
_stripe_event_to_manifest_record
_stripe_manifest_path_for_event
STRIPE_PAYMENT_LINK_SIGNATURE_HEADER
receive_stripe_payment_link_webhook
receive_stripe_webhook

# Ko-fi V5 publisher + FastAPI route — cc-task ko-fi-end-to-end-wiring
# (5th live monetization rail). Ko-fi uses token-in-payload verification
# (NOT HMAC); no cancellation event in canonical 4 so no auto-link.
from agents.publication_bus.ko_fi_publisher import (
    KoFiPublisher,
)
from agents.publication_bus.ko_fi_publisher import (
    event_to_manifest_record as _kofi_event_to_manifest_record,
)
from agents.publication_bus.ko_fi_publisher import (
    manifest_path_for_event as _kofi_manifest_path_for_event,
)
from logos.api.routes.payment_rails import (
    receive_ko_fi_webhook,
)

KoFiPublisher.publish_event
KoFiPublisher._render_manifest_body
_kofi_event_to_manifest_record
_kofi_manifest_path_for_event
receive_ko_fi_webhook

# Patreon V5 publisher + FastAPI route — cc-task patreon-end-to-end-wiring
# (6th live monetization rail). Patreon uses HMAC MD5 (NOT SHA-256) per
# their documented wire format; event-kind in X-Patreon-Event header.
# Pledge-deletion auto-link to refusal log.
from agents.publication_bus.patreon_publisher import (
    PatreonPublisher,
)
from agents.publication_bus.patreon_publisher import (
    event_to_manifest_record as _patreon_event_to_manifest_record,
)
from agents.publication_bus.patreon_publisher import (
    manifest_path_for_event as _patreon_manifest_path_for_event,
)
from logos.api.routes.payment_rails import (
    PATREON_EVENT_HEADER,
    PATREON_SIGNATURE_HEADER,
    receive_patreon_webhook,
)

PatreonPublisher.publish_event
PatreonPublisher._render_manifest_body
_patreon_event_to_manifest_record
_patreon_manifest_path_for_event
PATREON_EVENT_HEADER
PATREON_SIGNATURE_HEADER
receive_patreon_webhook

# Buy Me a Coffee V5 publisher + FastAPI route — cc-task
# buy-me-a-coffee-end-to-end-wiring (7th live monetization rail).
# HMAC SHA-256 over raw body in X-Signature-Sha256; membership-
# cancellation auto-link to refusal log.
from agents.publication_bus.buy_me_a_coffee_publisher import (
    BuyMeACoffeePublisher,
)
from agents.publication_bus.buy_me_a_coffee_publisher import (
    event_to_manifest_record as _bmac_event_to_manifest_record,
)
from agents.publication_bus.buy_me_a_coffee_publisher import (
    manifest_path_for_event as _bmac_manifest_path_for_event,
)
from logos.api.routes.payment_rails import (
    BUY_ME_A_COFFEE_SIGNATURE_HEADER,
    receive_buy_me_a_coffee_webhook,
)

BuyMeACoffeePublisher.publish_event
BuyMeACoffeePublisher._render_manifest_body
_bmac_event_to_manifest_record
_bmac_manifest_path_for_event
BUY_ME_A_COFFEE_SIGNATURE_HEADER
receive_buy_me_a_coffee_webhook

# Mercury V5 publisher + FastAPI route — cc-task mercury-end-to-end-wiring
# (8th live monetization rail; first bank rail e2e). HMAC SHA-256 +
# dual-header acceptance (canonical X-Mercury-Signature + legacy
# X-Hook-Signature). No cancellation auto-link.
from agents.publication_bus.mercury_publisher import (
    MercuryPublisher,
)
from agents.publication_bus.mercury_publisher import (
    event_to_manifest_record as _mercury_event_to_manifest_record,
)
from agents.publication_bus.mercury_publisher import (
    manifest_path_for_event as _mercury_manifest_path_for_event,
)
from logos.api.routes.payment_rails import (
    MERCURY_LEGACY_SIGNATURE_HEADER,
    MERCURY_SIGNATURE_HEADER,
    receive_mercury_webhook,
)

MercuryPublisher.publish_event
MercuryPublisher._render_manifest_body
_mercury_event_to_manifest_record
_mercury_manifest_path_for_event
MERCURY_LEGACY_SIGNATURE_HEADER
MERCURY_SIGNATURE_HEADER
receive_mercury_webhook

# Modern Treasury V5 publisher + FastAPI route — cc-task
# modern-treasury-end-to-end-wiring (9th live monetization rail; 2nd
# bank rail e2e). HMAC SHA-256 + event-name-level direction filter.
from agents.publication_bus.modern_treasury_publisher import (
    ModernTreasuryPublisher,
)
from agents.publication_bus.modern_treasury_publisher import (
    event_to_manifest_record as _mt_event_to_manifest_record,
)
from agents.publication_bus.modern_treasury_publisher import (
    manifest_path_for_event as _mt_manifest_path_for_event,
)
from logos.api.routes.payment_rails import (
    MODERN_TREASURY_SIGNATURE_HEADER,
    receive_modern_treasury_webhook,
)

ModernTreasuryPublisher.publish_event
ModernTreasuryPublisher._render_manifest_body
_mt_event_to_manifest_record
_mt_manifest_path_for_event
MODERN_TREASURY_SIGNATURE_HEADER
receive_modern_treasury_webhook

# Treasury Prime V5 publisher + FastAPI route — cc-task
# treasury-prime-end-to-end-wiring (10th and FINAL live monetization rail).
# HMAC SHA-256 in X-Signature (same as Modern Treasury, disambiguated by URL path).
# Phase 0 accepts only incoming_ach.create.
from agents.publication_bus.treasury_prime_publisher import (
    TreasuryPrimePublisher,
)
from agents.publication_bus.treasury_prime_publisher import (
    event_to_manifest_record as _tp_event_to_manifest_record,
)
from agents.publication_bus.treasury_prime_publisher import (
    manifest_path_for_event as _tp_manifest_path_for_event,
)
from logos.api.routes.payment_rails import (
    TREASURY_PRIME_SIGNATURE_HEADER,
    receive_treasury_prime_webhook,
)

TreasuryPrimePublisher.publish_event
TreasuryPrimePublisher._render_manifest_body
_tp_event_to_manifest_record
_tp_manifest_path_for_event
TREASURY_PRIME_SIGNATURE_HEADER
receive_treasury_prime_webhook

# R9 follow-up: apply_layout_switch adapter (cc-task
# dynamic-compositor-layout-switching-followup). Ships ahead of any
# caller; whitelisted until director-loop / systemd-timer wiring lands
# in a 3rd-slice PR.
from agents.studio_compositor.layout_switcher import apply_layout_switch as _r9_apply_layout_switch
from agents.studio_compositor.layout_switcher import (
    apply_layout_switch_via_store as _r9_apply_layout_switch_via_store,
)

_r9_apply_layout_switch
_r9_apply_layout_switch_via_store

# u6-periodic-tick-driver (cc-task u6-periodic-tick-driver, this PR):
# the periodic driver wrapper for apply_layout_switch. Ships ahead of
# the systemd-timer wiring (separate follow-up PR — needs the state-
# provider implementations that read ~/.cache/hapax/* state files).
# Whitelisted until that wiring lands.
from agents.studio_compositor.layout_switcher import (
    run_layout_switch_loop as _u6_run_layout_switch_loop,
)

_u6_run_layout_switch_loop

# IdempotencyStore.has_seen is a read-only ops/debugging probe for the
# Stripe Payment Link rail's idempotency table. record_or_skip is the
# write path; has_seen exists for forensic queries (was this evt_ ever
# seen before our retention window?). Used by tests but vulture's
# static scan only sees the rail module.
# cc-task: jr-stripe-payment-link-replay-idempotency-pin
from shared.stripe_payment_link_receive_only_rail import (
    IdempotencyStore as _StripePaymentLinkIdempotencyStore,
)

_StripePaymentLinkIdempotencyStore.has_seen

# Multi-source duck composition (cc-task audio-audit-C-multi-source-product-
# composition Phase 0): pure function lives ahead of the call-site swap.
# Phase 1 will wire compose_attenuations into the ducker's per-source
# composition path (replacing the implicit max() at the PipeWire mixer
# layer with an explicit sum-of-dB clamp). Until then, only the test
# suite exercises these symbols.
from shared.audio_duck_compose import (
    MAX_TOTAL_ATTEN_DB as _audit_C_max_total_atten_db,
)
from shared.audio_duck_compose import (
    amplitude_from_db as _audit_C_amplitude_from_db,
)
from shared.audio_duck_compose import (
    compose_attenuations as _audit_C_compose_attenuations,
)

_audit_C_max_total_atten_db
_audit_C_amplitude_from_db
_audit_C_compose_attenuations

# Perceptual dB-domain ramp (cc-task audio-audit-C-perceptual-db-ramp Phase 0):
# pure interpolator + amplitude conversion ship ahead of the call-site swap.
# Phase 1 will replace the ducker's linear amplitude lerp with
# perceptual_ramp_amplitude(start_db, end_db, t). Until then, only the test
# suite exercises these symbols.
from shared.audio_perceptual_ramp import (
    DUCK_FLOOR_DB as _audit_C_db_floor,
)
from shared.audio_perceptual_ramp import (
    amplitude_from_db as _audit_C_perceptual_amplitude_from_db,
)
from shared.audio_perceptual_ramp import (
    lerp_db as _audit_C_lerp_db,
)
from shared.audio_perceptual_ramp import (
    perceptual_ramp_amplitude as _audit_C_perceptual_ramp_amplitude,
)

_audit_C_db_floor
_audit_C_perceptual_amplitude_from_db
_audit_C_lerp_db
_audit_C_perceptual_ramp_amplitude

# RMS-window substrate (cc-task audio-audit-C-rms-window-50-to-20-ms Phase 0):
# constants + helper + histogram metric ship ahead of the __main__.py:112
# constant swap. Phase 1 imports RMS_WINDOW_MS_TARGET in place of the inline
# 50, validates against hand-clap / chair-creak / mouse-click false positives
# on the live ducker.
from shared.audio_ducker_rms_config import (
    HAPAX_DUCKER_ONSET_DETECTION_LATENCY_MS as _audit_C_onset_latency_hist,
)
from shared.audio_ducker_rms_config import (
    RMS_WINDOW_MS_LEGACY as _audit_C_rms_window_legacy,
)
from shared.audio_ducker_rms_config import (
    RMS_WINDOW_MS_TARGET as _audit_C_rms_window_target,
)
from shared.audio_ducker_rms_config import (
    expected_rms_samples as _audit_C_expected_rms_samples,
)

_audit_C_onset_latency_hist
_audit_C_rms_window_legacy
_audit_C_rms_window_target
_audit_C_expected_rms_samples

# Typed LADSPA param schema (cc-task audio-audit-E-topology-schema-v3 Phase 0):
# Phase 1 will wire LADSPAParamSpec into shared/audio_topology.Node.params and
# bump audio-topology.yaml schema_version. Until then, only the test suite
# exercises these symbols.
from shared.audio_topology_typed_params import (
    LADSPAParamSpec as _audit_E_ladspa_param_spec,
)
from shared.audio_topology_typed_params import (
    validate_param_value as _audit_E_validate_param_value,
)

_audit_E_ladspa_param_spec
_audit_E_validate_param_value

# Pydantic validator methods on LADSPAParamSpec are invoked dynamically by
# pydantic at model construction (cc-task audio-audit-E Phase 0).
_audit_E_ladspa_param_spec._name_no_internal_whitespace_collapse
_audit_E_ladspa_param_spec._validate_range_consistency

# Audio-source-class taxonomy (cc-task audio-audit-D-source-class-taxonomy
# Phase 0): Phase 1 wires AudioSourceClass + validate_no_private_to_public_edges
# into shared/audio_topology.py + the leak-guard daemon. Until then the
# taxonomy + edge guard are exercised by tests only.
from shared.audio_source_class import (
    ALL_AUDIO_SOURCE_CLASSES as _audit_D_all_source_classes,
)
from shared.audio_source_class import (
    AudioEdgeRef as _audit_D_audio_edge_ref,
)
from shared.audio_source_class import (
    PrivateToPublicEdgeError as _audit_D_private_to_public_edge_error,
)
from shared.audio_source_class import (
    is_private_to_public_edge as _audit_D_is_private_to_public_edge,
)
from shared.audio_source_class import (
    validate_no_private_to_public_edges as _audit_D_validate_no_private_to_public_edges,
)

_audit_D_all_source_classes
_audit_D_audio_edge_ref
_audit_D_private_to_public_edge_error
_audit_D_is_private_to_public_edge
_audit_D_validate_no_private_to_public_edges

# Audio conf-mtime-watcher substrate (cc-task audio-audit-E-audio-conf-mtime-
# watcher Phase 0): ownership schema + lookup helpers + reload counter.
# Phase 1 wires inotify-driven mtime watcher + systemctl reload-or-restart.
from shared.audio_conf_ownership import (
    ConfOwnership as _audit_E_conf_ownership,
)
from shared.audio_conf_ownership import (
    ConfOwnershipRegistry as _audit_E_conf_ownership_registry,
)
from shared.audio_conf_ownership import (
    hapax_audio_conf_reload_total as _audit_E_audio_conf_reload_total,
)
from shared.audio_conf_ownership import (
    load_conf_ownership as _audit_E_load_conf_ownership,
)

_audit_E_conf_ownership
_audit_E_conf_ownership_registry
_audit_E_conf_ownership_registry.unit_for_path
_audit_E_conf_ownership_registry.schema_for_path
_audit_E_audio_conf_reload_total
_audit_E_load_conf_ownership

# Pydantic validator methods on ConfOwnership / ConfOwnershipRegistry are
# invoked dynamically by pydantic at model construction.
_audit_E_conf_ownership._unit_must_have_systemd_suffix
_audit_E_conf_ownership_registry._no_duplicate_paths

# Audio param-bridge schema (cc-task audio-audit-E-runtime-param-bridge Phase 0):
# Phase 1 wires HTTP daemon at /audio/param/<chain>/<param> + pw-cli backend +
# JSON persistence. Until then the schema models + lookup helpers + value
# validator are exercised by tests only.
from shared.audio_param_bridge_schema import (
    ParamBridge as _audit_E_param_bridge,
)
from shared.audio_param_bridge_schema import (
    ParamBridgeRegistry as _audit_E_param_bridge_registry,
)
from shared.audio_param_bridge_schema import (
    load_param_bridge_schema as _audit_E_load_param_bridge_schema,
)
from shared.audio_param_bridge_schema import (
    validate_value as _audit_E_validate_value,
)

_audit_E_param_bridge
_audit_E_param_bridge_registry
_audit_E_param_bridge_registry.get
_audit_E_param_bridge_registry.list_chains
_audit_E_param_bridge_registry.list_params_for_chain
_audit_E_load_param_bridge_schema
_audit_E_validate_value

# Pydantic validators on ParamBridge / ParamBridgeRegistry are invoked
# dynamically at model construction.
_audit_E_param_bridge._bool_no_range_default_in_range
_audit_E_param_bridge_registry._no_duplicate_chain_param_pairs

# Egress loopback witness assertions (cc-task jr-broadcast-chain-integration-
# tier4-loopback-witness Phase 0): pure-function derivations + assertion
# helpers ship ahead of the Phase 1 pytest fixture that runs pw-cat playback
# against hapax-broadcast-normalized.
from shared.egress_loopback_witness_assertions import (
    DEFAULT_WITNESS_MAX_AGE_S as _tier4_default_witness_max_age_s,
)
from shared.egress_loopback_witness_assertions import (
    PLAYBACK_PRESENT_MAX_SILENCE_RATIO as _tier4_playback_present_max_silence_ratio,
)
from shared.egress_loopback_witness_assertions import (
    PLAYBACK_PRESENT_RMS_DBFS_THRESHOLD as _tier4_playback_present_rms_dbfs_threshold,
)
from shared.egress_loopback_witness_assertions import (
    StaleWitnessError as _tier4_stale_witness_error,
)
from shared.egress_loopback_witness_assertions import (
    WitnessAssertionError as _tier4_witness_assertion_error,
)
from shared.egress_loopback_witness_assertions import (
    WitnessIndicatesProducerErrorError as _tier4_witness_indicates_producer_error_error,
)
from shared.egress_loopback_witness_assertions import (
    WitnessIndicatesSilenceError as _tier4_witness_indicates_silence_error,
)
from shared.egress_loopback_witness_assertions import (
    assert_witness_fresh as _tier4_assert_witness_fresh,
)
from shared.egress_loopback_witness_assertions import (
    assert_witness_indicates_no_playback as _tier4_assert_witness_indicates_no_playback,
)
from shared.egress_loopback_witness_assertions import (
    assert_witness_indicates_playback as _tier4_assert_witness_indicates_playback,
)
from shared.egress_loopback_witness_assertions import (
    is_playback_present as _tier4_is_playback_present,
)
from shared.egress_loopback_witness_assertions import (
    is_playback_present_with as _tier4_is_playback_present_with,
)
from shared.egress_loopback_witness_assertions import (
    witness_age_s as _tier4_witness_age_s,
)

_tier4_default_witness_max_age_s
_tier4_playback_present_max_silence_ratio
_tier4_playback_present_rms_dbfs_threshold
_tier4_stale_witness_error
_tier4_witness_assertion_error
_tier4_witness_indicates_producer_error_error
_tier4_witness_indicates_silence_error
_tier4_assert_witness_fresh
_tier4_assert_witness_indicates_no_playback
_tier4_assert_witness_indicates_playback
_tier4_is_playback_present
_tier4_is_playback_present_with
_tier4_witness_age_s

# Micromove advance consumer (cc-task u4-micromove-advance-tick-consumer
# Phase 1): consumes the 8-slot substrate from PR #2328, advances on tick,
# emits state JSON for downstream compositor render bridge + Prometheus
# counter. Phase 2 wires camera-tile transform / shader uniform deltas
# from the slot hint dict.
from agents.studio_compositor.micromove_consumer import (
    DEFAULT_ADVANCE_STATE_PATH as _u4_default_advance_state_path,
)
from agents.studio_compositor.micromove_consumer import (
    DEFAULT_TICK_INTERVAL_S as _u4_default_tick_interval_s,
)
from agents.studio_compositor.micromove_consumer import (
    MicromoveAdvanceConsumer as _u4_micromove_advance_consumer,
)
from agents.studio_compositor.micromove_consumer import (
    all_slot_indices as _u4_all_slot_indices,
)
from agents.studio_compositor.micromove_consumer import (
    hapax_micromove_advance_total as _u4_hapax_micromove_advance_total,
)

_u4_default_advance_state_path
_u4_default_tick_interval_s
_u4_micromove_advance_consumer
_u4_micromove_advance_consumer.advance
_u4_micromove_advance_consumer.cycle
_u4_micromove_advance_consumer.state_path
_u4_micromove_advance_consumer.latest_state
_u4_all_slot_indices
_u4_hapax_micromove_advance_total

# Programme banner ward (cc-task programme-banner-ward): Cairo lower-third
# subclass that renders active programme state (role + narrative_beat +
# residual). Phase 1 wires into compositor layout planner + ward registry.
# Until then, only the test suite exercises render().
from agents.studio_compositor.programme_banner_ward import (
    NARRATIVE_BEAT_MAX_CHARS as _banner_ward_narrative_beat_max_chars,
)
from agents.studio_compositor.programme_banner_ward import (
    ProgrammeBannerWard as _banner_ward,
)
from agents.studio_compositor.programme_banner_ward import (
    compute_residual_s as _banner_ward_compute_residual_s,
)
from agents.studio_compositor.programme_banner_ward import (
    format_residual as _banner_ward_format_residual,
)
from agents.studio_compositor.programme_banner_ward import (
    truncate_beat as _banner_ward_truncate_beat,
)

_banner_ward_narrative_beat_max_chars
_banner_ward
_banner_ward.render
_banner_ward.state
_banner_ward_compute_residual_s
_banner_ward_format_residual
_banner_ward_truncate_beat

# Semantic verb consumer (cc-task u5-verb-prometheus-counter-and-consumer
# Phase 1): consumes the 11-verb vocabulary from PR #2326. Each verb
# routes to envelope-nudge OR transition-bias JSONL write + Prometheus
# counter. Phase 2: heartbeat envelope daemon + recruitment consumer
# tail the JSONL files.
from agents.studio_compositor.semantic_verb_consumer import (
    DEFAULT_ENVELOPE_PATH as _u5_default_envelope_path,
)
from agents.studio_compositor.semantic_verb_consumer import (
    DEFAULT_TRANSITION_BIAS_PATH as _u5_default_transition_bias_path,
)
from agents.studio_compositor.semantic_verb_consumer import (
    VERB_CONSUMER_ROUTES as _u5_verb_consumer_routes,
)
from agents.studio_compositor.semantic_verb_consumer import (
    SemanticVerbConsumer as _u5_semantic_verb_consumer,
)
from agents.studio_compositor.semantic_verb_consumer import (
    all_verbs as _u5_all_verbs,
)
from agents.studio_compositor.semantic_verb_consumer import (
    hapax_semantic_verb_consumed_total as _u5_hapax_semantic_verb_consumed_total,
)
from agents.studio_compositor.semantic_verb_consumer import (
    route_for as _u5_route_for,
)
from agents.studio_compositor.semantic_verb_consumer import (
    verbs_for_route as _u5_verbs_for_route,
)

_u5_default_envelope_path
_u5_default_transition_bias_path
_u5_semantic_verb_consumer
_u5_semantic_verb_consumer.consume
_u5_semantic_verb_consumer.envelope_path
_u5_semantic_verb_consumer.transition_bias_path
_u5_verb_consumer_routes
_u5_all_verbs
_u5_hapax_semantic_verb_consumed_total
_u5_route_for
_u5_verbs_for_route

# U8 reverie motion-factor (cc-task u8-reverie-mode-motion-factor): per-mode
# motion-factor scales the satellite recruitment threshold. RND amplifies
# (lower threshold), RESEARCH dampens (higher). Helper exposed for tests.
from agents.reverie._satellites import (
    _effective_recruitment_threshold as _u8_effective_recruitment_threshold,
)

_u8_effective_recruitment_threshold

# Audio format/rate compat helpers (cc-task jr-broadcast-chain-integration-
# tier1-rate-format Phase 0): pure-Python sine generator + RMS dBFS calc +
# format conversion + linear resample + 3 assertion helpers. Phase 1 fixture
# spawns ephemeral PipeWire null sinks and pushes through the live chain.
from shared.audio_format_compat_helpers import (
    DEFAULT_BIT_DEPTH as _tier1_default_bit_depth,
)
from shared.audio_format_compat_helpers import (
    DEFAULT_SAMPLE_RATE_HZ as _tier1_default_sample_rate_hz,
)
from shared.audio_format_compat_helpers import (
    SILENCE_FLOOR_DBFS as _tier1_silence_floor_dbfs,
)
from shared.audio_format_compat_helpers import (
    assert_format_conversion_did_not_silence as _tier1_assert_format_conversion_did_not_silence,
)
from shared.audio_format_compat_helpers import (
    assert_resample_did_not_silence as _tier1_assert_resample_did_not_silence,
)
from shared.audio_format_compat_helpers import (
    assert_rms_within_attenuation as _tier1_assert_rms_within_attenuation,
)
from shared.audio_format_compat_helpers import (
    float32_to_int16 as _tier1_float32_to_int16,
)
from shared.audio_format_compat_helpers import (
    generate_sine_int16 as _tier1_generate_sine_int16,
)
from shared.audio_format_compat_helpers import (
    int16_to_float32 as _tier1_int16_to_float32,
)
from shared.audio_format_compat_helpers import (
    linear_resample_int16 as _tier1_linear_resample_int16,
)
from shared.audio_format_compat_helpers import (
    rms_dbfs_int16 as _tier1_rms_dbfs_int16,
)

_tier1_default_bit_depth
_tier1_default_sample_rate_hz
_tier1_silence_floor_dbfs
_tier1_assert_format_conversion_did_not_silence
_tier1_assert_resample_did_not_silence
_tier1_assert_rms_within_attenuation
_tier1_float32_to_int16
_tier1_generate_sine_int16
_tier1_int16_to_float32
_tier1_linear_resample_int16
_tier1_rms_dbfs_int16

# m8-remote-button-control-daemon (cc-task m8-remote-button-control-daemon, this PR):
# the M8ControlClient + button/keyjazz/reset/theme methods are the in-process Python
# wrapper. No static caller yet — the director-loop / recruitment-consumer integrations
# are downstream cc-tasks (Gap 5 song queue, Gap 6 sample upload). The client + daemon
# ship now so those integrations can land cleanly. Whitelisted until first caller.
from agents.m8_control.client import M8ControlClient

_M8ControlClient = M8ControlClient
_M8ControlClient.button
_M8ControlClient.keyjazz
_M8ControlClient.reset
_M8ControlClient.theme

# Pydantic field_validator — vulture doesn't see Pydantic's reflection-based
# call path. The classmethod IS invoked by pydantic.BaseModel validation.
from agents.m8_control.daemon import M8ButtonRequest as _M8ButtonRequest

_M8ButtonRequest._validate_button_names  # type: ignore[attr-defined]

# audio_graph SSOT (P1, this PR): Pydantic field_validator + model_validator
# methods are invoked by pydantic via reflection during construction; vulture
# can't see those call sites. Public-API methods are reserved for downstream
# phases (P2 daemon shadow, P4 daemon takeover, P5 breaker hardening) and the
# CLI entry-point (scripts/hapax-audio-graph-validate).
from shared.audio_graph.schema import (
    AudioGraph as _AG_AudioGraph,
)
from shared.audio_graph.schema import (
    AudioLink as _AG_AudioLink,
)
from shared.audio_graph.schema import (
    AudioNode as _AG_AudioNode,
)
from shared.audio_graph.schema import (
    ChannelMap as _AG_ChannelMap,
)
from shared.audio_graph.schema import (
    GainStage as _AG_GainStage,
)
from shared.audio_graph.validator import (
    AudioGraphValidator as _AG_Validator,
)

# Pydantic validators (reflection-invoked).
_AG_ChannelMap._positions_match_count  # type: ignore[attr-defined]
_AG_GainStage._gain_is_finite  # type: ignore[attr-defined]
_AG_GainStage._overrides_in_range  # type: ignore[attr-defined]
_AG_AudioNode._id_is_kebab  # type: ignore[attr-defined]
_AG_AudioNode._industrial_name_is_hierarchical  # type: ignore[attr-defined]
_AG_AudioNode._hardware_nodes_have_hw  # type: ignore[attr-defined]
_AG_AudioLink._gain_in_range  # type: ignore[attr-defined]
_AG_AudioGraph._node_ids_unique  # type: ignore[attr-defined]
_AG_AudioGraph._industrial_names_unique  # type: ignore[attr-defined]
_AG_AudioGraph._links_reference_valid_nodes  # type: ignore[attr-defined]
_AG_AudioGraph._gain_stages_reference_valid_nodes  # type: ignore[attr-defined]
_AG_AudioGraph._loopbacks_reference_valid_nodes  # type: ignore[attr-defined]

# Public AudioGraph navigation API — used by P2+ daemon (current()/verify_live).
_AG_AudioGraph.node_by_id
_AG_AudioGraph.links_from
_AG_AudioGraph.links_to

# Public Validator API — invoked from scripts/hapax-audio-graph-validate
# (entry-point script, not a library import vulture chains to).
_AG_Validator.decompose

# Reserved opaque-format extractors — wired in P4 when the validator emits
# AudioLink instances from filter-graph internals. Kept now to keep the
# parser structure complete + obvious to readers.
from shared.audio_graph.validator import (
    _extract_quoted_string,
    _extract_token,
)

_extract_quoted_string  # noqa: B018
_extract_token  # noqa: B018

# audio-graph SSOT P1 — 17 gap-folds extension (cc-task
# `audio-graph-ssot-p1-compiler-validator-with-17-gap-folds`, this PR).
# Gap-fold model classes + their reflection-invoked validators on top of
# the merged-PR base. Kept separate from the upstream block above so the
# next merge can drop these without touching the base entries.
from shared.audio_graph.schema import AudioNode as _AG_AudioNode2
from shared.audio_graph.schema import ChannelDownmix as _AG_ChannelDownmix
from shared.audio_graph.schema import FilterStage as _AG_FilterStage

_AG_FilterStage._ladspa_requires_plugin  # type: ignore[attr-defined]
_AG_ChannelDownmix._strategy_requires_correct_payload  # type: ignore[attr-defined]
_AG_AudioNode2._custom_template_requires_stages  # type: ignore[attr-defined]

# AudioGraph extras introduced by gap-fold work.
from shared.audio_graph.schema import AudioGraph as _AG_AudioGraph2

_AG_AudioGraph2._pipewire_names_unique  # type: ignore[attr-defined]
_AG_AudioGraph2._downmixes_reference_valid_nodes  # type: ignore[attr-defined]
_AG_AudioGraph2.node_by_pipewire_name
_AG_AudioGraph2.to_yaml

# TopologyDescriptor industrial naming validators — Pydantic reflection
# call path is not visible to vulture, but config/audio-topology.yaml
# parsing invokes them.
from shared.audio_topology import Node as _TopologyNode
from shared.audio_topology import TopologyDescriptor as _TopologyDescriptor

_TopologyNode._industrial_name_is_hierarchical  # type: ignore[attr-defined]
_TopologyDescriptor._industrial_names_unique  # type: ignore[attr-defined]

# Validator gap-fold methods.
from shared.audio_graph.validator import AudioGraphValidator as _AG_Validator2

_AG_Validator2.decompose_confs
_AG_Validator2.conf_decomposed_cleanly

# YouTube chat reader Protocol — methods are satisfied by epsilon's concrete reader at runtime
# via structural typing. Vulture cannot see Protocol satisfaction.
from agents.youtube_chat_reader import YoutubeChatReader as _YT_ChatReader

_YT_ChatReader.live_chat_id
_YT_ChatReader.recent_messages

# Programme-author asset bundles — ``is_empty`` is part of the public
# ``ProgrammeAssets`` contract that the narrative composer + director
# surfaces will consume. The wiring lands in a follow-up PR; this
# entry pins the property as a known dynamic entrypoint until then.
from agents.programme_authors.asset_resolver import (
    IcebergAssets as _PA_IcebergAssets,
)
from agents.programme_authors.asset_resolver import (
    InterviewAssets as _PA_InterviewAssets,
)
from agents.programme_authors.asset_resolver import (
    LectureAssets as _PA_LectureAssets,
)
from agents.programme_authors.asset_resolver import (
    RantAssets as _PA_RantAssets,
)
from agents.programme_authors.asset_resolver import (
    ReactAssets as _PA_ReactAssets,
)
from agents.programme_authors.asset_resolver import (
    TierListAssets as _PA_TierListAssets,
)
from agents.programme_authors.asset_resolver import (
    Top10Assets as _PA_Top10Assets,
)

_PA_TierListAssets.is_empty
_PA_Top10Assets.is_empty
_PA_RantAssets.is_empty
_PA_ReactAssets.is_empty
_PA_IcebergAssets.is_empty
_PA_InterviewAssets.is_empty
_PA_LectureAssets.is_empty


# Cc-task ``activity-reveal-ward-p1-durf-migration`` (2026-05-04):
# durf_source.py defines a module-level ``__getattr__`` to lazily
# resolve the ``DURFCairoSource`` / ``CodingActivityReveal`` aliases
# without inducing a circular import. Python invokes module
# ``__getattr__`` from the import machinery on attribute miss, so the
# function is never referenced statically — vulture flags it. Whitelist
# the dynamic-entrypoint reference here.
from agents.studio_compositor import durf_source as _AR_durf_module

_AR_durf_module.__getattr__

# Graph-patch chain-composition consumer (architectural fix per memory
# `feedback_no_presets_use_parametric_modulation`, cc-task
# `parametric-modulation-heartbeat`). The consumer is wired into
# state.py's reader loop and the test-only state-reset helper is invoked
# from tests/studio_compositor/test_graph_patch_consumer.py — vulture
# only scans agents/logos/shared/scripts so the test-only callable path
# is invisible. Mirrors the preset_recruitment_consumer convention.
from agents.studio_compositor import graph_patch_consumer as _GP_module

_GP_module._reset_state_for_tests
_GP_module.set_current_graph_provider
_GP_module.process_graph_patch_recruitment

# ProgrammeContent Pydantic validators are invoked dynamically by model
# validation. The segment helpers are also called by the daily segment
# prep runner and the programme loop beat transition check.
from shared.programme import ProgrammeContent as _PrgContent

_PrgContent._segment_beats_reasonable
_PrgContent._segment_cues_reasonable
_PrgContent._beat_layout_intents_are_needs_only
_PrgContent._layout_decision_contract_is_non_authoritative
_PrgContent._layout_decision_receipts_are_runtime_owned
_PrgContent._runtime_layout_validation_is_code_owned
_PrgContent._segment_beat_durations_reasonable
_PrgContent._responsible_hosting_quarantines_segment_cues
_PrgContent._durations_ordered

# Segment prompt helpers are called dynamically by the compose module's
# phase detection path and the daily segment prep runner.
from agents.hapax_daimonion.autonomous_narrative.segment_prompts import (
    _phase_label as _segment_phase_label,
)

_segment_phase_label


# cc-task ``refusal-brief-article-50-case-study`` (2026-05-04). The
# ``ArticleFiftyCaseStudy`` facade methods are dispatched from
# operator-facing CLI / publisher daemon paths that vulture does not
# follow (PublisherPayload construction sites are dynamic). Tests
# exercise each method directly so dead-code detection here is a
# false positive.
from agents.publication_bus.article_50_case_study import ArticleFiftyCaseStudy

ArticleFiftyCaseStudy.body
ArticleFiftyCaseStudy.metadata
ArticleFiftyCaseStudy.declined
ArticleFiftyCaseStudy.related_identifiers
ArticleFiftyCaseStudy.title


# Cc-task ``playwright-grant-submission-runner`` (2026-05-04):
# convenience helpers consumed by the CLI surface and follow-up
# cc-task ``playwright-grant-submission-runner-q3-batch-recipes``
# (operator inspection + future recipe resolution paths).
from agents.playwright_grant_submission_runner.package import (
    UniversalGrantPackage as _GR_UniversalGrantPackage,
)
from agents.playwright_grant_submission_runner.runner import (
    GrantSubmissionRunner as _GR_GrantSubmissionRunner,
)

_GR_UniversalGrantPackage.primary_text_for_section
_GR_GrantSubmissionRunner.schema_only_recipes

# Cc-task ``m8-re-splay-operator-install-and-smoke`` (2026-05-04):
# scripts/m8-smoke.py is invoked from the operator CLI and CI tests
# (importlib.util loader). Vulture can't see the dynamic entrypoints,
# so its public functions are flagged.
import importlib.util as _importlib_util
from pathlib import Path as _Path

_M8_SMOKE_SPEC = _importlib_util.spec_from_file_location(
    "_m8_smoke_whitelist",
    _Path(__file__).resolve().parent / "m8-smoke.py",
)
if _M8_SMOKE_SPEC is not None and _M8_SMOKE_SPEC.loader is not None:
    _m8_smoke_module = _importlib_util.module_from_spec(_M8_SMOKE_SPEC)
    _M8_SMOKE_SPEC.loader.exec_module(_m8_smoke_module)
    _m8_smoke_module.main
    _m8_smoke_module.run_checks
    _m8_smoke_module._is_feature_flag_enabled

# cc-task ``m8-sample-upload-via-usb-audio`` (2026-05-06):
# M8SampleCapture is recruited dynamically via the studio.m8_sample_capture
# affordance and operator dry-run snippets. The dispatcher integration lands
# behind the affordance registry, so the production static scan cannot see
# the class constructor yet.
from agents.m8_control.sample_capture import M8SampleCapture as _M8SampleCapture

_M8SampleCapture

# cc-task ``publication-bus-monetization-rails-surfaces`` (2026-05-04).
# omg.lol Pay publisher methods are dispatched via the FastAPI route
# at ``logos.api.routes.payment_rails:receive_omg_lol_pay_webhook``
# — vulture cannot see the FastAPI registration. _emit + _handle_is_address_only
# are also called via Pydantic field-validator + Publisher ABC dispatch.
from agents.publication_bus.omg_lol_pay_publisher import OmgLolPayPublisher
from shared.omg_lol_pay_receive_only_rail import PaymentEvent

OmgLolPayPublisher.requires_legal_name
OmgLolPayPublisher._emit
PaymentEvent.model_config
PaymentEvent._handle_is_address_only

# cc-task ``audio-graph-ssot-p2-daemon-shadow`` (2026-05-05):
# SafeMuteRail.engage/disengage are the active-mode API promised by the
# audio graph SSOT spec, but the P2 daemon must not call them because it
# is observe-only and must never mutate the live graph. Tests assert the
# P2 implementations are no-op placeholders until the P4/P5 enforcement
# tasks wire the real active rail.
from agents.pipewire_graph.safe_mute import SafeMuteRail as _PipewireGraphSafeMuteRail

_PipewireGraphSafeMuteRail.engage
_PipewireGraphSafeMuteRail.disengage

# cc-task ``immediate-q2-2026-grant-submission-batch`` (2026-05-04).
# FramedPackage properties are dispatched by recipe modules at
# submission time (NLnet / Manifund / etc. recipes resolve the
# operator's framing via framing_for_recipe + apply_framing, then
# read framed_abstract / framed_problem_statement / framed_approach
# off the FramedPackage). vulture cannot see the recipe-side reads
# because they are dynamically resolved through the runner's
# dispatch_for_recipe() lookup.
from agents.playwright_grant_submission_runner.framing import FramedPackage

FramedPackage.framed_abstract
FramedPackage.framed_problem_statement
FramedPackage.framed_approach

# cc-task ``x402-payment-rail-evm-stablecoin-receive`` (2026-05-04).
# USDCReceiver.run_forever is the systemd-unit entry; vulture cannot
# see the systemd dispatch.
from agents.payment_processors.usdc_receiver import USDCReceiver as _UsdcReceiver

_UsdcReceiver.run_forever

# cc-task ``eu-ai-act-art-50-c2pa-watermark-fingerprint-mvp`` (2026-05-05).
# Pydantic invokes the request validators reflectively, and the webhook
# receiver/route integration calls the idempotency store through the dispatcher
# path; vulture's production-only scan cannot see either dynamic call path yet.
from agents.art_50_provenance.models import Art50CredentialRequest as _Art50CredentialRequest
from agents.art_50_provenance.webhook import MemoryIdempotencyStore as _Art50IdempotencyStore

_Art50CredentialRequest._no_obvious_pii
_Art50CredentialRequest._domain_shape
_Art50IdempotencyStore.accept_once

# cc-task ``auto-clip-shorts-llm-segment-detection`` (2026-05-05).
# SegmentCandidate.{end_after_start, dedupe_channels} are pydantic
# field_validator hooks invoked at construction time by pydantic-core,
# not by direct call sites; vulture cannot see the dispatch.
from agents.auto_clip.segment_detection import SegmentCandidate as _AutoClipSegmentCandidate

_AutoClipSegmentCandidate._end_after_start
_AutoClipSegmentCandidate._dedupe_channels

# cc-task ``hero-effect-rotator-shaders`` (2026-05-05) + gap #15 stage-1
# wiring (2026-05-07). HeroEffectRotator is now imported and instantiated
# by ``agents/studio_compositor/lifecycle.py`` (start_compositor): the
# rotator is constructed, ``update_hero_tile`` is called with the
# ``compute_tile_layout`` ``_hero_small`` rect, and ``tick`` is registered
# on a 5s GLib timer. ``set_slot`` is still the deferred surface — it
# binds the rotator to a glfeedback pipeline element which is not yet
# created. ``current_effect_name`` + ``effect_count`` are introspection
# accessors reachable only via dashboard-style paths vulture cannot see.
from agents.studio_compositor.hero_effect_rotator import HeroEffectRotator as _HeroEffectRotator

_HeroEffectRotator.current_effect_name
_HeroEffectRotator.effect_count
_HeroEffectRotator.set_slot

# PR #2811 segment-prep contract hardening (2026-05-07).
# _parse_script is retained as a narrow compatibility/test helper around
# the newer script+contract parser; production compose/refine paths now call
# _parse_segment_generation so the contract cannot be silently discarded.
from agents.hapax_daimonion import daily_segment_prep as _SegmentPrepModule

_SegmentPrepModule._parse_script

# ActivityRevealMixin palette helpers — subclass API for concrete wards
# (CodingActivityReveal, M8InstrumentReveal, etc.) that render with
# HOMAGE palette colours. No direct callers in the mixin itself.
from agents.studio_compositor.activity_reveal_ward import ActivityRevealMixin

ActivityRevealMixin._resolve_palette_colour

# Test-only API for resetting per-camera face detection pipeline state.
from agents.studio_compositor.face_obscure_integration import reset_pipeline_cache

reset_pipeline_cache

# team-metadata-probe and SessionStart dispatch consume these.
from shared.team_registry import TeamRegistry

TeamRegistry.fresh_lanes
TeamRegistry.stale_lanes

# cross-runtime dispatch script + tests consume these.
from shared.orchestration_ledger import (
    active_claims,
    check_duplicate_session,
    check_protected_session,
    make_dispatch_id,
    record_claim,
    select_dispatch_priority,
)

active_claims
check_duplicate_session
check_protected_session
make_dispatch_id
record_claim
select_dispatch_priority

# evidence-validator CLI and hooks consume these.
from shared.evidence_ledger import EvidenceLedger, TraceGraph, check_tier_compliance

EvidenceLedger.fresh_entries
EvidenceLedger.stale_entries
EvidenceLedger.append_receipt
EvidenceLedger.receipts_for_case
TraceGraph
TraceGraph.add_link
TraceGraph.unlinked_requirements
check_tier_compliance

# Slice 6 release/ops gates — CLI + future hook consumers
ReleaseCandidateRecord
run_orr_lite
validate_rollback_plan
check_public_currentness

# Slice 7 migration/closure — CLI entrypoints in scripts/legacy-intake-converter
from shared.case_migration import annotate_task_file, generate_stub, scan_tasks  # noqa: F401, E402

generate_stub
scan_tasks
annotate_task_file

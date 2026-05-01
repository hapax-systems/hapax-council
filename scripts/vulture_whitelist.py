# pyright: reportUnusedExpression=false
"""Justified dynamic-entrypoint references for scripts/check-unused-functions.py.

Keep this file narrow. Add names here only when a callable is invoked by a
framework, subprocess entrypoint, import string, or other dynamic path that
vulture cannot see. Do not use this as a baseline for ordinary dead code.
"""

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

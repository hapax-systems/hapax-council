# pyright: reportUnusedExpression=false
"""Justified dynamic-entrypoint references for scripts/check-unused-functions.py.

Keep this file narrow. Add names here only when a callable is invoked by a
framework, subprocess entrypoint, import string, or other dynamic path that
vulture cannot see. Do not use this as a baseline for ordinary dead code.
"""

from logos.api.routes.studio import studio_audio_safe_for_broadcast, studio_egress_state
from shared.audio_topology_inspector import check_l12_forward_invariant
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
from shared.director_control_audit import DirectorControlMoveAuditRecord
from shared.director_vocabulary import DirectorVocabulary, SpectacleLaneState
from shared.grounding_provider_router import (
    build_eval_artifact,
    build_privacy_egress_preflight,
    route_candidates_for_claim,
    validate_eval_suite,
    validate_provider_registry,
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
build_feedback_fixture

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

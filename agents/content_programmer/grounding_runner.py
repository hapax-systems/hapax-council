"""Grounding runner for scheduled content-programme opportunities.

The scheduler policy is deliberately pure: it chooses the next safe route for
an already-discovered opportunity and stops before execution. This runner owns
the execution-side audit trail. It materializes canonical run envelopes,
programme boundary events, format-to-public-event decisions, and emitted
ResearchVehiclePublicEvent records while failing closed for private, dry-run,
rights, privacy, WCS, audio, egress, and monetization blockers.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import threading
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from shared.content_programme_run_store import (
    AdapterExposure,
    ClaimRef,
    CommandExecutionRecord,
    CommandExecutionTrace,
    ContentProgrammeRunEnvelope,
    ConversionCandidate,
    DirectorPlanRef,
    GateRefs,
    NestedProgrammeOutcome,
    ProgrammeBoundaryEventRef,
    RightsPrivacyPublicMode,
    RunFinalStatus,
    RunStoreEventRef,
    ScoreRef,
    SelectedFormatRef,
    SelectedOpportunityRef,
    StateRef,
    UnavailableReason,
    WcsBinding,
    WcsHealthState,
    WitnessedOutcomeRecord,
    WitnessRequirement,
    build_livestream_role_state_for_run,
)
from shared.content_programme_scheduler_policy import (
    PublicPrivateMode,
    SchedulerOpportunity,
    ScheduleRoute,
    SchedulerRuntimeState,
    SchedulerWorldSurfaceSnapshot,
    SchedulingDecision,
    decide_schedule,
)
from shared.conversion_broker import DEFAULT_PUBLIC_EVENT_PATH
from shared.format_public_event_adapter import (
    BoundaryClaimShape,
    BoundaryCuepointChapterPolicy,
    BoundaryNoExpertSystemGate,
    BoundaryPublicEventMapping,
    BoundaryType,
    ClaimKind,
    FormatPublicEventDecision,
    ProgrammeBoundaryEvent,
    adapt_format_boundary_to_public_event,
)
from shared.format_wcs_requirement_matrix import (
    ContentProgrammeFormatId,
    FormatWCSRequirementRow,
    load_format_wcs_requirement_matrix,
)
from shared.research_vehicle_public_event import ResearchVehiclePublicEvent, Surface

log = logging.getLogger(__name__)

PRODUCER = "agents.content_programmer.grounding_runner"
DEFAULT_TICK_S = 30.0


def _default_state_root() -> Path:
    env = os.environ.get("HAPAX_STATE")
    if env:
        return Path(env)
    return Path.home() / "hapax-state"


DEFAULT_RUN_ROOT = _default_state_root() / "content-programme-runs"
DEFAULT_SCHEDULED_OPPORTUNITY_PATH = DEFAULT_RUN_ROOT / "scheduled-opportunities.jsonl"
DEFAULT_RUN_ENVELOPE_PATH = DEFAULT_RUN_ROOT / "envelopes.jsonl"
DEFAULT_BOUNDARY_EVENT_PATH = DEFAULT_RUN_ROOT / "boundaries.jsonl"
DEFAULT_PUBLIC_EVENT_DECISION_PATH = DEFAULT_RUN_ROOT / "public-event-decisions.jsonl"
DEFAULT_CURSOR_PATH = Path.home() / ".cache" / "hapax" / "content-grounding-runner-cursor.json"

_PUBLIC_MODES: frozenset[PublicPrivateMode] = frozenset(
    {"public_live", "public_archive", "public_monetizable"}
)
_REFUSAL_SUPPORT_BLOCKERS = {
    "supporter_show_control_forbidden",
    "operator_request_queue_forbidden",
    "community_moderation_obligation_forbidden",
    "manual_content_calendar_forbidden",
}
_FORMAT_CLAIM_KIND: dict[str, ClaimKind] = {
    "tier_list": "ranking",
    "react_commentary": "observation",
    "ranking": "ranking",
    "comparison": "comparison",
    "review": "classification",
    "watch_along": "observation",
    "explainer": "explanation",
    "rundown": "metadata",
    "debate": "comparison",
    "bracket": "ranking",
    "what_is_this": "classification",
    "refusal_breakdown": "refusal",
    "evidence_audit": "ranking",
}
_FORMAT_BOUNDARY_TYPE: dict[str, BoundaryType] = {
    "tier_list": "rank.assigned",
    "react_commentary": "claim.made",
    "ranking": "rank.assigned",
    "comparison": "comparison.resolved",
    "review": "claim.made",
    "watch_along": "evidence.observed",
    "explainer": "claim.made",
    "rundown": "criterion.declared",
    "debate": "comparison.resolved",
    "bracket": "rank.assigned",
    "what_is_this": "claim.made",
    "refusal_breakdown": "refusal.issued",
    "evidence_audit": "rank.assigned",
}


class RunnerModel(BaseModel):
    """Strict immutable base for runner records."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class RightsConsentSnapshot(RunnerModel):
    """Runner-facing rights, consent, public, and monetization posture."""

    rights_state: str
    privacy_state: str
    public_event_policy_state: str
    monetization_state: str
    unavailable_reasons: tuple[str, ...] = Field(default_factory=tuple)


class GroundingProgrammeStep(RunnerModel):
    """One programme step that must be grounded in compositor output."""

    step_id: str
    content_ref: str
    transition: str
    ward_id: str
    ward_state: dict[str, Any] = Field(default_factory=dict)
    expected_output_ref: str | None = None


class GroundingProgrammeSequence(RunnerModel):
    """Ordered programme sequence sent through the grounding harness."""

    sequence_id: str
    programme_id: str
    format_id: str
    grounding_question: str
    steps: tuple[GroundingProgrammeStep, ...] = Field(min_length=1)


class ResolvedContent(RunnerModel):
    """Content resolver output for a programme step."""

    step_id: str
    content_ref: str
    resolved_ref: str
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CompositorTransitionResult(RunnerModel):
    """Result returned after a programme step asks the compositor to transition."""

    step_id: str
    transition_id: str
    command_ref: str
    applied: bool
    response_ref: str | None = None
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)


class WardStateUpdate(RunnerModel):
    """Ward-state mutation caused by a grounded programme step."""

    step_id: str
    ward_id: str
    state_ref: str
    applied: bool
    state: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)


class CompositorOutputWitness(RunnerModel):
    """Observed compositor output after content, transition, and ward update."""

    step_id: str
    frame_ref: str
    captured_at: datetime
    changed: bool
    nonblank: bool
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)


GroundedStepStatus = Literal["completed", "blocked"]


class GroundedProgrammeStepResult(RunnerModel):
    """Grounding result for one programme step."""

    step_id: str
    status: GroundedStepStatus
    resolved_content: ResolvedContent | None = None
    transition_result: CompositorTransitionResult | None = None
    ward_update: WardStateUpdate | None = None
    output_witness: CompositorOutputWitness | None = None
    actual_outputs: tuple[str, ...] = Field(default_factory=tuple)
    unavailable_reasons: tuple[str, ...] = Field(default_factory=tuple)
    error: str | None = None


class GroundedProgrammeSequenceResult(RunnerModel):
    """Sequence-level grounding result with the observed compositor outputs."""

    sequence_id: str
    programme_id: str
    format_id: str
    grounding_question: str
    started_at: datetime
    completed_at: datetime
    final_status: GroundedStepStatus
    step_results: tuple[GroundedProgrammeStepResult, ...]
    actual_outputs: tuple[str, ...] = Field(default_factory=tuple)
    resolved_content_refs: tuple[str, ...] = Field(default_factory=tuple)
    transition_refs: tuple[str, ...] = Field(default_factory=tuple)
    ward_state_refs: tuple[str, ...] = Field(default_factory=tuple)
    output_witness_refs: tuple[str, ...] = Field(default_factory=tuple)
    unavailable_reasons: tuple[str, ...] = Field(default_factory=tuple)


ContentResolverFn = Callable[[GroundingProgrammeStep], ResolvedContent]
TransitionTriggerFn = Callable[
    [GroundingProgrammeStep, ResolvedContent],
    CompositorTransitionResult,
]
WardStateUpdateFn = Callable[
    [GroundingProgrammeStep, ResolvedContent, CompositorTransitionResult],
    WardStateUpdate,
]
CompositorOutputWitnessFn = Callable[
    [
        GroundingProgrammeStep,
        ResolvedContent,
        CompositorTransitionResult,
        WardStateUpdate,
    ],
    CompositorOutputWitness,
]


class ProgrammeSequenceGroundingRunner:
    """Validate programme steps against real compositor-side effects.

    The runner is dependency-injected so the production loop can wire the
    resolver, compositor command client, ward-state writer, and frame witness
    reader directly, while tests can use deterministic fakes. A step only
    completes after content resolves, the transition applies, ward state is
    written, and a changed, nonblank compositor frame is witnessed.
    """

    def __init__(
        self,
        *,
        resolve_content: ContentResolverFn,
        trigger_transition: TransitionTriggerFn,
        update_ward_state: WardStateUpdateFn,
        observe_compositor_output: CompositorOutputWitnessFn,
    ) -> None:
        self._resolve_content = resolve_content
        self._trigger_transition = trigger_transition
        self._update_ward_state = update_ward_state
        self._observe_compositor_output = observe_compositor_output

    def run_sequence(
        self,
        sequence: GroundingProgrammeSequence | Mapping[str, Any],
        *,
        now: datetime | None = None,
    ) -> GroundedProgrammeSequenceResult:
        """Run a sequence and stop at the first ungrounded programme step."""

        programme_sequence = (
            sequence
            if isinstance(sequence, GroundingProgrammeSequence)
            else GroundingProgrammeSequence.model_validate(sequence)
        )
        started_at = _utc(now)
        step_results: list[GroundedProgrammeStepResult] = []

        for step in programme_sequence.steps:
            step_result = self._run_step(step)
            step_results.append(step_result)
            if step_result.status == "blocked":
                break

        completed_at = _utc(now)
        actual_outputs = tuple(
            output for result in step_results for output in result.actual_outputs
        )
        final_status: GroundedStepStatus = (
            "completed"
            if len(step_results) == len(programme_sequence.steps)
            and all(result.status == "completed" for result in step_results)
            else "blocked"
        )
        return GroundedProgrammeSequenceResult(
            sequence_id=programme_sequence.sequence_id,
            programme_id=programme_sequence.programme_id,
            format_id=programme_sequence.format_id,
            grounding_question=programme_sequence.grounding_question,
            started_at=started_at,
            completed_at=completed_at,
            final_status=final_status,
            step_results=tuple(step_results),
            actual_outputs=actual_outputs,
            resolved_content_refs=_unique_strs(
                result.resolved_content.resolved_ref
                for result in step_results
                if result.resolved_content is not None
            ),
            transition_refs=_unique_strs(
                result.transition_result.transition_id
                for result in step_results
                if result.transition_result is not None
            ),
            ward_state_refs=_unique_strs(
                result.ward_update.state_ref
                for result in step_results
                if result.ward_update is not None
            ),
            output_witness_refs=_unique_strs(
                result.output_witness.frame_ref
                for result in step_results
                if result.output_witness is not None
            ),
            unavailable_reasons=_unique_strs(
                reason for result in step_results for reason in result.unavailable_reasons
            ),
        )

    def _run_step(self, step: GroundingProgrammeStep) -> GroundedProgrammeStepResult:
        try:
            resolved = self._resolve_content(step)
        except Exception as exc:  # noqa: BLE001
            return _blocked_grounded_step(
                step,
                reasons=("content_resolution_failed",),
                error=f"{type(exc).__name__}: {exc}",
            )

        blockers = _content_resolution_blockers(step, resolved)
        if blockers:
            return _blocked_grounded_step(step, resolved=resolved, reasons=blockers)

        try:
            transition = self._trigger_transition(step, resolved)
        except Exception as exc:  # noqa: BLE001
            return _blocked_grounded_step(
                step,
                resolved=resolved,
                reasons=("transition_failed",),
                error=f"{type(exc).__name__}: {exc}",
            )

        blockers = _transition_blockers(step, transition)
        if blockers:
            return _blocked_grounded_step(
                step,
                resolved=resolved,
                transition=transition,
                reasons=blockers,
            )

        try:
            ward_update = self._update_ward_state(step, resolved, transition)
        except Exception as exc:  # noqa: BLE001
            return _blocked_grounded_step(
                step,
                resolved=resolved,
                transition=transition,
                reasons=("ward_state_update_failed",),
                error=f"{type(exc).__name__}: {exc}",
            )

        blockers = _ward_state_blockers(step, ward_update)
        if blockers:
            return _blocked_grounded_step(
                step,
                resolved=resolved,
                transition=transition,
                ward_update=ward_update,
                reasons=blockers,
            )

        try:
            witness = self._observe_compositor_output(step, resolved, transition, ward_update)
        except Exception as exc:  # noqa: BLE001
            return _blocked_grounded_step(
                step,
                resolved=resolved,
                transition=transition,
                ward_update=ward_update,
                reasons=("compositor_output_witness_failed",),
                error=f"{type(exc).__name__}: {exc}",
            )

        blockers = _compositor_output_blockers(step, witness)
        if blockers:
            return _blocked_grounded_step(
                step,
                resolved=resolved,
                transition=transition,
                ward_update=ward_update,
                witness=witness,
                reasons=blockers,
            )

        actual_outputs = (
            f"content:{resolved.resolved_ref}",
            f"transition:{transition.transition_id}",
            f"ward_state:{ward_update.state_ref}",
            f"compositor_output:{witness.frame_ref}",
        )
        return GroundedProgrammeStepResult(
            step_id=step.step_id,
            status="completed",
            resolved_content=resolved,
            transition_result=transition,
            ward_update=ward_update,
            output_witness=witness,
            actual_outputs=actual_outputs,
        )


class ContentProgrammeRun(RunnerModel):
    """Compact run record for the content-programming grounding loop.

    The canonical persisted payload remains ``ContentProgrammeRunEnvelope``.
    This record is the runner's operational summary: it exposes the fields the
    grounding loop must reason over without duplicating the full envelope graph.
    """

    schema_version: Literal[1] = 1
    run_id: str
    programme_id: str
    scheduler_decision_id: str
    opportunity_id: str
    format_id: str
    grounding_question: str
    selected_substrates: tuple[str, ...] = Field(default_factory=tuple)
    selected_inputs: tuple[str, ...] = Field(default_factory=tuple)
    rights_consent: RightsConsentSnapshot
    director_plan_ref: str
    director_move_refs: tuple[str, ...] = Field(default_factory=tuple)
    requested_public_private_mode: PublicPrivateMode
    public_private_mode: PublicPrivateMode
    expected_outputs: tuple[str, ...] = Field(default_factory=tuple)
    actual_outputs: tuple[str, ...] = Field(default_factory=tuple)
    score_refs: tuple[str, ...] = Field(default_factory=tuple)
    refusal_refs: tuple[str, ...] = Field(default_factory=tuple)
    correction_refs: tuple[str, ...] = Field(default_factory=tuple)
    unavailable_reasons: tuple[str, ...] = Field(default_factory=tuple)
    run_envelope_ref: str


class ScheduledProgrammeOpportunity(RunnerModel):
    """One scheduler-consumed opportunity plus runner execution inputs."""

    opportunity: SchedulerOpportunity
    world: SchedulerWorldSurfaceSnapshot = Field(default_factory=SchedulerWorldSurfaceSnapshot)
    decision: SchedulingDecision | None = None
    runtime_state: SchedulerRuntimeState | None = None
    format_row: FormatWCSRequirementRow | None = None
    selected_input_refs: tuple[str, ...] = Field(default_factory=tuple)
    substrate_refs: tuple[str, ...] = Field(default_factory=tuple)
    semantic_capability_refs: tuple[str, ...] = Field(default_factory=tuple)
    director_snapshot_ref: str | None = None
    director_plan_ref: str | None = None
    director_move_refs: tuple[str, ...] = Field(default_factory=tuple)
    expected_outputs: tuple[str, ...] = Field(default_factory=tuple)
    broadcast_refs: tuple[str, ...] = Field(default_factory=tuple)
    archive_refs: tuple[str, ...] = Field(default_factory=tuple)

    def resolved_decision(self, *, now: datetime | None = None) -> SchedulingDecision:
        """Return the supplied scheduler decision or evaluate the scheduler policy."""

        if self.decision is not None:
            return self.decision
        return decide_schedule(
            self.opportunity,
            self.world,
            runtime_state=self.runtime_state,
            format_row=self.format_row,
            now=now,
        )


class GroundingRunnerMetrics(RunnerModel):
    """Low-cardinality counters recorded by one runner tick."""

    scheduled_seen: int = 0
    processed: int = 0
    skipped_existing: int = 0
    format_frequency: dict[str, int] = Field(default_factory=dict)
    completion_by_status: dict[str, int] = Field(default_factory=dict)
    audience_events_by_surface: dict[str, int] = Field(default_factory=dict)
    artifact_events: int = 0
    support_refusals: int = 0
    rights_refusals: int = 0
    grounding_corrections: int = 0
    public_events_emitted: int = 0
    public_events_refused: int = 0


class GroundingRunnerBatch(RunnerModel):
    """Structured result from one runner tick."""

    scheduled_seen: int
    processed: int
    skipped_existing: int
    runs: tuple[ContentProgrammeRun, ...] = Field(default_factory=tuple)
    envelopes: tuple[ContentProgrammeRunEnvelope, ...] = Field(default_factory=tuple)
    boundary_events: tuple[ProgrammeBoundaryEvent, ...] = Field(default_factory=tuple)
    public_event_decisions: tuple[FormatPublicEventDecision, ...] = Field(default_factory=tuple)
    public_events: tuple[ResearchVehiclePublicEvent, ...] = Field(default_factory=tuple)
    metrics: GroundingRunnerMetrics


class _MaterializedRun(RunnerModel):
    summary: ContentProgrammeRun
    envelope: ContentProgrammeRunEnvelope
    boundary_events: tuple[ProgrammeBoundaryEvent, ...]
    public_event_decisions: tuple[FormatPublicEventDecision, ...]
    public_events: tuple[ResearchVehiclePublicEvent, ...]


class ContentProgrammingGroundingRunner:
    """Execute scheduled programme opportunities into append-only audit logs."""

    def __init__(
        self,
        *,
        scheduled_opportunity_path: Path = DEFAULT_SCHEDULED_OPPORTUNITY_PATH,
        run_envelope_path: Path = DEFAULT_RUN_ENVELOPE_PATH,
        boundary_event_path: Path = DEFAULT_BOUNDARY_EVENT_PATH,
        public_event_decision_path: Path = DEFAULT_PUBLIC_EVENT_DECISION_PATH,
        public_event_path: Path = DEFAULT_PUBLIC_EVENT_PATH,
        cursor_path: Path = DEFAULT_CURSOR_PATH,
        tick_s: float = DEFAULT_TICK_S,
    ) -> None:
        self.scheduled_opportunity_path = scheduled_opportunity_path
        self.run_envelope_path = run_envelope_path
        self.boundary_event_path = boundary_event_path
        self.public_event_decision_path = public_event_decision_path
        self.public_event_path = public_event_path
        self.cursor_path = cursor_path
        self.tick_s = max(1.0, tick_s)
        self._stop_evt = threading.Event()

    def run_once(
        self,
        scheduled: Sequence[ScheduledProgrammeOpportunity | Mapping[str, Any]] | None = None,
        *,
        now: datetime | None = None,
    ) -> GroundingRunnerBatch:
        """Process unseen scheduled opportunities once.

        When ``scheduled`` is omitted, the runner reads
        ``scheduled_opportunity_path``. A scheduled record may carry either a
        scheduler decision or just the scheduler opportunity plus world snapshot;
        in the latter case this method calls the scheduler policy exactly once.
        """

        resolved_now = _utc(now)
        items = (
            tuple(_coerce_scheduled(item) for item in scheduled)
            if scheduled is not None
            else (tuple(_iter_scheduled_opportunities(self.scheduled_opportunity_path)))
        )
        processed_keys = _load_cursor(self.cursor_path)
        known_run_ids = _load_jsonl_ids(self.run_envelope_path, "run_id")
        metrics = GroundingRunnerMetrics(scheduled_seen=len(items))
        materialized: list[_MaterializedRun] = []
        skipped = 0

        for item in items:
            decision = item.resolved_decision(now=resolved_now)
            key = _scheduled_key(item.opportunity, decision)
            run_id = _run_id(item.opportunity, decision)
            if key in processed_keys or run_id in known_run_ids:
                skipped += 1
                continue
            run = _materialize_run(item, decision, now=resolved_now)
            materialized.append(run)
            processed_keys.add(key)
            known_run_ids.add(run.envelope.run_id)
            metrics = _record_metrics(metrics, run, item, decision)

        if materialized:
            _append_jsonl_models(self.run_envelope_path, [run.envelope for run in materialized])
            _append_jsonl_models(
                self.boundary_event_path,
                [boundary for run in materialized for boundary in run.boundary_events],
            )
            _append_jsonl_models(
                self.public_event_decision_path,
                [decision for run in materialized for decision in run.public_event_decisions],
            )
            _append_jsonl_models(
                self.public_event_path,
                [event for run in materialized for event in run.public_events],
            )
            _save_cursor(self.cursor_path, processed_keys)
        metrics = metrics.model_copy(
            update={
                "processed": len(materialized),
                "skipped_existing": skipped,
            }
        )
        return GroundingRunnerBatch(
            scheduled_seen=len(items),
            processed=len(materialized),
            skipped_existing=skipped,
            runs=tuple(run.summary for run in materialized),
            envelopes=tuple(run.envelope for run in materialized),
            boundary_events=tuple(
                boundary for run in materialized for boundary in run.boundary_events
            ),
            public_event_decisions=tuple(
                decision for run in materialized for decision in run.public_event_decisions
            ),
            public_events=tuple(event for run in materialized for event in run.public_events),
            metrics=metrics,
        )

    def run_forever(self) -> None:
        """Run the append-only grounding loop until SIGTERM/SIGINT."""

        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, lambda *_: self.stop())
            except ValueError:
                pass
        log.info(
            "content_programming_grounding_runner starting scheduled=%s envelopes=%s "
            "boundaries=%s public_decisions=%s cursor=%s tick=%.1fs",
            self.scheduled_opportunity_path,
            self.run_envelope_path,
            self.boundary_event_path,
            self.public_event_decision_path,
            self.cursor_path,
            self.tick_s,
        )
        while not self._stop_evt.is_set():
            try:
                self.run_once()
            except Exception:  # noqa: BLE001
                log.exception("content grounding runner tick failed; continuing")
            self._stop_evt.wait(self.tick_s)

    def stop(self) -> None:
        self._stop_evt.set()


def _materialize_run(
    item: ScheduledProgrammeOpportunity,
    decision: SchedulingDecision,
    *,
    now: datetime,
) -> _MaterializedRun:
    opportunity = item.opportunity
    route = decision.route
    requested_mode = opportunity.public_mode
    effective_mode = _mode_for_route(route, requested_mode=requested_mode)
    unavailable = _unavailable_reasons(item, decision, effective_mode=effective_mode)
    final_status = _final_status(route, decision, unavailable)
    evidence_refs = _evidence_refs(item)
    evidence_envelope_refs = tuple(f"ee:{ref}" for ref in evidence_refs)
    run_id = _run_id(opportunity, decision)
    programme_id = _sanitize_id(f"programme:{opportunity.format_id}:{opportunity.opportunity_id}")
    condition_id = "condition_content_programming_grounding_runner"
    rights_posture = _rights_privacy_public_mode(
        item,
        decision,
        requested_mode=requested_mode,
        effective_mode=effective_mode,
        unavailable=unavailable,
    )
    selected = CommandExecutionRecord(
        record_id=f"selected:{run_id}",
        state="selected" if decision.selected else "blocked_by_policy",
        occurred_at=now,
        refs=(decision.decision_id,),
    )
    commanded = CommandExecutionRecord(
        record_id=f"commanded:{run_id}",
        state=_command_state(route, final_status),
        occurred_at=now,
        refs=(run_id, decision.decision_id),
    )
    witnessed = WitnessedOutcomeRecord(
        outcome_id=f"outcome:{run_id}:grounding",
        witness_state="witness_verified" if evidence_envelope_refs else "witness_unavailable",
        evidence_envelope_refs=evidence_envelope_refs,
        capability_outcome_ref=f"coe:{run_id}:grounding",
        posterior_update_allowed=bool(evidence_envelope_refs and final_status == "completed"),
    )
    substrate_refs = _substrate_refs(item)
    director_snapshot_ref = (
        item.director_snapshot_ref
        or f"director-snapshot:{opportunity.format_id}:{opportunity.opportunity_id}"
    )
    role_state = build_livestream_role_state_for_run(
        run_id=run_id,
        public_private_mode=effective_mode,
        final_status=final_status,
        grounding_question=opportunity.grounding_question,
        director_snapshot_ref=director_snapshot_ref,
        available_wcs_surfaces=tuple(
            dict.fromkeys(
                (*evidence_refs,)
                if effective_mode == "private"
                else (*substrate_refs, *evidence_refs, *item.broadcast_refs)
            )
        ),
        blocked_wcs_surfaces=tuple(f"blocker:{reason}" for reason in unavailable),
        private_only_wcs_surfaces=substrate_refs if effective_mode == "private" else (),
        monetization_ready=rights_posture.monetization_state == "ready",
    )
    run = ContentProgrammeRunEnvelope(
        run_id=run_id,
        programme_id=programme_id,
        opportunity_decision_id=decision.decision_id,
        format_id=opportunity.format_id,
        condition_id=condition_id,
        selected_at=now,
        selected_by="content_programme_scheduler_policy",
        grounding_question=opportunity.grounding_question,
        requested_public_private_mode=requested_mode,
        public_private_mode=effective_mode,
        rights_privacy_public_mode=rights_posture,
        role_state=role_state,
        selected_opportunity=SelectedOpportunityRef(
            decision_id=decision.decision_id,
            decision_ref=f"content-programme-scheduler-policy:{decision.decision_id}",
            opportunity_id=opportunity.opportunity_id,
            content_opportunity_tuple_ref=f"content-opportunity:{opportunity.opportunity_id}",
            posterior_sample_refs=tuple(f"posterior:{key}" for key in opportunity.source_priors),
            reward_vector_ref=f"reward:{opportunity.decision_id}",
        ),
        selected_format=SelectedFormatRef(
            format_id=opportunity.format_id,
            registry_ref="schemas/content-programme-format.schema.json",
            row_ref=f"schemas/content-programme-format.schema.json#{opportunity.format_id}",
            grounding_question=opportunity.grounding_question,
            grounding_attempt_types=_grounding_attempt_types(opportunity.format_id),
        ),
        broadcast_refs=item.broadcast_refs if effective_mode == "public_live" else (),
        archive_refs=item.archive_refs
        if effective_mode in {"public_archive", "public_monetizable"}
        else (),
        selected_input_refs=_selected_input_refs(item),
        substrate_refs=substrate_refs,
        semantic_capability_refs=_semantic_capability_refs(item),
        director_plan=DirectorPlanRef(
            director_snapshot_ref=director_snapshot_ref,
            director_plan_ref=item.director_plan_ref
            or f"director-plan:{opportunity.format_id}:{decision.route.value}",
            director_move_refs=_director_move_refs(item),
            condition_id=condition_id,
        ),
        gate_refs=GateRefs(
            grounding_gate_refs=(
                (f"grounding-gate:{run_id}:claim-shape",)
                if evidence_refs and "missing_grounding_gate" not in unavailable
                else ()
            ),
            rights_gate_refs=(f"rights-gate:{run_id}:{rights_posture.rights_state}",),
            privacy_gate_refs=(f"privacy-gate:{run_id}:{rights_posture.privacy_state}",),
            monetization_gate_refs=(
                (f"monetization-gate:{run_id}:ready",)
                if rights_posture.monetization_state == "ready"
                else ()
            ),
            public_event_gate_refs=(f"public-event-gate:{run_id}:{effective_mode}",),
        ),
        wcs=WcsBinding(
            semantic_substrate_refs=substrate_refs,
            grounding_contract_refs=(f"grounding-contract:{opportunity.format_id}",),
            evidence_envelope_refs=evidence_envelope_refs,
            witness_requirements=(
                WitnessRequirement(
                    requirement_id=f"witness-required:{run_id}:grounding",
                    substrate_ref=_first_or(_substrate_refs(item), f"substrate:{run_id}"),
                    required_witness_refs=(f"witness:{run_id}:grounding",),
                    missing_witness_refs=(
                        (f"witness:{run_id}:grounding",) if "witness_missing" in unavailable else ()
                    ),
                ),
            ),
            capability_outcome_refs=(f"coe:{run_id}:grounding",),
            health_state=_wcs_health(
                item.world, effective_mode=effective_mode, unavailable=unavailable
            ),
            unavailable_reasons=unavailable,
            public_private_posture=rights_posture,
        ),
        events=(
            RunStoreEventRef(
                event_id=f"event:{run_id}:selected", sequence=0, event_type="selected"
            ),
            RunStoreEventRef(event_id=f"event:{run_id}:started", sequence=1, event_type="started"),
        ),
        claims=(
            ClaimRef(
                claim_id=f"claim:{run_id}:grounding",
                evidence_refs=evidence_refs,
                evidence_envelope_refs=evidence_envelope_refs,
                uncertainty_ref=f"uncertainty:{run_id}:scope",
                posterior_state_ref=(
                    f"posterior-state:{run_id}:grounding"
                    if evidence_envelope_refs and final_status == "completed"
                    else None
                ),
            ),
        )
        if evidence_refs
        else (),
        uncertainties=(
            StateRef(
                state_id=f"uncertainty:{run_id}:scope",
                reason="Claim scope is limited to the selected inputs and witnessed evidence.",
                evidence_refs=evidence_refs,
            ),
        ),
        refusals=_refusal_refs(run_id, final_status, evidence_refs, unavailable),
        corrections=_correction_refs(run_id, final_status, evidence_refs),
        scores=_score_refs(run_id, final_status, evidence_refs),
        conversion_candidates=(),
        nested_outcomes=(),
        command_execution=CommandExecutionTrace(
            selected=selected,
            commanded_states=(commanded,),
            executed_states=(commanded,),
            witnessed_outcomes=(witnessed,),
        ),
        witnessed_outcomes=(witnessed,),
        adapter_exposure=AdapterExposure(ref=f"adapter-exposure:{run_id}"),
        final_status=final_status,
    )
    boundaries = _build_boundaries(run, item, decision, now=now, unavailable=unavailable)
    public_decisions = tuple(
        adapt_format_boundary_to_public_event(run, boundary, generated_at=now)
        for boundary in boundaries
    )
    public_events = tuple(
        cast("ResearchVehiclePublicEvent", adapter_decision.public_event)
        for adapter_decision in public_decisions
        if adapter_decision.public_event is not None
    )
    boundary_refs = tuple(
        _boundary_ref(boundary, adapter_decision)
        for boundary, adapter_decision in zip(boundaries, public_decisions, strict=True)
    )
    run = _finalize_run(
        run,
        boundary_refs=boundary_refs,
        public_events=public_events,
        final_status=final_status,
        unavailable=unavailable,
    )
    summary = _summary_for_run(
        run,
        item,
        decision,
        expected_outputs=_expected_outputs(item, run),
        actual_outputs=_actual_outputs(boundaries, public_events, public_decisions),
        unavailable=unavailable,
    )
    return _MaterializedRun(
        summary=summary,
        envelope=run,
        boundary_events=boundaries,
        public_event_decisions=public_decisions,
        public_events=public_events,
    )


def _finalize_run(
    run: ContentProgrammeRunEnvelope,
    *,
    boundary_refs: tuple[ProgrammeBoundaryEventRef, ...],
    public_events: tuple[ResearchVehiclePublicEvent, ...],
    final_status: RunFinalStatus,
    unavailable: tuple[UnavailableReason, ...],
) -> ContentProgrammeRunEnvelope:
    public_event_refs = tuple(event.event_id for event in public_events)
    policy_state = (
        "linked"
        if public_event_refs
        else "held"
        if run.public_private_mode in _PUBLIC_MODES
        else "not_public"
    )
    conversion = ConversionCandidate(
        candidate_id=f"conversion:{run.run_id}:archive-replay",
        conversion_type="archive_replay",
        state="linked" if public_event_refs else "held",
        research_vehicle_public_event_ref=_first(public_event_refs),
        unavailable_reasons=unavailable if not public_event_refs else (),
    )
    run_events = (
        *run.events,
        RunStoreEventRef(
            event_id=f"event:{run.run_id}:boundary-emitted",
            sequence=2,
            event_type="boundary_emitted",
        ),
        RunStoreEventRef(
            event_id=f"event:{run.run_id}:completed",
            sequence=3,
            event_type=_terminal_event_type(final_status),
        ),
    )
    posture = run.rights_privacy_public_mode.model_copy(
        update={"public_event_policy_state": policy_state}
    )
    return run.model_copy(
        update={
            "rights_privacy_public_mode": posture,
            "events": run_events,
            "boundary_event_refs": boundary_refs,
            "conversion_candidates": (conversion,),
            "nested_outcomes": _nested_outcomes(
                run,
                public_event_refs=public_event_refs,
                boundary_refs=boundary_refs,
                conversion_candidate_ref=conversion.candidate_id,
                unavailable=unavailable,
            ),
        }
    )


def _build_boundaries(
    run: ContentProgrammeRunEnvelope,
    item: ScheduledProgrammeOpportunity,
    decision: SchedulingDecision,
    *,
    now: datetime,
    unavailable: tuple[UnavailableReason, ...],
) -> tuple[ProgrammeBoundaryEvent, ...]:
    boundary_types: list[BoundaryType] = ["programme.started"]
    if decision.route is ScheduleRoute.REFUSAL or run.final_status == "refused":
        boundary_types.append("refusal.issued")
    elif decision.route is ScheduleRoute.CORRECTION or run.final_status == "corrected":
        boundary_types.append("correction.made")
    else:
        boundary_types.append(_FORMAT_BOUNDARY_TYPE.get(run.format_id, "claim.made"))
    if run.public_private_mode in {"public_archive", "public_monetizable"}:
        boundary_types.append("chapter.boundary")
        boundary_types.append("artifact.candidate")
    elif run.public_private_mode == "public_live":
        boundary_types.append("live_cuepoint.candidate")
    boundary_types.append("programme.ended")
    return tuple(
        _boundary(
            run,
            item,
            decision,
            boundary_type=boundary_type,
            sequence=index,
            now=now,
            unavailable=unavailable,
        )
        for index, boundary_type in enumerate(boundary_types, start=1)
    )


def _boundary(
    run: ContentProgrammeRunEnvelope,
    item: ScheduledProgrammeOpportunity,
    decision: SchedulingDecision,
    *,
    boundary_type: BoundaryType,
    sequence: int,
    now: datetime,
    unavailable: tuple[UnavailableReason, ...],
) -> ProgrammeBoundaryEvent:
    status_claim_kind = _claim_kind(run.format_id, boundary_type)
    public_claim_allowed = (
        decision.public_claim_allowed
        and run.public_private_mode in _PUBLIC_MODES
        and "unsupported_claim" not in unavailable
        and "grounding_gate_failed" not in unavailable
    )
    if boundary_type == "refusal.issued":
        gate_state = "refusal"
        claim_allowed = False
        public_claim_allowed = False
    elif boundary_type == "correction.made":
        gate_state = "correction_required"
        claim_allowed = False
    elif "grounding_gate_failed" in unavailable or "unsupported_claim" in unavailable:
        gate_state = "fail"
        claim_allowed = False
    elif run.public_private_mode == "dry_run":
        gate_state = "dry_run"
        claim_allowed = True
    elif run.public_private_mode == "private":
        gate_state = "private_only"
        claim_allowed = True
    else:
        gate_state = "pass"
        claim_allowed = True
    boundary_id = _sanitize_id(f"pbe:{run.run_id}:{sequence:03d}:{boundary_type}")
    duplicate_key = _sanitize_id(f"{run.programme_id}:{run.run_id}:{boundary_type}:{sequence:03d}")
    return ProgrammeBoundaryEvent(
        boundary_id=boundary_id,
        emitted_at=now,
        programme_id=run.programme_id,
        run_id=run.run_id,
        format_id=run.format_id,
        sequence=sequence,
        boundary_type=boundary_type,
        public_private_mode=run.public_private_mode,
        grounding_question=run.grounding_question,
        summary=_boundary_summary(run, boundary_type),
        evidence_refs=_boundary_evidence_refs(run, item),
        no_expert_system_gate=BoundaryNoExpertSystemGate(
            gate_ref=_first(run.gate_refs.grounding_gate_refs),
            gate_state=gate_state,
            claim_allowed=claim_allowed,
            public_claim_allowed=public_claim_allowed,
            infractions=tuple(decision.blocked_reasons),
        ),
        claim_shape=BoundaryClaimShape(
            claim_kind=status_claim_kind,
            authority_ceiling="evidence_bound"
            if claim_allowed or boundary_type in {"refusal.issued", "correction.made"}
            else "internal_only",
            confidence_label=_confidence_label(boundary_type, unavailable),
            uncertainty=_uncertainty(run, unavailable),
            scope_limit=(
                "Limited to the selected source bundle, WCS evidence, and explicit "
                "programme boundary."
            ),
        ),
        public_event_mapping=_public_event_mapping(run, boundary_type, unavailable),
        cuepoint_chapter_policy=_cuepoint_chapter_policy(run, boundary_type, unavailable),
        dry_run_unavailable_reasons=(
            unavailable if run.public_private_mode in {"private", "dry_run"} else ()
        ),
        duplicate_key=duplicate_key,
    )


def _public_event_mapping(
    run: ContentProgrammeRunEnvelope,
    boundary_type: BoundaryType,
    unavailable: tuple[UnavailableReason, ...],
) -> BoundaryPublicEventMapping:
    event_type = "programme.boundary"
    state_kind = "programme_state"
    if boundary_type == "chapter.boundary":
        event_type = "chapter.marker"
        state_kind = "chapter"
    elif boundary_type == "clip.candidate":
        event_type = "shorts.candidate"
        state_kind = "short_form"
    elif boundary_type in {"artifact.candidate", "refusal.issued", "correction.made"}:
        event_type = "publication.artifact"
        state_kind = "archive_artifact"

    allowed = _allowed_surfaces(run, boundary_type)
    denied = _denied_surfaces(run, allowed)
    return BoundaryPublicEventMapping(
        internal_only=False,
        research_vehicle_event_type=event_type,
        state_kind=state_kind,
        source_substrate_id="programme_grounding_runner",
        allowed_surfaces=allowed,
        denied_surfaces=denied,
        fallback_action=_fallback_action(run.public_private_mode, unavailable),
        unavailable_reasons=unavailable,
    )


def _cuepoint_chapter_policy(
    run: ContentProgrammeRunEnvelope,
    boundary_type: BoundaryType,
    unavailable: tuple[UnavailableReason, ...],
) -> BoundaryCuepointChapterPolicy:
    chapterish = boundary_type in {"chapter.boundary", "claim.made", "rank.assigned"}
    return BoundaryCuepointChapterPolicy(
        live_ad_cuepoint_allowed=run.public_private_mode == "public_live"
        and "egress_blocked" not in unavailable
        and "audio_blocked" not in unavailable,
        vod_chapter_allowed=run.public_private_mode in {"public_archive", "public_monetizable"}
        and chapterish,
        live_cuepoint_distinct_from_vod_chapter=True,
        chapter_label=_chapter_label(run, boundary_type) if chapterish else None,
        timecode=f"00:{max(0, (boundary_type != 'programme.started') * 30):02d}",
        cuepoint_unavailable_reason="egress_blocked" if "egress_blocked" in unavailable else None,
    )


def _rights_privacy_public_mode(
    item: ScheduledProgrammeOpportunity,
    decision: SchedulingDecision,
    *,
    requested_mode: PublicPrivateMode,
    effective_mode: PublicPrivateMode,
    unavailable: tuple[UnavailableReason, ...],
) -> RightsPrivacyPublicMode:
    return RightsPrivacyPublicMode(
        requested_mode=requested_mode,
        effective_mode=effective_mode,
        rights_state=_rights_state(item.opportunity.rights_state, unavailable),
        privacy_state=_privacy_state(item.world, effective_mode, unavailable),
        public_event_policy_state="required" if effective_mode in _PUBLIC_MODES else "held",
        monetization_state=_monetization_state(item, decision, effective_mode, unavailable),
        unavailable_reasons=unavailable,
    )


def _unavailable_reasons(
    item: ScheduledProgrammeOpportunity,
    decision: SchedulingDecision,
    *,
    effective_mode: PublicPrivateMode,
) -> tuple[UnavailableReason, ...]:
    reasons: list[UnavailableReason] = []
    if effective_mode == "private":
        reasons.append("private_mode")
    elif effective_mode == "dry_run":
        reasons.append("dry_run_mode")
    if not item.opportunity.evidence_refs and not item.world.evidence_refs:
        reasons.append("missing_evidence_ref")
    for blocker in decision.blocked_reasons:
        reasons.extend(_blocker_to_unavailable(blocker))
    if decision.route is ScheduleRoute.REFUSAL:
        reasons.append("unsupported_claim")
    return _unique_unavailable(reasons)


def _blocker_to_unavailable(blocker: str) -> tuple[UnavailableReason, ...]:
    text = blocker.lower()
    reasons: list[UnavailableReason] = []
    if "evidence" in text:
        reasons.append("missing_evidence_ref")
    if "grounding" in text or "expert_system" in text or "claim" in text or "unsupported" in text:
        reasons.append("grounding_gate_failed")
    if "witness" in text:
        reasons.append("witness_missing")
    if "rights" in text or "media_reference" in text:
        reasons.append("rights_blocked")
    if "third_party" in text or "media_reference" in text:
        reasons.append("third_party_media_blocked")
    if "privacy" in text or "consent" in text:
        reasons.append("privacy_blocked")
    if "egress" in text or "live_provider" in text:
        reasons.append("egress_blocked")
    if "audio" in text:
        reasons.append("audio_blocked")
    if "monetization" in text:
        reasons.extend(("monetization_blocked", "monetization_readiness_missing"))
    if "public_event" in text or "research_vehicle" in text:
        reasons.append("research_vehicle_public_event_missing")
    if "archive" in text:
        reasons.append("archive_missing")
    if "stale" in text:
        reasons.append("source_stale")
    if "surface" in text or "wcs_health" in text or "scrim" in text or "profile" in text:
        reasons.append("world_surface_blocked")
    if blocker in _REFUSAL_SUPPORT_BLOCKERS:
        reasons.append("operator_review_required")
    return tuple(reasons)


def _final_status(
    route: ScheduleRoute,
    decision: SchedulingDecision,
    unavailable: tuple[UnavailableReason, ...],
) -> RunFinalStatus:
    if route is ScheduleRoute.REFUSAL:
        return "refused"
    if route is ScheduleRoute.CORRECTION:
        return "corrected"
    hard_blockers = {
        "rights_blocked",
        "privacy_blocked",
        "egress_blocked",
        "audio_blocked",
        "monetization_blocked",
        "world_surface_blocked",
        "witness_missing",
        "missing_evidence_ref",
        "grounding_gate_failed",
        "unsupported_claim",
    }
    if decision.public_route_blocked or hard_blockers.intersection(unavailable):
        return "blocked"
    return "completed"


def _summary_for_run(
    run: ContentProgrammeRunEnvelope,
    item: ScheduledProgrammeOpportunity,
    decision: SchedulingDecision,
    *,
    expected_outputs: tuple[str, ...],
    actual_outputs: tuple[str, ...],
    unavailable: tuple[UnavailableReason, ...],
) -> ContentProgrammeRun:
    return ContentProgrammeRun(
        run_id=run.run_id,
        programme_id=run.programme_id,
        scheduler_decision_id=decision.decision_id,
        opportunity_id=item.opportunity.opportunity_id,
        format_id=run.format_id,
        grounding_question=run.grounding_question,
        selected_substrates=run.substrate_refs,
        selected_inputs=run.selected_input_refs,
        rights_consent=RightsConsentSnapshot(
            rights_state=run.rights_privacy_public_mode.rights_state,
            privacy_state=run.rights_privacy_public_mode.privacy_state,
            public_event_policy_state=run.rights_privacy_public_mode.public_event_policy_state,
            monetization_state=run.rights_privacy_public_mode.monetization_state,
            unavailable_reasons=tuple(unavailable),
        ),
        director_plan_ref=run.director_plan.director_plan_ref,
        director_move_refs=run.director_plan.director_move_refs,
        requested_public_private_mode=run.requested_public_private_mode,
        public_private_mode=run.public_private_mode,
        expected_outputs=expected_outputs,
        actual_outputs=actual_outputs,
        score_refs=tuple(score.score_ref for score in run.scores),
        refusal_refs=tuple(refusal.state_id for refusal in run.refusals),
        correction_refs=tuple(correction.state_id for correction in run.corrections),
        unavailable_reasons=tuple(unavailable),
        run_envelope_ref=f"ContentProgrammeRunEnvelope:{run.run_id}",
    )


def _nested_outcomes(
    run: ContentProgrammeRunEnvelope,
    *,
    public_event_refs: tuple[str, ...],
    boundary_refs: tuple[ProgrammeBoundaryEventRef, ...],
    conversion_candidate_ref: str,
    unavailable: tuple[UnavailableReason, ...],
) -> tuple[NestedProgrammeOutcome, ...]:
    boundary_ids = tuple(ref.boundary_id for ref in boundary_refs)
    has_verified_witness = any(
        outcome.witness_state == "witness_verified" and outcome.evidence_envelope_refs
        for outcome in run.witnessed_outcomes
    )
    observation_state = "verified" if has_verified_witness else "missing"
    claim_state = "accepted"
    if run.final_status == "refused":
        claim_state = "refused"
    elif run.final_status == "corrected":
        claim_state = "corrected"
    elif unavailable:
        claim_state = "blocked"
    public_event_state = "accepted" if public_event_refs else "held"
    conversion_state = "linked" if public_event_refs else "held"
    return (
        NestedProgrammeOutcome(
            outcome_id=f"nested:{run.run_id}:observation",
            kind="observation",
            state=observation_state,
            capability_outcome_refs=run.wcs.capability_outcome_refs,
            evidence_envelope_refs=run.wcs.evidence_envelope_refs,
            witness_refs=(f"witness:{run.run_id}:grounding",) if has_verified_witness else (),
            boundary_event_refs=boundary_ids,
            blocked_reasons=unavailable if observation_state == "missing" else (),
            learning_update_allowed=observation_state == "verified",
        ),
        NestedProgrammeOutcome(
            outcome_id=f"nested:{run.run_id}:claim-gate",
            kind="claim_gate",
            state=claim_state,
            parent_outcome_refs=(f"nested:{run.run_id}:observation",),
            capability_outcome_refs=run.wcs.capability_outcome_refs,
            evidence_envelope_refs=run.wcs.evidence_envelope_refs,
            boundary_event_refs=boundary_ids,
            blocked_reasons=unavailable if claim_state in {"blocked", "refused"} else (),
            claim_posterior_update_allowed=claim_state == "accepted"
            and run.final_status == "completed"
            and bool(run.wcs.evidence_envelope_refs),
            learning_update_allowed=claim_state == "accepted",
        ),
        NestedProgrammeOutcome(
            outcome_id=f"nested:{run.run_id}:artifact",
            kind="artifact",
            state="emitted" if run.final_status in {"completed", "corrected"} else "held",
            parent_outcome_refs=(f"nested:{run.run_id}:claim-gate",),
            evidence_envelope_refs=run.wcs.evidence_envelope_refs,
            boundary_event_refs=boundary_ids,
            public_event_refs=public_event_refs,
            conversion_candidate_refs=(conversion_candidate_ref,),
            learning_update_allowed=run.final_status in {"completed", "corrected"},
        ),
        NestedProgrammeOutcome(
            outcome_id=f"nested:{run.run_id}:public-event",
            kind="public_event",
            state=public_event_state,
            parent_outcome_refs=(f"nested:{run.run_id}:artifact",),
            evidence_envelope_refs=run.wcs.evidence_envelope_refs,
            boundary_event_refs=boundary_ids,
            public_event_refs=public_event_refs,
            blocked_reasons=(
                ("research_vehicle_public_event_missing",) if not public_event_refs else ()
            ),
            learning_update_allowed=bool(public_event_refs),
        ),
        NestedProgrammeOutcome(
            outcome_id=f"nested:{run.run_id}:conversion",
            kind="conversion",
            state=conversion_state,
            parent_outcome_refs=(f"nested:{run.run_id}:public-event",),
            evidence_envelope_refs=run.wcs.evidence_envelope_refs,
            public_event_refs=public_event_refs,
            conversion_candidate_refs=(conversion_candidate_ref,),
            blocked_reasons=(
                ("research_vehicle_public_event_missing",)
                if not public_event_refs and run.requested_public_private_mode in _PUBLIC_MODES
                else ()
            ),
            learning_update_allowed=bool(public_event_refs),
            public_conversion_success=bool(public_event_refs and run.final_status == "completed"),
        ),
        NestedProgrammeOutcome(
            outcome_id=f"nested:{run.run_id}:refusal",
            kind="refusal",
            state="refused" if run.refusals else "not_applicable",
            parent_outcome_refs=(f"nested:{run.run_id}:claim-gate",),
            evidence_envelope_refs=run.wcs.evidence_envelope_refs,
            refusal_or_correction_refs=tuple(refusal.state_id for refusal in run.refusals),
            blocked_reasons=unavailable if run.refusals else (),
            learning_update_allowed=bool(run.refusals),
        ),
        NestedProgrammeOutcome(
            outcome_id=f"nested:{run.run_id}:correction",
            kind="correction",
            state="corrected" if run.corrections else "not_applicable",
            parent_outcome_refs=(f"nested:{run.run_id}:claim-gate",),
            evidence_envelope_refs=run.wcs.evidence_envelope_refs,
            public_event_refs=public_event_refs if run.corrections else (),
            refusal_or_correction_refs=tuple(correction.state_id for correction in run.corrections),
            learning_update_allowed=bool(run.corrections),
        ),
    )


def _record_metrics(
    metrics: GroundingRunnerMetrics,
    run: _MaterializedRun,
    item: ScheduledProgrammeOpportunity,
    decision: SchedulingDecision,
) -> GroundingRunnerMetrics:
    format_frequency = dict(metrics.format_frequency)
    format_frequency[run.envelope.format_id] = format_frequency.get(run.envelope.format_id, 0) + 1
    completion = dict(metrics.completion_by_status)
    completion[run.envelope.final_status] = completion.get(run.envelope.final_status, 0) + 1
    audience = dict(metrics.audience_events_by_surface)
    for event in run.public_events:
        for surface in event.surface_policy.allowed_surfaces:
            audience[surface] = audience.get(surface, 0) + 1
    support_refusals = metrics.support_refusals + int(
        bool(set(decision.blocked_reasons) & _REFUSAL_SUPPORT_BLOCKERS)
    )
    rights_refusals = metrics.rights_refusals + int(
        "rights_blocked" in run.envelope.rights_privacy_public_mode.unavailable_reasons
        or "third_party_media_blocked"
        in run.envelope.rights_privacy_public_mode.unavailable_reasons
    )
    grounding_corrections = metrics.grounding_corrections + int(
        decision.route is ScheduleRoute.CORRECTION or bool(run.envelope.corrections)
    )
    artifact_events = metrics.artifact_events + sum(
        1
        for boundary in run.boundary_events
        if boundary.boundary_type in {"artifact.candidate", "refusal.issued", "correction.made"}
    )
    return metrics.model_copy(
        update={
            "format_frequency": format_frequency,
            "completion_by_status": completion,
            "audience_events_by_surface": audience,
            "artifact_events": artifact_events,
            "support_refusals": support_refusals,
            "rights_refusals": rights_refusals,
            "grounding_corrections": grounding_corrections,
            "public_events_emitted": metrics.public_events_emitted + len(run.public_events),
            "public_events_refused": metrics.public_events_refused
            + sum(1 for decision in run.public_event_decisions if decision.status == "refused"),
        }
    )


def _mode_for_route(
    route: ScheduleRoute,
    *,
    requested_mode: PublicPrivateMode,
) -> PublicPrivateMode:
    if route is ScheduleRoute.PRIVATE:
        return "private"
    if route in {ScheduleRoute.DRY_RUN, ScheduleRoute.REFUSAL}:
        return "dry_run"
    if route is ScheduleRoute.PUBLIC_LIVE:
        return "public_live"
    if route is ScheduleRoute.MONETIZED:
        return "public_monetizable"
    if route in {ScheduleRoute.PUBLIC_ARCHIVE, ScheduleRoute.CORRECTION}:
        return requested_mode if requested_mode in _PUBLIC_MODES else "public_archive"
    return "dry_run"


def _rights_state(rights_state: str, unavailable: tuple[UnavailableReason, ...]) -> str:
    if "rights_blocked" in unavailable or "third_party_media_blocked" in unavailable:
        return "blocked"
    if rights_state == "operator_original":
        return "operator_original"
    if rights_state == "platform_embed_only":
        return "platform_embed_only"
    if rights_state in {"cleared", "operator_controlled", "public_domain", "cc_compatible"}:
        return "cleared"
    if rights_state == "blocked":
        return "blocked"
    return "unknown"


def _privacy_state(
    world: SchedulerWorldSurfaceSnapshot,
    effective_mode: PublicPrivateMode,
    unavailable: tuple[UnavailableReason, ...],
) -> str:
    if (
        "privacy_blocked" in unavailable
        or not world.privacy_clear
        and effective_mode in _PUBLIC_MODES
    ):
        return "blocked"
    if effective_mode == "private":
        return "operator_private"
    return "public_safe" if world.privacy_clear or effective_mode != "private" else "unknown"


def _monetization_state(
    item: ScheduledProgrammeOpportunity,
    decision: SchedulingDecision,
    effective_mode: PublicPrivateMode,
    unavailable: tuple[UnavailableReason, ...],
) -> str:
    if effective_mode != "public_monetizable":
        return "not_requested"
    if decision.monetization_allowed and item.world.monetization_ready:
        return "ready"
    if "monetization_blocked" in unavailable or "monetization_readiness_missing" in unavailable:
        return "blocked"
    return "unknown"


def _wcs_health(
    world: SchedulerWorldSurfaceSnapshot,
    *,
    effective_mode: PublicPrivateMode,
    unavailable: tuple[UnavailableReason, ...],
) -> WcsHealthState:
    if "world_surface_blocked" in unavailable:
        return "blocked"
    if world.health_state != "unknown":
        return world.health_state
    if effective_mode == "private":
        return "private_only"
    if effective_mode == "dry_run":
        return "dry_run"
    return "unknown"


def _command_state(route: ScheduleRoute, final_status: RunFinalStatus) -> str:
    if final_status in {"blocked", "refused", "aborted"}:
        return "blocked_by_policy"
    if route is ScheduleRoute.DRY_RUN:
        return "dry_run"
    return "accepted"


def _terminal_event_type(final_status: RunFinalStatus) -> str:
    return {
        "blocked": "blocked",
        "refused": "refusal_issued",
        "corrected": "correction_made",
        "conversion_held": "conversion_held",
        "aborted": "aborted",
    }.get(final_status, "completed")


def _boundary_ref(
    boundary: ProgrammeBoundaryEvent,
    decision: FormatPublicEventDecision,
) -> ProgrammeBoundaryEventRef:
    mapping_ref = decision.public_event.event_id if decision.public_event is not None else None
    return ProgrammeBoundaryEventRef(
        boundary_id=boundary.boundary_id,
        sequence=boundary.sequence,
        boundary_type=boundary.boundary_type,
        duplicate_key=boundary.duplicate_key,
        cuepoint_chapter_distinction=_cuepoint_distinction(boundary),
        public_event_mapping_ref=mapping_ref,
        mapping_state="research_vehicle_linked"
        if mapping_ref
        else "held"
        if decision.status == "refused"
        else "research_vehicle_required",
        unavailable_reasons=decision.unavailable_reasons,
    )


def _cuepoint_distinction(boundary: ProgrammeBoundaryEvent) -> str:
    if boundary.boundary_type == "live_cuepoint.candidate":
        return "live_cuepoint_candidate"
    if boundary.boundary_type == "chapter.boundary":
        return "vod_chapter_boundary"
    if (
        boundary.cuepoint_chapter_policy.live_ad_cuepoint_allowed
        and boundary.cuepoint_chapter_policy.vod_chapter_allowed
    ):
        return "both_distinct"
    return "none"


def _allowed_surfaces(
    run: ContentProgrammeRunEnvelope,
    boundary_type: BoundaryType,
) -> tuple[Surface, ...]:
    surfaces: list[Surface] = ["archive"]
    if run.public_private_mode in {"public_archive", "public_live", "public_monetizable"}:
        surfaces.extend(["youtube_description", "youtube_chapters", "youtube_captions"])
    if run.public_private_mode == "public_live":
        surfaces.append("youtube_cuepoints")
        surfaces.append("omg_statuslog")
    if run.public_private_mode == "public_monetizable":
        surfaces.append("monetization")
    if boundary_type == "clip.candidate":
        surfaces.append("youtube_shorts")
    if boundary_type == "chapter.boundary":
        surfaces.append("replay")
    return tuple(dict.fromkeys(surfaces))


def _denied_surfaces(
    run: ContentProgrammeRunEnvelope,
    allowed: tuple[Surface, ...],
) -> tuple[Surface, ...]:
    denied = {
        "youtube_cuepoints",
        "youtube_shorts",
        "monetization",
        "mastodon",
        "bluesky",
        "discord",
    } - set(allowed)
    if run.public_private_mode in {"private", "dry_run"}:
        denied.update({"youtube_description", "youtube_chapters", "youtube_captions", "archive"})
    return tuple(sorted(cast("set[Surface]", denied)))


def _fallback_action(
    mode: PublicPrivateMode,
    unavailable: tuple[UnavailableReason, ...],
) -> str:
    if "operator_review_required" in unavailable:
        return "operator_review"
    if mode == "private":
        return "private_only"
    if mode == "dry_run":
        return "dry_run"
    if "archive_missing" in unavailable:
        return "hold"
    return "chapter_only"


def _claim_kind(format_id: str, boundary_type: BoundaryType) -> ClaimKind:
    if boundary_type == "refusal.issued":
        return "refusal"
    if boundary_type == "correction.made":
        return "correction"
    if boundary_type in {"programme.started", "programme.ended", "chapter.boundary"}:
        return "metadata"
    return _FORMAT_CLAIM_KIND.get(format_id, "observation")


def _confidence_label(
    boundary_type: BoundaryType,
    unavailable: tuple[UnavailableReason, ...],
) -> str:
    if boundary_type in {"refusal.issued", "correction.made"}:
        return "high"
    if unavailable:
        return "low"
    return "medium_high"


def _uncertainty(
    run: ContentProgrammeRunEnvelope,
    unavailable: tuple[UnavailableReason, ...],
) -> str:
    if unavailable:
        return "The run failed closed on explicit gates: " + ", ".join(unavailable) + "."
    return (
        "This is an evidence-bound programme claim, not an expert-system verdict; "
        f"scope is limited to {run.format_id} inputs."
    )


def _boundary_summary(run: ContentProgrammeRunEnvelope, boundary_type: BoundaryType) -> str:
    labels = {
        "programme.started": "Started the scheduled grounding programme.",
        "criterion.declared": "Declared the criterion used to structure the programme.",
        "evidence.observed": "Observed selected evidence through the programme substrate.",
        "claim.made": "Made an evidence-bound programme claim.",
        "rank.assigned": "Assigned a rank within declared criteria and evidence.",
        "comparison.resolved": "Resolved a bounded comparison from selected evidence.",
        "uncertainty.marked": "Marked explicit uncertainty for the programme output.",
        "refusal.issued": "Refused an unsupported or blocked programme claim.",
        "correction.made": "Issued a correction as a first-class programme output.",
        "clip.candidate": "Staged a clip candidate from programme evidence.",
        "live_cuepoint.candidate": "Staged a live cuepoint candidate from programme evidence.",
        "chapter.boundary": "Staged a VOD chapter boundary from programme evidence.",
        "artifact.candidate": "Staged an archive artifact candidate from programme evidence.",
        "programme.ended": "Ended the scheduled grounding programme.",
    }
    return f"{labels[boundary_type]} Format={run.format_id}."


def _chapter_label(run: ContentProgrammeRunEnvelope, boundary_type: BoundaryType) -> str:
    label = boundary_type.replace(".", " ").replace("_", " ").title()
    return f"{run.format_id}: {label}"


def _boundary_evidence_refs(
    run: ContentProgrammeRunEnvelope,
    item: ScheduledProgrammeOpportunity,
) -> tuple[str, ...]:
    return _unique_strs(
        (
            *item.opportunity.evidence_refs,
            *item.world.evidence_refs,
            *run.selected_input_refs,
            *run.wcs.evidence_envelope_refs,
            *run.gate_refs.grounding_gate_refs,
        )
    )


def _evidence_refs(item: ScheduledProgrammeOpportunity) -> tuple[str, ...]:
    return _unique_strs((*item.opportunity.evidence_refs, *item.world.evidence_refs))


def _selected_input_refs(item: ScheduledProgrammeOpportunity) -> tuple[str, ...]:
    return _unique_strs(
        item.selected_input_refs
        or (
            item.opportunity.input_source_id,
            *item.opportunity.evidence_refs,
        )
    )


def _substrate_refs(item: ScheduledProgrammeOpportunity) -> tuple[str, ...]:
    return _unique_strs(
        item.substrate_refs
        or (
            f"substrate:{item.opportunity.format_id}",
            f"source:{item.opportunity.input_source_id}",
        )
    )


def _semantic_capability_refs(item: ScheduledProgrammeOpportunity) -> tuple[str, ...]:
    return _unique_strs(
        item.semantic_capability_refs or (f"capability:format:{item.opportunity.format_id}",)
    )


def _director_move_refs(item: ScheduledProgrammeOpportunity) -> tuple[str, ...]:
    if item.director_move_refs:
        return item.director_move_refs
    if item.format_row is not None:
        return tuple(f"director-move:{move}" for move in item.format_row.director_moves)
    try:
        row = load_format_wcs_requirement_matrix().require_row(
            cast("ContentProgrammeFormatId", item.opportunity.format_id)
        )
    except Exception:  # noqa: BLE001
        return ("director-move:mark_boundary", "director-move:hold")
    return tuple(f"director-move:{move}" for move in row.director_moves)


def _grounding_attempt_types(format_id: str) -> tuple[str, ...]:
    if format_id in {"tier_list", "ranking", "bracket"}:
        return ("ranking", "uncertainty")
    if format_id in {"comparison", "debate"}:
        return ("comparison", "uncertainty")
    if format_id == "refusal_breakdown":
        return ("refusal", "uncertainty")
    if format_id == "evidence_audit":
        return ("classification", "uncertainty")
    return ("observation", "uncertainty")


def _expected_outputs(
    item: ScheduledProgrammeOpportunity,
    run: ContentProgrammeRunEnvelope,
) -> tuple[str, ...]:
    if item.expected_outputs:
        return item.expected_outputs
    if item.format_row is not None:
        return tuple(item.format_row.archive_outputs)
    try:
        row = load_format_wcs_requirement_matrix().require_row(
            cast("ContentProgrammeFormatId", run.format_id)
        )
    except Exception:  # noqa: BLE001
        return ("run_card", "replay_note")
    return tuple(row.archive_outputs)


def _actual_outputs(
    boundaries: tuple[ProgrammeBoundaryEvent, ...],
    public_events: tuple[ResearchVehiclePublicEvent, ...],
    decisions: tuple[FormatPublicEventDecision, ...],
) -> tuple[str, ...]:
    outputs: list[str] = [f"boundary:{boundary.boundary_type}" for boundary in boundaries]
    outputs.extend(f"public_event:{event.event_type}" for event in public_events)
    outputs.extend(
        f"public_event_decision:{decision.status}:{decision.boundary_type}"
        for decision in decisions
    )
    return tuple(outputs)


def _refusal_refs(
    run_id: str,
    final_status: RunFinalStatus,
    evidence_refs: tuple[str, ...],
    unavailable: tuple[UnavailableReason, ...],
) -> tuple[StateRef, ...]:
    if final_status != "refused":
        return ()
    return (
        StateRef(
            state_id=f"refusal:{run_id}:fail-closed",
            reason="Run failed closed instead of emitting unsupported public content.",
            evidence_refs=(*evidence_refs, *(f"unavailable:{reason}" for reason in unavailable)),
        ),
    )


def _correction_refs(
    run_id: str,
    final_status: RunFinalStatus,
    evidence_refs: tuple[str, ...],
) -> tuple[StateRef, ...]:
    if final_status != "corrected":
        return ()
    return (
        StateRef(
            state_id=f"correction:{run_id}:grounding",
            reason="Correction was selected by the scheduler as the next programme route.",
            evidence_refs=evidence_refs,
        ),
    )


def _score_refs(
    run_id: str,
    final_status: RunFinalStatus,
    evidence_refs: tuple[str, ...],
) -> tuple[ScoreRef, ...]:
    if not evidence_refs:
        return ()
    return (
        ScoreRef(
            evaluation_id=f"fge:{run_id}:grounding",
            dimension="grounding_completion",
            score_ref=f"score:{run_id}:{final_status}",
            evidence_refs=evidence_refs,
        ),
    )


def _coerce_scheduled(
    item: ScheduledProgrammeOpportunity | Mapping[str, Any],
) -> ScheduledProgrammeOpportunity:
    if isinstance(item, ScheduledProgrammeOpportunity):
        return item
    return ScheduledProgrammeOpportunity.model_validate(item)


def _iter_scheduled_opportunities(path: Path) -> Iterator[ScheduledProgrammeOpportunity]:
    yield from _iter_jsonl_model(path, ScheduledProgrammeOpportunity)


def _iter_jsonl_model[T: BaseModel](path: Path, model: type[T]) -> Iterator[T]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return
    except OSError:
        log.warning("failed to read JSONL path %s", path, exc_info=True)
        return
    for line_number, raw in enumerate(lines, start=1):
        if not raw.strip():
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("skipping invalid JSON in %s:%d", path, line_number)
            continue
        try:
            yield model.model_validate(payload)
        except ValidationError:
            log.warning("skipping invalid record in %s:%d", path, line_number, exc_info=True)


def _append_jsonl_models(path: Path, models: Sequence[BaseModel]) -> None:
    if not models:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for model in models:
            fh.write(json.dumps(model.model_dump(mode="json"), sort_keys=True) + "\n")


def _load_jsonl_ids(path: Path, field: str) -> set[str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, OSError):
        return set()
    ids: set[str] = set()
    for raw in lines:
        if not raw.strip():
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        value = payload.get(field) if isinstance(payload, dict) else None
        if isinstance(value, str):
            ids.add(value)
    return ids


def _load_cursor(path: Path) -> set[str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return set()
    if isinstance(payload, list):
        return {item for item in payload if isinstance(item, str)}
    if isinstance(payload, dict):
        values = payload.get("processed_schedule_keys", [])
        if isinstance(values, list):
            return {item for item in values if isinstance(item, str)}
    return set()


def _save_cursor(path: Path, keys: set[str]) -> None:
    payload = {
        "schema_version": 1,
        "processed_schedule_keys": sorted(keys),
        "updated_at": datetime.now(UTC).isoformat(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _scheduled_key(opportunity: SchedulerOpportunity, decision: SchedulingDecision) -> str:
    return _sanitize_id(f"{opportunity.opportunity_id}:{decision.decision_id}")


def _run_id(opportunity: SchedulerOpportunity, decision: SchedulingDecision) -> str:
    return _sanitize_id(f"run:{opportunity.opportunity_id}:{decision.decision_id}")


def _sanitize_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {":", ".", "_", "-"} else "_" for ch in value)


def _first(values: Sequence[str]) -> str | None:
    return values[0] if values else None


def _first_or(values: Sequence[str], default: str) -> str:
    return values[0] if values else default


def _unique_strs(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _blocked_grounded_step(
    step: GroundingProgrammeStep,
    *,
    reasons: Sequence[str],
    resolved: ResolvedContent | None = None,
    transition: CompositorTransitionResult | None = None,
    ward_update: WardStateUpdate | None = None,
    witness: CompositorOutputWitness | None = None,
    error: str | None = None,
) -> GroundedProgrammeStepResult:
    return GroundedProgrammeStepResult(
        step_id=step.step_id,
        status="blocked",
        resolved_content=resolved,
        transition_result=transition,
        ward_update=ward_update,
        output_witness=witness,
        unavailable_reasons=_unique_strs(reasons),
        error=error,
    )


def _content_resolution_blockers(
    step: GroundingProgrammeStep, resolved: ResolvedContent
) -> tuple[str, ...]:
    blockers: list[str] = []
    if resolved.step_id != step.step_id:
        blockers.append("content_step_mismatch")
    if resolved.content_ref != step.content_ref:
        blockers.append("content_ref_mismatch")
    if _blank(resolved.resolved_ref):
        blockers.append("content_unresolved")
    if not resolved.evidence_refs:
        blockers.append("content_resolution_evidence_missing")
    return tuple(blockers)


def _transition_blockers(
    step: GroundingProgrammeStep, transition: CompositorTransitionResult
) -> tuple[str, ...]:
    blockers: list[str] = []
    if transition.step_id != step.step_id:
        blockers.append("transition_step_mismatch")
    if _blank(transition.transition_id):
        blockers.append("transition_id_missing")
    if _blank(transition.command_ref):
        blockers.append("transition_command_missing")
    if not transition.applied:
        blockers.append("transition_not_applied")
    if not transition.evidence_refs:
        blockers.append("transition_evidence_missing")
    return tuple(blockers)


def _ward_state_blockers(
    step: GroundingProgrammeStep, ward_update: WardStateUpdate
) -> tuple[str, ...]:
    blockers: list[str] = []
    if ward_update.step_id != step.step_id:
        blockers.append("ward_state_step_mismatch")
    if ward_update.ward_id != step.ward_id:
        blockers.append("ward_state_ward_mismatch")
    if _blank(ward_update.state_ref):
        blockers.append("ward_state_ref_missing")
    if not ward_update.applied:
        blockers.append("ward_state_not_applied")
    if not ward_update.evidence_refs:
        blockers.append("ward_state_evidence_missing")
    return tuple(blockers)


def _compositor_output_blockers(
    step: GroundingProgrammeStep, witness: CompositorOutputWitness
) -> tuple[str, ...]:
    blockers: list[str] = []
    if witness.step_id != step.step_id:
        blockers.append("compositor_output_step_mismatch")
    if _blank(witness.frame_ref):
        blockers.append("compositor_output_missing")
    if not witness.changed:
        blockers.append("compositor_output_not_changed")
    if not witness.nonblank:
        blockers.append("compositor_output_blank")
    if not witness.evidence_refs:
        blockers.append("compositor_output_evidence_missing")
    if step.expected_output_ref and step.expected_output_ref not in (
        witness.frame_ref,
        *witness.evidence_refs,
    ):
        blockers.append("compositor_output_unexpected")
    return tuple(blockers)


def _blank(value: str) -> bool:
    return not value.strip()


def _unique_unavailable(values: Iterable[UnavailableReason]) -> tuple[UnavailableReason, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [
    "CompositorOutputWitness",
    "CompositorTransitionResult",
    "ContentResolverFn",
    "DEFAULT_BOUNDARY_EVENT_PATH",
    "DEFAULT_CURSOR_PATH",
    "DEFAULT_PUBLIC_EVENT_DECISION_PATH",
    "DEFAULT_RUN_ENVELOPE_PATH",
    "DEFAULT_SCHEDULED_OPPORTUNITY_PATH",
    "DEFAULT_TICK_S",
    "CompositorOutputWitnessFn",
    "ContentProgrammeRun",
    "ContentProgrammingGroundingRunner",
    "GroundedProgrammeSequenceResult",
    "GroundedProgrammeStepResult",
    "GroundingProgrammeSequence",
    "GroundingProgrammeStep",
    "GroundingRunnerBatch",
    "GroundingRunnerMetrics",
    "GroundedStepStatus",
    "ProgrammeSequenceGroundingRunner",
    "ResolvedContent",
    "RightsConsentSnapshot",
    "ScheduledProgrammeOpportunity",
    "TransitionTriggerFn",
    "WardStateUpdate",
    "WardStateUpdateFn",
]

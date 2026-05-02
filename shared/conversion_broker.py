"""Readiness-gated conversion broker for content programme outputs.

The broker is deliberately narrow: it consumes canonical
``ContentProgrammeRunEnvelope`` + ``ProgrammeBoundaryEvent`` records, evaluates
target-family readiness against ``conversion-target-readiness-threshold-matrix``,
records typed conversion candidates, and appends eligible
``ResearchVehiclePublicEvent`` records to the existing publication bus.
"""

from __future__ import annotations

import json
import re
from collections.abc import Hashable, Iterable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Literal

from prometheus_client import REGISTRY, CollectorRegistry, Counter
from pydantic import BaseModel, ConfigDict, Field

from shared.content_programme_run_store import (
    ContentProgrammeRunEnvelope,
    PrivacyState,
    PublicPrivateMode,
    RightsState,
)
from shared.conversion_target_readiness import (
    DEFAULT_MATRIX_PATH,
    PUBLIC_READINESS_STATES,
    ConversionTargetReadinessMatrix,
    GateDimension,
    ReadinessState,
    TargetFamilyId,
    decide_readiness_state,
    load_conversion_target_readiness_matrix,
)
from shared.format_public_event_adapter import (
    FormatPublicEventDecision,
    ProgrammeBoundaryEvent,
    adapt_format_boundary_to_public_event,
)
from shared.research_vehicle_public_event import (
    PrivacyClass,
    PublicEventProvenance,
    ResearchVehiclePublicEvent,
    RightsClass,
)

type ConversionTargetType = Literal[
    "youtube_vod",
    "youtube_shorts",
    "youtube_chapter",
    "youtube_caption",
    "replay_demo",
    "archive_replay",
    "dataset_card",
    "zine",
    "artifact_edition",
    "grant_packet",
    "support_prompt",
    "residency_packet",
    "license_packet",
    "refusal_artifact",
    "correction_artifact",
    "failure_artifact",
    "monetization_review",
]
type CandidateResult = Literal["generated", "published", "blocked"]
type OutcomeKind = Literal["artifact", "revenue"]

DEFAULT_PUBLIC_EVENT_PATH = Path("/dev/shm/hapax-public-events/events.jsonl")
DEFAULT_CANDIDATE_PATH = Path.home() / "hapax-state" / "conversion-broker" / "candidates.jsonl"

_PUBLIC_SAFE_RIGHTS: frozenset[RightsState] = frozenset(
    {"operator_original", "cleared", "platform_embed_only"}
)
_PUBLIC_SAFE_PRIVACY: frozenset[PrivacyState] = frozenset({"public_safe", "aggregate_only"})
_TARGET_FAMILY_BY_TYPE: dict[ConversionTargetType, TargetFamilyId] = {
    "youtube_vod": "youtube_vod_packaging",
    "youtube_shorts": "youtube_vod_packaging",
    "youtube_chapter": "youtube_vod_packaging",
    "youtube_caption": "youtube_vod_packaging",
    "replay_demo": "replay_demo",
    "archive_replay": "replay_demo",
    "dataset_card": "dataset_card",
    "zine": "artifact_edition_release",
    "artifact_edition": "artifact_edition_release",
    "grant_packet": "grants_fellowships",
    "support_prompt": "support_prompt",
    "residency_packet": "residency",
    "license_packet": "licensing",
    "refusal_artifact": "artifact_edition_release",
    "correction_artifact": "artifact_edition_release",
    "failure_artifact": "artifact_edition_release",
    "monetization_review": "support_prompt",
}
_MODE_STATE_RANK: tuple[ReadinessState, ...] = (
    "private-evidence",
    "dry-run",
    "public-archive",
    "public-live",
    "public-monetizable",
)


class ConversionBrokerModel(BaseModel):
    """Strict immutable base for broker contract records."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ConversionSourceEvent(ConversionBrokerModel):
    """One source event or public-event projection behind a candidate."""

    source_ref: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    sequence: int | None = None


class ConversionTargetRequest(ConversionBrokerModel):
    """Explicit target request when a caller wants a non-derived candidate."""

    target_type: ConversionTargetType
    requested_readiness_state: ReadinessState | None = None

    @property
    def target_family_id(self) -> TargetFamilyId:
        return _TARGET_FAMILY_BY_TYPE[self.target_type]


class ConversionCandidate(ConversionBrokerModel):
    """Typed conversion candidate emitted by the broker.

    This record keeps conversion value subordinate to readiness evidence:
    salience and revenue hints are retained as candidate context but cannot
    upgrade ``readiness_state``.
    """

    schema_version: Literal[1] = 1
    candidate_id: str
    source_run_id: str
    source_programme_id: str
    source_run_ref: str
    source_events: tuple[ConversionSourceEvent, ...] = Field(min_length=1)
    target_family_id: TargetFamilyId
    target_type: ConversionTargetType
    salience: float = Field(ge=0.0, le=1.0)
    rights_class: RightsClass
    privacy_class: PrivacyClass
    provenance: PublicEventProvenance | None
    provenance_refs: tuple[str, ...] = Field(default_factory=tuple)
    frame_refs: tuple[str, ...] = Field(default_factory=tuple)
    chapter_refs: tuple[str, ...] = Field(default_factory=tuple)
    archive_refs: tuple[str, ...] = Field(default_factory=tuple)
    claim_text: str
    requested_readiness_state: ReadinessState
    readiness_state: ReadinessState
    ready_for_publication_bus: bool
    publication_bus_event_ref: str | None = None
    blocked_reason: str | None = None
    missing_gate_dimensions: tuple[GateDimension, ...] = Field(default_factory=tuple)
    readiness_gate_source: str = "config/conversion-target-readiness-threshold-matrix.json"
    anti_overclaim_signals: tuple[str, ...] = Field(default_factory=tuple)

    def to_json_line(self) -> str:
        """Serialize as a deterministic JSONL line for candidate audit logs."""

        return json.dumps(self.model_dump(mode="json"), sort_keys=True) + "\n"


class ConversionBrokerDecision(ConversionBrokerModel):
    """Decision bundle for one programme boundary."""

    schema_version: Literal[1] = 1
    decision_id: str
    run_id: str
    boundary_id: str
    format_public_event_decision_id: str
    candidates: tuple[ConversionCandidate, ...]
    public_events: tuple[ResearchVehiclePublicEvent, ...] = Field(default_factory=tuple)

    def to_json_line(self) -> str:
        """Serialize as a deterministic JSONL line for broker decisions."""

        return json.dumps(self.model_dump(mode="json"), sort_keys=True) + "\n"


class ConversionBrokerMetrics:
    """Prometheus counters owned by the conversion broker."""

    def __init__(self, registry: CollectorRegistry = REGISTRY) -> None:
        self.candidates_total = Counter(
            "hapax_conversion_broker_candidates_total",
            "Conversion candidates generated by target family/type/readiness/result.",
            ["target_family", "target_type", "readiness_state", "result"],
            registry=registry,
        )
        self.public_events_total = Counter(
            "hapax_conversion_broker_public_events_total",
            "Publication-bus events surfaced by the conversion broker.",
            ["target_family", "target_type", "result"],
            registry=registry,
        )
        self.outcomes_total = Counter(
            "hapax_conversion_broker_outcomes_total",
            "Artifact and revenue outcomes observed by the conversion broker.",
            ["outcome_kind", "result"],
            registry=registry,
        )

    def record_candidate(self, candidate: ConversionCandidate) -> None:
        terminal_result: CandidateResult | None = (
            "published"
            if candidate.ready_for_publication_bus
            else "blocked"
            if candidate.blocked_reason is not None
            else None
        )
        self.candidates_total.labels(
            target_family=candidate.target_family_id,
            target_type=candidate.target_type,
            readiness_state=candidate.readiness_state,
            result="generated",
        ).inc()
        for outcome in _outcome_kinds(candidate):
            self.outcomes_total.labels(outcome_kind=outcome, result="generated").inc()
        if terminal_result is not None:
            self.candidates_total.labels(
                target_family=candidate.target_family_id,
                target_type=candidate.target_type,
                readiness_state=candidate.readiness_state,
                result=terminal_result,
            ).inc()
        if terminal_result == "published":
            self.public_events_total.labels(
                target_family=candidate.target_family_id,
                target_type=candidate.target_type,
                result="published",
            ).inc()
        elif terminal_result == "blocked":
            self.public_events_total.labels(
                target_family=candidate.target_family_id,
                target_type=candidate.target_type,
                result="blocked",
            ).inc()
        if terminal_result is not None:
            for outcome in _outcome_kinds(candidate):
                self.outcomes_total.labels(
                    outcome_kind=outcome,
                    result=terminal_result,
                ).inc()


class ConversionBroker:
    """Append candidate decisions and eligible public events with idempotency."""

    def __init__(
        self,
        *,
        public_event_path: Path = DEFAULT_PUBLIC_EVENT_PATH,
        candidate_path: Path = DEFAULT_CANDIDATE_PATH,
        matrix: ConversionTargetReadinessMatrix | None = None,
        metrics: ConversionBrokerMetrics | None = None,
    ) -> None:
        self.public_event_path = public_event_path
        self.candidate_path = candidate_path
        self.matrix = matrix or load_conversion_target_readiness_matrix()
        self.metrics = metrics or ConversionBrokerMetrics()
        self._known_public_event_ids: set[str] | None = None
        self._known_candidate_ids: set[str] | None = None

    def process_boundary(
        self,
        run: ContentProgrammeRunEnvelope,
        boundary_event: ProgrammeBoundaryEvent | Mapping[str, object],
        *,
        generated_at: datetime | str,
        target_requests: Sequence[ConversionTargetRequest] | None = None,
    ) -> ConversionBrokerDecision:
        """Evaluate one run boundary and persist candidates/public events."""

        decision = build_conversion_broker_decision(
            run,
            boundary_event,
            generated_at=generated_at,
            matrix=self.matrix,
            target_requests=target_requests,
        )
        self._append_candidates(decision.candidates)
        for event in decision.public_events:
            if not self._public_event_already_written(event.event_id):
                self._append_public_event(event)
        for candidate in decision.candidates:
            self.metrics.record_candidate(candidate)
        return decision

    def _append_candidates(self, candidates: Sequence[ConversionCandidate]) -> None:
        if self._known_candidate_ids is None:
            self._known_candidate_ids = _load_jsonl_ids(self.candidate_path, "candidate_id")
        new_candidates = [c for c in candidates if c.candidate_id not in self._known_candidate_ids]
        if not new_candidates:
            return
        self.candidate_path.parent.mkdir(parents=True, exist_ok=True)
        with self.candidate_path.open("a", encoding="utf-8") as fh:
            for candidate in new_candidates:
                fh.write(candidate.to_json_line())
                self._known_candidate_ids.add(candidate.candidate_id)

    def _append_public_event(self, event: ResearchVehiclePublicEvent) -> None:
        self.public_event_path.parent.mkdir(parents=True, exist_ok=True)
        with self.public_event_path.open("a", encoding="utf-8") as fh:
            fh.write(event.to_json_line())
        if self._known_public_event_ids is not None:
            self._known_public_event_ids.add(event.event_id)

    def _public_event_already_written(self, event_id: str) -> bool:
        if self._known_public_event_ids is None:
            self._known_public_event_ids = _load_jsonl_ids(self.public_event_path, "event_id")
        return event_id in self._known_public_event_ids


def build_conversion_broker_decision(
    run: ContentProgrammeRunEnvelope,
    boundary_event: ProgrammeBoundaryEvent | Mapping[str, object],
    *,
    generated_at: datetime | str,
    matrix: ConversionTargetReadinessMatrix | None = None,
    target_requests: Sequence[ConversionTargetRequest] | None = None,
) -> ConversionBrokerDecision:
    """Build candidates and public-event outputs for one boundary."""

    boundary = _coerce_boundary(boundary_event)
    readiness_matrix = matrix or load_conversion_target_readiness_matrix()
    format_decision = adapt_format_boundary_to_public_event(
        run,
        boundary,
        generated_at=generated_at,
    )
    requests = (
        tuple(target_requests)
        if target_requests is not None
        else target_requests_for_boundary(run, boundary, format_decision)
    )
    candidates = tuple(
        _build_candidate(
            run=run,
            boundary=boundary,
            format_decision=format_decision,
            target_request=request,
            matrix=readiness_matrix,
        )
        for request in requests
    )
    public_events = (
        (format_decision.public_event,)
        if format_decision.public_event is not None
        and any(candidate.ready_for_publication_bus for candidate in candidates)
        else ()
    )
    return ConversionBrokerDecision(
        decision_id=_sanitize_id(f"cbd:{run.run_id}:{boundary.boundary_id}"),
        run_id=run.run_id,
        boundary_id=boundary.boundary_id,
        format_public_event_decision_id=format_decision.decision_id,
        candidates=candidates,
        public_events=public_events,
    )


def target_requests_for_boundary(
    run: ContentProgrammeRunEnvelope,
    boundary: ProgrammeBoundaryEvent,
    format_decision: FormatPublicEventDecision,
) -> tuple[ConversionTargetRequest, ...]:
    """Derive independently gated target requests from a boundary."""

    targets: list[ConversionTargetType] = []
    event = format_decision.public_event
    surfaces = set(event.surface_policy.allowed_surfaces if event is not None else ())
    if {"youtube_description", "youtube_channel_sections"} & surfaces:
        targets.append("youtube_vod")
    if "youtube_chapters" in surfaces or boundary.boundary_type == "chapter.boundary":
        targets.append("youtube_chapter")
    if "youtube_captions" in surfaces or (
        event is not None and event.event_type == "caption.segment"
    ):
        targets.append("youtube_caption")
    if "youtube_shorts" in surfaces or boundary.boundary_type == "clip.candidate":
        targets.append("youtube_shorts")
    if {"archive", "replay"} & surfaces or run.archive_refs:
        targets.append("archive_replay")
    if boundary.boundary_type == "refusal.issued":
        targets.append("refusal_artifact")
    elif boundary.boundary_type == "correction.made":
        targets.append("correction_artifact")
    elif run.final_status in {"blocked", "aborted", "conversion_held"}:
        targets.append("failure_artifact")
    elif boundary.boundary_type == "artifact.candidate" or (
        event is not None and event.event_type == "publication.artifact"
    ):
        targets.append("artifact_edition")

    text = " ".join(
        (
            run.format_id,
            run.grounding_question,
            " ".join(run.semantic_capability_refs),
            " ".join(boundary.evidence_refs),
        )
    ).lower()
    if "dataset" in text:
        targets.append("dataset_card")
    if "grant" in text or "fellowship" in text:
        targets.append("grant_packet")
    if "support" in text or "monetization" in text:
        targets.append("support_prompt")
    if "residenc" in text:
        targets.append("residency_packet")
    if "licens" in text:
        targets.append("license_packet")

    if not targets:
        targets.append("archive_replay")
    return tuple(ConversionTargetRequest(target_type=target) for target in _dedupe(targets))


def _build_candidate(
    *,
    run: ContentProgrammeRunEnvelope,
    boundary: ProgrammeBoundaryEvent,
    format_decision: FormatPublicEventDecision,
    target_request: ConversionTargetRequest,
    matrix: ConversionTargetReadinessMatrix,
) -> ConversionCandidate:
    event = format_decision.public_event
    requested_state = target_request.requested_readiness_state or _requested_state_for_target(
        run.public_private_mode,
        target_request.target_family_id,
        matrix,
    )
    satisfied = _satisfied_gate_dimensions(
        run,
        event,
        requested_state=requested_state,
    )
    readiness_decision = decide_readiness_state(
        matrix,
        target_request.target_family_id,
        requested_state,
        satisfied,
    )
    public_ready = (
        readiness_decision.allowed
        and readiness_decision.effective_state in PUBLIC_READINESS_STATES
        and event is not None
        and _public_event_supports_target(event, target_request.target_type)
    )
    blocked_reason = _blocked_reason(
        format_decision=format_decision,
        readiness_allowed=readiness_decision.allowed,
        operator_visible_reason=readiness_decision.operator_visible_reason,
        missing=readiness_decision.missing_gate_dimensions,
        public_ready=public_ready,
        event=event,
        requested_state=requested_state,
    )
    return ConversionCandidate(
        candidate_id=_sanitize_id(
            f"conversion:{run.run_id}:{boundary.boundary_id}:{target_request.target_type}"
        ),
        source_run_id=run.run_id,
        source_programme_id=run.programme_id,
        source_run_ref=f"ContentProgrammeRunEnvelope:{run.run_id}",
        source_events=_source_events(run, boundary, event),
        target_family_id=target_request.target_family_id,
        target_type=target_request.target_type,
        salience=event.salience if event is not None else _fallback_salience(run, boundary),
        rights_class=event.rights_class if event is not None else _rights_class(run),
        privacy_class=event.privacy_class if event is not None else _privacy_class(run),
        provenance=event.provenance if event is not None else None,
        provenance_refs=_provenance_refs(run, boundary, event),
        frame_refs=_frame_refs(event),
        chapter_refs=_chapter_refs(event),
        archive_refs=run.archive_refs,
        claim_text=_claim_text(boundary),
        requested_readiness_state=requested_state,
        readiness_state=readiness_decision.effective_state,
        ready_for_publication_bus=public_ready,
        publication_bus_event_ref=event.event_id if event is not None and public_ready else None,
        blocked_reason=blocked_reason,
        missing_gate_dimensions=readiness_decision.missing_gate_dimensions,
        readiness_gate_source=str(DEFAULT_MATRIX_PATH.relative_to(DEFAULT_MATRIX_PATH.parents[1])),
        anti_overclaim_signals=_anti_overclaim_signals(run),
    )


def _satisfied_gate_dimensions(
    run: ContentProgrammeRunEnvelope,
    event: ResearchVehiclePublicEvent | None,
    *,
    requested_state: ReadinessState,
) -> frozenset[GateDimension]:
    satisfied: set[GateDimension] = set()
    if run.wcs.evidence_envelope_refs and run.wcs.health_state in {"healthy", "degraded"}:
        satisfied.add("wcs")
    if run.run_id and run.programme_id and run.events:
        satisfied.add("programme")
    if event is not None or _run_public_event_refs(run):
        satisfied.add("public_event")
    if run.archive_refs or (event is not None and (event.frame_ref or event.chapter_ref)):
        satisfied.add("archive")
    if run.rights_privacy_public_mode.rights_state in _PUBLIC_SAFE_RIGHTS:
        satisfied.add("rights")
    if _privacy_satisfies(run.rights_privacy_public_mode.privacy_state, requested_state):
        satisfied.add("privacy")
    if _provenance_refs(run, None, event):
        satisfied.add("provenance")
    if event is not None and "egress_blocked" not in _all_blocker_strings(run):
        satisfied.add("egress")
    if (
        run.rights_privacy_public_mode.monetization_state == "ready"
        or run.gate_refs.monetization_gate_refs
    ):
        satisfied.add("monetization")
    if _has_operator_attestation(run, event):
        satisfied.add("operator_attestation")
    if _no_hidden_operator_labor(run):
        satisfied.add("no_hidden_operator_labor")
    return frozenset(satisfied)


def _requested_state_for_target(
    mode: PublicPrivateMode,
    target_family_id: TargetFamilyId,
    matrix: ConversionTargetReadinessMatrix,
) -> ReadinessState:
    preferred = _state_for_mode(mode)
    target = matrix.by_family_id()[target_family_id]
    if preferred in target.allowed_states:
        return preferred
    preferred_index = _MODE_STATE_RANK.index(preferred) if preferred in _MODE_STATE_RANK else -1
    allowed = [
        state for state in _MODE_STATE_RANK[: preferred_index + 1] if state in target.allowed_states
    ]
    return allowed[-1] if allowed else "blocked"


def _state_for_mode(mode: PublicPrivateMode) -> ReadinessState:
    return {
        "private": "private-evidence",
        "dry_run": "dry-run",
        "public_archive": "public-archive",
        "public_live": "public-live",
        "public_monetizable": "public-monetizable",
    }[mode]


def _blocked_reason(
    *,
    format_decision: FormatPublicEventDecision,
    readiness_allowed: bool,
    operator_visible_reason: str,
    missing: tuple[GateDimension, ...],
    public_ready: bool,
    event: ResearchVehiclePublicEvent | None,
    requested_state: ReadinessState,
) -> str | None:
    if public_ready:
        return None
    reasons: list[str] = []
    if not readiness_allowed:
        reasons.append(operator_visible_reason)
    if missing:
        reasons.append("missing gates: " + ",".join(missing))
    if event is None and requested_state in PUBLIC_READINESS_STATES:
        reasons.append("format public-event adapter did not emit a public event")
    if format_decision.hard_unavailable_reasons:
        reasons.append(
            "format public-event hard blockers: "
            + ",".join(format_decision.hard_unavailable_reasons)
        )
    return "; ".join(_dedupe(reasons)) if reasons else None


def _public_event_supports_target(
    event: ResearchVehiclePublicEvent,
    target_type: ConversionTargetType,
) -> bool:
    surfaces = set(event.surface_policy.allowed_surfaces)
    if target_type == "youtube_vod":
        return bool({"youtube_description", "youtube_channel_sections"} & surfaces)
    if target_type == "youtube_chapter":
        return "youtube_chapters" in surfaces or event.event_type == "chapter.marker"
    if target_type == "youtube_caption":
        return "youtube_captions" in surfaces or event.event_type == "caption.segment"
    if target_type == "youtube_shorts":
        return "youtube_shorts" in surfaces or event.event_type in {
            "shorts.candidate",
            "shorts.upload",
        }
    if target_type in {"archive_replay", "replay_demo"}:
        return bool({"archive", "replay"} & surfaces)
    if target_type in {
        "dataset_card",
        "zine",
        "artifact_edition",
        "refusal_artifact",
        "correction_artifact",
        "failure_artifact",
        "grant_packet",
        "support_prompt",
        "residency_packet",
        "license_packet",
        "monetization_review",
    }:
        return event.event_type in {"publication.artifact", "metadata.update", "programme.boundary"}
    return False


def _source_events(
    run: ContentProgrammeRunEnvelope,
    boundary: ProgrammeBoundaryEvent,
    event: ResearchVehiclePublicEvent | None,
) -> tuple[ConversionSourceEvent, ...]:
    refs: list[ConversionSourceEvent] = [
        ConversionSourceEvent(
            source_ref=f"ProgrammeBoundaryEvent:{boundary.boundary_id}",
            event_type=boundary.boundary_type,
            sequence=boundary.sequence,
        )
    ]
    refs.extend(
        ConversionSourceEvent(
            source_ref=f"ContentProgrammeRunStoreEvent:{source.event_id}",
            event_type=source.event_type,
            sequence=source.sequence,
        )
        for source in run.events
    )
    if event is not None:
        refs.append(
            ConversionSourceEvent(
                source_ref=f"ResearchVehiclePublicEvent:{event.event_id}",
                event_type=event.event_type,
            )
        )
    return tuple(refs)


def _provenance_refs(
    run: ContentProgrammeRunEnvelope,
    boundary: ProgrammeBoundaryEvent | None,
    event: ResearchVehiclePublicEvent | None,
) -> tuple[str, ...]:
    refs: list[str] = []
    refs.extend(run.selected_input_refs)
    refs.extend(run.substrate_refs)
    refs.extend(run.wcs.evidence_envelope_refs)
    refs.extend(ref for claim in run.claims for ref in claim.evidence_refs)
    if boundary is not None:
        refs.extend(boundary.evidence_refs)
    if event is not None:
        if event.provenance.token:
            refs.append(event.provenance.token)
        refs.extend(event.provenance.evidence_refs)
        refs.extend(event.provenance.citation_refs)
    return _dedupe(refs)


def _frame_refs(event: ResearchVehiclePublicEvent | None) -> tuple[str, ...]:
    if event is None or event.frame_ref is None:
        return ()
    return (f"{event.frame_ref.kind}:{event.frame_ref.uri}",)


def _chapter_refs(event: ResearchVehiclePublicEvent | None) -> tuple[str, ...]:
    if event is None or event.chapter_ref is None:
        return ()
    return (f"{event.chapter_ref.kind}:{event.chapter_ref.timecode}:{event.chapter_ref.label}",)


def _claim_text(boundary: ProgrammeBoundaryEvent) -> str:
    return " ".join(
        part
        for part in (
            boundary.summary.strip(),
            boundary.claim_shape.scope_limit.strip(),
            boundary.claim_shape.uncertainty.strip(),
        )
        if part
    )


def _fallback_salience(run: ContentProgrammeRunEnvelope, boundary: ProgrammeBoundaryEvent) -> float:
    if boundary.boundary_type in {"refusal.issued", "correction.made"}:
        return 0.72
    if run.final_status in {"blocked", "aborted", "conversion_held"}:
        return 0.58
    return 0.5


def _rights_class(run: ContentProgrammeRunEnvelope) -> RightsClass:
    return {
        "operator_original": "operator_original",
        "cleared": "operator_controlled",
        "platform_embed_only": "platform_embedded",
        "blocked": "third_party_uncleared",
        "unknown": "unknown",
    }[run.rights_privacy_public_mode.rights_state]


def _privacy_class(run: ContentProgrammeRunEnvelope) -> PrivacyClass:
    return {
        "operator_private": "operator_private",
        "public_safe": "public_safe",
        "aggregate_only": "aggregate_only",
        "blocked": "consent_required",
        "unknown": "unknown",
    }[run.rights_privacy_public_mode.privacy_state]


def _privacy_satisfies(state: PrivacyState, requested_state: ReadinessState) -> bool:
    if requested_state in PUBLIC_READINESS_STATES:
        return state in _PUBLIC_SAFE_PRIVACY
    return state in {"operator_private", "public_safe", "aggregate_only"}


def _run_public_event_refs(run: ContentProgrammeRunEnvelope) -> tuple[str, ...]:
    refs: list[str] = []
    refs.extend(
        ref.public_event_mapping_ref
        for ref in run.boundary_event_refs
        if ref.public_event_mapping_ref is not None
    )
    refs.extend(
        candidate.research_vehicle_public_event_ref
        for candidate in run.conversion_candidates
        if candidate.research_vehicle_public_event_ref is not None
    )
    return _dedupe(refs)


def _has_operator_attestation(
    run: ContentProgrammeRunEnvelope,
    event: ResearchVehiclePublicEvent | None,
) -> bool:
    haystack = " ".join(
        (
            *run.selected_input_refs,
            *run.substrate_refs,
            *run.wcs.evidence_envelope_refs,
            *run.gate_refs.grounding_gate_refs,
            *(event.provenance.evidence_refs if event is not None else ()),
        )
    ).lower()
    return "operator-attestation" in haystack or "attestation" in haystack


def _no_hidden_operator_labor(run: ContentProgrammeRunEnvelope) -> bool:
    policy = run.operator_labor_policy
    return (
        policy.single_operator_only
        and not policy.request_queue_allowed
        and not policy.manual_content_calendar_allowed
        and not policy.supporter_controlled_programming_allowed
        and not policy.personalized_supporter_treatment_allowed
    )


def _all_blocker_strings(run: ContentProgrammeRunEnvelope) -> tuple[str, ...]:
    return _dedupe(
        (
            *run.rights_privacy_public_mode.unavailable_reasons,
            *run.wcs.unavailable_reasons,
            *(
                reason
                for candidate in run.conversion_candidates
                for reason in candidate.unavailable_reasons
            ),
        )
    )


def _anti_overclaim_signals(run: ContentProgrammeRunEnvelope) -> tuple[str, ...]:
    signals: list[str] = []
    if run.scores:
        signals.append("engagement")
    if run.rights_privacy_public_mode.monetization_state != "not_requested":
        signals.append("revenue_potential")
    return tuple(signals)


def _outcome_kinds(candidate: ConversionCandidate) -> tuple[OutcomeKind, ...]:
    outcomes: list[OutcomeKind] = []
    if candidate.target_family_id in {
        "dataset_card",
        "artifact_edition_release",
        "replay_demo",
        "youtube_vod_packaging",
    } or candidate.target_type in {
        "refusal_artifact",
        "correction_artifact",
        "failure_artifact",
    }:
        outcomes.append("artifact")
    if (
        candidate.target_family_id
        in {
            "grants_fellowships",
            "support_prompt",
            "residency",
            "licensing",
        }
        or candidate.readiness_state == "public-monetizable"
    ):
        outcomes.append("revenue")
    return tuple(outcomes)


def _coerce_boundary(
    boundary_event: ProgrammeBoundaryEvent | Mapping[str, object],
) -> ProgrammeBoundaryEvent:
    if isinstance(boundary_event, ProgrammeBoundaryEvent):
        return boundary_event
    return ProgrammeBoundaryEvent.model_validate(boundary_event)


def _load_jsonl_ids(path: Path, field: str) -> set[str]:
    ids: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ids
    for line in lines:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and isinstance(item.get(field), str):
            ids.add(item[field])
    return ids


def _dedupe[T: Hashable](values: Iterable[T]) -> tuple[T, ...]:
    return tuple(dict.fromkeys(values))


def _sanitize_id(raw: str) -> str:
    lowered = raw.lower().replace("+00:00", "z")
    cleaned = re.sub(r"[^a-z0-9_:-]+", "_", lowered)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_:")
    if not cleaned or not cleaned[0].isalpha():
        cleaned = f"conversion:{cleaned}"
    return cleaned


__all__ = [
    "ConversionBroker",
    "ConversionBrokerDecision",
    "ConversionBrokerMetrics",
    "ConversionCandidate",
    "ConversionSourceEvent",
    "ConversionTargetRequest",
    "ConversionTargetType",
    "DEFAULT_CANDIDATE_PATH",
    "DEFAULT_PUBLIC_EVENT_PATH",
    "build_conversion_broker_decision",
    "target_requests_for_boundary",
]

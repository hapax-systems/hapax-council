"""Livestream health group contract built from the existing truth spine.

This module is a consumer. It does not probe live routes, infer public-live
state, or repair audio/egress services. Callers pass the current
``LivestreamEgressState``, ``audio_safe_for_broadcast`` state, substrate rows,
programme state, archive decisions, and public-aperture decisions; the health
envelope only summarizes what those authorities already say.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared.archive_replay_public_events import ArchiveReplayPublicLinkDecision
from shared.broadcast_audio_health import BroadcastAudioHealth, BroadcastAudioStatus
from shared.cross_surface_event_contract import (
    CROSS_SURFACE_APERTURES,
    ApertureReality,
    CrossSurfaceApertureContract,
    CrossSurfaceFanoutDecision,
)
from shared.director_vocabulary import ContentSubstrate
from shared.livestream_egress_state import (
    EvidenceStatus,
    FloorState,
    LivestreamEgressEvidence,
    LivestreamEgressState,
)
from shared.programme import Programme, ProgrammeStatus
from shared.research_vehicle_public_event import (
    PrivacyClass,
    ResearchVehiclePublicEvent,
    RightsClass,
)

_PUBLIC_SAFE_RIGHTS: frozenset[RightsClass] = frozenset(
    {"operator_original", "operator_controlled", "third_party_attributed", "platform_embedded"}
)
_PUBLIC_SAFE_PRIVACY: frozenset[PrivacyClass] = frozenset({"public_safe", "aggregate_only"})
_ACTIVE_APERTURE_REALITIES: frozenset[ApertureReality] = frozenset(
    {"active_canonical", "active_legacy", "active_artifact", "active_archive"}
)
_USABLE_SUBSTRATE_STATUSES = {"public-live", "private", "dry-run", "archive-only", "degraded"}


class LivestreamHealthGroupId(StrEnum):
    LOCAL_PREVIEW = "local_preview"
    BROADCAST_TRANSPORT = "broadcast_transport"
    PUBLIC_INGEST = "public_ingest"
    ARCHIVE = "archive"
    AUDIO = "audio"
    PRIVACY = "privacy"
    SUBSTRATE_FRESHNESS = "substrate_freshness"
    PROGRAMME_STATE = "programme_state"
    PUBLIC_APERTURES = "public_apertures"


class LivestreamHealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    BLOCKED = "blocked"
    STALE = "stale"
    MISSING = "missing"
    UNKNOWN = "unknown"


class SubstrateFreshnessObservation(BaseModel):
    """Runtime freshness observation for one ``ContentSubstrate`` row."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    substrate_id: str
    status: Literal["fresh", "stale", "missing", "unknown"] = "fresh"
    checked_at: str | None = None
    observed_age_s: float | None = Field(default=0.0, ge=0.0)
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    note: str | None = None


class LivestreamHealthGroup(BaseModel):
    """One named health group with explicit truth-source references."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    group_id: LivestreamHealthGroupId
    status: LivestreamHealthStatus
    claim_allowed: bool
    degraded_reasons: tuple[str, ...] = Field(default_factory=tuple)
    blocked_reasons: tuple[str, ...] = Field(default_factory=tuple)
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    source_refs: tuple[str, ...] = Field(default_factory=tuple)
    next_actions: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _non_healthy_groups_explain_themselves(self) -> LivestreamHealthGroup:
        if self.status is not LivestreamHealthStatus.HEALTHY and not (
            self.degraded_reasons or self.blocked_reasons
        ):
            raise ValueError(f"{self.group_id.value} non-healthy status needs a reason")
        if self.claim_allowed and self.status in {
            LivestreamHealthStatus.BLOCKED,
            LivestreamHealthStatus.MISSING,
            LivestreamHealthStatus.UNKNOWN,
            LivestreamHealthStatus.STALE,
        }:
            raise ValueError(f"{self.group_id.value} claim_allowed cannot be {self.status.value}")
        return self


class LivestreamHealthEnvelope(BaseModel):
    """Aggregate livestream health answer for UI, director, and public gates."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    checked_at: str
    overall_status: LivestreamHealthStatus
    groups: tuple[LivestreamHealthGroup, ...]
    safe_to_watch: bool
    safe_to_publish: bool
    safe_to_monetize: bool
    useful_for_research_capture: bool
    public_claim_allowed_source: Literal["LivestreamEgressState.public_claim_allowed"]
    audio_safe_source: Literal["BroadcastAudioHealth.safe"]
    substrate_source: Literal["ContentSubstrate"]
    blocking_reasons: tuple[str, ...] = Field(default_factory=tuple)
    degraded_reasons: tuple[str, ...] = Field(default_factory=tuple)
    next_actions: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _validate_group_set_and_claim_implications(self) -> LivestreamHealthEnvelope:
        expected = {group_id.value for group_id in LivestreamHealthGroupId}
        actual = {group.group_id.value for group in self.groups}
        if actual != expected:
            raise ValueError(
                f"health envelope groups drifted; missing={sorted(expected - actual)}, "
                f"extra={sorted(actual - expected)}"
            )
        if self.safe_to_monetize and not self.safe_to_publish:
            raise ValueError("safe_to_monetize requires safe_to_publish")
        if self.safe_to_publish and not self.safe_to_watch:
            raise ValueError("safe_to_publish requires safe_to_watch")
        if self.safe_to_watch and self._group(LivestreamHealthGroupId.LOCAL_PREVIEW).status in {
            LivestreamHealthStatus.BLOCKED,
            LivestreamHealthStatus.MISSING,
            LivestreamHealthStatus.UNKNOWN,
        }:
            raise ValueError("safe_to_watch requires local preview truth")
        return self

    def _group(self, group_id: LivestreamHealthGroupId) -> LivestreamHealthGroup:
        return next(group for group in self.groups if group.group_id is group_id)

    def groups_by_id(self) -> dict[str, LivestreamHealthGroup]:
        """Return groups keyed by stable group id."""

        return {group.group_id.value: group for group in self.groups}


def build_livestream_health_envelope(
    *,
    egress: LivestreamEgressState,
    audio_safe_for_broadcast: BroadcastAudioHealth,
    substrates: Iterable[ContentSubstrate | Mapping[str, Any]] = (),
    substrate_observations: Mapping[str, SubstrateFreshnessObservation | Mapping[str, Any]]
    | None = None,
    programme: Programme | Mapping[str, Any] | None = None,
    archive_decisions: Iterable[ArchiveReplayPublicLinkDecision | Mapping[str, Any]] = (),
    public_events: Iterable[ResearchVehiclePublicEvent | Mapping[str, Any]] = (),
    public_apertures: Iterable[CrossSurfaceApertureContract | Mapping[str, Any]] | None = None,
    fanout_decisions: Iterable[CrossSurfaceFanoutDecision | Mapping[str, Any]] = (),
    checked_at: str | None = None,
) -> LivestreamHealthEnvelope:
    """Build a health envelope from already-resolved truth surfaces."""

    observed_at = checked_at or datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    substrate_rows = _coerce_substrates(substrates)
    substrate_obs = _coerce_substrate_observations(substrate_observations or {})
    programme_state = _coerce_programme(programme)
    archive_rows = _coerce_archive_decisions(archive_decisions)
    events = _coerce_public_events(public_events)
    apertures = _coerce_public_apertures(public_apertures)
    fanout = _coerce_fanout_decisions(fanout_decisions)

    groups = (
        _egress_group(
            LivestreamHealthGroupId.LOCAL_PREVIEW,
            egress,
            sources=("local_preview",),
            claim_allowed=egress_evidence_passes(egress, "local_preview"),
            missing_status=LivestreamHealthStatus.MISSING,
        ),
        _egress_group(
            LivestreamHealthGroupId.BROADCAST_TRANSPORT,
            egress,
            sources=("hls_playlist", "rtmp_output", "mediamtx_hls"),
            claim_allowed=egress_evidence_passes(
                egress, "hls_playlist", "rtmp_output", "mediamtx_hls"
            ),
            missing_status=LivestreamHealthStatus.MISSING,
        ),
        _public_ingest_group(egress),
        _archive_group(egress, archive_rows),
        _audio_group(audio_safe_for_broadcast),
        _privacy_group(egress),
        _substrate_group(substrate_rows, substrate_obs),
        _programme_group(programme_state),
        _public_aperture_group(apertures, events, fanout),
    )

    by_id = {group.group_id: group for group in groups}
    safe_to_watch = (
        by_id[LivestreamHealthGroupId.LOCAL_PREVIEW].claim_allowed
        and by_id[LivestreamHealthGroupId.PRIVACY].claim_allowed
        and by_id[LivestreamHealthGroupId.AUDIO].status
        not in {LivestreamHealthStatus.BLOCKED, LivestreamHealthStatus.UNKNOWN}
    )
    safe_to_publish = (
        safe_to_watch
        and egress.public_claim_allowed
        and by_id[LivestreamHealthGroupId.BROADCAST_TRANSPORT].claim_allowed
        and by_id[LivestreamHealthGroupId.PUBLIC_INGEST].claim_allowed
        and by_id[LivestreamHealthGroupId.AUDIO].claim_allowed
        and by_id[LivestreamHealthGroupId.PUBLIC_APERTURES].claim_allowed
    )
    monetization_evidence = _has_monetization_evidence(
        substrates=substrate_rows,
        observations=substrate_obs,
        public_events=events,
        fanout_decisions=fanout,
    )
    safe_to_monetize = (
        safe_to_publish and egress.monetization_risk in {"none", "low"} and monetization_evidence
    )
    useful_for_research_capture = (
        egress.research_capture_ready
        and by_id[LivestreamHealthGroupId.LOCAL_PREVIEW].claim_allowed
        and by_id[LivestreamHealthGroupId.ARCHIVE].status
        not in {LivestreamHealthStatus.BLOCKED, LivestreamHealthStatus.MISSING}
        and by_id[LivestreamHealthGroupId.SUBSTRATE_FRESHNESS].status
        not in {
            LivestreamHealthStatus.BLOCKED,
            LivestreamHealthStatus.MISSING,
            LivestreamHealthStatus.STALE,
            LivestreamHealthStatus.UNKNOWN,
        }
    )

    blocking = _dedupe(reason for group in groups for reason in group.blocked_reasons)
    degraded = _dedupe(reason for group in groups for reason in group.degraded_reasons)
    return LivestreamHealthEnvelope(
        checked_at=observed_at,
        overall_status=_overall_status(groups),
        groups=groups,
        safe_to_watch=safe_to_watch,
        safe_to_publish=safe_to_publish,
        safe_to_monetize=safe_to_monetize,
        useful_for_research_capture=useful_for_research_capture,
        public_claim_allowed_source="LivestreamEgressState.public_claim_allowed",
        audio_safe_source="BroadcastAudioHealth.safe",
        substrate_source="ContentSubstrate",
        blocking_reasons=tuple(blocking),
        degraded_reasons=tuple(degraded),
        next_actions=tuple(_dedupe(action for group in groups for action in group.next_actions)),
    )


def egress_evidence_passes(egress: LivestreamEgressState, *sources: str) -> bool:
    """Return true only when all named egress evidence records pass."""

    by_source = _evidence_by_source(egress)
    return all(
        source in by_source
        and by_source[source].status is EvidenceStatus.PASS
        and not by_source[source].stale
        for source in sources
    )


def _egress_group(
    group_id: LivestreamHealthGroupId,
    egress: LivestreamEgressState,
    *,
    sources: tuple[str, ...],
    claim_allowed: bool,
    missing_status: LivestreamHealthStatus,
) -> LivestreamHealthGroup:
    by_source = _evidence_by_source(egress)
    records = [by_source[source] for source in sources if source in by_source]
    missing = [source for source in sources if source not in by_source]
    if missing:
        return LivestreamHealthGroup(
            group_id=group_id,
            status=missing_status,
            claim_allowed=False,
            blocked_reasons=tuple(f"{source}:missing" for source in missing),
            source_refs=tuple(f"LivestreamEgressState.evidence:{source}" for source in sources),
            next_actions=("restore missing egress evidence producer",),
        )

    status = _status_from_egress_records(records)
    degraded, blocked = _reasons_from_egress_records(records)
    return LivestreamHealthGroup(
        group_id=group_id,
        status=status,
        claim_allowed=claim_allowed and status is LivestreamHealthStatus.HEALTHY,
        degraded_reasons=tuple(degraded),
        blocked_reasons=tuple(blocked),
        evidence_refs=tuple(_egress_ref(record) for record in records),
        source_refs=tuple(f"LivestreamEgressState.evidence:{source}" for source in sources),
        next_actions=_egress_next_actions(egress, records),
    )


def _public_ingest_group(egress: LivestreamEgressState) -> LivestreamHealthGroup:
    group = _egress_group(
        LivestreamHealthGroupId.PUBLIC_INGEST,
        egress,
        sources=("active_video_id", "youtube_ingest", "metadata"),
        claim_allowed=egress.public_claim_allowed,
        missing_status=LivestreamHealthStatus.MISSING,
    )
    if egress.public_claim_allowed:
        return group
    blockers = tuple(_dedupe((*group.blocked_reasons, *egress.public_claim_blockers)))
    if group.status is LivestreamHealthStatus.HEALTHY:
        return group.model_copy(
            update={
                "status": LivestreamHealthStatus.BLOCKED,
                "claim_allowed": False,
                "blocked_reasons": blockers
                or ("LivestreamEgressState.public_claim_allowed:false",),
                "next_actions": _dedupe((*group.next_actions, egress.operator_action)),
            }
        )
    return group.model_copy(
        update={
            "claim_allowed": False,
            "blocked_reasons": blockers,
            "next_actions": _dedupe((*group.next_actions, egress.operator_action)),
        }
    )


def _archive_group(
    egress: LivestreamEgressState,
    archive_decisions: tuple[ArchiveReplayPublicLinkDecision, ...],
) -> LivestreamHealthGroup:
    base = _egress_group(
        LivestreamHealthGroupId.ARCHIVE,
        egress,
        sources=("hls_archive",),
        claim_allowed=egress_evidence_passes(egress, "hls_archive"),
        missing_status=LivestreamHealthStatus.MISSING,
    )
    if archive_decisions:
        allowed = [
            decision for decision in archive_decisions if decision.public_replay_link_claim_allowed
        ]
        capture = [
            decision for decision in archive_decisions if decision.archive_capture_claim_allowed
        ]
        reasons = tuple(
            _dedupe(
                reason for decision in archive_decisions for reason in decision.unavailable_reasons
            )
        )
        if allowed:
            status = (
                LivestreamHealthStatus.HEALTHY
                if base.status is LivestreamHealthStatus.HEALTHY
                else base.status
            )
            return base.model_copy(
                update={
                    "status": status,
                    "claim_allowed": base.status
                    in {LivestreamHealthStatus.HEALTHY, LivestreamHealthStatus.DEGRADED},
                    "evidence_refs": _dedupe(
                        (
                            *base.evidence_refs,
                            *(decision.decision_id for decision in allowed),
                        )
                    ),
                    "source_refs": _dedupe((*base.source_refs, "ArchiveReplayPublicLinkDecision")),
                }
            )
        if capture:
            return base.model_copy(
                update={
                    "status": LivestreamHealthStatus.DEGRADED,
                    "claim_allowed": base.status
                    in {LivestreamHealthStatus.HEALTHY, LivestreamHealthStatus.DEGRADED},
                    "degraded_reasons": _dedupe(
                        (
                            *base.degraded_reasons,
                            "archive_capture_available_but_public_replay_link_not_claimable",
                            *reasons,
                        )
                    ),
                    "source_refs": _dedupe((*base.source_refs, "ArchiveReplayPublicLinkDecision")),
                }
            )
        return base.model_copy(
            update={
                "status": LivestreamHealthStatus.BLOCKED,
                "claim_allowed": False,
                "blocked_reasons": _dedupe(
                    (*base.blocked_reasons, "archive_capture_not_claimable", *reasons)
                ),
                "source_refs": _dedupe((*base.source_refs, "ArchiveReplayPublicLinkDecision")),
            }
        )

    if base.status is LivestreamHealthStatus.HEALTHY:
        return base.model_copy(
            update={
                "status": LivestreamHealthStatus.DEGRADED,
                "claim_allowed": True,
                "degraded_reasons": ("archive_replay_public_link_decision_missing",),
                "source_refs": _dedupe((*base.source_refs, "LivestreamEgressState.hls_archive")),
            }
        )
    return base


def _audio_group(audio: BroadcastAudioHealth) -> LivestreamHealthGroup:
    reason_codes = tuple(reason.code for reason in audio.blocking_reasons)
    if audio.safe and audio.status is BroadcastAudioStatus.SAFE:
        status = LivestreamHealthStatus.HEALTHY
        degraded: tuple[str, ...] = ()
        blocked: tuple[str, ...] = ()
    elif audio.safe:
        status = LivestreamHealthStatus.DEGRADED
        degraded = tuple(reason.code for reason in audio.warnings) or (
            f"audio_status:{audio.status.value}",
        )
        blocked = ()
    elif audio.status is BroadcastAudioStatus.UNKNOWN:
        status = LivestreamHealthStatus.UNKNOWN
        degraded = ()
        blocked = reason_codes or ("audio_safe_for_broadcast_unknown",)
    else:
        status = LivestreamHealthStatus.BLOCKED
        degraded = ()
        blocked = reason_codes or (f"audio_status:{audio.status.value}",)
    return LivestreamHealthGroup(
        group_id=LivestreamHealthGroupId.AUDIO,
        status=status,
        claim_allowed=audio.safe and audio.status is BroadcastAudioStatus.SAFE,
        degraded_reasons=degraded,
        blocked_reasons=blocked,
        evidence_refs=tuple(f"audio:{key}" for key in sorted(audio.evidence)),
        source_refs=("BroadcastAudioHealth",),
        next_actions=tuple(reason.message for reason in audio.blocking_reasons),
    )


def _privacy_group(egress: LivestreamEgressState) -> LivestreamHealthGroup:
    if egress.privacy_floor is FloorState.SATISFIED:
        status = LivestreamHealthStatus.HEALTHY
        blocked: tuple[str, ...] = ()
    elif egress.privacy_floor is FloorState.UNKNOWN:
        status = LivestreamHealthStatus.UNKNOWN
        blocked = ("privacy_floor_unknown",)
    else:
        status = LivestreamHealthStatus.BLOCKED
        blocked = ("privacy_floor_blocked",)
    privacy_evidence = [record for record in egress.evidence if record.source == "privacy_floor"]
    return LivestreamHealthGroup(
        group_id=LivestreamHealthGroupId.PRIVACY,
        status=status,
        claim_allowed=egress.privacy_floor is FloorState.SATISFIED,
        blocked_reasons=blocked,
        evidence_refs=tuple(_egress_ref(record) for record in privacy_evidence),
        source_refs=("LivestreamEgressState.privacy_floor",),
        next_actions=("restore face-obscure/privacy floor evidence",) if blocked else (),
    )


def _substrate_group(
    substrates: tuple[ContentSubstrate, ...],
    observations: Mapping[str, SubstrateFreshnessObservation],
) -> LivestreamHealthGroup:
    if not substrates:
        return LivestreamHealthGroup(
            group_id=LivestreamHealthGroupId.SUBSTRATE_FRESHNESS,
            status=LivestreamHealthStatus.MISSING,
            claim_allowed=False,
            blocked_reasons=("content_substrate_rows_missing",),
            source_refs=("ContentSubstrate",),
            next_actions=("load the livestream substrate registry rows",),
        )

    claimable: list[str] = []
    usable: list[str] = []
    stale: list[str] = []
    blocked: list[str] = []
    degraded: list[str] = []
    evidence_refs: list[str] = []

    for row in substrates:
        observation = observations.get(row.substrate_id)
        evidence_refs.extend(_substrate_evidence_refs(row, observation))
        if row.integration_status == "public-live":
            if _substrate_fresh(row, observation):
                claimable.append(row.substrate_id)
                usable.append(row.substrate_id)
            else:
                stale.append(_substrate_freshness_reason(row, observation))
            continue

        if row.integration_status == "unavailable":
            blocked.append(f"{row.substrate_id}:unavailable:{row.fallback.reason}")
        elif row.integration_status in _USABLE_SUBSTRATE_STATUSES:
            usable.append(row.substrate_id)
            degraded.append(f"{row.substrate_id}:{row.integration_status}:{row.fallback.reason}")
        else:
            degraded.append(f"{row.substrate_id}:{row.integration_status}:{row.fallback.reason}")

    if claimable and not stale and not blocked and not degraded:
        status = LivestreamHealthStatus.HEALTHY
    elif claimable or usable:
        status = LivestreamHealthStatus.DEGRADED
    elif stale:
        status = LivestreamHealthStatus.STALE
    else:
        status = LivestreamHealthStatus.BLOCKED

    return LivestreamHealthGroup(
        group_id=LivestreamHealthGroupId.SUBSTRATE_FRESHNESS,
        status=status,
        claim_allowed=bool(claimable)
        and status
        in {
            LivestreamHealthStatus.HEALTHY,
            LivestreamHealthStatus.DEGRADED,
        },
        degraded_reasons=tuple(_dedupe((*degraded, *stale))),
        blocked_reasons=tuple(_dedupe(blocked if not usable and not claimable else ())),
        evidence_refs=tuple(_dedupe(evidence_refs)),
        source_refs=("ContentSubstrate", "SubstrateFreshnessObservation"),
        next_actions=tuple(
            _dedupe(
                "refresh substrate health signal or lower public claim"
                for _reason in [*stale, *blocked]
            )
        ),
    )


def _programme_group(programme: Programme | None) -> LivestreamHealthGroup:
    if programme is None:
        return LivestreamHealthGroup(
            group_id=LivestreamHealthGroupId.PROGRAMME_STATE,
            status=LivestreamHealthStatus.DEGRADED,
            claim_allowed=False,
            degraded_reasons=("programme_state_missing",),
            source_refs=("ProgrammePlanStore.active_programme",),
            next_actions=(
                "start or load an active programme when programme-aware capture is required",
            ),
        )
    if programme.status is ProgrammeStatus.ACTIVE:
        return LivestreamHealthGroup(
            group_id=LivestreamHealthGroupId.PROGRAMME_STATE,
            status=LivestreamHealthStatus.HEALTHY,
            claim_allowed=True,
            evidence_refs=(f"programme:{programme.programme_id}",),
            source_refs=("Programme",),
        )
    return LivestreamHealthGroup(
        group_id=LivestreamHealthGroupId.PROGRAMME_STATE,
        status=LivestreamHealthStatus.DEGRADED,
        claim_allowed=False,
        degraded_reasons=(f"programme:{programme.programme_id}:{programme.status.value}",),
        evidence_refs=(f"programme:{programme.programme_id}",),
        source_refs=("Programme",),
        next_actions=("activate a programme before programme-state public claims",),
    )


def _public_aperture_group(
    apertures: tuple[CrossSurfaceApertureContract, ...],
    public_events: tuple[ResearchVehiclePublicEvent, ...],
    fanout_decisions: tuple[CrossSurfaceFanoutDecision, ...],
) -> LivestreamHealthGroup:
    if fanout_decisions:
        allowed = [
            decision
            for decision in fanout_decisions
            if decision.decision == "allow" and decision.health_status == "ok"
        ]
        blocked = [
            reason
            for decision in fanout_decisions
            if decision.health_status == "blocked"
            for reason in decision.reasons
        ]
        degraded = [
            reason
            for decision in fanout_decisions
            if decision.health_status == "degraded"
            for reason in decision.reasons
        ]
        if allowed and not blocked and not degraded:
            status = LivestreamHealthStatus.HEALTHY
        elif allowed:
            status = LivestreamHealthStatus.DEGRADED
        elif blocked and not degraded:
            status = LivestreamHealthStatus.BLOCKED
        else:
            status = LivestreamHealthStatus.DEGRADED
        return LivestreamHealthGroup(
            group_id=LivestreamHealthGroupId.PUBLIC_APERTURES,
            status=status,
            claim_allowed=bool(allowed),
            degraded_reasons=tuple(_dedupe(degraded if allowed or not blocked else ())),
            blocked_reasons=tuple(_dedupe(blocked if not allowed else ())),
            evidence_refs=tuple(decision.decision_id for decision in fanout_decisions),
            source_refs=("CrossSurfaceFanoutDecision", "ResearchVehiclePublicEvent"),
            next_actions=tuple(_dedupe(decision.child_task for decision in fanout_decisions)),
        )

    active_apertures = [
        aperture.aperture_id
        for aperture in apertures
        if aperture.current_reality in _ACTIVE_APERTURE_REALITIES
    ]
    event_refs = tuple(event.event_id for event in public_events)
    if public_events and active_apertures:
        return LivestreamHealthGroup(
            group_id=LivestreamHealthGroupId.PUBLIC_APERTURES,
            status=LivestreamHealthStatus.DEGRADED,
            claim_allowed=False,
            degraded_reasons=("public_event_present_but_fanout_decision_missing",),
            evidence_refs=event_refs,
            source_refs=("ResearchVehiclePublicEvent", "CrossSurfaceApertureContract"),
            next_actions=("run the appropriate public aperture adapter in dry-run/decision mode",),
        )
    if active_apertures:
        return LivestreamHealthGroup(
            group_id=LivestreamHealthGroupId.PUBLIC_APERTURES,
            status=LivestreamHealthStatus.DEGRADED,
            claim_allowed=False,
            degraded_reasons=("static_aperture_contract_only:no_fanout_decision",),
            evidence_refs=tuple(f"aperture:{aperture}" for aperture in active_apertures),
            source_refs=("CrossSurfaceApertureContract",),
            next_actions=("produce a ResearchVehiclePublicEvent fanout decision",),
        )
    return LivestreamHealthGroup(
        group_id=LivestreamHealthGroupId.PUBLIC_APERTURES,
        status=LivestreamHealthStatus.BLOCKED,
        claim_allowed=False,
        blocked_reasons=("no_active_public_aperture_truth",),
        source_refs=("CrossSurfaceApertureContract",),
        next_actions=("wire at least one public aperture contract or fanout decision",),
    )


def _has_monetization_evidence(
    *,
    substrates: tuple[ContentSubstrate, ...],
    observations: Mapping[str, SubstrateFreshnessObservation],
    public_events: tuple[ResearchVehiclePublicEvent, ...],
    fanout_decisions: tuple[CrossSurfaceFanoutDecision, ...],
) -> bool:
    event_monetizable = any(
        event.surface_policy.claim_monetizable
        and event.rights_class in _PUBLIC_SAFE_RIGHTS
        and event.privacy_class in _PUBLIC_SAFE_PRIVACY
        and (not event.surface_policy.requires_provenance or bool(event.provenance.token))
        for event in public_events
    )
    fanout_monetizable = any(
        decision.decision == "allow" and decision.surface_policy_snapshot.claim_monetizable
        for decision in fanout_decisions
    )
    substrate_monetizable = any(
        row.public_claim_permissions.claim_monetizable
        and row.integration_status == "public-live"
        and _substrate_fresh(row, observations.get(row.substrate_id))
        for row in substrates
    )
    return event_monetizable or fanout_monetizable or substrate_monetizable


def _coerce_substrates(
    substrates: Iterable[ContentSubstrate | Mapping[str, Any]],
) -> tuple[ContentSubstrate, ...]:
    return tuple(
        row if isinstance(row, ContentSubstrate) else ContentSubstrate.model_validate(row)
        for row in substrates
    )


def _coerce_substrate_observations(
    observations: Mapping[str, SubstrateFreshnessObservation | Mapping[str, Any]],
) -> dict[str, SubstrateFreshnessObservation]:
    coerced: dict[str, SubstrateFreshnessObservation] = {}
    for key, value in observations.items():
        observation = (
            value
            if isinstance(value, SubstrateFreshnessObservation)
            else SubstrateFreshnessObservation.model_validate({"substrate_id": key, **value})
        )
        if observation.substrate_id != key:
            raise ValueError(
                f"substrate observation key {key!r} != substrate_id {observation.substrate_id!r}"
            )
        coerced[key] = observation
    return coerced


def _coerce_programme(programme: Programme | Mapping[str, Any] | None) -> Programme | None:
    if programme is None:
        return None
    if isinstance(programme, Programme):
        return programme
    return Programme.model_validate(programme)


def _coerce_archive_decisions(
    decisions: Iterable[ArchiveReplayPublicLinkDecision | Mapping[str, Any]],
) -> tuple[ArchiveReplayPublicLinkDecision, ...]:
    return tuple(
        decision
        if isinstance(decision, ArchiveReplayPublicLinkDecision)
        else ArchiveReplayPublicLinkDecision.model_validate(decision)
        for decision in decisions
    )


def _coerce_public_events(
    public_events: Iterable[ResearchVehiclePublicEvent | Mapping[str, Any]],
) -> tuple[ResearchVehiclePublicEvent, ...]:
    return tuple(
        event
        if isinstance(event, ResearchVehiclePublicEvent)
        else ResearchVehiclePublicEvent.model_validate(event)
        for event in public_events
    )


def _coerce_public_apertures(
    public_apertures: Iterable[CrossSurfaceApertureContract | Mapping[str, Any]] | None,
) -> tuple[CrossSurfaceApertureContract, ...]:
    if public_apertures is None:
        return CROSS_SURFACE_APERTURES
    return tuple(
        aperture
        if isinstance(aperture, CrossSurfaceApertureContract)
        else CrossSurfaceApertureContract.model_validate(aperture)
        for aperture in public_apertures
    )


def _coerce_fanout_decisions(
    fanout_decisions: Iterable[CrossSurfaceFanoutDecision | Mapping[str, Any]],
) -> tuple[CrossSurfaceFanoutDecision, ...]:
    return tuple(
        decision
        if isinstance(decision, CrossSurfaceFanoutDecision)
        else CrossSurfaceFanoutDecision.model_validate(decision)
        for decision in fanout_decisions
    )


def _evidence_by_source(
    egress: LivestreamEgressState,
) -> dict[str, LivestreamEgressEvidence]:
    return {record.source: record for record in egress.evidence}


def _status_from_egress_records(
    records: list[LivestreamEgressEvidence],
) -> LivestreamHealthStatus:
    if any(record.status is EvidenceStatus.FAIL for record in records):
        return LivestreamHealthStatus.BLOCKED
    if any(record.stale for record in records):
        return LivestreamHealthStatus.STALE
    if any(record.status is EvidenceStatus.UNKNOWN for record in records):
        return LivestreamHealthStatus.UNKNOWN
    if any(record.status is EvidenceStatus.WARN for record in records):
        return LivestreamHealthStatus.DEGRADED
    return LivestreamHealthStatus.HEALTHY


def _reasons_from_egress_records(
    records: list[LivestreamEgressEvidence],
) -> tuple[list[str], list[str]]:
    degraded: list[str] = []
    blocked: list[str] = []
    for record in records:
        reason = f"{record.source}:{record.status.value}:{record.summary}"
        if record.status is EvidenceStatus.FAIL:
            blocked.append(reason)
        elif record.status in {EvidenceStatus.WARN, EvidenceStatus.UNKNOWN} or record.stale:
            degraded.append(reason)
    return degraded, blocked


def _egress_ref(record: LivestreamEgressEvidence) -> str:
    if record.timestamp:
        return f"egress:{record.source}:{record.timestamp}"
    if record.age_s is not None:
        return f"egress:{record.source}:age_s={record.age_s:.1f}"
    return f"egress:{record.source}"


def _egress_next_actions(
    egress: LivestreamEgressState,
    records: list[LivestreamEgressEvidence],
) -> tuple[str, ...]:
    if all(record.status is EvidenceStatus.PASS and not record.stale for record in records):
        return ()
    if egress.operator_action and egress.operator_action != "none":
        return (egress.operator_action,)
    return ("restore failing egress evidence source",)


def _substrate_fresh(
    row: ContentSubstrate,
    observation: SubstrateFreshnessObservation | None,
) -> bool:
    if row.freshness_ttl_s is None:
        return observation is not None and observation.status == "fresh"
    if observation is None:
        return False
    if observation.status != "fresh":
        return False
    return (
        observation.observed_age_s is not None and observation.observed_age_s <= row.freshness_ttl_s
    )


def _substrate_freshness_reason(
    row: ContentSubstrate,
    observation: SubstrateFreshnessObservation | None,
) -> str:
    if observation is None:
        return f"{row.substrate_id}:freshness_missing:{row.health_signal.freshness_ref}"
    if observation.status != "fresh":
        return f"{row.substrate_id}:freshness_{observation.status}:{observation.note or ''}".rstrip(
            ":"
        )
    if row.freshness_ttl_s is not None and observation.observed_age_s is not None:
        return (
            f"{row.substrate_id}:stale:"
            f"age_s={observation.observed_age_s:.1f}>ttl_s={row.freshness_ttl_s}"
        )
    return f"{row.substrate_id}:freshness_unknown"


def _substrate_evidence_refs(
    row: ContentSubstrate,
    observation: SubstrateFreshnessObservation | None,
) -> tuple[str, ...]:
    refs = [f"substrate:{row.substrate_id}", row.health_signal.status_ref]
    if row.health_signal.freshness_ref:
        refs.append(row.health_signal.freshness_ref)
    if observation:
        refs.extend(observation.evidence_refs)
    return tuple(refs)


def _overall_status(groups: tuple[LivestreamHealthGroup, ...]) -> LivestreamHealthStatus:
    statuses = [group.status for group in groups]
    for candidate in (
        LivestreamHealthStatus.BLOCKED,
        LivestreamHealthStatus.MISSING,
        LivestreamHealthStatus.STALE,
        LivestreamHealthStatus.UNKNOWN,
        LivestreamHealthStatus.DEGRADED,
    ):
        if candidate in statuses:
            return candidate
    return LivestreamHealthStatus.HEALTHY


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


__all__ = [
    "LivestreamHealthEnvelope",
    "LivestreamHealthGroup",
    "LivestreamHealthGroupId",
    "LivestreamHealthStatus",
    "SubstrateFreshnessObservation",
    "build_livestream_health_envelope",
    "egress_evidence_passes",
]

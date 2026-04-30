"""Archive replay public-link adapter contracts.

This module maps HLS archive sidecars into canonical
``ResearchVehiclePublicEvent`` records only when replay/public-link evidence is
fresh and claim-bearing. It does not rotate archive media or publish replay
links; it is the contract downstream replay surfaces can consume without
inferring readiness from archive capture alone.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from shared.research_vehicle_public_event import (
    PrivacyClass,
    PublicEventChapterRef,
    PublicEventProvenance,
    PublicEventSource,
    PublicEventSurfacePolicy,
    ResearchVehiclePublicEvent,
    RightsClass,
    Surface,
)
from shared.stream_archive import SegmentSidecar, sidecar_path_for
from shared.temporal_span_registry import (
    ClaimBearingMediaOutput,
    SpanClaimGateDecision,
    TemporalSpanRegistry,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_REPLAY_PUBLIC_EVENT_FIXTURES = (
    REPO_ROOT / "config" / "archive-replay-public-event-fixtures.json"
)

TASK_ANCHOR = "archive-replay-public-event-link-adapter"
PRODUCER = "shared.archive_replay_public_events"
CURSOR_OWNER = "archive-replay-public-event-link-adapter:sidecar_path+event_id"
IDEMPOTENCY_OWNER = "archive-replay-public-event-link-adapter:event_id"
ARCHIVE_CAPTURE_KIND = "hls_archive_capture"
PUBLIC_REPLAY_PUBLICATION_KIND = "research_vehicle_public_event"

_PUBLIC_SAFE_RIGHTS: frozenset[RightsClass] = frozenset(
    {"operator_original", "operator_controlled", "third_party_attributed"}
)
_PUBLIC_SAFE_PRIVACY: frozenset[PrivacyClass] = frozenset({"public_safe", "aggregate_only"})
_ALLOWED_REPLAY_SURFACES: tuple[Surface, ...] = ("archive", "replay")
_DENIED_REPLAY_SURFACES: tuple[Surface, ...] = (
    "youtube_description",
    "youtube_cuepoints",
    "youtube_chapters",
    "youtube_captions",
    "youtube_shorts",
    "youtube_channel_sections",
    "arena",
    "omg_statuslog",
    "omg_weblog",
    "omg_now",
    "mastodon",
    "bluesky",
    "discord",
    "captions",
    "cuepoints",
    "health",
    "monetization",
)

type ArchiveReplayGateStatus = Literal["pass", "fail", "missing", "stale"]
type ArchiveReplayDecisionStatus = Literal["emitted", "held", "refused"]
type ArchiveReplayFixtureCase = Literal[
    "clean_public_replay_link",
    "missing_temporal_span_refs",
    "private_temporal_span_ref",
    "rights_privacy_blocked",
    "egress_blocked",
    "capture_only_no_public_url",
]


class ArchiveReplayPublicEventError(ValueError):
    """Raised when archive replay fixture contracts cannot load safely."""


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ArchiveReplayPublicLinkEvidence(FrozenModel):
    """Evidence required before an archive sidecar can become a replay link."""

    schema_version: Literal[1] = 1
    public_url: str | None
    broadcast_id: str | None = None
    programme_id: str | None = None
    replay_title: str = Field(min_length=1)
    salience: float = Field(ge=0.0, le=1.0)
    rights_class: RightsClass
    privacy_class: PrivacyClass
    rights_basis: str = Field(min_length=1)
    attribution_refs: tuple[str, ...] = Field(default_factory=tuple)
    provenance_token: str | None
    provenance_evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    temporal_span_refs: tuple[str, ...] = Field(default_factory=tuple)
    source_segment_refs: tuple[str, ...] = Field(default_factory=tuple)
    egress_public_claim_allowed: bool
    egress_evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    audio_safe_for_broadcast: bool
    public_event_gate_ref: str | None
    public_event_gate_status: ArchiveReplayGateStatus
    evidence_fresh_at: str
    evidence_max_age_s: float = Field(gt=0.0)


class ArchiveReplayPublicLinkDecision(FrozenModel):
    """Adapter decision with explicit separation of capture and publication."""

    schema_version: Literal[1] = 1
    decision_id: str
    idempotency_key: str
    status: ArchiveReplayDecisionStatus
    archive_capture_kind: Literal["hls_archive_capture"] = ARCHIVE_CAPTURE_KIND
    archive_capture_claim_allowed: bool
    public_replay_publication_kind: Literal["research_vehicle_public_event"] = (
        PUBLIC_REPLAY_PUBLICATION_KIND
    )
    public_replay_link_claim_allowed: bool
    public_event: ResearchVehiclePublicEvent | None
    unavailable_reasons: tuple[str, ...] = Field(default_factory=tuple)
    source_segment_refs: tuple[str, ...] = Field(min_length=1)
    temporal_span_refs: tuple[str, ...] = Field(default_factory=tuple)
    gate_refs: tuple[str, ...] = Field(default_factory=tuple)
    evidence_freshness_ref: str
    span_gate_status: str
    span_gate_reason_codes: tuple[str, ...] = Field(default_factory=tuple)
    cursor_owner: Literal["archive-replay-public-event-link-adapter:sidecar_path+event_id"] = (
        CURSOR_OWNER
    )
    idempotency_owner: Literal["archive-replay-public-event-link-adapter:event_id"] = (
        IDEMPOTENCY_OWNER
    )


class ArchiveReplayFixture(FrozenModel):
    case: ArchiveReplayFixtureCase
    sidecar: dict[str, Any]
    evidence: ArchiveReplayPublicLinkEvidence
    expected_status: ArchiveReplayDecisionStatus
    expected_public_replay_link_claim_allowed: bool
    expected_unavailable_reasons: tuple[str, ...] = Field(default_factory=tuple)


class ArchiveReplayFixtureSet(FrozenModel):
    schema_version: Literal[1]
    fixture_set_id: str
    schema_ref: Literal["schemas/archive-replay-public-event.schema.json"]
    generated_from: tuple[str, ...] = Field(min_length=1)
    declared_at: str
    producer: str
    cursor_owner: Literal["archive-replay-public-event-link-adapter:sidecar_path+event_id"]
    idempotency_owner: Literal["archive-replay-public-event-link-adapter:event_id"]
    fixtures: tuple[ArchiveReplayFixture, ...] = Field(min_length=1)

    def by_case(self) -> dict[ArchiveReplayFixtureCase, ArchiveReplayFixture]:
        """Return replay fixtures keyed by fixture case."""

        return {fixture.case: fixture for fixture in self.fixtures}

    def validate_contract(self, registry: TemporalSpanRegistry) -> None:
        """Validate fixture expectations against the adapter decision contract."""

        required: set[ArchiveReplayFixtureCase] = {
            "clean_public_replay_link",
            "missing_temporal_span_refs",
            "private_temporal_span_ref",
            "rights_privacy_blocked",
            "egress_blocked",
            "capture_only_no_public_url",
        }
        cases = set(self.by_case())
        if cases != required:
            missing = sorted(required - cases)
            extra = sorted(cases - required)
            raise ArchiveReplayPublicEventError(
                f"fixture cases drifted; missing={missing}, extra={extra}"
            )
        for fixture in self.fixtures:
            sidecar = SegmentSidecar.from_dict(fixture.sidecar)
            decision = adapt_hls_sidecar_to_replay_public_event(
                sidecar,
                fixture.evidence,
                registry=registry,
                generated_at=self.declared_at,
                now=self.declared_at,
            )
            if decision.status != fixture.expected_status:
                raise ArchiveReplayPublicEventError(
                    f"{fixture.case} status drifted: {decision.status}"
                )
            if (
                decision.public_replay_link_claim_allowed
                != fixture.expected_public_replay_link_claim_allowed
            ):
                raise ArchiveReplayPublicEventError(
                    f"{fixture.case} public replay claim decision drifted"
                )
            missing_reasons = [
                reason
                for reason in fixture.expected_unavailable_reasons
                if reason not in decision.unavailable_reasons
            ]
            if missing_reasons:
                raise ArchiveReplayPublicEventError(
                    f"{fixture.case} missing expected reasons: {missing_reasons}"
                )


def adapt_hls_sidecar_to_replay_public_event(
    sidecar: SegmentSidecar | dict[str, Any],
    evidence: ArchiveReplayPublicLinkEvidence | dict[str, Any],
    *,
    registry: TemporalSpanRegistry,
    generated_at: datetime | str,
    now: datetime | str,
) -> ArchiveReplayPublicLinkDecision:
    """Map one HLS sidecar to a replay/link public-event decision."""

    source_sidecar = (
        sidecar if isinstance(sidecar, SegmentSidecar) else SegmentSidecar.from_dict(sidecar)
    )
    link_evidence = (
        evidence
        if isinstance(evidence, ArchiveReplayPublicLinkEvidence)
        else ArchiveReplayPublicLinkEvidence.model_validate(evidence)
    )
    generated = _normalise_iso(generated_at)
    observed_now = _normalise_datetime(now)
    event_id = archive_replay_public_event_id(source_sidecar, link_evidence)
    span_decision = _evaluate_span_gate(
        event_id=event_id,
        evidence=link_evidence,
        registry=registry,
    )
    source_segment_refs = _source_segment_refs(source_sidecar, link_evidence)
    unavailable = _unavailable_reasons(
        sidecar=source_sidecar,
        evidence=link_evidence,
        span_decision=span_decision,
        now=observed_now,
    )
    public_claim_allowed = not unavailable
    public_event = (
        _build_public_event(
            sidecar=source_sidecar,
            evidence=link_evidence,
            event_id=event_id,
            generated_at=generated,
            source_segment_refs=source_segment_refs,
        )
        if public_claim_allowed
        else None
    )
    status: ArchiveReplayDecisionStatus
    if public_claim_allowed:
        status = "emitted"
    elif unavailable == ("public_replay_url_missing",):
        status = "held"
    else:
        status = "refused"
    return ArchiveReplayPublicLinkDecision(
        decision_id=f"archive_replay_decision:{event_id}",
        idempotency_key=event_id,
        status=status,
        archive_capture_claim_allowed=source_sidecar.archive_kind == "hls",
        public_replay_link_claim_allowed=public_claim_allowed,
        public_event=public_event,
        unavailable_reasons=unavailable,
        source_segment_refs=source_segment_refs,
        temporal_span_refs=link_evidence.temporal_span_refs,
        gate_refs=_gate_refs(link_evidence),
        evidence_freshness_ref=link_evidence.evidence_fresh_at,
        span_gate_status=span_decision.status,
        span_gate_reason_codes=span_decision.reason_codes,
    )


def archive_replay_public_event_id(
    sidecar: SegmentSidecar,
    evidence: ArchiveReplayPublicLinkEvidence,
) -> str:
    """Stable idempotency key for one archive replay/public-link event."""

    digest_source = "|".join(
        [
            sidecar.segment_id,
            sidecar.segment_start_ts,
            sidecar.segment_end_ts,
            sidecar.segment_path,
            evidence.public_url or "missing-public-url",
            *evidence.temporal_span_refs,
        ]
    )
    digest = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()[:16]
    return _sanitize_id(f"rvpe:archive_replay:{sidecar.segment_id}:{digest}")


def load_archive_replay_public_event_fixtures(
    path: Path = ARCHIVE_REPLAY_PUBLIC_EVENT_FIXTURES,
    *,
    registry: TemporalSpanRegistry,
) -> ArchiveReplayFixtureSet:
    """Load and validate archive replay public-event fixture contracts."""

    try:
        fixture_set = ArchiveReplayFixtureSet.model_validate(_load_json_object(path))
        fixture_set.validate_contract(registry)
        return fixture_set
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise ArchiveReplayPublicEventError(
            f"invalid archive replay public-event fixtures at {path}: {exc}"
        ) from exc


def _evaluate_span_gate(
    *,
    event_id: str,
    evidence: ArchiveReplayPublicLinkEvidence,
    registry: TemporalSpanRegistry,
) -> SpanClaimGateDecision:
    return registry.evaluate_claim_bearing_output(
        ClaimBearingMediaOutput(
            output_id=_sanitize_id(f"media_output:archive_replay:{event_id}"),
            output_kind="public_event_clip",
            claim_bearing=True,
            diagnostic_only=False,
            public_scope="public_safe",
            span_refs=evidence.temporal_span_refs,
            evidence_refs=(
                *evidence.provenance_evidence_refs,
                *evidence.egress_evidence_refs,
            ),
        )
    )


def _unavailable_reasons(
    *,
    sidecar: SegmentSidecar,
    evidence: ArchiveReplayPublicLinkEvidence,
    span_decision: SpanClaimGateDecision,
    now: datetime,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if sidecar.archive_kind != "hls":
        reasons.append("unsupported_archive_kind")
    if not evidence.public_url:
        reasons.append("public_replay_url_missing")
    if not evidence.provenance_token:
        reasons.append("missing_provenance")
    if not evidence.provenance_evidence_refs:
        reasons.append("missing_provenance_evidence_refs")
    if evidence.rights_class not in _PUBLIC_SAFE_RIGHTS:
        reasons.append("rights_blocked")
    if evidence.privacy_class not in _PUBLIC_SAFE_PRIVACY:
        reasons.append("privacy_blocked")
    if not evidence.egress_public_claim_allowed:
        reasons.append("egress_blocked")
    if not evidence.egress_evidence_refs:
        reasons.append("egress_evidence_missing")
    if not evidence.audio_safe_for_broadcast:
        reasons.append("audio_blocked")
    if evidence.public_event_gate_ref is None:
        reasons.append("public_event_gate_missing")
    elif evidence.public_event_gate_status != "pass":
        reasons.append(f"public_event_gate_{evidence.public_event_gate_status}")
    age = (now - _normalise_datetime(evidence.evidence_fresh_at)).total_seconds()
    if age < 0 or age > evidence.evidence_max_age_s:
        reasons.append("source_stale")
    if not span_decision.allowed:
        reasons.extend(span_decision.reason_codes)
        reasons.append(f"temporal_span_gate_{span_decision.status}")
    return _dedupe(reasons)


def _build_public_event(
    *,
    sidecar: SegmentSidecar,
    evidence: ArchiveReplayPublicLinkEvidence,
    event_id: str,
    generated_at: str,
    source_segment_refs: tuple[str, ...],
) -> ResearchVehiclePublicEvent:
    return ResearchVehiclePublicEvent(
        schema_version=1,
        event_id=event_id,
        event_type="archive.segment",
        occurred_at=sidecar.segment_start_ts,
        broadcast_id=evidence.broadcast_id,
        programme_id=evidence.programme_id,
        condition_id=sidecar.condition_id,
        source=PublicEventSource(
            producer=PRODUCER,
            substrate_id="archive_replay",
            task_anchor=TASK_ANCHOR,
            evidence_ref=source_segment_refs[0],
            freshness_ref="archive_replay_public_link.evidence_fresh_at",
        ),
        salience=evidence.salience,
        state_kind="archive_artifact",
        rights_class=evidence.rights_class,
        privacy_class=evidence.privacy_class,
        provenance=PublicEventProvenance(
            token=evidence.provenance_token,
            generated_at=generated_at,
            producer=PRODUCER,
            evidence_refs=_event_evidence_refs(evidence, source_segment_refs),
            rights_basis=evidence.rights_basis,
            citation_refs=list(evidence.attribution_refs),
        ),
        public_url=evidence.public_url,
        frame_ref=None,
        chapter_ref=PublicEventChapterRef(
            kind="chapter",
            label=evidence.replay_title,
            timecode="00:00",
            source_event_id=event_id,
        ),
        attribution_refs=list(evidence.attribution_refs),
        surface_policy=PublicEventSurfacePolicy(
            allowed_surfaces=list(_ALLOWED_REPLAY_SURFACES),
            denied_surfaces=list(_DENIED_REPLAY_SURFACES),
            claim_live=False,
            claim_archive=True,
            claim_monetizable=False,
            requires_egress_public_claim=True,
            requires_audio_safe=True,
            requires_provenance=True,
            requires_human_review=False,
            rate_limit_key="archive.segment:replay",
            redaction_policy="none",
            fallback_action="hold",
            dry_run_reason=None,
        ),
    )


def _source_segment_refs(
    sidecar: SegmentSidecar,
    evidence: ArchiveReplayPublicLinkEvidence,
) -> tuple[str, ...]:
    sidecar_path = str(sidecar_path_for(Path(sidecar.segment_path)))
    return _dedupe((sidecar.segment_path, sidecar_path, *evidence.source_segment_refs))


def _event_evidence_refs(
    evidence: ArchiveReplayPublicLinkEvidence,
    source_segment_refs: tuple[str, ...],
) -> list[str]:
    return list(
        _dedupe(
            (
                *source_segment_refs,
                *evidence.temporal_span_refs,
                *evidence.provenance_evidence_refs,
                *evidence.egress_evidence_refs,
                *(_gate_refs(evidence)),
            )
        )
    )


def _gate_refs(evidence: ArchiveReplayPublicLinkEvidence) -> tuple[str, ...]:
    if evidence.public_event_gate_ref is None:
        return ()
    return (evidence.public_event_gate_ref,)


def _normalise_iso(value: datetime | str) -> str:
    return _normalise_datetime(value).isoformat().replace("+00:00", "Z")


def _normalise_datetime(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text).astimezone(UTC)


def _sanitize_id(value: str) -> str:
    safe = re.sub(r"[^a-z0-9_:-]+", "_", value.lower())
    safe = re.sub(r"_+", "_", safe).strip("_")
    if not safe or not safe[0].isalpha():
        safe = f"rvpe:{safe}"
    return safe


def _dedupe(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ArchiveReplayPublicEventError(f"{path} did not contain a JSON object")
    return payload


__all__ = [
    "ARCHIVE_REPLAY_PUBLIC_EVENT_FIXTURES",
    "ARCHIVE_CAPTURE_KIND",
    "CURSOR_OWNER",
    "IDEMPOTENCY_OWNER",
    "PUBLIC_REPLAY_PUBLICATION_KIND",
    "TASK_ANCHOR",
    "ArchiveReplayFixture",
    "ArchiveReplayFixtureCase",
    "ArchiveReplayFixtureSet",
    "ArchiveReplayPublicEventError",
    "ArchiveReplayPublicLinkDecision",
    "ArchiveReplayPublicLinkEvidence",
    "adapt_hls_sidecar_to_replay_public_event",
    "archive_replay_public_event_id",
    "load_archive_replay_public_event_fixtures",
]

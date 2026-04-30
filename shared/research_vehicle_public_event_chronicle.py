"""Chronicle high-salience adapter for ResearchVehiclePublicEvent records.

The adapter is intentionally conservative: chronicle salience is only a signal
that something may be worth preserving or publishing. It is not authority for
truth, rights, privacy, public-live status, or monetization.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from shared.livestream_egress_state import LivestreamEgressState
from shared.research_vehicle_public_event import (
    EventType,
    FallbackAction,
    PrivacyClass,
    PublicEventChapterRef,
    PublicEventFrameRef,
    PublicEventProvenance,
    PublicEventSource,
    PublicEventSurfacePolicy,
    ResearchVehiclePublicEvent,
    RightsClass,
    StateKind,
    Surface,
)

PRODUCER = "agents.chronicle_high_salience_public_event_producer"
TASK_ANCHOR = "chronicle-high-salience-public-event-producer"

type ChroniclePublicEventStatus = Literal["emitted", "refused"]

_GATE_KEYS = ("grounding_gate_result", "grounding_commitment_gate", "grounding_gate")
_PUBLIC_SAFE_RIGHTS: frozenset[RightsClass] = frozenset(
    {"operator_original", "operator_controlled", "third_party_attributed", "platform_embedded"}
)
_PUBLIC_SAFE_PRIVACY: frozenset[PrivacyClass] = frozenset({"public_safe", "aggregate_only"})
_ALL_SURFACES: tuple[Surface, ...] = (
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
    "archive",
    "replay",
    "captions",
    "cuepoints",
    "health",
    "monetization",
)
_CHRONICLE_LIVE_SURFACES: tuple[Surface, ...] = (
    "omg_statuslog",
    "mastodon",
    "bluesky",
    "discord",
    "archive",
    "health",
)
_AESTHETIC_LIVE_SURFACES: tuple[Surface, ...] = (
    "arena",
    "mastodon",
    "bluesky",
    "discord",
    "archive",
    "replay",
    "health",
)
_ARCHIVE_ONLY_SURFACES: tuple[Surface, ...] = ("archive", "health")


@dataclass(frozen=True)
class ChroniclePublicEventPolicyConfig:
    """Configurable policy defaults for chronicle public-event projection."""

    salience_threshold: float = 0.7
    freshness_ttl_s: float = 300.0
    chronicle_source_substrate_id: str = "research_cards"
    aesthetic_source_substrate_id: str = "local_visual_pool"
    rights_basis: str = "source-qualified chronicle observation"


class ChroniclePublicEventDecision(BaseModel):
    """Policy decision for one chronicle event projection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    decision_id: str
    idempotency_key: str | None
    status: ChroniclePublicEventStatus
    source_event_ref: str
    source_event_type: str | None
    mapped_event_type: EventType | None
    public_event: ResearchVehiclePublicEvent | None
    unavailable_reasons: tuple[str, ...] = Field(default_factory=tuple)
    grounding_gate_ref: str | None
    confidence_label: str | None
    confidence_value: float | None
    uncertainty: str | None
    correction_ref: str | None
    cursor_owner: Literal["chronicle-high-salience-public-event-producer:byte-offset"] = (
        "chronicle-high-salience-public-event-producer:byte-offset"
    )

    def to_json_line(self) -> str:
        """Serialize the decision for audit logs or tests."""
        return json.dumps(self.model_dump(mode="json"), sort_keys=True) + "\n"


def build_chronicle_public_event(
    chronicle_event: Mapping[str, Any],
    *,
    evidence_ref: str,
    egress_state: LivestreamEgressState,
    generated_at: str,
    now: float,
    policy: ChroniclePublicEventPolicyConfig | None = None,
) -> ChroniclePublicEventDecision:
    """Map one chronicle JSON object to a fail-closed public-event decision."""

    cfg = policy or ChroniclePublicEventPolicyConfig()
    payload = _payload(chronicle_event)
    source_event_ref = _source_event_ref(chronicle_event)
    source_event_type = _clean_optional_str(chronicle_event.get("event_type"))
    mapped_event_type = _mapped_event_type(chronicle_event, payload)
    salience = _salience(payload)
    if mapped_event_type is None or salience is None or salience < cfg.salience_threshold:
        reasons = ["internal_only" if mapped_event_type is None else "below_salience_threshold"]
        return ChroniclePublicEventDecision(
            decision_id=f"chronicle_public_event:{_sanitize_id(source_event_ref)}",
            idempotency_key=None,
            status="refused",
            source_event_ref=source_event_ref,
            source_event_type=source_event_type,
            mapped_event_type=mapped_event_type,
            public_event=None,
            unavailable_reasons=tuple(reasons),
            grounding_gate_ref=None,
            confidence_label=None,
            confidence_value=None,
            uncertainty=None,
            correction_ref=None,
        )

    occurred_at = _occurred_at(chronicle_event, payload, generated_at)
    event_id = chronicle_public_event_id(chronicle_event, mapped_event_type=mapped_event_type)
    gate = _grounding_gate(payload)
    gate_ref = _grounding_gate_ref(gate)
    gate_claim = _mapping(gate.get("claim")) if gate is not None else None
    gate_result = _mapping(gate.get("gate_result")) if gate is not None else None
    confidence = _mapping(gate_claim.get("confidence")) if gate_claim is not None else None
    confidence_label = _clean_optional_str(confidence.get("label")) if confidence else None
    confidence_value = _float_or_none(confidence.get("value")) if confidence else None
    uncertainty = _clean_optional_str(gate_claim.get("uncertainty")) if gate_claim else None
    correction_ref = _correction_ref(gate_claim)
    rights_class = _rights_class(payload, gate_claim)
    privacy_class = _privacy_class(payload, gate_claim)
    provenance_token = _provenance_token(payload, event_id)
    citation_refs = _citation_refs(payload, gate_claim)
    attribution_refs = _dedupe((*_string_tuple(payload.get("attribution_refs")), *citation_refs))
    frame_ref = _frame_ref(payload, event_id=event_id, occurred_at=occurred_at)
    chapter_ref = _chapter_ref(payload, event_id=event_id)
    public_url = _clean_optional_str(payload.get("public_url"))

    source_age_s = _event_age_s(occurred_at, now)
    source_blockers = _source_blockers(
        source_age_s=source_age_s,
        freshness_ttl_s=cfg.freshness_ttl_s,
        rights_class=rights_class,
        privacy_class=privacy_class,
        provenance_token=provenance_token,
        gate=gate,
        gate_claim=gate_claim,
        gate_result=gate_result,
        confidence_label=confidence_label,
        uncertainty=uncertainty,
        correction_ref=correction_ref,
        has_surface_reference=bool(public_url or frame_ref or chapter_ref),
        has_attribution=bool(attribution_refs),
    )
    archive_blockers = _archive_blockers(gate_result, source_blockers)
    live_blockers = _live_blockers(egress_state, gate_result, archive_blockers)
    archive_ready = not archive_blockers
    live_ready = not live_blockers
    surface_policy = _surface_policy(
        mapped_event_type=mapped_event_type,
        live_ready=live_ready,
        archive_ready=archive_ready,
        source_blockers=source_blockers,
        archive_blockers=archive_blockers,
        live_blockers=live_blockers,
    )

    public_event = ResearchVehiclePublicEvent(
        schema_version=1,
        event_id=event_id,
        event_type=mapped_event_type,
        occurred_at=occurred_at,
        broadcast_id=_clean_optional_str(payload.get("broadcast_id")),
        programme_id=_clean_optional_str(payload.get("programme_id")),
        condition_id=_clean_optional_str(
            payload.get("condition_id") or payload.get("objective_id")
        ),
        source=PublicEventSource(
            producer=PRODUCER,
            substrate_id=_source_substrate_id(mapped_event_type, cfg),
            task_anchor=TASK_ANCHOR,
            evidence_ref=evidence_ref,
            freshness_ref="chronicle_event.age_s",
        ),
        salience=salience,
        state_kind=_state_kind(mapped_event_type),
        rights_class=rights_class,
        privacy_class=privacy_class,
        provenance=PublicEventProvenance(
            token=provenance_token,
            generated_at=generated_at,
            producer=PRODUCER,
            evidence_refs=list(
                _dedupe(
                    (
                        source_event_ref,
                        f"ChronicleEvent.event_type:{source_event_type or 'unknown'}",
                        f"ChronicleEvent.salience:{salience:.3f}",
                        "LivestreamEgressState.public_claim_allowed",
                        *(_gate_evidence_refs(gate, gate_claim)),
                        *(f"blocker:{reason}" for reason in live_blockers),
                    )
                )
            ),
            rights_basis=_clean_optional_str(payload.get("rights_basis")) or cfg.rights_basis,
            citation_refs=list(citation_refs),
        ),
        public_url=public_url if (live_ready or archive_ready) else None,
        frame_ref=frame_ref,
        chapter_ref=chapter_ref,
        attribution_refs=list(attribution_refs),
        surface_policy=surface_policy,
    )
    reasons = _dedupe((*source_blockers, *archive_blockers, *live_blockers))
    return ChroniclePublicEventDecision(
        decision_id=f"chronicle_public_event:{event_id}",
        idempotency_key=event_id,
        status="emitted",
        source_event_ref=source_event_ref,
        source_event_type=source_event_type,
        mapped_event_type=mapped_event_type,
        public_event=public_event,
        unavailable_reasons=reasons,
        grounding_gate_ref=gate_ref,
        confidence_label=confidence_label,
        confidence_value=confidence_value,
        uncertainty=uncertainty,
        correction_ref=correction_ref,
    )


def is_chronicle_public_event_candidate(
    chronicle_event: Mapping[str, Any],
    *,
    policy: ChroniclePublicEventPolicyConfig | None = None,
) -> bool:
    """Return True when a chronicle row merits full public-event gate evaluation."""

    cfg = policy or ChroniclePublicEventPolicyConfig()
    payload = _payload(chronicle_event)
    mapped_event_type = _mapped_event_type(chronicle_event, payload)
    salience = _salience(payload)
    return (
        mapped_event_type is not None
        and salience is not None
        and salience >= cfg.salience_threshold
    )


def chronicle_public_event_id(
    chronicle_event: Mapping[str, Any],
    *,
    mapped_event_type: EventType,
) -> str:
    """Stable idempotency key for one chronicle public-event projection."""

    ts = _clean_optional_str(chronicle_event.get("ts")) or "unknown_ts"
    trace_id = _clean_optional_str(chronicle_event.get("trace_id")) or "missing_trace"
    span_id = _clean_optional_str(chronicle_event.get("span_id")) or "missing_span"
    source = _clean_optional_str(chronicle_event.get("source")) or "unknown_source"
    event_type = _clean_optional_str(chronicle_event.get("event_type")) or "unknown_event"
    return _sanitize_id(
        f"rvpe:chronicle:{mapped_event_type}:{ts}:{trace_id}:{span_id}:{source}:{event_type}"
    )


def _payload(event: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = event.get("payload")
    if isinstance(payload, Mapping):
        return payload
    return {}


def _mapped_event_type(
    event: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> EventType | None:
    requested = _clean_optional_str(
        payload.get("research_vehicle_event_type") or payload.get("public_event_type")
    )
    if requested == "internal_only":
        return None
    if requested in {"chronicle.high_salience", "aesthetic.frame_capture"}:
        return cast("EventType", requested)
    source_event_type = _clean_optional_str(event.get("event_type"))
    state_kind = _clean_optional_str(payload.get("state_kind"))
    if (
        source_event_type == "aesthetic.frame_capture"
        or state_kind == "aesthetic_frame"
        or isinstance(payload.get("frame_ref"), Mapping)
        or _clean_optional_str(payload.get("frame_uri")) is not None
    ):
        return "aesthetic.frame_capture"
    return "chronicle.high_salience"


def _salience(payload: Mapping[str, Any]) -> float | None:
    raw = payload.get("salience")
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, (int, float)):
        return max(0.0, min(1.0, float(raw)))
    return None


def _occurred_at(
    event: Mapping[str, Any],
    payload: Mapping[str, Any],
    generated_at: str,
) -> str:
    for raw in (payload.get("occurred_at"), payload.get("timestamp"), event.get("timestamp")):
        if isinstance(raw, str):
            normalised = _normalise_iso(raw)
            if normalised is not None:
                return normalised
    raw_ts = event.get("ts")
    if isinstance(raw_ts, bool):
        return generated_at
    if isinstance(raw_ts, (int, float)):
        return datetime.fromtimestamp(float(raw_ts), tz=UTC).isoformat().replace("+00:00", "Z")
    return generated_at


def _grounding_gate(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    for key in _GATE_KEYS:
        value = payload.get(key)
        if isinstance(value, Mapping):
            return value
    return None


def _grounding_gate_ref(gate: Mapping[str, Any] | None) -> str | None:
    if gate is None:
        return None
    return _clean_optional_str(gate.get("gate_id") or gate.get("gate_ref"))


def _source_blockers(
    *,
    source_age_s: float | None,
    freshness_ttl_s: float,
    rights_class: RightsClass,
    privacy_class: PrivacyClass,
    provenance_token: str | None,
    gate: Mapping[str, Any] | None,
    gate_claim: Mapping[str, Any] | None,
    gate_result: Mapping[str, Any] | None,
    confidence_label: str | None,
    uncertainty: str | None,
    correction_ref: str | None,
    has_surface_reference: bool,
    has_attribution: bool,
) -> tuple[str, ...]:
    blockers: list[str] = []
    if source_age_s is None or source_age_s > freshness_ttl_s:
        blockers.append("source_stale")
    if gate is None or gate_claim is None or gate_result is None:
        blockers.append("missing_grounding_gate")
    elif gate.get("gate_state") != "pass":
        blockers.append("grounding_gate_failed")
    if gate_result is not None and gate_result.get("may_emit_claim") is not True:
        blockers.append("unsupported_claim")
    if gate_claim is not None and not _string_tuple(gate_claim.get("evidence_refs")):
        blockers.append("unsupported_claim")
    if gate is not None:
        infractions = _string_tuple(gate.get("infractions"))
        if infractions:
            blockers.append("grounding_gate_failed")
            blockers.extend(f"grounding_infraction:{infraction}" for infraction in infractions)
        policy = _mapping(gate.get("no_expert_system_policy"))
        if policy is not None and policy.get("authoritative_verdict_allowed") is not False:
            blockers.append("hidden_expertise")
    if not confidence_label or confidence_label == "none" or uncertainty is None:
        blockers.append("unlabelled_uncertainty")
    if correction_ref is None:
        blockers.append("missing_refusal_correction_path")
    if rights_class not in _PUBLIC_SAFE_RIGHTS:
        blockers.append("rights_blocked")
    if privacy_class not in _PUBLIC_SAFE_PRIVACY:
        blockers.append("privacy_blocked")
    if provenance_token is None:
        blockers.append("missing_provenance")
    if not has_surface_reference:
        blockers.append("missing_surface_reference")
    if not has_attribution:
        blockers.append("missing_attribution_ref")
    return _dedupe(blockers)


def _archive_blockers(
    gate_result: Mapping[str, Any] | None,
    source_blockers: tuple[str, ...],
) -> tuple[str, ...]:
    blockers = list(source_blockers)
    if gate_result is None or gate_result.get("may_publish_archive") is not True:
        blockers.append("grounding_gate_archive_blocked")
    return _dedupe(blockers)


def _live_blockers(
    egress_state: LivestreamEgressState,
    gate_result: Mapping[str, Any] | None,
    archive_blockers: tuple[str, ...],
) -> tuple[str, ...]:
    blockers = list(archive_blockers)
    if gate_result is None or gate_result.get("may_publish_live") is not True:
        blockers.append("grounding_gate_live_blocked")
    if not egress_state.public_claim_allowed:
        blockers.append("egress_blocked")
    if any(item.stale for item in egress_state.evidence):
        blockers.append("stale_egress")
    return _dedupe(blockers)


def _surface_policy(
    *,
    mapped_event_type: EventType,
    live_ready: bool,
    archive_ready: bool,
    source_blockers: tuple[str, ...],
    archive_blockers: tuple[str, ...],
    live_blockers: tuple[str, ...],
) -> PublicEventSurfacePolicy:
    if live_ready:
        allowed = (
            _AESTHETIC_LIVE_SURFACES
            if mapped_event_type == "aesthetic.frame_capture"
            else _CHRONICLE_LIVE_SURFACES
        )
    elif archive_ready:
        allowed = _ARCHIVE_ONLY_SURFACES
    else:
        allowed = ()
    denied = tuple(surface for surface in _ALL_SURFACES if surface not in allowed)
    dry_run_reason = None if allowed else ";".join(_dedupe((*archive_blockers, *live_blockers)))
    return PublicEventSurfacePolicy(
        allowed_surfaces=list(allowed),
        denied_surfaces=list(denied),
        claim_live=live_ready,
        claim_archive=archive_ready,
        claim_monetizable=False,
        requires_egress_public_claim=True,
        requires_audio_safe=False,
        requires_provenance=True,
        requires_human_review=False,
        rate_limit_key=f"{mapped_event_type}:{_state_kind(mapped_event_type)}",
        redaction_policy="aggregate_only",
        fallback_action=_fallback_action(
            archive_ready=archive_ready,
            live_ready=live_ready,
            source_blockers=source_blockers,
        ),
        dry_run_reason=dry_run_reason,
    )


def _fallback_action(
    *,
    archive_ready: bool,
    live_ready: bool,
    source_blockers: tuple[str, ...],
) -> FallbackAction:
    if live_ready:
        return "hold"
    if archive_ready:
        return "archive_only"
    if "privacy_blocked" in source_blockers:
        return "private_only"
    if "grounding_gate_failed" in source_blockers or "unsupported_claim" in source_blockers:
        return "hold"
    return "hold"


def _state_kind(mapped_event_type: EventType) -> StateKind:
    if mapped_event_type == "aesthetic.frame_capture":
        return "aesthetic_frame"
    return "research_observation"


def _source_substrate_id(
    mapped_event_type: EventType,
    policy: ChroniclePublicEventPolicyConfig,
) -> str:
    if mapped_event_type == "aesthetic.frame_capture":
        return policy.aesthetic_source_substrate_id
    return policy.chronicle_source_substrate_id


def _rights_class(
    payload: Mapping[str, Any],
    gate_claim: Mapping[str, Any] | None,
) -> RightsClass:
    value = _clean_optional_str(payload.get("rights_class"))
    if value is None and gate_claim is not None:
        value = _clean_optional_str(gate_claim.get("rights_state"))
    if value in {
        "operator_original",
        "operator_controlled",
        "third_party_attributed",
        "third_party_uncleared",
        "platform_embedded",
        "unknown",
    }:
        return cast("RightsClass", value)
    return "unknown"


def _privacy_class(
    payload: Mapping[str, Any],
    gate_claim: Mapping[str, Any] | None,
) -> PrivacyClass:
    value = _clean_optional_str(payload.get("privacy_class"))
    if value is None and gate_claim is not None:
        value = _clean_optional_str(gate_claim.get("privacy_state"))
    if value in {
        "operator_private",
        "consent_required",
        "aggregate_only",
        "public_safe",
        "unknown",
    }:
        return cast("PrivacyClass", value)
    return "unknown"


def _provenance_token(payload: Mapping[str, Any], event_id: str) -> str | None:
    token = _clean_optional_str(
        payload.get("provenance_token") or payload.get("public_event_provenance_token")
    )
    if token:
        return token
    grounding = payload.get("grounding_provenance")
    if _string_tuple(grounding):
        return f"chronicle:{event_id}"
    return None


def _citation_refs(
    payload: Mapping[str, Any],
    gate_claim: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    refs: list[str] = [*_string_tuple(payload.get("citation_refs"))]
    if gate_claim is not None:
        refs.extend(_string_tuple(gate_claim.get("evidence_refs")))
        provenance = _mapping(gate_claim.get("provenance"))
        if provenance is not None:
            refs.extend(_string_tuple(provenance.get("source_refs")))
    return _dedupe(refs)


def _gate_evidence_refs(
    gate: Mapping[str, Any] | None,
    gate_claim: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    if gate is None:
        return ("GroundingCommitmentGate:missing",)
    refs = []
    gate_ref = _grounding_gate_ref(gate)
    if gate_ref is not None:
        refs.append(f"GroundingCommitmentGate:{gate_ref}")
    if gate_claim is not None:
        confidence = _mapping(gate_claim.get("confidence"))
        if confidence is not None:
            label = _clean_optional_str(confidence.get("label"))
            value = _float_or_none(confidence.get("value"))
            refs.append(f"GroundingCommitmentGate.confidence:{label or 'none'}:{value}")
        uncertainty = _clean_optional_str(gate_claim.get("uncertainty"))
        if uncertainty is not None:
            refs.append(f"GroundingCommitmentGate.uncertainty:{uncertainty}")
        correction = _correction_ref(gate_claim)
        if correction is not None:
            refs.append(f"GroundingCommitmentGate.correction_path:{correction}")
    return tuple(refs)


def _frame_ref(
    payload: Mapping[str, Any],
    *,
    event_id: str,
    occurred_at: str,
) -> PublicEventFrameRef | None:
    raw = payload.get("frame_ref")
    if isinstance(raw, Mapping):
        try:
            return PublicEventFrameRef.model_validate(raw)
        except ValueError:
            return None
    uri = _clean_optional_str(
        payload.get("frame_uri") or payload.get("frame_path") or payload.get("thumbnail_uri")
    )
    if uri is None:
        return None
    captured_at = _normalise_iso(_clean_optional_str(payload.get("captured_at")) or occurred_at)
    return PublicEventFrameRef(
        kind="frame",
        uri=uri,
        captured_at=captured_at or occurred_at,
        source_event_id=event_id,
    )


def _chapter_ref(payload: Mapping[str, Any], *, event_id: str) -> PublicEventChapterRef | None:
    raw = payload.get("chapter_ref")
    if isinstance(raw, Mapping):
        try:
            return PublicEventChapterRef.model_validate(raw)
        except ValueError:
            return None
    label = _clean_optional_str(payload.get("chapter_label"))
    timecode = _clean_optional_str(payload.get("timecode"))
    if label is None or timecode is None:
        return None
    return PublicEventChapterRef(
        kind="chapter",
        label=label,
        timecode=timecode,
        source_event_id=event_id,
    )


def _correction_ref(gate_claim: Mapping[str, Any] | None) -> str | None:
    if gate_claim is None:
        return None
    path = _mapping(gate_claim.get("refusal_correction_path"))
    if path is None:
        return None
    return _clean_optional_str(
        path.get("correction_event_ref") or path.get("artifact_ref") or path.get("refusal_reason")
    )


def _source_event_ref(event: Mapping[str, Any]) -> str:
    trace_id = _clean_optional_str(event.get("trace_id")) or "missing_trace"
    span_id = _clean_optional_str(event.get("span_id")) or "missing_span"
    source = _clean_optional_str(event.get("source")) or "unknown_source"
    event_type = _clean_optional_str(event.get("event_type")) or "unknown_event"
    return f"ChronicleEvent:{source}:{event_type}:{trace_id}:{span_id}"


def _event_age_s(occurred_at: str, now: float) -> float | None:
    text = occurred_at[:-1] + "+00:00" if occurred_at.endswith("Z") else occurred_at
    try:
        return max(0.0, now - datetime.fromisoformat(text).timestamp())
    except ValueError:
        return None


def _normalise_iso(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _clean_optional_str(value: object) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return None


def _float_or_none(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _mapping(value: object) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    return None


def _string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        stripped = value.strip()
        return (stripped,) if stripped else ()
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray | str):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return ()


def _dedupe(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _sanitize_id(raw: str) -> str:
    lowered = raw.lower().replace("+00:00", "z")
    cleaned = re.sub(r"[^a-z0-9_:]+", "_", lowered)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_:")
    if not cleaned or not cleaned[0].isalpha():
        cleaned = f"rvpe:{cleaned}"
    return cleaned


__all__ = [
    "ChroniclePublicEventDecision",
    "ChroniclePublicEventPolicyConfig",
    "build_chronicle_public_event",
    "chronicle_public_event_id",
    "is_chronicle_public_event_candidate",
]

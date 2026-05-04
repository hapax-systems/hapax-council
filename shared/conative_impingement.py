"""Typed conative/action-tendency impingement envelopes.

Conative impingements carry content plus action-readiness. They are not
permission to execute. Recruitment still selects a fulfillment surface, and
world/route/claim evidence can inhibit execution.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

ActionTendency = Literal[
    "speak",
    "withhold",
    "repair",
    "refuse",
    "annotate",
    "route_attention",
    "mark_boundary",
    "hold_pressure",
]

ImpulseTerminalState = Literal[
    "pending",
    "completed",
    "inhibited",
    "redirected",
    "interrupted",
    "failed",
]

CompulsionBand = Literal["too_low", "healthy", "too_high"]

LOW_COMPULSION_CEILING = 0.12
HIGH_COMPULSION_FLOOR = 0.86
ACTION_TENDENCY_PRIOR_WEIGHT = 0.04


class ActionTendencyImpingement(BaseModel):
    """First-class envelope for an action-readiness impingement."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    impulse_id: str = Field(min_length=1)
    content_summary: str = Field(min_length=1, max_length=500)
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    valence: str = Field(min_length=1)
    urgency: float = Field(ge=0.0, le=1.0)
    drive_name: str = Field(min_length=1)
    action_tendency: ActionTendency
    speech_act_candidate: str = Field(min_length=1)
    strength_posterior: float = Field(ge=0.0, le=1.0)
    role_context: str = Field(min_length=1)
    inhibition_policy: str = Field(min_length=1)
    wcs_snapshot_ref: str | None
    learning_policy: str = Field(min_length=1)
    route_evidence_ref: str | None = None
    public_claim_evidence_ref: str | None = None
    terminal_state: ImpulseTerminalState = "pending"
    terminal_reason: str | None = None
    raw_drive_text_spoken: Literal[False] = False

    @property
    def compulsion_band(self) -> CompulsionBand:
        return compulsion_band(self.strength_posterior)


def compulsion_band(strength_posterior: float) -> CompulsionBand:
    """Classify compulsion pressure without making it a route gate."""
    if strength_posterior < LOW_COMPULSION_CEILING:
        return "too_low"
    if strength_posterior > HIGH_COMPULSION_FLOOR:
        return "too_high"
    return "healthy"


def impulse_id_from_impingement(impingement: object, *, prefix: str = "narration") -> str:
    """Return a stable impulse id from content, impingement id, or digest."""
    content = getattr(impingement, "content", {}) or {}
    if isinstance(content, Mapping):
        content_id = content.get("impulse_id") or content.get("drive_id")
        if content_id:
            return str(content_id)
    imp_id = getattr(impingement, "id", None)
    if imp_id:
        return str(imp_id)
    source = str(getattr(impingement, "source", "unknown"))
    digest_source = {
        "source": source,
        "content": dict(content) if isinstance(content, Mapping) else {},
    }
    try:
        encoded = json.dumps(digest_source, sort_keys=True, default=str)
    except TypeError:
        encoded = repr(digest_source)
    return f"{prefix}-{hashlib.sha256(encoded.encode('utf-8')).hexdigest()[:12]}"


def action_tendency_impulse_from_impingement(
    impingement: object,
    *,
    terminal_state: ImpulseTerminalState = "pending",
    terminal_reason: str | None = None,
    default_execution_refs: bool = True,
) -> ActionTendencyImpingement:
    """Build a typed conative envelope from a legacy impingement object."""
    content = getattr(impingement, "content", {}) or {}
    content_dict: Mapping[str, Any] = content if isinstance(content, Mapping) else {}
    strength = _float_or_none(getattr(impingement, "strength", None))
    posterior = _clamp(
        _float_or_none(content_dict.get("strength_posterior"))
        if content_dict.get("strength_posterior") is not None
        else (strength if strength is not None else 0.3),
        0.0,
        1.0,
    )
    wcs_default = (
        "wcs:audio.broadcast_voice:voice-output-witness" if default_execution_refs else None
    )
    route_default = (
        "route:audio.broadcast_voice:health_witness_required" if default_execution_refs else None
    )
    claim_default = (
        "claim_posture:bounded_nonassertive_narration" if default_execution_refs else None
    )
    return ActionTendencyImpingement(
        impulse_id=impulse_id_from_impingement(impingement),
        content_summary=_content_summary(content_dict),
        evidence_refs=tuple(_evidence_refs(impingement, content_dict)),
        valence=str(content_dict.get("valence") or "pressure"),
        urgency=_clamp(_float_or_none(content_dict.get("urgency")) or posterior, 0.0, 1.0),
        drive_name=str(content_dict.get("drive_name") or content_dict.get("drive") or "narration"),
        action_tendency=_action_tendency(content_dict.get("action_tendency")),
        speech_act_candidate=str(
            content_dict.get("speech_act_candidate") or "autonomous_narrative"
        ),
        strength_posterior=posterior,
        role_context=str(content_dict.get("role_context") or "livestream_public_voice"),
        inhibition_policy=str(
            content_dict.get("inhibition_policy") or "wcs_route_role_claim_gates"
        ),
        wcs_snapshot_ref=_optional_ref(
            content_dict.get("wcs_snapshot_ref"),
            default=wcs_default,
        ),
        learning_policy=str(
            content_dict.get("learning_policy") or "separate_drive_selection_execution_world_claim"
        ),
        route_evidence_ref=_optional_ref(
            content_dict.get("route_evidence_ref"),
            default=route_default,
        ),
        public_claim_evidence_ref=_optional_ref(
            content_dict.get("public_claim_evidence_ref"),
            default=claim_default,
        ),
        terminal_state=terminal_state,
        terminal_reason=terminal_reason,
    )


def narrative_drive_content_payload(
    *,
    impingement_id: str,
    narrative: str,
    drive_name: str,
    strength_posterior: float,
    chronicle_event_count: int,
    stimmung_stance: str,
    programme_role: str | None,
    programme_authorization: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the conative content payload emitted by narrative_drive.

    ``programme_authorization`` (optional) is a dict matching the schema
    consumed by ``cpal.destination_channel._programme_authorization_evidence``:
    ``{"authorized": True, "authorized_at": <epoch>, "expires_at": <epoch>,
    "programme_id": ..., "evidence_ref": ...}``. When present, it lets
    the playback gate confirm fresh broadcast voice authorization without
    a separate state-file read; absent, the gate falls through to its
    "programme_authorization_missing" code, which is correct fail-closed
    behavior when no programme is active.
    """
    role = programme_role or "none"
    impulse = ActionTendencyImpingement(
        impulse_id=f"narration-{impingement_id}",
        content_summary=narrative[:500],
        evidence_refs=(
            "source:endogenous.narrative_drive",
            f"drive:{drive_name}",
            f"chronicle:window_count:{chronicle_event_count}",
            f"stimmung:{stimmung_stance}",
            f"programme_role:{role}",
        ),
        valence="pressure",
        urgency=_clamp(strength_posterior, 0.0, 1.0),
        drive_name=drive_name,
        action_tendency="speak",
        speech_act_candidate="autonomous_narrative",
        strength_posterior=_clamp(strength_posterior, 0.0, 1.0),
        role_context=f"programme_role:{role}",
        inhibition_policy="wcs_route_role_claim_gates",
        wcs_snapshot_ref="wcs:audio.broadcast_voice:voice-output-witness",
        route_evidence_ref="route:audio.broadcast_voice:health_witness_required",
        public_claim_evidence_ref="claim_posture:bounded_nonassertive_narration",
        learning_policy="separate_drive_selection_execution_world_claim",
    )
    payload = impulse.model_dump(mode="json")
    payload.update(
        {
            "narrative": narrative,
            "drive": drive_name,
            "chronicle_event_count": chronicle_event_count,
            "stimmung_stance": stimmung_stance,
            "programme_role": role,
        }
    )
    if programme_authorization is not None:
        payload["programme_authorization"] = programme_authorization
    return payload


def execution_inhibition_reasons(impulse: ActionTendencyImpingement) -> tuple[str, ...]:
    """Return fail-closed execution blockers for missing evidence refs.

    This checks execution evidence only. Compulsion range remains a scoring and
    rendering signal, not a hard route gate.
    """
    reasons: list[str] = []
    if not _ref_available(impulse.wcs_snapshot_ref):
        reasons.append("wcs_snapshot_ref_missing")
    if not _ref_available(impulse.route_evidence_ref):
        reasons.append("route_evidence_ref_missing")
    if not _ref_available(impulse.public_claim_evidence_ref):
        reasons.append("public_claim_evidence_ref_missing")
    if not impulse.evidence_refs:
        reasons.append("evidence_refs_missing")
    return tuple(reasons)


def action_tendency_prior_for_candidate(
    *,
    action_tendency: str | None,
    strength_posterior: float,
    capability_name: str,
    payload: Mapping[str, Any] | None = None,
) -> float:
    """Small soft prior for candidate scoring; never filters candidates."""
    if not action_tendency:
        return 0.0
    payload = payload or {}
    tendency_match = _action_tendency_match_score(action_tendency, capability_name, payload)
    if tendency_match <= 0.0:
        return 0.0
    band = compulsion_band(_clamp(strength_posterior, 0.0, 1.0))
    band_multiplier = {"too_low": 0.25, "healthy": 1.0, "too_high": 0.45}[band]
    return ACTION_TENDENCY_PRIOR_WEIGHT * tendency_match * band_multiplier


def _action_tendency_match_score(
    action_tendency: str,
    capability_name: str,
    payload: Mapping[str, Any],
) -> float:
    name = capability_name.lower()
    medium = str(payload.get("medium") or "").lower()
    tendency = action_tendency.lower()
    if tendency == "speak":
        if medium == "auditory" or any(token in name for token in ("narration", "voice", "speech")):
            return 1.0
        if medium in {"textual", "notification"} or "caption" in name:
            return 0.35
    if tendency in {"withhold", "hold_pressure"}:
        if any(token in name for token in ("hold", "regulation", "suppress")):
            return 0.8
    if tendency in {"repair", "refuse", "mark_boundary"}:
        if any(token in name for token in ("repair", "refusal", "boundary")):
            return 0.8
    if tendency == "annotate":
        if medium in {"textual", "visual"} or any(token in name for token in ("caption", "note")):
            return 0.7
    if tendency == "route_attention":
        if "attention" in name or medium == "notification":
            return 0.8
    return 0.0


def _content_summary(content: Mapping[str, Any]) -> str:
    value = (
        content.get("content_summary")
        or content.get("summary")
        or content.get("narrative")
        or content.get("metric")
        or "narration drive"
    )
    return str(value).strip()[:500] or "narration drive"


def _evidence_refs(impingement: object, content: Mapping[str, Any]) -> list[str]:
    refs = [
        f"source:{getattr(impingement, 'source', 'unknown')}",
        f"drive:{content.get('drive_name') or content.get('drive') or 'narration'}",
    ]
    imp_id = getattr(impingement, "id", None)
    if imp_id:
        refs.append(f"impingement:{imp_id}")
    existing = content.get("evidence_refs")
    if isinstance(existing, list | tuple):
        refs.extend(str(ref) for ref in existing if ref)
    return refs


def _action_tendency(value: object) -> ActionTendency:
    allowed = set(get_args(ActionTendency))
    raw = str(value or "speak")
    return raw if raw in allowed else "speak"  # type: ignore[return-value]


def _optional_ref(value: object, *, default: str | None) -> str | None:
    if value is None:
        return default
    text = str(value).strip()
    return text or None


def _ref_available(value: str | None) -> bool:
    if value is None:
        return False
    normalized = value.strip().lower()
    if not normalized:
        return False
    unavailable_tokens = {"missing", "unavailable", "unknown", "none", "dry_run"}
    return normalized not in unavailable_tokens and not normalized.endswith(":missing")


def _float_or_none(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _clamp(value: float | None, minimum: float, maximum: float) -> float:
    if value is None:
        return minimum
    return max(minimum, min(maximum, value))


__all__ = [
    "ACTION_TENDENCY_PRIOR_WEIGHT",
    "ActionTendency",
    "ActionTendencyImpingement",
    "CompulsionBand",
    "ImpulseTerminalState",
    "action_tendency_impulse_from_impingement",
    "action_tendency_prior_for_candidate",
    "compulsion_band",
    "execution_inhibition_reasons",
    "impulse_id_from_impingement",
    "narrative_drive_content_payload",
]

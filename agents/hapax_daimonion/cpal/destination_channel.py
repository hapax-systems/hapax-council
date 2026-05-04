"""CPAL TTS destination classification and route compatibility.

Every Hapax TTS utterance is classified as ``livestream`` or ``private`` at
synthesis time. Those legacy labels are now metrics/classification labels only:
playback callsites must resolve them through ``shared.voice_output_router`` so
public voice binds to the broadcast policy target and private voice fails closed
unless the exact private monitor route has fresh evidence.

**Classification rules** (order matters — first match wins):

1. Operator/private-risk contexts → PRIVATE, even if malformed content carries
   a public-looking token.
2. Explicit public/broadcast intent → LIVESTREAM, still gated by fresh
   programme authorization and ``audio_safe_for_broadcast.safe``.
3. Impingement ``source`` starts with ``"operator.sidechat"`` → PRIVATE.
4. Impingement ``content["channel"] == "sidechat"`` → PRIVATE.
5. Impingement ``content["kind"] == "debug"`` → PRIVATE.
6. ``voice_register == TEXTMODE`` AND the impingement was sidechat-origin
   (covered by 1/2 above; the register alone does not flip destination).
7. Otherwise → PRIVATE.

The register gate (rule 6) is intentionally subordinate: TEXTMODE can
be set by HOMAGE packages unrelated to sidechat (e.g., a BitchX lineage
announcement), but register alone never authorizes broadcast. Broadcast
still requires explicit intent plus the playback safety gates.

**Feature flag**: ``HAPAX_TTS_DESTINATION_ROUTING_ACTIVE`` (default ``1``).
The flag parser remains for dashboards and legacy controls, but it no longer
authorizes fallback to ``HAPAX_TTS_TARGET`` or the system default for private
routes.

**Telemetry**: Prometheus counter ``hapax_tts_destination_total{destination}``
increments on every classification. The classification is also logged at
INFO level; the log message never contains the utterance body or
operator-identifying content, only the chosen destination and a short
provenance tag.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from shared.broadcast_audio_health import (
    DEFAULT_STATE_PATH as DEFAULT_BROADCAST_AUDIO_HEALTH_PATH,
)
from shared.broadcast_audio_health import (
    read_broadcast_audio_health_state,
)
from shared.voice_output_router import (
    DEFAULT_PRIVATE_MONITOR_STATUS_PATH,
    VoiceOutputDestination,
    VoiceRouteResult,
    VoiceRouteState,
    media_role_for_route,
    resolve_voice_output_route,
    target_for_route,
)
from shared.voice_register import VoiceRegister

log = logging.getLogger(__name__)


DESTINATION_ROUTING_ENV: str = "HAPAX_TTS_DESTINATION_ROUTING_ACTIVE"
"""Legacy feature flag parser. It does not permit private/default fallback."""

DEFAULT_TARGET_ENV: str = "HAPAX_TTS_TARGET"
"""Legacy default target env var. Semantic routing no longer consumes it."""

BROADCAST_BIAS_ENV: str = "HAPAX_DAIMONION_BROADCAST_BIAS_ENABLED"
"""Feature flag for autonomous-narrative broadcast bias.

When ``1`` (default), autonomous narrative impingements that arrive during
an active programme with a broadcast-eligible role are classified
``LIVESTREAM`` instead of falling through to the ``PRIVATE`` default.
All downstream safety gates (programme authorization, audio health,
private-risk context, route evidence) remain enforced.

Set to ``0`` to revert to the legacy behavior where autonomous narration
always routes private unless explicit broadcast tokens are present.
"""

BROADCAST_AUTH_MAX_AGE_S: float = 120.0
"""Maximum age for per-utterance public/broadcast voice authorization."""

LIVESTREAM_SINK: str = "hapax-livestream"
"""Legacy livestream sink label retained for dashboards and compatibility."""

PRIVATE_SINK: str = "hapax-private"
"""Private null sink that is audible only through the exact monitor bridge."""


class DestinationChannel(StrEnum):
    """Where an utterance plays back.

    ``LIVESTREAM`` — public broadcast candidate. It is never the default
    playback path and must still pass programme/audio safety gates.

    ``PRIVATE`` — operator-only path and fail-closed default. Operator is the
    audience, not the stream audience.
    """

    LIVESTREAM = "livestream"
    PRIVATE = "private"


@dataclass(frozen=True)
class VoicePlaybackDecision:
    """Fail-closed playback decision used before any TTS audio is emitted."""

    destination: DestinationChannel
    route: VoiceRouteResult
    allowed: bool
    reason_code: str
    operator_visible_reason: str
    safety_gate: dict[str, Any]

    @property
    def target(self) -> str | None:
        if not self.allowed:
            return None
        return target_for_route(self.route)

    @property
    def media_role(self) -> str | None:
        if self.allowed:
            return media_role_for_route(self.route)
        if self.route.target_binding is not None:
            return self.route.target_binding.media_role
        return None


def is_routing_active() -> bool:
    """Return ``True`` when per-utterance destination routing is on.

    Reads ``HAPAX_TTS_DESTINATION_ROUTING_ACTIVE`` on every call (no
    caching) so an operator flipping the flag at runtime via a systemd
    drop-in reload takes effect on the next utterance.

    Default: ``True`` (unset, empty, or "1" → active). Only the literal
    "0" forces legacy behavior.
    """
    raw = os.environ.get(DESTINATION_ROUTING_ENV)
    if raw is None:
        return True
    return raw.strip() != "0"


def _extract_content(impingement: Any) -> dict[str, Any]:
    """Pull the ``content`` dict off an impingement-like object.

    We do a ``getattr`` rather than isinstance-checking because the
    impingement path accepts both Pydantic ``Impingement`` instances
    and the simpler mock objects tests use. Returns an empty dict on
    anything that doesn't look like an impingement.
    """
    content = getattr(impingement, "content", None)
    if isinstance(content, dict):
        return content
    return {}


def classify_destination(
    impingement: Any,
    *,
    voice_register: VoiceRegister | None = None,
) -> DestinationChannel:
    """Decide which destination an impingement-origin utterance belongs on.

    See module docstring for the rules. Defensive to malformed inputs:
    missing, malformed, operator-private, or ambiguous contexts now resolve
    ``PRIVATE`` so they either bind the exact private monitor or drop. Public
    broadcast is opt-in and still needs :func:`resolve_playback_decision` to
    pass programme and audio-safety gates.

    Parameters
    ----------
    impingement
        The triggering impingement (or any object exposing ``source`` and
        ``content``). ``None`` is tolerated and maps to ``PRIVATE``.
    voice_register
        Current HOMAGE voice register, if CPAL supplies one. Used only
        in combination with the sidechat rules; register alone never
        flips destination.

    Returns
    -------
    DestinationChannel
    """
    if impingement is None:
        return DestinationChannel.PRIVATE

    source = getattr(impingement, "source", "") or ""
    content = _extract_content(impingement)
    channel = content.get("channel")
    kind = content.get("kind")

    if _is_private_risk_context(source, content):
        return DestinationChannel.PRIVATE

    # Rule 1: operator-sidechat provenance.
    if isinstance(source, str) and source.startswith("operator.sidechat"):
        return DestinationChannel.PRIVATE

    # Rule 2: explicit channel tag on the impingement content.
    if channel == "sidechat":
        return DestinationChannel.PRIVATE

    # Rule 3: debug utterances.
    if kind == "debug":
        return DestinationChannel.PRIVATE

    if _has_explicit_broadcast_intent(content):
        return DestinationChannel.LIVESTREAM

    # Rule 3.5: Endogenous-narrative broadcast bias.
    # When the feature flag is enabled and an active programme with a
    # broadcast-eligible role exists, endogenous narrative impingements
    # classify as LIVESTREAM. This covers the legacy ``autonomous_narrative``
    # source plus the endogenous-drive emitters (``endogenous.narrative_drive``,
    # ``endogenous.gem``) that compose Hapax's autonomous vocal presence on
    # the livestream. This is a soft prior — all downstream safety gates
    # (programme auth, audio health, route evidence) still apply in
    # resolve_playback_decision. The intent is explicit at classification
    # time (not implicit/default) because the programme context is the
    # evidence for broadcast authorization.
    if (
        _is_broadcast_bias_enabled()
        and _is_endogenous_narrative_source(source)
        and _programme_authorizes_broadcast()
    ):
        return DestinationChannel.LIVESTREAM

    # Rule 4: TEXTMODE alone does NOT route private (see module docstring).
    # It would only combine with sidechat provenance, which rules 1/2
    # already captured. This branch exists so adding a future sidechat
    # register signal remains a one-line change.
    _ = voice_register  # intentionally unused at the top level

    return DestinationChannel.PRIVATE


def resolve_playback_decision(
    impingement: Any,
    *,
    voice_register: VoiceRegister | None = None,
    private_monitor_status_path: Path = DEFAULT_PRIVATE_MONITOR_STATUS_PATH,
    broadcast_audio_health_path: Path = DEFAULT_BROADCAST_AUDIO_HEALTH_PATH,
    now: float | None = None,
) -> VoicePlaybackDecision:
    """Resolve an impingement-like utterance to an allowed or blocked route.

    This is the hard-stop gate: default/private-risk contexts resolve private
    or drop, while public broadcast requires all of:

    * explicit public/broadcast intent on the utterance context,
    * fresh programme authorization on the same context,
    * fresh ``audio_safe_for_broadcast.safe == true``.
    """

    destination = classify_and_record(impingement, voice_register=voice_register)
    route = resolve_route(
        destination,
        private_monitor_status_path=private_monitor_status_path,
        now=now,
    )
    content = _extract_content(impingement)

    if destination == DestinationChannel.PRIVATE:
        if route.state == VoiceRouteState.BLOCKED:
            return _blocked_decision(
                destination=destination,
                route=route,
                reason_code=route.reason_code,
                operator_visible_reason=route.operator_visible_reason,
                safety_gate={
                    "context_default": "private_or_drop",
                    "explicit_broadcast_intent": False,
                    "private_route_state": route.state.value,
                    "private_route_reason_code": route.reason_code,
                },
            )
        return VoicePlaybackDecision(
            destination=destination,
            route=route,
            allowed=True,
            reason_code=route.reason_code,
            operator_visible_reason=route.operator_visible_reason,
            safety_gate={
                "context_default": "private_or_drop",
                "explicit_broadcast_intent": False,
                "private_route_state": route.state.value,
                "private_route_reason_code": route.reason_code,
            },
        )

    source = getattr(impingement, "source", "") or ""
    intent = _broadcast_intent_evidence(content, source=source)
    programme_auth = _programme_authorization_evidence(content, now=now)
    audio_health = read_broadcast_audio_health_state(
        broadcast_audio_health_path,
        now=now,
    )
    safety_gate = {
        "context_default": "private_or_drop",
        "explicit_broadcast_intent": intent["present"],
        "broadcast_intent": intent,
        "programme_authorization": programme_auth,
        "audio_safe_for_broadcast": {
            "safe": audio_health.safe,
            "status": str(audio_health.status),
            "freshness_s": audio_health.freshness_s,
            "blocking_reason_codes": [
                getattr(reason, "code", "unknown") for reason in audio_health.blocking_reasons
            ],
        },
        "public_route_state": route.state.value,
        "public_route_reason_code": route.reason_code,
    }
    if not intent["present"]:
        return _blocked_decision(
            destination=destination,
            route=route,
            reason_code="broadcast_intent_missing",
            operator_visible_reason=(
                "Broadcast voice requires explicit public/broadcast intent; default is private/drop."
            ),
            safety_gate=safety_gate,
        )
    if not programme_auth["authorized"]:
        return _blocked_decision(
            destination=destination,
            route=route,
            reason_code=programme_auth["reason_code"],
            operator_visible_reason=(
                "Broadcast voice requires fresh programme authorization; playback is blocked."
            ),
            safety_gate=safety_gate,
        )
    if not audio_health.safe:
        return _blocked_decision(
            destination=destination,
            route=route,
            reason_code="audio_safe_for_broadcast_false",
            operator_visible_reason=(
                "Broadcast voice requires audio_safe_for_broadcast.safe=true; playback is blocked."
            ),
            safety_gate=safety_gate,
        )
    if route.state == VoiceRouteState.BLOCKED:
        return _blocked_decision(
            destination=destination,
            route=route,
            reason_code=route.reason_code,
            operator_visible_reason=route.operator_visible_reason,
            safety_gate=safety_gate,
        )
    return VoicePlaybackDecision(
        destination=destination,
        route=route,
        allowed=True,
        reason_code="broadcast_voice_authorized",
        operator_visible_reason="Broadcast voice authorization and audio safety gates passed.",
        safety_gate=safety_gate,
    )


def resolve_target(destination: DestinationChannel) -> str | None:
    """Translate a ``DestinationChannel`` to a pw-cat ``--target`` sink name.

    Legacy compatibility helper for older callers. New callsites should use
    :func:`resolve_route` and inspect the returned route envelope before
    playback. A blocked route returns ``None`` here, but callers must not treat
    that as permission to use the system default.
    """
    return target_for_route(resolve_route(destination))


def resolve_route(
    destination: DestinationChannel,
    *,
    private_monitor_status_path: Path = DEFAULT_PRIVATE_MONITOR_STATUS_PATH,
    now: float | None = None,
) -> VoiceRouteResult:
    """Resolve a legacy destination channel through the semantic route API.

    The old ``PRIVATE`` / ``LIVESTREAM`` labels remain stable for metrics and
    classification, but playback routing now flows through typed semantic
    destinations and fail-closed evidence checks.
    """
    semantic = {
        DestinationChannel.LIVESTREAM: VoiceOutputDestination.PUBLIC_BROADCAST,
        DestinationChannel.PRIVATE: VoiceOutputDestination.PRIVATE_ASSISTANT_MONITOR,
    }[destination]
    return resolve_voice_output_route(
        semantic,
        private_monitor_status_path=private_monitor_status_path,
        now=now,
    )


# pw-cat ``--media-role`` values for each destination. The role
# selects which WirePlumber role-based loopback the stream lands in.
# ``Assistant`` for PRIVATE keeps the existing duck behavior + can be
# routed to ``hapax-private`` via ``50-hapax-voice-duck.conf``.
# ``Broadcast`` for LIVESTREAM is the new role added 2026-04-26 to
# allow a per-destination split — it lands in
# ``loopback.sink.role.broadcast`` whose ``preferred-target`` is
# ``hapax-voice-fx-capture`` (broadcast chain). Without this split,
# both kinds of stream share role=Assistant and wireplumber's policy
# can't tell them apart, forcing the operator to choose between leak
# protection and broadcast TTS.
PRIVATE_MEDIA_ROLE: str = "Assistant"
BROADCAST_MEDIA_ROLE: str = "Broadcast"


def resolve_role(destination: DestinationChannel) -> str:
    """Translate a ``DestinationChannel`` to a pw-cat ``--media-role``.

    Behavior:

    * ``PRIVATE`` → :data:`PRIVATE_MEDIA_ROLE` (``"Assistant"``).
      Wireplumber's existing assistant role-based loopback handles
      ducking + routing.
    * ``LIVESTREAM`` → :data:`BROADCAST_MEDIA_ROLE` (``"Broadcast"``).
      A separate role-based loopback (added 2026-04-26 to
      ``50-hapax-voice-duck.conf``) routes Broadcast streams to
      ``hapax-voice-fx-capture`` so they reach the livestream chain.

    The split is what lets wireplumber simultaneously enforce the
    ``feedback_l12_equals_livestream_invariant`` (livestream gets
    voice) AND ``interpersonal_transparency`` (private cognition stays
    on operator monitor). Before the split, both rules used
    ``role=Assistant`` and wireplumber had to pick one target —
    either broadcast (leak risk) or private (silent stream).
    """
    route = resolve_route(destination)
    return media_role_for_route(route) or (
        PRIVATE_MEDIA_ROLE if destination == DestinationChannel.PRIVATE else BROADCAST_MEDIA_ROLE
    )


def _blocked_decision(
    *,
    destination: DestinationChannel,
    route: VoiceRouteResult,
    reason_code: str,
    operator_visible_reason: str,
    safety_gate: dict[str, Any],
) -> VoicePlaybackDecision:
    return VoicePlaybackDecision(
        destination=destination,
        route=route,
        allowed=False,
        reason_code=reason_code,
        operator_visible_reason=operator_visible_reason,
        safety_gate=safety_gate,
    )


def _has_explicit_broadcast_intent(content: dict[str, Any]) -> bool:
    return _broadcast_intent_evidence(content)["present"]


def _is_private_risk_context(source: object, content: dict[str, Any]) -> bool:
    source_text = source if isinstance(source, str) else ""
    if source_text.startswith(("operator.", "blue_yeti", "microphone.")):
        return True
    channel = content.get("channel")
    if channel in {"sidechat", "private", "operator_private"}:
        return True
    input_device = content.get("input_device") or content.get("microphone")
    if isinstance(input_device, str) and "yeti" in input_device.lower():
        return True
    return content.get("private") is True or content.get("operator_private") is True


def _is_broadcast_bias_enabled() -> bool:
    """Return ``True`` when endogenous-narrative broadcast bias is active.

    Reads ``HAPAX_DAIMONION_BROADCAST_BIAS_ENABLED`` on every call (no
    caching) so an operator flipping the flag at runtime takes effect on
    the next utterance.

    Default: ``True`` (unset, empty, or "1" → active). Only the literal
    "0" forces legacy private-only behavior.
    """
    raw = os.environ.get(BROADCAST_BIAS_ENV)
    if raw is None:
        return True
    return raw.strip() != "0"


# Sources whose impingements are eligible for the broadcast bias. The
# legacy ``autonomous_narrative`` source covered the original autonomous
# narration path; the ``endogenous.*`` sources cover narrative_drive,
# gem-producer, and other endogenous cognitive emitters whose default
# fall-through to PRIVATE leaves Hapax silent on the livestream.
_BROADCAST_BIAS_ENDOGENOUS_PREFIX: str = "endogenous."
_BROADCAST_BIAS_LEGACY_SOURCES: frozenset[str] = frozenset({"autonomous_narrative"})


def _is_endogenous_narrative_source(source: object) -> bool:
    """Return ``True`` when ``source`` is a broadcast-bias-eligible emitter.

    Matches both the legacy ``autonomous_narrative`` source (preserved
    for the existing autonomous narration path) and any ``endogenous.*``
    cognitive emitter (narrative_drive, gem-producer, etc.).
    """
    if not isinstance(source, str):
        return False
    if source in _BROADCAST_BIAS_LEGACY_SOURCES:
        return True
    return source.startswith(_BROADCAST_BIAS_ENDOGENOUS_PREFIX)


# Roles where broadcast voice is appropriate. LISTENING is excluded
# because the operator explicitly chose a receptive programme role —
# Hapax speaking to the audience defeats the role's intent. The seven
# segmented-content roles (TIER_LIST through LECTURE, shipped via
# #2465) are all broadcast-eligible: each is a Hapax-authored
# narrative format whose entire point is to broadcast.
_BROADCAST_ELIGIBLE_ROLES: frozenset[str] = frozenset(
    {
        # Operator-context roles (Phase 1)
        "showcase",
        "ritual",
        "interlude",
        "work_block",
        "tutorial",
        "wind_down",
        "hothouse_pressure",
        "ambient",
        "experiment",
        "repair",
        "invitation",
        # Segmented-content roles (operator outcome 2)
        "tier_list",
        "top_10",
        "rant",
        "react",
        "iceberg",
        "interview",
        "lecture",
    }
)


def _programme_authorizes_broadcast() -> bool:
    """Return ``True`` when the active programme's role is broadcast-eligible.

    Reads the programme store on every call (filesystem-as-bus, small file).
    Returns ``False`` on any error or missing programme — fail-closed to
    private when programme state is ambiguous.
    """
    try:
        from agents.hapax_daimonion.cpal.programme_context import default_provider

        programme = default_provider()
        if programme is None:
            return False
        if programme.status != "active":
            return False
        return programme.role.value in _BROADCAST_ELIGIBLE_ROLES
    except Exception:
        log.debug("programme broadcast authorization check failed", exc_info=True)
        return False


def _broadcast_intent_evidence(
    content: dict[str, Any],
    *,
    source: object = "",
) -> dict[str, Any]:
    candidates: tuple[object, ...] = (
        content.get("voice_output_destination"),
        content.get("destination"),
        content.get("channel"),
        content.get("route"),
        content.get("intent"),
    )
    explicit_bool = (
        content.get("public_broadcast_intent") is True or content.get("broadcast_intent") is True
    )
    explicit_token = any(
        isinstance(value, str)
        and value
        in {
            "broadcast",
            "livestream",
            "public",
            "public_broadcast",
            "public_broadcast_voice",
        }
        for value in candidates
    )
    nested = content.get("voice_output")
    nested_token = False
    if isinstance(nested, dict):
        nested_token = (
            any(
                nested.get(key)
                in {
                    "broadcast",
                    "livestream",
                    "public",
                    "public_broadcast",
                    "public_broadcast_voice",
                }
                for key in ("destination", "intent", "route")
            )
            or nested.get("public_broadcast_intent") is True
        )
    # Implicit intent from the broadcast-bias path: when the flag is on
    # AND the source is a bias-eligible endogenous emitter AND the active
    # programme authorizes broadcast, that combination IS the intent.
    # The programme authorization check is the load-bearing safety gate,
    # not the per-utterance token; without it this branch returns False
    # and the explicit-token requirement still applies.
    bias_implicit = (
        _is_broadcast_bias_enabled()
        and _is_endogenous_narrative_source(source)
        and _programme_authorizes_broadcast()
    )
    return {
        "present": bool(explicit_bool or explicit_token or nested_token or bias_implicit),
        "explicit_bool": explicit_bool,
        "explicit_token": explicit_token,
        "nested_token": nested_token,
        "bias_implicit": bias_implicit,
    }


def _programme_authorization_evidence(
    content: dict[str, Any],
    *,
    now: float | None,
) -> dict[str, Any]:
    auth = (
        content.get("programme_authorization")
        or content.get("broadcast_programme_authorization")
        or content.get("broadcast_authorization")
    )
    if not isinstance(auth, dict):
        return {
            "authorized": False,
            "reason_code": "programme_authorization_missing",
            "age_s": None,
        }
    if not (
        auth.get("authorized") is True
        or auth.get("broadcast_voice_authorized") is True
        or auth.get("public_broadcast_authorized") is True
    ):
        return {
            "authorized": False,
            "reason_code": "programme_authorization_not_granted",
            "age_s": None,
        }

    ts = time_or_none(auth.get("authorized_at"))
    if ts is None:
        ts = time_or_none(auth.get("checked_at"))
    expires_at = time_or_none(auth.get("expires_at")) or time_or_none(auth.get("fresh_until"))
    current = _now(now)
    if expires_at is not None and expires_at < current:
        return {
            "authorized": False,
            "reason_code": "programme_authorization_expired",
            "age_s": round(current - expires_at, 3),
        }
    if ts is None:
        return {
            "authorized": False,
            "reason_code": "programme_authorization_timestamp_missing",
            "age_s": None,
        }
    age = max(0.0, current - ts)
    if age > BROADCAST_AUTH_MAX_AGE_S:
        return {
            "authorized": False,
            "reason_code": "programme_authorization_stale",
            "age_s": round(age, 3),
        }
    return {
        "authorized": True,
        "reason_code": "programme_authorization_fresh",
        "age_s": round(age, 3),
        "programme_id": auth.get("programme_id"),
        "evidence_ref": auth.get("evidence_ref"),
    }


def time_or_none(value: object) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def _now(now: float | None) -> float:
    if now is not None:
        return now
    return datetime.now(tz=UTC).timestamp()


class _DestinationCounter:
    """``hapax_tts_destination_total{destination}`` counter wrapper.

    Pre-registers one child per ``DestinationChannel`` value so scrapes
    always see the full label set, even before the first utterance fires.
    Degrades to a no-op if ``prometheus_client`` is unavailable (tests,
    minimal installs) — classification must never crash because metrics
    are missing.
    """

    def __init__(self) -> None:
        self._counter: Any = None
        try:
            from prometheus_client import Counter
        except ImportError:  # pragma: no cover — prometheus-client is a hard dep
            log.debug("prometheus_client unavailable; destination counter disabled")
            return
        try:
            self._counter = Counter(
                "hapax_tts_destination_total",
                "CPAL TTS utterances grouped by destination sink",
                ["destination"],
            )
        except ValueError:
            # Duplicate registration (tests reloading the module).
            from prometheus_client import REGISTRY

            self._counter = REGISTRY._names_to_collectors.get(  # noqa: SLF001
                "hapax_tts_destination_total"
            )
        if self._counter is not None:
            for dest in DestinationChannel:
                try:
                    self._counter.labels(destination=dest.value).inc(0)
                except Exception:  # pragma: no cover — label init is best-effort
                    log.debug("destination counter label init failed", exc_info=True)

    def inc(self, destination: DestinationChannel) -> None:
        if self._counter is None:
            return
        try:
            self._counter.labels(destination=destination.value).inc()
        except Exception:  # pragma: no cover
            log.debug("destination counter inc failed", exc_info=True)


_counter = _DestinationCounter()


def record_destination(destination: DestinationChannel) -> None:
    """Increment the Prometheus counter for ``destination``.

    Call this exactly once per classified utterance (at classification
    time, not at playback time, so the counter tracks intent even when
    the subprocess spawn fails).
    """
    _counter.inc(destination)


def classify_and_record(
    impingement: Any,
    *,
    voice_register: VoiceRegister | None = None,
) -> DestinationChannel:
    """One-shot helper: classify the impingement, increment the counter, log.

    The INFO log includes only the destination and the impingement's
    ``source`` tag — never the narrative body, operator text, or any
    payload that could leak private content into stdout. Callers that
    need structured per-utterance telemetry should emit
    ``hapax_span`` / ``hapax_event`` separately.
    """
    destination = classify_destination(impingement, voice_register=voice_register)
    record_destination(destination)
    source = getattr(impingement, "source", None) if impingement is not None else None
    log.info(
        "CPAL TTS destination resolved: destination=%s source=%s",
        destination.value,
        source or "<none>",
    )
    return destination


__all__ = [
    "DESTINATION_ROUTING_ENV",
    "DEFAULT_TARGET_ENV",
    "BROADCAST_MEDIA_ROLE",
    "LIVESTREAM_SINK",
    "PRIVATE_MEDIA_ROLE",
    "PRIVATE_SINK",
    "DestinationChannel",
    "VoicePlaybackDecision",
    "classify_and_record",
    "classify_destination",
    "is_routing_active",
    "record_destination",
    "resolve_playback_decision",
    "resolve_route",
    "resolve_role",
    "resolve_target",
]

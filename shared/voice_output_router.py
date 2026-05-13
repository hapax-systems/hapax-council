"""Typed semantic routing for daimonion voice output.

This module carries TWO public API layers:

1. **Policy API** (legacy / production): ``VoiceOutputDestination`` enum +
   ``resolve_voice_output_route()`` function + witness-gated routing
   policy machinery. This is the policy authority — it binds a semantic
   destination to a concrete PipeWire target via ``config/audio-routing.yaml``
   and attaches the evidence gate that makes the route safe to use.
   Existing consumers (``destination_channel.py``,
   ``audio_expression_surface.py``) call this layer.

2. **Role API** (new, cc-task ``voice-output-router-semantic-api``):
   ``VoiceRole`` Literal + ``VoiceOutputRouter.route()`` + simple
   ``RouteResult`` dataclass. Caller asks for an audio surface by ROLE
   ("assistant" / "broadcast" / "private_monitor" / "notification") and
   gets back a sink_name + provenance. Config lives in
   ``config/voice-output-routes.yaml``. The director-loop semantic
   audio route consumer (cc-task ``director-loop-semantic-audio-route``)
   talks to this layer.

The two layers are intentionally co-located in one module so future
unification is mechanical, not a cross-file rewrite. They share no
state or implementation today; the role API is a thin facade over the
operator-curated YAML map, while the policy API is the witness-gated
runtime authority.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Final, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from shared.audio_routing_policy import (
    DEFAULT_POLICY_PATH,
    AudioRoutingPolicy,
    RoutePolicy,
    load_audio_routing_policy,
)

log = logging.getLogger(__name__)

DEFAULT_PRIVATE_MONITOR_STATUS_PATH = Path("/dev/shm/hapax-audio/private-monitor-target.json")
PRIVATE_MONITOR_STATUS_MAX_AGE_S = 300.0

NO_DEFAULT_FALLBACK_POLICY = "no_default_fallback"

PRIVATE_MONITOR_TARGET_REF = "audio.mpc_private_monitor"

PUBLIC_BROADCAST_SOURCE_ID = "broadcast-tts"
PRIVATE_ASSISTANT_SOURCE_ID = "assistant-private"
PRIVATE_NOTIFICATION_SOURCE_ID = "notification-private"

PUBLIC_BROADCAST_MEDIA_ROLE = "Broadcast"
PRIVATE_ASSISTANT_MEDIA_ROLE = "Assistant"
PRIVATE_NOTIFICATION_MEDIA_ROLE = "Notification"

PROHIBITED_PUBLIC_FALLBACK_REFS: tuple[str, ...] = (
    "route:private.assistant_monitor",
    "route:private.notification_monitor",
    "system-default",
    "wireplumber-default",
    "input.loopback.sink.role.multimedia",
    "hapax-pc-loudnorm",
    "l12-usb-return",
)

PROHIBITED_PRIVATE_FALLBACK_REFS: tuple[str, ...] = (
    "route:broadcast",
    "route:public.broadcast_voice",
    "hapax-livestream",
    "hapax-livestream-tap",
    "hapax-voice-fx-capture",
    "input.loopback.sink.role.broadcast",
    "input.loopback.sink.role.multimedia",
    "hapax-pc-loudnorm",
    "l12-usb-return",
    "l12-capture",
    "multimedia-default",
    "system-default",
    "wireplumber-default",
)

RAW_HIGH_LEVEL_TARGETS: frozenset[str] = frozenset(
    {
        "assistant",
        "broadcast",
        "default",
        "hapax-livestream",
        "hapax-livestream-tap",
        "hapax-notification-private",
        "hapax-private",
        "hapax-voice-fx-capture",
        "input.loopback.sink.role.assistant",
        "input.loopback.sink.role.broadcast",
        "input.loopback.sink.role.multimedia",
        "input.loopback.sink.role.notification",
        "livestream",
        "multimedia",
        "notification",
        "private",
        "public",
        "system-default",
        "voice-fx",
    }
)


class VoiceOutputDestination(StrEnum):
    """Allowed semantic voice-output destinations."""

    PUBLIC_BROADCAST = "public_broadcast"
    PRIVATE_ASSISTANT_MONITOR = "private_assistant_monitor"
    PRIVATE_NOTIFICATION_MONITOR = "private_notification_monitor"
    DRY_RUN_PROBE = "dry_run_probe"


class VoiceRouteState(StrEnum):
    """Whether a semantic route may be used for playback."""

    ACCEPTED = "accepted"
    BLOCKED = "blocked"


class VoiceRouteWitnessRequirement(StrEnum):
    """Runtime evidence required before a route claim can be trusted."""

    PUBLIC_AUDIO_HEALTH = "public_audio_health"
    PRIVATE_MONITOR_STATUS = "private_monitor_status"
    ROUTE_INTENT_ONLY = "route_intent_only"


class VoiceRouteBinding(BaseModel):
    """Concrete binding selected for a semantic destination."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    route_id: str
    source_id: str
    target: str | None
    target_ref: str | None
    media_role: str | None
    pipewire_node: str | None
    target_chain: tuple[str, ...] = Field(default_factory=tuple)
    route_class: str
    fallback_policy: str = NO_DEFAULT_FALLBACK_POLICY
    prohibited_fallback_refs: tuple[str, ...] = Field(default_factory=tuple)
    raw_high_level_target_assumption: bool = False


class VoiceRouteResult(BaseModel):
    """Route decision envelope returned by semantic voice routing."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    semantic_destination: VoiceOutputDestination | None
    state: VoiceRouteState
    accepted: bool
    reason_code: str
    operator_visible_reason: str
    target_binding: VoiceRouteBinding | None
    witness_requirement: VoiceRouteWitnessRequirement
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)


class _PrivateMonitorStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    state: str
    reason_code: str
    operator_visible_reason: str
    exact_target_present: bool
    bridge_nodes_present: bool
    fallback_policy: str
    target_ref: str
    sanitized: bool


def resolve_voice_output_route(
    destination: VoiceOutputDestination | str,
    *,
    policy_path: Path | None = None,
    private_monitor_status_path: Path = DEFAULT_PRIVATE_MONITOR_STATUS_PATH,
    private_monitor_max_age_s: float = PRIVATE_MONITOR_STATUS_MAX_AGE_S,
    now: float | None = None,
) -> VoiceRouteResult:
    """Resolve a semantic voice-output destination to a safe playback route.

    Strings are accepted only when they match a semantic enum value. Raw names
    such as ``"private"``, ``"public"``, concrete PipeWire nodes, or default
    sinks are rejected as high-level target bypasses.
    """

    semantic_destination = _coerce_destination(destination)
    if semantic_destination is None:
        raw = str(destination)
        reason_code = (
            "raw_high_level_target_refused"
            if raw in RAW_HIGH_LEVEL_TARGETS
            else "semantic_destination_unknown"
        )
        return VoiceRouteResult(
            semantic_destination=None,
            state=VoiceRouteState.BLOCKED,
            accepted=False,
            reason_code=reason_code,
            operator_visible_reason=(
                "Voice output must use a typed semantic destination; raw audio targets are refused."
            ),
            target_binding=None,
            witness_requirement=VoiceRouteWitnessRequirement.ROUTE_INTENT_ONLY,
        )

    if semantic_destination == VoiceOutputDestination.DRY_RUN_PROBE:
        return _dry_run_result()

    policy = load_audio_routing_policy(policy_path or DEFAULT_POLICY_PATH)
    route = _route_for_destination(policy, semantic_destination)
    if route is None:
        return _blocked_result(
            semantic_destination,
            None,
            reason_code="audio_route_policy_missing",
            operator_visible_reason="No audio routing policy row exists for this destination.",
            witness_requirement=_witness_for_destination(semantic_destination),
        )

    binding = _binding_from_route(
        semantic_destination,
        route,
        target=None,
        reason_allows_target=False,
    )
    policy_error = _route_policy_error(semantic_destination, route)
    if policy_error is not None:
        return _blocked_result(
            semantic_destination,
            binding,
            reason_code=policy_error,
            operator_visible_reason="Audio route policy does not satisfy the fail-closed contract.",
            witness_requirement=_witness_for_destination(semantic_destination),
            evidence_refs=route.evidence_refs,
        )

    if semantic_destination in {
        VoiceOutputDestination.PRIVATE_ASSISTANT_MONITOR,
        VoiceOutputDestination.PRIVATE_NOTIFICATION_MONITOR,
    }:
        gate = _private_monitor_gate(
            private_monitor_status_path,
            now=now,
            max_age_s=private_monitor_max_age_s,
        )
        if gate is not None:
            return _blocked_result(
                semantic_destination,
                binding,
                reason_code=gate.reason_code,
                operator_visible_reason=gate.operator_visible_reason,
                witness_requirement=VoiceRouteWitnessRequirement.PRIVATE_MONITOR_STATUS,
                evidence_refs=route.evidence_refs,
            )

    accepted_binding = _binding_from_route(
        semantic_destination,
        route,
        target=route.target_chain[0],
        reason_allows_target=True,
    )
    return VoiceRouteResult(
        semantic_destination=semantic_destination,
        state=VoiceRouteState.ACCEPTED,
        accepted=True,
        reason_code=_accepted_reason_code(semantic_destination),
        operator_visible_reason="Semantic voice-output route is bound to an explicit target.",
        target_binding=accepted_binding,
        witness_requirement=_witness_for_destination(semantic_destination),
        evidence_refs=route.evidence_refs,
    )


def target_for_route(result: VoiceRouteResult) -> str | None:
    """Return the playback target only when the route envelope is accepted."""

    if not result.accepted or result.target_binding is None:
        return None
    return result.target_binding.target


def media_role_for_route(result: VoiceRouteResult) -> str | None:
    """Return the PipeWire media role only when the route envelope is accepted."""

    if not result.accepted or result.target_binding is None:
        return None
    return result.target_binding.media_role


def _coerce_destination(value: VoiceOutputDestination | str) -> VoiceOutputDestination | None:
    if isinstance(value, VoiceOutputDestination):
        return value
    try:
        return VoiceOutputDestination(str(value))
    except ValueError:
        return None


def _route_for_destination(
    policy: AudioRoutingPolicy,
    destination: VoiceOutputDestination,
) -> RoutePolicy | None:
    source_id = {
        VoiceOutputDestination.PUBLIC_BROADCAST: PUBLIC_BROADCAST_SOURCE_ID,
        VoiceOutputDestination.PRIVATE_ASSISTANT_MONITOR: PRIVATE_ASSISTANT_SOURCE_ID,
        VoiceOutputDestination.PRIVATE_NOTIFICATION_MONITOR: PRIVATE_NOTIFICATION_SOURCE_ID,
    }.get(destination)
    if source_id is None:
        return None
    return next((route for route in policy.routes if route.source_id == source_id), None)


def _binding_from_route(
    destination: VoiceOutputDestination,
    route: RoutePolicy,
    *,
    target: str | None,
    reason_allows_target: bool,
) -> VoiceRouteBinding:
    return VoiceRouteBinding(
        route_id=_route_id(destination),
        source_id=route.source_id,
        target=target if reason_allows_target else None,
        target_ref=_target_ref(destination, route, target if reason_allows_target else None),
        media_role=_media_role(destination),
        pipewire_node=route.pipewire_node,
        target_chain=route.target_chain,
        route_class=route.route_class,
        prohibited_fallback_refs=_prohibited_fallback_refs(destination),
    )


def _route_id(destination: VoiceOutputDestination) -> str:
    return {
        VoiceOutputDestination.PUBLIC_BROADCAST: "route:public.broadcast_voice",
        VoiceOutputDestination.PRIVATE_ASSISTANT_MONITOR: "route:private.assistant_monitor",
        VoiceOutputDestination.PRIVATE_NOTIFICATION_MONITOR: ("route:private.notification_monitor"),
        VoiceOutputDestination.DRY_RUN_PROBE: "route:dry_run.voice_probe",
    }[destination]


def _media_role(destination: VoiceOutputDestination) -> str | None:
    return {
        VoiceOutputDestination.PUBLIC_BROADCAST: PUBLIC_BROADCAST_MEDIA_ROLE,
        VoiceOutputDestination.PRIVATE_ASSISTANT_MONITOR: PRIVATE_ASSISTANT_MEDIA_ROLE,
        VoiceOutputDestination.PRIVATE_NOTIFICATION_MONITOR: PRIVATE_NOTIFICATION_MEDIA_ROLE,
        VoiceOutputDestination.DRY_RUN_PROBE: None,
    }[destination]


def _target_ref(
    destination: VoiceOutputDestination,
    route: RoutePolicy,
    target: str | None,
) -> str | None:
    if destination in {
        VoiceOutputDestination.PRIVATE_ASSISTANT_MONITOR,
        VoiceOutputDestination.PRIVATE_NOTIFICATION_MONITOR,
    }:
        return PRIVATE_MONITOR_TARGET_REF
    if target is None:
        return None
    return f"pipewire:{target or route.pipewire_node}"


def _prohibited_fallback_refs(destination: VoiceOutputDestination) -> tuple[str, ...]:
    if destination == VoiceOutputDestination.PUBLIC_BROADCAST:
        return PROHIBITED_PUBLIC_FALLBACK_REFS
    if destination in {
        VoiceOutputDestination.PRIVATE_ASSISTANT_MONITOR,
        VoiceOutputDestination.PRIVATE_NOTIFICATION_MONITOR,
    }:
        return PROHIBITED_PRIVATE_FALLBACK_REFS
    return ("system-default", "wireplumber-default")


def _witness_for_destination(
    destination: VoiceOutputDestination,
) -> VoiceRouteWitnessRequirement:
    if destination == VoiceOutputDestination.PUBLIC_BROADCAST:
        return VoiceRouteWitnessRequirement.PUBLIC_AUDIO_HEALTH
    if destination in {
        VoiceOutputDestination.PRIVATE_ASSISTANT_MONITOR,
        VoiceOutputDestination.PRIVATE_NOTIFICATION_MONITOR,
    }:
        return VoiceRouteWitnessRequirement.PRIVATE_MONITOR_STATUS
    return VoiceRouteWitnessRequirement.ROUTE_INTENT_ONLY


def _accepted_reason_code(destination: VoiceOutputDestination) -> str:
    return {
        VoiceOutputDestination.PUBLIC_BROADCAST: "public_broadcast_route_bound",
        VoiceOutputDestination.PRIVATE_ASSISTANT_MONITOR: "private_assistant_monitor_bound",
        VoiceOutputDestination.PRIVATE_NOTIFICATION_MONITOR: "private_notification_monitor_bound",
        VoiceOutputDestination.DRY_RUN_PROBE: "dry_run_probe_no_playback",
    }[destination]


def _route_policy_error(
    destination: VoiceOutputDestination,
    route: RoutePolicy,
) -> str | None:
    if route.default_fallback_allowed:
        return "audio_route_default_fallback_allowed"
    if not route.target_chain:
        return "audio_route_target_chain_missing"

    if destination == VoiceOutputDestination.PUBLIC_BROADCAST:
        if not route.broadcast_eligible or not route.public_claim_allowed:
            return "public_broadcast_route_not_public_eligible"
        if route.target_chain[0] in PROHIBITED_PUBLIC_FALLBACK_REFS:
            return "public_broadcast_route_target_is_fallback"
        return None

    if destination in {
        VoiceOutputDestination.PRIVATE_ASSISTANT_MONITOR,
        VoiceOutputDestination.PRIVATE_NOTIFICATION_MONITOR,
    }:
        if route.broadcast_eligible or route.public_claim_allowed:
            return "private_route_public_eligible"
        leaked_refs = set(route.target_chain).intersection(PROHIBITED_PRIVATE_FALLBACK_REFS)
        if leaked_refs:
            return "private_route_has_public_or_default_fallback"
        return None

    return None


class _PrivateMonitorGate:
    def __init__(self, *, reason_code: str, operator_visible_reason: str) -> None:
        self.reason_code = reason_code
        self.operator_visible_reason = operator_visible_reason


def _private_monitor_gate(
    status_path: Path,
    *,
    now: float | None,
    max_age_s: float,
) -> _PrivateMonitorGate | None:
    ts = time.time() if now is None else now
    try:
        age = max(0.0, ts - status_path.stat().st_mtime)
    except FileNotFoundError:
        return _PrivateMonitorGate(
            reason_code="private_monitor_status_missing",
            operator_visible_reason=(
                "Private monitor target evidence is missing; private voice route remains silent."
            ),
        )
    except OSError:
        return _PrivateMonitorGate(
            reason_code="private_monitor_status_unreadable",
            operator_visible_reason=(
                "Private monitor target evidence cannot be read; private voice route remains silent."
            ),
        )

    if age > max_age_s:
        return _PrivateMonitorGate(
            reason_code="private_monitor_status_stale",
            operator_visible_reason=(
                "Private monitor target evidence is stale; private voice route remains silent."
            ),
        )

    try:
        payload = json.loads(status_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("status payload must be an object")
        status = _PrivateMonitorStatus.model_validate(payload)
    except (json.JSONDecodeError, OSError, ValidationError, ValueError):
        return _PrivateMonitorGate(
            reason_code="private_monitor_status_malformed",
            operator_visible_reason=(
                "Private monitor target evidence is malformed; private voice route remains silent."
            ),
        )

    if status.state != "ready":
        return _PrivateMonitorGate(
            reason_code=status.reason_code or "mpc_private_monitor_target_absent",
            operator_visible_reason=(
                status.operator_visible_reason
                or "MPC Live III private monitor target is absent; private voice route remains silent."
            ),
        )

    if (
        not status.exact_target_present
        or not status.bridge_nodes_present
        or status.fallback_policy != NO_DEFAULT_FALLBACK_POLICY
        or status.target_ref != PRIVATE_MONITOR_TARGET_REF
        or status.sanitized is not True
    ):
        return _PrivateMonitorGate(
            reason_code="private_monitor_status_invalid",
            operator_visible_reason=(
                "Private monitor evidence does not prove the fail-closed MPC Live III target."
            ),
        )

    return None


def _dry_run_result() -> VoiceRouteResult:
    binding = VoiceRouteBinding(
        route_id=_route_id(VoiceOutputDestination.DRY_RUN_PROBE),
        source_id="dry-run-probe",
        target=None,
        target_ref="dry-run:no-playback",
        media_role=None,
        pipewire_node=None,
        target_chain=(),
        route_class="dry_run",
        prohibited_fallback_refs=("system-default", "wireplumber-default"),
    )
    return VoiceRouteResult(
        semantic_destination=VoiceOutputDestination.DRY_RUN_PROBE,
        state=VoiceRouteState.ACCEPTED,
        accepted=True,
        reason_code="dry_run_probe_no_playback",
        operator_visible_reason="Dry-run probe records intent without playing audio.",
        target_binding=binding,
        witness_requirement=VoiceRouteWitnessRequirement.ROUTE_INTENT_ONLY,
    )


def _blocked_result(
    destination: VoiceOutputDestination,
    binding: VoiceRouteBinding | None,
    *,
    reason_code: str,
    operator_visible_reason: str,
    witness_requirement: VoiceRouteWitnessRequirement,
    evidence_refs: tuple[str, ...] = (),
) -> VoiceRouteResult:
    return VoiceRouteResult(
        semantic_destination=destination,
        state=VoiceRouteState.BLOCKED,
        accepted=False,
        reason_code=reason_code,
        operator_visible_reason=operator_visible_reason,
        target_binding=binding,
        witness_requirement=witness_requirement,
        evidence_refs=evidence_refs,
    )


__all__ = [
    "DEFAULT_PRIVATE_MONITOR_STATUS_PATH",
    "DEFAULT_ROUTES_PATH",
    "PRIVATE_MONITOR_STATUS_MAX_AGE_S",
    "VOICE_ROLES",
    "Provenance",
    "RouteResult",
    "VoiceOutputDestination",
    "VoiceOutputRouter",
    "VoiceRole",
    "VoiceRoleRouterError",
    "VoiceRouteBinding",
    "VoiceRouteResult",
    "VoiceRouteState",
    "VoiceRouteWitnessRequirement",
    "media_role_for_route",
    "resolve_voice_output_route",
    "target_for_route",
]


# ---------------------------------------------------------------------------
# Role API (cc-task: voice-output-router-semantic-api)
# ---------------------------------------------------------------------------


VoiceRole = Literal["assistant", "broadcast", "private_monitor", "notification"]
VOICE_ROLES: Final[tuple[VoiceRole, ...]] = (
    "assistant",
    "broadcast",
    "private_monitor",
    "notification",
)
_VOICE_ROLE_SET: Final[frozenset[str]] = frozenset(VOICE_ROLES)

DEFAULT_ROUTES_PATH: Final[Path] = (
    Path(__file__).resolve().parent.parent / "config" / "voice-output-routes.yaml"
)

Provenance = Literal["config_role", "fallback", "unavailable"]


class VoiceRoleRouterError(ValueError):
    """Raised when the role-keyed router cannot serve a request safely."""


@dataclass(frozen=True)
class RouteResult:
    """Resolved route for one semantic role.

    ``sink_name`` is the PipeWire sink identifier the caller should
    pass to ``pw-cat --target=...``. ``None`` when the role is
    configured but the sink isn't available right now (per the
    operator-injected ``sink_present`` check).
    """

    role: VoiceRole
    sink_name: str | None
    provenance: Provenance
    live_at: str
    description: str | None = None


class VoiceOutputRouter:
    """YAML-config-driven role → PipeWire sink resolver.

    The router lazy-loads ``config/voice-output-routes.yaml`` on the
    first ``route()`` call and reloads automatically when the file's
    mtime advances. No daemon thread; reload is synchronous and cheap.

    A ``sink_present`` predicate may be injected at construction time
    to upgrade ``"config_role"`` results to ``"unavailable"`` when the
    live PipeWire graph doesn't carry the configured sink. The router
    itself never inspects the live graph — that's caller policy.

    This is the role-keyed semantic API the cc-task
    ``voice-output-router-semantic-api`` calls for. It deliberately
    does NOT duplicate the policy machinery in
    ``resolve_voice_output_route()`` (witness gates, fallback, dry-run);
    that function remains the policy authority for live-routing
    decisions. The director-loop consumer
    (``director-loop-semantic-audio-route``) calls into this class.
    """

    def __init__(
        self,
        *,
        routes_path: Path | None = None,
        sink_present: Callable[[str], bool] | None = None,
    ) -> None:
        self._routes_path = routes_path if routes_path is not None else DEFAULT_ROUTES_PATH
        self._sink_present = sink_present
        self._mapping: dict[VoiceRole, dict[str, str]] = {}
        self._loaded_mtime: float | None = None

    def _load_if_stale(self) -> None:
        try:
            mtime = self._routes_path.stat().st_mtime
        except FileNotFoundError:
            self._mapping = {}
            self._loaded_mtime = None
            return
        if self._loaded_mtime is not None and self._loaded_mtime == mtime:
            return
        try:
            data = yaml.safe_load(self._routes_path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            log.warning(
                "voice_output_router: failed to read %s; treating as empty",
                self._routes_path,
                exc_info=True,
            )
            self._mapping = {}
            self._loaded_mtime = mtime
            return
        roles_section = data.get("roles") if isinstance(data, dict) else None
        mapping: dict[VoiceRole, dict[str, str]] = {}
        if isinstance(roles_section, dict):
            for raw_role, raw_entry in roles_section.items():
                if raw_role not in _VOICE_ROLE_SET or not isinstance(raw_entry, dict):
                    continue
                sink_name = raw_entry.get("sink_name")
                if not isinstance(sink_name, str) or not sink_name.strip():
                    continue
                description = raw_entry.get("description")
                mapping[raw_role] = {  # type: ignore[index]
                    "sink_name": sink_name.strip(),
                    "description": (description.strip() if isinstance(description, str) else ""),
                }
        self._mapping = mapping
        self._loaded_mtime = mtime

    def route(self, role: VoiceRole | str) -> RouteResult:
        """Resolve one semantic role to a sink_name + provenance.

        Raises ``VoiceRoleRouterError`` for an unknown role string —
        the operator's audio policy is bounded to four roles, and a
        typo in caller code is a programmer error, not a runtime
        condition that should be silently masked.
        """

        if role not in _VOICE_ROLE_SET:
            raise VoiceRoleRouterError(f"unknown voice role {role!r}; valid roles: {VOICE_ROLES!r}")
        self._load_if_stale()
        live_at = datetime.now(tz=UTC).isoformat()
        entry = self._mapping.get(role)  # type: ignore[arg-type]
        if entry is None:
            return RouteResult(
                role=role,  # type: ignore[arg-type]
                sink_name=None,
                provenance="unavailable",
                live_at=live_at,
            )
        sink_name = entry["sink_name"]
        if self._sink_present is not None and not self._sink_present(sink_name):
            return RouteResult(
                role=role,  # type: ignore[arg-type]
                sink_name=None,
                provenance="unavailable",
                live_at=live_at,
                description=entry.get("description") or None,
            )
        return RouteResult(
            role=role,  # type: ignore[arg-type]
            sink_name=sink_name,
            provenance="config_role",
            live_at=live_at,
            description=entry.get("description") or None,
        )

    def known_roles(self) -> tuple[VoiceRole, ...]:
        """Return the roles currently configured (operator dashboard helper)."""

        self._load_if_stale()
        return tuple(role for role in VOICE_ROLES if role in self._mapping)

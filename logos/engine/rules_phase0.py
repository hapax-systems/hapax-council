"""Phase 0 reactive rules — deterministic, no LLM calls.

Includes: collector-refresh, config-changed, SDLC events, carrier intake,
voice/presence transitions, consent transitions, biometric state cascade.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading

from logos._carrier import CarrierRegistry
from logos._telemetry import hapax_event
from logos.engine.models import Action, ChangeEvent
from logos.engine.rules import Rule

_log = logging.getLogger(__name__)

# ── File-to-cache-tier mapping ───────────────────────────────────────────────

_FAST_REFRESH_FILES = {"health-history.jsonl"}
_SLOW_REFRESH_FILES = {"drift-report.json", "scout-report.json", "operator-profile.json"}


# ── Collector refresh ────────────────────────────────────────────────────────


async def _handle_collector_refresh(*, tier: str) -> str:
    from logos.api.cache import cache

    if tier == "fast":
        await cache.refresh_fast()
    else:
        await cache.refresh_slow()
    _log.info("Cache %s refresh triggered by file change", tier)
    return f"cache.refresh_{tier}"


def _collector_refresh_filter(event: ChangeEvent) -> bool:
    return event.path.name in _FAST_REFRESH_FILES | _SLOW_REFRESH_FILES


def _collector_refresh_produce(event: ChangeEvent) -> list[Action]:
    filename = event.path.name
    tier = "fast" if filename in _FAST_REFRESH_FILES else "slow"
    return [
        Action(
            name=f"collector-refresh-{tier}",
            handler=_handle_collector_refresh,
            args={"tier": tier},
            phase=0,
            priority=10,
        )
    ]


COLLECTOR_REFRESH_RULE = Rule(
    name="collector-refresh",
    description="Refresh logos cache tier when profiles/ data changes",
    trigger_filter=_collector_refresh_filter,
    produce=_collector_refresh_produce,
    phase=0,
)


# ── Config changed ──────────────────────────────────────────────────────────


async def _handle_config_changed(*, path: str) -> str:
    _log.info("Axiom config changed: %s (loaders will pick up on next call)", path)
    return "config-reloaded"


def _config_changed_filter(event: ChangeEvent) -> bool:
    return event.path.name == "registry.yaml" and "axioms" in event.path.parts


def _config_changed_produce(event: ChangeEvent) -> list[Action]:
    return [
        Action(
            name="config-changed",
            handler=_handle_config_changed,
            args={"path": str(event.path)},
            phase=0,
            priority=5,
        )
    ]


CONFIG_CHANGED_RULE = Rule(
    name="config-changed",
    description="Log axiom registry reload on axioms/registry.yaml change",
    trigger_filter=_config_changed_filter,
    produce=_config_changed_produce,
    phase=0,
)


# ── SDLC events ─────────────────────────────────────────────────────────────


async def _handle_sdlc_event(*, path: str) -> str:
    from logos._notify import send_notification
    from logos.api.cache import cache

    await asyncio.to_thread(
        send_notification,
        "SDLC Pipeline Event",
        "New event logged to sdlc-events.jsonl",
        priority="default",
        tags=["gear"],
    )
    await cache.refresh_slow()
    _log.info("SDLC event notification sent + slow cache refreshed")
    return "sdlc-notified"


def _sdlc_event_filter(event: ChangeEvent) -> bool:
    return event.path.name == "sdlc-events.jsonl"


def _sdlc_event_produce(event: ChangeEvent) -> list[Action]:
    return [
        Action(
            name="sdlc-event-logged",
            handler=_handle_sdlc_event,
            args={"path": str(event.path)},
            phase=0,
            priority=20,
        )
    ]


SDLC_EVENT_RULE = Rule(
    name="sdlc-event-logged",
    description="Notify and refresh cache on SDLC pipeline event",
    trigger_filter=_sdlc_event_filter,
    produce=_sdlc_event_produce,
    phase=0,
    cooldown_s=30,
)


# ── Carrier fact intake (DD-26) ──────────────────────────────────────────────

_carrier_registry: CarrierRegistry | None = None
_DEFAULT_CARRIER_CAPACITY = 5


def get_carrier_registry() -> CarrierRegistry:
    global _carrier_registry  # noqa: PLW0603
    if _carrier_registry is None:
        from logos._carrier import CarrierRegistry as _CR

        _carrier_registry = _CR()
    return _carrier_registry


def set_carrier_registry(registry: CarrierRegistry) -> None:
    global _carrier_registry  # noqa: PLW0603
    _carrier_registry = registry


async def _handle_carrier_intake(*, path: str, principal_id: str) -> str:
    from pathlib import Path as _Path

    from logos._agent_governor import create_agent_governor
    from logos._carrier_intake import intake_carrier_fact

    registry = get_carrier_registry()
    if principal_id not in registry._capacities:
        registry.register(principal_id, _DEFAULT_CARRIER_CAPACITY)

    governor = create_agent_governor(
        "carrier-intake",
        axiom_bindings=[
            {"axiom_id": "interpersonal_transparency", "role": "enforcer"},
        ],
    )

    result = await asyncio.to_thread(
        intake_carrier_fact,
        _Path(path),
        principal_id,
        registry,
        governor=governor,
    )
    status = "accepted" if result.accepted else "rejected"
    return f"carrier:{status}:{result.source_domain}"


def _carrier_intake_filter(event: ChangeEvent) -> bool:
    if event.frontmatter is None:
        return False
    return bool(event.frontmatter.get("carrier"))


def _carrier_intake_produce(event: ChangeEvent) -> list[Action]:
    principal_id = "operator"
    if event.frontmatter:
        principal_id = event.frontmatter.get("carrier_principal", "operator")
    return [
        Action(
            name=f"carrier-intake:{event.path}",
            handler=_handle_carrier_intake,
            args={"path": str(event.path), "principal_id": str(principal_id)},
            phase=0,
            priority=30,
        )
    ]


CARRIER_INTAKE_RULE = Rule(
    name="carrier-intake",
    description="Process carrier-flagged files into CarrierRegistry (DD-26)",
    trigger_filter=_carrier_intake_filter,
    produce=_carrier_intake_produce,
    phase=0,
    cooldown_s=0,
)


# ── Voice/presence transitions ──────────────────────────────────────────────

_transition_lock = threading.Lock()
_last_presence_state: str = ""
_last_consent_phase: str = "no_guest"


async def _handle_presence_transition(*, from_state: str, to_state: str) -> str:
    _log.info("PRESENCE transition: %s -> %s", from_state, to_state)
    if to_state == "AWAY":
        hapax_event("presence", "operator_away", metadata={"from_state": from_state})
    elif to_state == "PRESENT" and from_state == "AWAY":
        hapax_event("presence", "operator_returned", metadata={"from_state": from_state})
    return f"presence:{from_state}->{to_state}"


# Stashed perception data to eliminate TOCTOU between filter and produce.
# Filter reads the file once and stashes; produce consumes the stash.
_stashed_perception_data: dict | None = None


def _presence_transition_filter(event: ChangeEvent) -> bool:
    global _stashed_perception_data  # noqa: PLW0603
    if event.path.name != "perception-state.json":
        return False
    try:
        data = json.loads(event.path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    current = data.get("presence_state", "")
    with _transition_lock:
        changed = bool(current and current != _last_presence_state)
    if changed:
        _stashed_perception_data = data
    return changed


def _presence_transition_produce(event: ChangeEvent) -> list[Action]:
    global _last_presence_state, _stashed_perception_data  # noqa: PLW0603
    data = _stashed_perception_data
    _stashed_perception_data = None
    if data is None:
        return []
    current = data.get("presence_state", "")
    with _transition_lock:
        if current == _last_presence_state:
            return []
        from_state = _last_presence_state
        _last_presence_state = current
    return [
        Action(
            name=f"presence-transition:{from_state}->{current}",
            handler=_handle_presence_transition,
            args={"from_state": from_state, "to_state": current},
            phase=0,
            priority=10,
        )
    ]


PRESENCE_TRANSITION_RULE = Rule(
    name="presence-transition",
    description="React to Bayesian presence state transitions (PRESENT/UNCERTAIN/AWAY)",
    trigger_filter=_presence_transition_filter,
    produce=_presence_transition_produce,
    phase=0,
    cooldown_s=5,
)


# ── Consent transitions ─────────────────────────────────────────────────────


async def _handle_consent_transition(*, from_phase: str, to_phase: str) -> str:
    _log.info("CONSENT transition: %s -> %s", from_phase, to_phase)
    if to_phase == "consent_pending":
        from logos._notify import send_notification

        await asyncio.to_thread(
            send_notification,
            title="Guest Detected",
            message="Non-operator person detected. Consent flow initiated.",
            priority="high",
        )
    elif to_phase == "no_guest" and from_phase in ("consent_pending", "consent_refused"):
        from logos._notify import send_notification

        await asyncio.to_thread(
            send_notification,
            title="Guest Left",
            message=f"Guest departed ({from_phase}). Perception curtailment lifted.",
            priority="default",
        )
    hapax_event(
        "consent",
        f"phase_{to_phase}",
        metadata={"from_phase": from_phase, "to_phase": to_phase},
    )
    return f"consent:{from_phase}->{to_phase}"


# Stashed consent data (same TOCTOU fix as presence above).
_stashed_consent_data: dict | None = None


def _consent_transition_filter(event: ChangeEvent) -> bool:
    global _stashed_consent_data  # noqa: PLW0603
    if event.path.name != "perception-state.json":
        return False
    try:
        data = json.loads(event.path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    current = data.get("consent_phase", "no_guest")
    with _transition_lock:
        changed = current != _last_consent_phase
    if changed:
        _stashed_consent_data = data
    return changed


def _consent_transition_produce(event: ChangeEvent) -> list[Action]:
    global _last_consent_phase, _stashed_consent_data  # noqa: PLW0603
    data = _stashed_consent_data
    _stashed_consent_data = None
    if data is None:
        return []
    current = data.get("consent_phase", "no_guest")
    with _transition_lock:
        if current == _last_consent_phase:
            return []
        from_phase = _last_consent_phase
        _last_consent_phase = current
    return [
        Action(
            name=f"consent-transition:{from_phase}->{current}",
            handler=_handle_consent_transition,
            args={"from_phase": from_phase, "to_phase": current},
            phase=0,
            priority=5,
        )
    ]


CONSENT_TRANSITION_RULE = Rule(
    name="consent-transition",
    description="React to consent phase transitions (guest detection, consent resolution)",
    trigger_filter=_consent_transition_filter,
    produce=_consent_transition_produce,
    phase=0,
    cooldown_s=5,
)


# ── Biometric state cascade ─────────────────────────────────────────────────

_BIOMETRIC_FILES = {"heartrate.json", "hrv.json", "activity.json", "eda.json"}
_biometric_lock = threading.Lock()
_last_stress_elevated: bool = False


async def _handle_biometric_state_change(*, path: str) -> str:
    from pathlib import Path as _Path

    from agents.hapax_daimonion.watch_signals import WATCH_STATE_DIR, is_stress_elevated

    global _last_stress_elevated  # noqa: PLW0603
    stress_now = is_stress_elevated(WATCH_STATE_DIR)
    with _biometric_lock:
        changed = stress_now != _last_stress_elevated
        if changed:
            _last_stress_elevated = stress_now
    if changed:
        _log.info("Stress transition: %s -> %s", _last_stress_elevated, stress_now)
        hapax_event(
            "biometric",
            "stress_transition",
            metadata={"from": _last_stress_elevated, "to": stress_now},
        )
    _log.debug("Biometric state change processed: %s", path)
    return f"biometric-update:{_Path(path).name}"


def _biometric_state_filter(event: ChangeEvent) -> bool:
    return event.path.name in _BIOMETRIC_FILES and "watch" in event.path.parts


def _biometric_state_produce(event: ChangeEvent) -> list[Action]:
    return [
        Action(
            name=f"biometric-state:{event.path.name}",
            handler=_handle_biometric_state_change,
            args={"path": str(event.path)},
            phase=0,
            priority=15,
        )
    ]


BIOMETRIC_STATE_RULE = Rule(
    name="biometric-state-change",
    description="Update Stimmung biometric dimensions on watch state file changes",
    trigger_filter=_biometric_state_filter,
    produce=_biometric_state_produce,
    phase=0,
    cooldown_s=30,
)


# ── Phone health summary ────────────────────────────────────────────────────


async def _handle_phone_health_summary(*, path: str) -> str:
    from pathlib import Path as _Path

    _log.info("Phone health summary received: %s", path)

    # Wire profiler bridge: extract health facts and push to profile store
    try:
        from agents.profiler_sources import read_phone_health_summary

        facts = read_phone_health_summary(_Path(path).parent)
        hapax_event(
            "biometric",
            "health_summary_received",
            metadata={"path": path, "facts": len(facts)},
        )
    except (ImportError, OSError):
        hapax_event("biometric", "health_summary_received", metadata={"path": path})

    return f"phone-health:{path}"


def _phone_health_filter(event: ChangeEvent) -> bool:
    return event.path.name == "phone_health_summary.json" and "watch" in event.path.parts


def _phone_health_produce(event: ChangeEvent) -> list[Action]:
    return [
        Action(
            name="phone-health-summary",
            handler=_handle_phone_health_summary,
            args={"path": str(event.path)},
            phase=0,
            priority=20,
        )
    ]


PHONE_HEALTH_SUMMARY_RULE = Rule(
    name="phone-health-summary",
    description="Extract health facts from phone summary and emit telemetry",
    trigger_filter=_phone_health_filter,
    produce=_phone_health_produce,
    phase=0,
    cooldown_s=3600,
)

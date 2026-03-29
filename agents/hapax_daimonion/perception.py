"""Unified perception layer for the Hapax Daimonion daemon.

Fuses audio and visual signals into a single EnvironmentState snapshot
every fast tick (2-3s). Slow enrichment (10-15s) adds LLM workspace
analysis.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from agents.hapax_daimonion.primitives import Behavior
from shared.impingement import Impingement, ImpingementType

if TYPE_CHECKING:
    from shared.hyprland import WindowInfo

log = logging.getLogger(__name__)


class PerceptionTier(Enum):
    """Processing tier for a perception backend."""

    FAST = "fast"  # <10ms, every fast tick
    SLOW = "slow"  # >100ms or I/O, every slow tick
    EVENT = "event"  # async event-driven (e.g., Hyprland IPC)


@runtime_checkable
class PerceptionBackend(Protocol):
    """Interface for pluggable perception backends.

    Each backend provides a set of named Behaviors and declares its tier.
    Backends are registered on PerceptionEngine; conflicts on `provides`
    names are rejected at registration time.
    """

    @property
    def name(self) -> str:
        """Unique backend identifier."""
        ...

    @property
    def provides(self) -> frozenset[str]:
        """Set of Behavior names this backend contributes."""
        ...

    @property
    def tier(self) -> PerceptionTier:
        """Processing tier (fast/slow/event)."""
        ...

    def available(self) -> bool:
        """Return True if the backend's dependencies are met at runtime."""
        ...

    def contribute(self, behaviors: dict[str, Behavior]) -> None:
        """Update the given behaviors dict with fresh readings."""
        ...

    def start(self) -> None:
        """Lifecycle hook: called when the engine starts."""
        ...

    def stop(self) -> None:
        """Lifecycle hook: called when the engine stops."""
        ...


def compute_interruptibility(
    *,
    vad_confidence: float,
    activity_mode: str,
    in_voice_session: bool,
    operator_present: bool,
    phone_call_active: bool = False,
    phone_call_incoming: bool = False,
    phone_media_playing: bool = False,
    window_count: int = 0,
    physiological_load: float = 0.0,
    circadian_alignment: float = 0.1,
    system_health_ratio: float = 1.0,
    gaze_direction: str = "unknown",
    emotion: str = "neutral",
    posture: str = "unknown",
    ir_drowsiness_score: float = 0.0,
) -> float:
    """Compute an interruptibility score from perception signals.

    Returns a float in [0.0, 1.0] where 1.0 = fully interruptible.
    """
    if not operator_present:
        return 0.0
    if in_voice_session:
        return 0.1

    score = 1.0

    # Active phone call — hard veto on interruptibility
    if phone_call_active:
        return 0.05
    # Incoming call — nearly uninterruptible (ringing)
    if phone_call_incoming:
        return 0.1

    # Active speech reduces interruptibility
    if vad_confidence > 0.5:
        score -= 0.4 * vad_confidence

    # Production activity reduces interruptibility
    activity_penalties = {"production": 0.5, "meeting": 0.6, "coding": 0.3}
    score -= activity_penalties.get(activity_mode, 0.0)

    # Phone media playing — mild reduction
    if phone_media_playing:
        score -= 0.15

    # Many open windows = deep multitasking context
    if window_count > 8:
        score -= 0.2

    # Physiological load (0.0=resting, 1.0=max stress → -0.3)
    score -= 0.3 * physiological_load

    # Circadian alignment (0.1=peak→+0, 0.5=neutral→-0.2, 0.8=non-prod→-0.35)
    score -= 0.5 * max(0.0, circadian_alignment - 0.1)

    # System health (1.0=healthy→+0, 0.5=degraded→-0.25)
    if system_health_ratio < 1.0:
        score -= 0.5 * (1.0 - system_health_ratio)

    # Classification consumption: gaze/emotion/posture enrichments
    if gaze_direction == "away":
        score -= 0.25  # looking elsewhere = occupied
    if emotion in ("angry", "fear", "disgust"):
        score -= 0.2  # stressed = don't interrupt
    if posture == "slouching":
        score -= 0.1  # low energy = gentler

    # IR drowsiness — don't interrupt drowsy operator with low-priority items
    if ir_drowsiness_score > 0.6:
        score -= 0.2

    return max(0.0, min(1.0, score))


@dataclass(frozen=True)
class EnvironmentState:
    """Immutable snapshot of the fused audio-visual environment.

    Produced by PerceptionEngine every fast tick. Slow-tick fields
    (activity_mode, workspace_context) are carried forward from the
    last slow enrichment.
    """

    timestamp: float

    # Audio signals (fast tick)
    speech_detected: bool = False
    vad_confidence: float = 0.0

    # Visual signals (fast tick)
    face_count: int = 0
    guest_count: int = 0
    operator_present: bool = False

    # Presence (fast tick, from PresenceDetector or Bayesian engine)
    presence_score: str = "likely_absent"
    presence_state: str | None = None  # Bayesian: "PRESENT", "UNCERTAIN", "AWAY"
    presence_probability: float | None = None  # Bayesian posterior

    # Enriched signals (slow tick, carried forward)
    activity_mode: str = "unknown"
    workspace_context: str = ""

    # Phone state (Bluetooth)
    phone_call_active: bool = False
    phone_call_incoming: bool = False
    phone_media_playing: bool = False
    phone_battery_pct: int = 100
    phone_notification_count: int = 0
    phone_media_app: str = ""

    # Desktop topology (updated by HyprlandEventListener)
    active_window: WindowInfo | None = None
    window_count: int = 0
    active_workspace_id: int = 0

    # Voice session state
    in_voice_session: bool = False
    interruptibility_score: float = 1.0

    # Consent state (set by ConsentStateTracker after creation)
    consent_phase: str = "no_guest"

    # Directive (set by Governor after creation)
    directive: str = "process"

    @property
    def conversation_detected(self) -> bool:
        """True when non-operator person(s) present AND speech detected."""
        return self.guest_count > 0 and self.speech_detected


class PerceptionEngine:
    """Produces EnvironmentState snapshots by fusing sensor signals.

    Fast tick (called every ~2.5s): reads VAD, face detection, presence.
    Slow enrichment (called every ~12s): runs workspace analysis.
    Slow fields are carried forward between slow ticks.

    The engine does not own its own async loop — the daemon calls tick()
    on the fast cadence and slow_tick() on the slow cadence.
    """

    def __init__(
        self,
        presence,
        workspace_monitor,
        vad_speech_threshold: float = 0.5,
    ) -> None:
        self._presence = presence
        self._workspace_monitor = workspace_monitor
        self._vad_speech_threshold = vad_speech_threshold

        # Slow-tick Behaviors (replacing plain fields)
        self._b_activity_mode: Behavior[str] = Behavior("unknown")
        self._b_workspace_context: Behavior[str] = Behavior("")

        # Desktop Behaviors (replacing plain fields)
        self._b_active_window: Behavior[WindowInfo | None] = Behavior(None)
        self._b_window_count: Behavior[int] = Behavior(0)
        self._b_active_workspace_id: Behavior[int] = Behavior(0)

        # Fast-tick Behaviors (new — updated each tick from sensors)
        self._b_vad_confidence: Behavior[float] = Behavior(0.0)
        self._b_operator_present: Behavior[bool] = Behavior(False)
        self._b_face_count: Behavior[int] = Behavior(0)
        self._b_operator_visible: Behavior[bool] = Behavior(False)
        self._b_face_detected: Behavior[bool] = Behavior(False)
        self._b_guest_count: Behavior[int] = Behavior(0)

        # Phase 2 extension point: all behaviors by name
        self.behaviors: dict[str, Behavior] = {
            "activity_mode": self._b_activity_mode,
            "workspace_context": self._b_workspace_context,
            "active_window": self._b_active_window,
            "window_count": self._b_window_count,
            "active_workspace_id": self._b_active_workspace_id,
            "vad_confidence": self._b_vad_confidence,
            "operator_present": self._b_operator_present,
            "face_count": self._b_face_count,
            "operator_visible": self._b_operator_visible,
            "face_detected": self._b_face_detected,
            "guest_count": self._b_guest_count,
        }

        # Impingement drain (R3) — accumulates impingements for daemon consumption
        self._prev_behavior_values: dict[str, float] = {}
        self._pending_impingements: list[Impingement] = []

        # Voice session flag (set by daemon each tick)
        self._in_voice_session: bool = False

        # Backend registry
        self._backends: dict[str, PerceptionBackend] = {}
        self._provided_by: dict[str, str] = {}  # behavior_name → backend_name

        # Subscribers
        self._subscribers: list[Callable[[EnvironmentState], None]] = []

        # Latest state
        self.latest: EnvironmentState | None = None

    def _fval(self, name: str, default: float = 0.0) -> float:
        """Read a float Behavior value."""
        b = self.behaviors.get(name)
        return float(b.value) if b is not None else default

    def _sval(self, name: str, default: str = "") -> str:
        """Read a string Behavior value."""
        b = self.behaviors.get(name)
        return str(b.value) if b is not None else default

    def _boolval(self, name: str, default: bool = False) -> bool:
        """Read a boolean Behavior value."""
        b = self.behaviors.get(name)
        return bool(b.value) if b is not None else default

    def _optval(self, name: str) -> object | None:
        """Read an optional Behavior value (may be None)."""
        b = self.behaviors.get(name)
        return b.value if b is not None else None

    def subscribe(self, callback: Callable[[EnvironmentState], None]) -> None:
        """Register a callback for each new EnvironmentState."""
        self._subscribers.append(callback)

    def set_voice_session_active(self, active: bool) -> None:
        """Update voice session flag. Called by daemon before each tick."""
        self._in_voice_session = active

    def drain_impingements(self) -> list[Impingement]:
        """Drain pending impingements (called by daemon to write to JSONL)."""
        result = self._pending_impingements
        self._pending_impingements = []
        return result

    def _check_behavior_changes(self, behaviors: dict[str, Behavior]) -> None:
        """Check for significant behavior changes and emit impingements."""
        for name, behavior in behaviors.items():
            val = behavior.value
            if not isinstance(val, (int, float)):
                continue
            prev = self._prev_behavior_values.get(name, 0.0)
            delta = abs(float(val) - float(prev))
            if delta > 0.15:
                self._prev_behavior_values[name] = float(val)
                self._pending_impingements.append(
                    Impingement(
                        timestamp=time.time(),
                        source=f"perception.{name}",
                        type=ImpingementType.STATISTICAL_DEVIATION,
                        strength=min(1.0, delta),
                        content={
                            "metric": name,
                            "value": float(val),
                            "previous": float(prev),
                            "delta": round(delta, 3),
                        },
                    )
                )

    def register_backend(self, backend: PerceptionBackend) -> None:
        """Register a perception backend. Raises ValueError on name or provides conflicts."""
        if backend.name in self._backends:
            raise ValueError(f"Backend already registered: {backend.name}")
        conflicts = backend.provides & frozenset(self._provided_by)
        if conflicts:
            owners = {name: self._provided_by[name] for name in conflicts}
            raise ValueError(f"Behavior name conflicts: {owners}")
        if not backend.available():
            log.warning("Backend %s not available, skipping registration", backend.name)
            return
        self._backends[backend.name] = backend
        for name in backend.provides:
            self._provided_by[name] = backend.name
        backend.start()
        log.info("Registered perception backend: %s (provides: %s)", backend.name, backend.provides)

    def replace_backend(self, backend: PerceptionBackend) -> None:
        """Replace a backend by name. New backend must be available."""
        if not backend.available():
            log.warning("Replacement backend %s unavailable, keeping current", backend.name)
            return
        old = self._backends.pop(backend.name, None)
        if old is not None:
            old.stop()
            for name in old.provides:
                self._provided_by.pop(name, None)
        self.register_backend(backend)

    @property
    def registered_backends(self) -> dict[str, PerceptionBackend]:
        """Return a copy of registered backends."""
        return dict(self._backends)

    def tick(self) -> EnvironmentState:
        """Produce a fast-tick EnvironmentState from current sensor readings.

        Reads from presence detector (VAD + face), polls registered backends,
        and carries forward slow-tick enrichment fields.
        """
        now = time.monotonic()
        vad_conf = getattr(self._presence, "latest_vad_confidence", 0.0)
        face_detected = getattr(self._presence, "face_detected", False)
        face_count = getattr(self._presence, "face_count", 0)
        operator_visible = getattr(self._presence, "operator_visible", False)

        # Update fast-tick Behaviors
        self._b_vad_confidence.update(vad_conf, now)
        self._b_operator_present.update(face_detected, now)
        self._b_face_count.update(face_count, now)
        self._b_operator_visible.update(operator_visible, now)
        self._b_face_detected.update(face_detected, now)
        self._b_guest_count.update(getattr(self._presence, "guest_count", 0), now)

        # Poll registered backends — each gets a view scoped to its declared provides
        # (D5.2: prevents backends from writing to behaviors they don't own)
        # Fusion backends (presence_engine) run last and receive full behaviors dict.
        fusion_backends = []
        for name, backend in self._backends.items():
            if name == "presence_engine":
                fusion_backends.append((name, backend))
                continue
            try:
                scoped = {k: self.behaviors[k] for k in backend.provides if k in self.behaviors}
                backend.contribute(scoped)
                # Sync back any new behaviors created within provides scope
                for k in backend.provides:
                    if k in scoped and k not in self.behaviors:
                        self.behaviors[k] = scoped[k]
            except Exception:
                log.exception("Backend %s contribute failed", name)

        # Fusion backends run after all others, reading from full behaviors dict
        for name, backend in fusion_backends:
            try:
                backend.contribute(self.behaviors)
            except Exception:
                log.exception("Backend %s contribute failed", name)

        interruptibility = compute_interruptibility(
            vad_confidence=self._b_vad_confidence.value,
            activity_mode=self._b_activity_mode.value,
            phone_call_active=self._boolval("phone_call_active"),
            phone_call_incoming=self._boolval("phone_call_incoming"),
            phone_media_playing=self._boolval("phone_media_playing"),
            in_voice_session=self._in_voice_session,
            operator_present=self._b_operator_present.value,
            window_count=self._b_window_count.value,
            physiological_load=self._fval("physiological_load", 0.0),
            circadian_alignment=self._fval("circadian_alignment", 0.1),
            system_health_ratio=self._fval("system_health_ratio", 1.0),
            gaze_direction=self._sval("gaze_direction", "unknown"),
            emotion=self._sval("top_emotion", "neutral"),
            posture=self._sval("posture", "unknown"),
            ir_drowsiness_score=self._fval("ir_drowsiness_score", 0.0),
        )

        presence_score = getattr(self._presence, "score", "likely_absent")

        # Bayesian presence engine outputs (if registered)
        bayesian_state = self._optval("presence_state")
        bayesian_prob = self._optval("presence_probability")

        # Deduplicated guest count from fused face detection
        guest_count = getattr(self._presence, "guest_count", 0)

        # Derive operator_present from Bayesian state when available
        operator_present = self._b_operator_present.value
        if bayesian_state is not None:
            operator_present = bayesian_state in ("PRESENT", "UNCERTAIN")

        state = EnvironmentState(
            timestamp=now,
            speech_detected=vad_conf >= self._vad_speech_threshold,
            vad_confidence=self._b_vad_confidence.value,
            face_count=self._b_face_count.value,
            guest_count=guest_count,
            operator_present=operator_present,
            presence_score=presence_score,
            presence_state=bayesian_state,
            presence_probability=bayesian_prob,
            activity_mode=self._b_activity_mode.value,
            phone_call_active=self._boolval("phone_call_active"),
            phone_call_incoming=self._boolval("phone_call_incoming"),
            phone_media_playing=self._boolval("phone_media_playing"),
            phone_battery_pct=int(self._fval("phone_battery_pct", 100)),
            phone_notification_count=int(self._fval("phone_notification_count", 0)),
            phone_media_app=self._sval("phone_media_app", ""),
            workspace_context=self._b_workspace_context.value,
            active_window=self._b_active_window.value,
            window_count=self._b_window_count.value,
            active_workspace_id=self._b_active_workspace_id.value,
            in_voice_session=self._in_voice_session,
            interruptibility_score=interruptibility,
        )

        # Emit impingements for significant behavior changes
        self._check_behavior_changes(self.behaviors)

        self.latest = state

        for cb in self._subscribers:
            try:
                cb(state)
            except Exception:
                log.exception("Perception subscriber error")

        return state

    @property
    def min_watermark(self) -> float:
        """Minimum watermark across all behaviors — staleness of the least-fresh signal."""
        return min(b.watermark for b in self.behaviors.values())

    def update_desktop_state(
        self,
        active_window: WindowInfo | None = None,
        window_count: int = 0,
        active_workspace_id: int = 0,
    ) -> None:
        """Update desktop topology from HyprlandEventListener."""
        now = time.monotonic()
        self._b_active_window.update(active_window, now)
        self._b_window_count.update(window_count, now)
        self._b_active_workspace_id.update(active_workspace_id, now)

    def update_slow_fields(
        self,
        activity_mode: str | None = None,
        workspace_context: str | None = None,
    ) -> None:
        """Update carried-forward fields from slow-tick enrichment."""
        now = time.monotonic()
        if activity_mode is not None:
            self._b_activity_mode.update(activity_mode, now)
        if workspace_context is not None:
            self._b_workspace_context.update(workspace_context, now)

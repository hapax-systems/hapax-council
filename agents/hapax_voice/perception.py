"""Unified perception layer for the Hapax Voice daemon.

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

from agents.hapax_voice.primitives import Behavior

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
    window_count: int = 0,
    physiological_load: float = 0.0,
    circadian_alignment: float = 0.1,
    system_health_ratio: float = 1.0,
) -> float:
    """Compute an interruptibility score from perception signals.

    Returns a float in [0.0, 1.0] where 1.0 = fully interruptible.
    """
    if not operator_present:
        return 0.0
    if in_voice_session:
        return 0.1

    score = 1.0

    # Active speech reduces interruptibility
    if vad_confidence > 0.5:
        score -= 0.4 * vad_confidence

    # Production activity reduces interruptibility
    activity_penalties = {"production": 0.5, "meeting": 0.6, "coding": 0.3}
    score -= activity_penalties.get(activity_mode, 0.0)

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
    operator_present: bool = False

    # Presence (fast tick, from PresenceDetector)
    presence_score: str = "likely_absent"

    # Enriched signals (slow tick, carried forward)
    activity_mode: str = "unknown"
    workspace_context: str = ""

    # Desktop topology (updated by HyprlandEventListener)
    active_window: WindowInfo | None = None
    window_count: int = 0
    active_workspace_id: int = 0

    # Voice session state
    in_voice_session: bool = False
    interruptibility_score: float = 1.0

    # Directive (set by Governor after creation)
    directive: str = "process"

    @property
    def conversation_detected(self) -> bool:
        """True when multiple faces AND speech detected."""
        return self.face_count > 1 and self.speech_detected


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
        }

        # Voice session flag (set by daemon each tick)
        self._in_voice_session: bool = False

        # Backend registry
        self._backends: dict[str, PerceptionBackend] = {}
        self._provided_by: dict[str, str] = {}  # behavior_name → backend_name

        # Subscribers
        self._subscribers: list[Callable[[EnvironmentState], None]] = []

        # Latest state
        self.latest: EnvironmentState | None = None

    def _bval(self, name: str, default: float) -> float:
        """Read an optional Behavior value with a safe default."""
        b = self.behaviors.get(name)
        return b.value if b is not None else default

    def subscribe(self, callback: Callable[[EnvironmentState], None]) -> None:
        """Register a callback for each new EnvironmentState."""
        self._subscribers.append(callback)

    def set_voice_session_active(self, active: bool) -> None:
        """Update voice session flag. Called by daemon before each tick."""
        self._in_voice_session = active

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

        # Update fast-tick Behaviors
        self._b_vad_confidence.update(vad_conf, now)
        self._b_operator_present.update(face_detected, now)
        self._b_face_count.update(face_count, now)

        # Poll registered backends — each gets a view scoped to its declared provides
        # (D5.2: prevents backends from writing to behaviors they don't own)
        for name, backend in self._backends.items():
            try:
                scoped = {k: self.behaviors[k] for k in backend.provides if k in self.behaviors}
                backend.contribute(scoped)
                # Sync back any new behaviors created within provides scope
                for k in backend.provides:
                    if k in scoped and k not in self.behaviors:
                        self.behaviors[k] = scoped[k]
            except Exception:
                log.exception("Backend %s contribute failed", name)

        interruptibility = compute_interruptibility(
            vad_confidence=self._b_vad_confidence.value,
            activity_mode=self._b_activity_mode.value,
            in_voice_session=self._in_voice_session,
            operator_present=self._b_operator_present.value,
            window_count=self._b_window_count.value,
            physiological_load=self._bval("physiological_load", 0.0),
            circadian_alignment=self._bval("circadian_alignment", 0.1),
            system_health_ratio=self._bval("system_health_ratio", 1.0),
        )

        presence_score = getattr(self._presence, "score", "likely_absent")

        state = EnvironmentState(
            timestamp=now,
            speech_detected=vad_conf >= self._vad_speech_threshold,
            vad_confidence=self._b_vad_confidence.value,
            face_count=self._b_face_count.value,
            operator_present=self._b_operator_present.value,
            presence_score=presence_score,
            activity_mode=self._b_activity_mode.value,
            workspace_context=self._b_workspace_context.value,
            active_window=self._b_active_window.value,
            window_count=self._b_window_count.value,
            active_workspace_id=self._b_active_workspace_id.value,
            in_voice_session=self._in_voice_session,
            interruptibility_score=interruptibility,
        )

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

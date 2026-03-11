"""Unified perception layer for the Hapax Voice daemon.

Fuses audio and visual signals into a single EnvironmentState snapshot
every fast tick (2-3s). Slow enrichment (10-15s) adds LLM workspace
analysis and PANNs ambient classification.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shared.hyprland import WindowInfo

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class EnvironmentState:
    """Immutable snapshot of the fused audio-visual environment.

    Produced by PerceptionEngine every fast tick. Slow-tick fields
    (activity_mode, workspace_context, ambient_detailed) are carried
    forward from the last slow enrichment.
    """

    timestamp: float

    # Audio signals (fast tick)
    speech_detected: bool = False
    speech_volume_db: float = -60.0
    ambient_class: str = "silence"
    vad_confidence: float = 0.0

    # Visual signals (fast tick)
    face_count: int = 0
    operator_present: bool = False
    gaze_at_camera: bool = False

    # Enriched signals (slow tick, carried forward)
    activity_mode: str = "unknown"
    workspace_context: str = ""
    ambient_detailed: str = ""

    # Desktop topology (updated by HyprlandEventListener)
    active_window: WindowInfo | None = None
    window_count: int = 0
    active_workspace_id: int = 0

    # Directive (set by Governor after creation)
    directive: str = "process"

    @property
    def conversation_detected(self) -> bool:
        """True when multiple faces AND speech detected."""
        return self.face_count > 1 and self.speech_detected


class PerceptionEngine:
    """Produces EnvironmentState snapshots by fusing sensor signals.

    Fast tick (called every ~2.5s): reads VAD, face detection, gaze.
    Slow enrichment (called every ~12s): runs PANNs, workspace analysis.
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

        # Desktop state (updated by HyprlandEventListener)
        self._desktop_active_window: WindowInfo | None = None
        self._desktop_window_count: int = 0
        self._desktop_active_workspace_id: int = 0

        # Slow-tick carried-forward fields
        self._slow_activity_mode: str = "unknown"
        self._slow_workspace_context: str = ""
        self._slow_ambient_detailed: str = ""
        self._slow_ambient_class: str = "silence"

        # Subscribers
        self._subscribers: list[Callable[[EnvironmentState], None]] = []

        # Latest state
        self.latest: EnvironmentState | None = None

    def subscribe(self, callback: Callable[[EnvironmentState], None]) -> None:
        """Register a callback for each new EnvironmentState."""
        self._subscribers.append(callback)

    def tick(self) -> EnvironmentState:
        """Produce a fast-tick EnvironmentState from current sensor readings.

        Reads from presence detector (VAD + face) and carries forward
        slow-tick enrichment fields.
        """
        vad_conf = getattr(self._presence, "latest_vad_confidence", 0.0)
        face_detected = getattr(self._presence, "face_detected", False)
        face_count = getattr(self._presence, "face_count", 0)

        state = EnvironmentState(
            timestamp=time.monotonic(),
            speech_detected=vad_conf >= self._vad_speech_threshold,
            vad_confidence=vad_conf,
            ambient_class=self._slow_ambient_class,
            face_count=face_count,
            operator_present=face_detected,
            gaze_at_camera=False,  # b-path: proper gaze model
            activity_mode=self._slow_activity_mode,
            workspace_context=self._slow_workspace_context,
            ambient_detailed=self._slow_ambient_detailed,
            active_window=self._desktop_active_window,
            window_count=self._desktop_window_count,
            active_workspace_id=self._desktop_active_workspace_id,
        )

        self.latest = state

        for cb in self._subscribers:
            try:
                cb(state)
            except Exception:
                log.exception("Perception subscriber error")

        return state

    def update_desktop_state(
        self,
        active_window: WindowInfo | None = None,
        window_count: int = 0,
        active_workspace_id: int = 0,
    ) -> None:
        """Update desktop topology from HyprlandEventListener."""
        self._desktop_active_window = active_window
        self._desktop_window_count = window_count
        self._desktop_active_workspace_id = active_workspace_id

    def update_slow_fields(
        self,
        activity_mode: str | None = None,
        workspace_context: str | None = None,
        ambient_class: str | None = None,
        ambient_detailed: str | None = None,
    ) -> None:
        """Update carried-forward fields from slow-tick enrichment."""
        if activity_mode is not None:
            self._slow_activity_mode = activity_mode
        if workspace_context is not None:
            self._slow_workspace_context = workspace_context
        if ambient_class is not None:
            self._slow_ambient_class = ambient_class
        if ambient_detailed is not None:
            self._slow_ambient_detailed = ambient_detailed

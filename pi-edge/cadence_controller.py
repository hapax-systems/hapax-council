"""cadence_controller.py — Activity-gated cadence for Pi NoIR edge daemon.

Issue #143. Replaces a fixed ~3s post cadence with an activity-aware state
machine. Cadence state is driven by recent detections (person/hand/motion
triggers registered via ``record_activity``); higher activity raises the tick
rate, quiescent periods drop it.

States:
    QUIESCENT  — no detections in ``quiescent_window_s`` → ``quiescent_interval_s`` sleep
    IDLE       — occasional detections → ``idle_interval_s`` sleep (old default)
    ACTIVE     — detection within ``active_window_s`` → ``active_interval_s`` sleep
    HOT        — rapid detections (``hot_min_events`` in ``hot_window_s``) + motion
                 → ``hot_interval_s`` sleep

Hysteresis: once ACTIVE/HOT, remain for at least ``hysteresis_s`` after the
last triggering event to prevent oscillation at detection boundaries.

Config is optionally loaded from ``~/hapax-edge/cadence-config.yaml`` so the
operator can tune thresholds in place. Missing/invalid config silently falls
back to the defaults in :class:`CadenceConfig` — the Pi must keep running.

Dependency discipline: pure-Python, stdlib + ``collections.deque``. No numpy,
no pydantic — this runs on Raspberry Pi 4 alongside CV inference and the
footprint matters.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

log = logging.getLogger(__name__)

CadenceState = Literal["QUIESCENT", "IDLE", "ACTIVE", "HOT"]

ALL_STATES: tuple[CadenceState, ...] = ("QUIESCENT", "IDLE", "ACTIVE", "HOT")

DEFAULT_CONFIG_PATH = Path.home() / "hapax-edge" / "cadence-config.yaml"


@dataclass
class CadenceConfig:
    """Tunable parameters for the cadence state machine.

    All intervals are in seconds.
    """

    quiescent_interval_s: float = 10.0
    idle_interval_s: float = 3.0
    active_interval_s: float = 1.0
    hot_interval_s: float = 0.5

    # No detections within this window → drop from IDLE to QUIESCENT.
    quiescent_window_s: float = 60.0
    # Any detection within this window → climb to (at least) ACTIVE.
    active_window_s: float = 5.0
    # Counting window + threshold + motion gate for HOT.
    hot_window_s: float = 3.0
    hot_min_events: int = 4
    hot_motion_threshold: float = 0.05

    # Once ACTIVE/HOT, remain for at least this long after the last event.
    hysteresis_s: float = 3.0

    # Hard bounds on the event deque size (prevents unbounded growth).
    event_buffer: int = 64


@dataclass
class CadenceController:
    """Gates the Pi daemon's capture/post cadence on observed activity."""

    config: CadenceConfig = field(default_factory=CadenceConfig)
    state: CadenceState = "IDLE"

    _events: deque[float] = field(init=False)
    _last_event_ts: float | None = field(init=False, default=None)
    _last_motion: float = field(init=False, default=0.0)
    _last_transition_ts: float = field(init=False, default=0.0)
    _start_ts: float | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        self._events = deque(maxlen=max(8, self.config.event_buffer))
        # ``_start_ts`` anchors "how long has the controller observed silence?"
        # It is lazy-initialized on the first ``record_activity``/``evaluate``
        # call so callers passing synthetic ``now`` (tests) get intuitive
        # semantics: (now - start_ts) == (now - first_ever_observation_ts).

    # ------------------------------------------------------------------
    # Activity feed
    # ------------------------------------------------------------------
    def record_activity(
        self,
        *,
        persons: int = 0,
        hands: int = 0,
        motion_delta: float = 0.0,
        now: float | None = None,
    ) -> None:
        """Feed a detection tick. Any non-zero signal counts as an event."""
        ts = time.monotonic() if now is None else now
        self._last_motion = float(motion_delta)
        if persons > 0 or hands > 0 or motion_delta >= self.config.hot_motion_threshold:
            self._events.append(ts)
            self._last_event_ts = ts

    # ------------------------------------------------------------------
    # State resolution
    # ------------------------------------------------------------------
    def evaluate(self, now: float | None = None) -> CadenceState:
        """Resolve the current state. Idempotent apart from transition logging."""
        ts = time.monotonic() if now is None else now
        prev = self.state
        target = self._target_state(ts)

        in_hysteresis = prev in ("ACTIVE", "HOT") and self._last_event_ts is not None
        if in_hysteresis and (ts - (self._last_event_ts or 0.0)) < self.config.hysteresis_s:
            # Hold the floor at ACTIVE — allow HOT↔ACTIVE but don't fall to IDLE/QUIESCENT yet.
            if target in ("QUIESCENT", "IDLE"):
                target = "ACTIVE"

        if target != prev:
            log.info("cadence transition %s → %s", prev, target)
            self._last_transition_ts = ts
            self.state = target
        return self.state

    def _target_state(self, ts: float) -> CadenceState:
        cfg = self.config
        # Trim events outside the longest window we care about.
        horizon = max(cfg.quiescent_window_s, cfg.active_window_s, cfg.hot_window_s)
        while self._events and ts - self._events[0] > horizon:
            self._events.popleft()

        recent_hot = sum(1 for e in self._events if ts - e <= cfg.hot_window_s)
        if recent_hot >= cfg.hot_min_events and self._last_motion >= cfg.hot_motion_threshold:
            return "HOT"

        recent_active = any(ts - e <= cfg.active_window_s for e in self._events)
        if recent_active:
            return "ACTIVE"

        # Silence window vs. last event. First-ever evaluate with no events
        # seeds ``_start_ts`` so subsequent evaluates can measure "how long
        # have we been silent since the controller was created?".  The default
        # state stays IDLE on the very first tick (``_start_ts is None``).
        if self._last_event_ts is not None:
            if ts - self._last_event_ts > cfg.quiescent_window_s:
                return "QUIESCENT"
            return "IDLE"

        if self._start_ts is None:
            self._start_ts = ts
            return "IDLE"

        if ts - self._start_ts > cfg.quiescent_window_s:
            return "QUIESCENT"
        return "IDLE"

    # ------------------------------------------------------------------
    # Consumers
    # ------------------------------------------------------------------
    def get_sleep_duration(self, now: float | None = None) -> float:
        """Sleep duration the daemon's main loop should honor."""
        state = self.evaluate(now=now)
        cfg = self.config
        return {
            "QUIESCENT": cfg.quiescent_interval_s,
            "IDLE": cfg.idle_interval_s,
            "ACTIVE": cfg.active_interval_s,
            "HOT": cfg.hot_interval_s,
        }[state]

    def snapshot(self) -> dict[str, object]:
        """Compact JSON-safe snapshot for heartbeat/IR report payloads."""
        return {
            "state": self.state,
            "last_event_age_s": (
                round(time.monotonic() - self._last_event_ts, 3)
                if self._last_event_ts is not None
                else None
            ),
            "recent_events": len(self._events),
            "interval_s": self.get_sleep_duration(),
        }


# ----------------------------------------------------------------------
# Config loading
# ----------------------------------------------------------------------
def load_config(path: Path | None = None) -> CadenceConfig:
    """Load ``CadenceConfig`` from YAML. Returns defaults on any failure.

    We parse a tiny subset of YAML (``key: value`` lines, ``#`` comments) so the
    Pi does not need ``pyyaml`` just for this. Unknown keys are ignored.
    """
    p = path or DEFAULT_CONFIG_PATH
    cfg = CadenceConfig()
    try:
        text = p.read_text()
    except (OSError, FileNotFoundError):
        return cfg

    overrides: dict[str, float | int] = {}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not value:
            continue
        try:
            overrides[key] = float(value) if "." in value else int(value)
        except ValueError:
            log.warning("cadence-config: invalid value for %s: %r", key, value)

    for key, value in overrides.items():
        if hasattr(cfg, key):
            current = getattr(cfg, key)
            setattr(cfg, key, type(current)(value))
        else:
            log.debug("cadence-config: unknown key %s (ignored)", key)
    return cfg

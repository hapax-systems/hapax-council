"""Interview unknowns ward — displays remaining gaps and open questions.

Reads from /dev/shm/hapax-compositor/interview-unknowns.json, which
the interview agent updates after each topic exploration.

CASE-INTERVIEW-SEGMENT-SYSTEM-20260518 Task N1.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path

from agents.studio_compositor.homage.transitional_source import HomageTransitionalSource

log = logging.getLogger(__name__)

UNKNOWNS_STATE_FILE = Path("/dev/shm/hapax-compositor/interview-unknowns.json")
_POLL_INTERVAL_S: float = 1.0
_ENTER_RAMP_S: float = 0.5
_EXIT_RAMP_S: float = 0.6


@dataclass(frozen=True)
class InterviewUnknownsState:
    active: bool = False
    remaining_topics: tuple[str, ...] = ()
    sparse_dimensions: tuple[str, ...] = ()
    low_confidence_keys: tuple[str, ...] = ()
    goal_gaps: tuple[str, ...] = ()


_EMPTY_STATE = InterviewUnknownsState()


def _read_unknowns_state(path: Path) -> InterviewUnknownsState:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return InterviewUnknownsState(
            active=data.get("active", False),
            remaining_topics=tuple(data.get("remaining_topics", [])),
            sparse_dimensions=tuple(data.get("sparse_dimensions", [])),
            low_confidence_keys=tuple(data.get("low_confidence_keys", [])),
            goal_gaps=tuple(data.get("goal_gaps", [])),
        )
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return _EMPTY_STATE


class InterviewUnknownsWard(HomageTransitionalSource):
    """Displays remaining knowledge gaps and unexplored topics."""

    def __init__(
        self,
        *,
        state_file: Path = UNKNOWNS_STATE_FILE,
        start_thread: bool = True,
    ) -> None:
        HomageTransitionalSource.__init__(
            self,
            source_id="interview-unknowns-card",
            entering_duration_s=_ENTER_RAMP_S,
            exiting_duration_s=_EXIT_RAMP_S,
        )
        self._state_file = state_file
        self._state: InterviewUnknownsState = _EMPTY_STATE
        self._state_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._poll_thread: threading.Thread | None = None

        if start_thread:
            self._poll_thread = threading.Thread(
                target=self._poll_loop,
                name="interview-unknowns-poll",
                daemon=True,
            )
            self._poll_thread.start()

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._poll_once()
            except Exception as exc:
                log.warning("interview-unknowns: poll failed: %s", exc, exc_info=True)
            self._stop_event.wait(_POLL_INTERVAL_S)

    def _poll_once(self) -> InterviewUnknownsState:
        state = _read_unknowns_state(self._state_file)
        with self._state_lock:
            prev_active = self._state.active
            self._state = state
            if state.active and not prev_active:
                self.request_enter()
            elif not state.active and prev_active:
                self.request_exit()
        return state

    def stop(self) -> None:
        self._stop_event.set()
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=3.0)

    @property
    def current_state(self) -> InterviewUnknownsState:
        with self._state_lock:
            return self._state

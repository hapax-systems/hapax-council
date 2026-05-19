"""Interview delta ward -- displays knowledge-model changes after each operator answer.

Reads from /dev/shm/hapax-compositor/interview-delta.json, which the
interview agent writes after processing each operator answer.  Shows
new facts, contradictions, and follow-up suggestions.  Fades in when
the delta becomes active, fades out when cleared.

CASE-INTERVIEW-SEGMENT-SYSTEM-20260518 Task I2.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path

from agents.studio_compositor.homage_transitional_source import HomageTransitionalSource

log = logging.getLogger(__name__)

INTERVIEW_DELTA_FILE = Path("/dev/shm/hapax-compositor/interview-delta.json")
_POLL_INTERVAL_S: float = 1.0
_ENTER_RAMP_S: float = 0.5
_EXIT_RAMP_S: float = 0.6


@dataclass(frozen=True)
class InterviewDeltaState:
    active: bool = False
    new_facts: tuple[str, ...] = ()
    contradictions: tuple[str, ...] = ()
    follow_ups: tuple[str, ...] = ()


_EMPTY_STATE = InterviewDeltaState()


def _read_interview_delta(path: Path) -> InterviewDeltaState:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return InterviewDeltaState(
            active=data.get("active", False),
            new_facts=tuple(data.get("new_facts", [])),
            contradictions=tuple(data.get("contradictions", [])),
            follow_ups=tuple(data.get("follow_ups", [])),
        )
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return _EMPTY_STATE


class InterviewDeltaWard(HomageTransitionalSource):
    """Displays knowledge-model deltas: new facts, contradictions, follow-ups."""

    def __init__(
        self,
        *,
        state_file: Path = INTERVIEW_DELTA_FILE,
        start_thread: bool = True,
    ) -> None:
        HomageTransitionalSource.__init__(
            self,
            source_id="interview-delta-card",
            entering_duration_s=_ENTER_RAMP_S,
            exiting_duration_s=_EXIT_RAMP_S,
        )
        self._state_file = state_file
        self._state: InterviewDeltaState = _EMPTY_STATE
        self._state_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._poll_thread: threading.Thread | None = None

        if start_thread:
            self._poll_thread = threading.Thread(
                target=self._poll_loop,
                name="interview-delta-poll",
                daemon=True,
            )
            self._poll_thread.start()

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._poll_once()
            except Exception as exc:
                log.warning("interview-delta: poll failed: %s", exc, exc_info=True)
            self._stop_event.wait(_POLL_INTERVAL_S)

    def _poll_once(self) -> InterviewDeltaState:
        state = _read_interview_delta(self._state_file)
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
    def current_state(self) -> InterviewDeltaState:
        with self._state_lock:
            return self._state

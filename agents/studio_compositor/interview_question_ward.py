"""Interview question card ward — displays current interview question + source pressure.

Reads from /dev/shm/hapax-compositor/interview-state.json, which the
interview agent (logos/interview.py) writes after each question ask.
Fades in when an INTERVIEW programme activates, fades out when it ends.

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

INTERVIEW_STATE_FILE = Path("/dev/shm/hapax-compositor/interview-state.json")
_POLL_INTERVAL_S: float = 1.0
_ENTER_RAMP_S: float = 0.5
_EXIT_RAMP_S: float = 0.6


@dataclass(frozen=True)
class InterviewQuestionState:
    active: bool = False
    current_question: str = ""
    topic: str = ""
    depth: str = ""
    rationale: str = ""
    source_refs: tuple[str, ...] = ()
    topics_explored: int = 0
    topics_total: int = 0
    facts_recorded: int = 0


_EMPTY_STATE = InterviewQuestionState()


def _read_interview_state(path: Path) -> InterviewQuestionState:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return InterviewQuestionState(
            active=data.get("active", False),
            current_question=data.get("current_question", ""),
            topic=data.get("topic", ""),
            depth=data.get("depth", ""),
            rationale=data.get("rationale", ""),
            source_refs=tuple(data.get("source_refs", [])),
            topics_explored=data.get("topics_explored", 0),
            topics_total=data.get("topics_total", 0),
            facts_recorded=data.get("facts_recorded", 0),
        )
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return _EMPTY_STATE


class InterviewQuestionWard(HomageTransitionalSource):
    """Displays the current interview question, topic, and source pressure."""

    def __init__(
        self,
        *,
        state_file: Path = INTERVIEW_STATE_FILE,
        start_thread: bool = True,
    ) -> None:
        HomageTransitionalSource.__init__(
            self,
            source_id="interview-question-card",
            entering_duration_s=_ENTER_RAMP_S,
            exiting_duration_s=_EXIT_RAMP_S,
        )
        self._state_file = state_file
        self._state: InterviewQuestionState = _EMPTY_STATE
        self._state_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._poll_thread: threading.Thread | None = None

        if start_thread:
            self._poll_thread = threading.Thread(
                target=self._poll_loop,
                name="interview-question-poll",
                daemon=True,
            )
            self._poll_thread.start()

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._poll_once()
            except Exception as exc:
                log.warning("interview-question: poll failed: %s", exc, exc_info=True)
            self._stop_event.wait(_POLL_INTERVAL_S)

    def _poll_once(self) -> InterviewQuestionState:
        state = _read_interview_state(self._state_file)
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
    def current_state(self) -> InterviewQuestionState:
        with self._state_lock:
            return self._state

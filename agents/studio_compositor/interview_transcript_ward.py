"""Interview transcript ward — displays operator answers + timestamps.

Reads from /dev/shm/hapax-compositor/interview-transcript.json, which
the interview agent writes after each operator response.

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

TRANSCRIPT_STATE_FILE = Path("/dev/shm/hapax-compositor/interview-transcript.json")
_POLL_INTERVAL_S: float = 1.0
_ENTER_RAMP_S: float = 0.5
_EXIT_RAMP_S: float = 0.6


@dataclass(frozen=True)
class TranscriptEntry:
    speaker: str = ""
    text: str = ""
    timestamp: float = 0.0


@dataclass(frozen=True)
class InterviewTranscriptState:
    active: bool = False
    entries: tuple[TranscriptEntry, ...] = ()
    total_turns: int = 0


_EMPTY_STATE = InterviewTranscriptState()


def _read_transcript_state(path: Path) -> InterviewTranscriptState:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = tuple(
            TranscriptEntry(
                speaker=e.get("speaker", ""),
                text=e.get("text", ""),
                timestamp=e.get("timestamp", 0.0),
            )
            for e in data.get("entries", [])[-10:]
        )
        return InterviewTranscriptState(
            active=data.get("active", False),
            entries=entries,
            total_turns=data.get("total_turns", 0),
        )
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return _EMPTY_STATE


class InterviewTranscriptWard(HomageTransitionalSource):
    """Displays recent interview transcript entries."""

    def __init__(
        self,
        *,
        state_file: Path = TRANSCRIPT_STATE_FILE,
        start_thread: bool = True,
    ) -> None:
        HomageTransitionalSource.__init__(
            self,
            source_id="interview-transcript-card",
            entering_duration_s=_ENTER_RAMP_S,
            exiting_duration_s=_EXIT_RAMP_S,
        )
        self._state_file = state_file
        self._state: InterviewTranscriptState = _EMPTY_STATE
        self._state_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._poll_thread: threading.Thread | None = None

        if start_thread:
            self._poll_thread = threading.Thread(
                target=self._poll_loop,
                name="interview-transcript-poll",
                daemon=True,
            )
            self._poll_thread.start()

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._poll_once()
            except Exception as exc:
                log.warning("interview-transcript: poll failed: %s", exc, exc_info=True)
            self._stop_event.wait(_POLL_INTERVAL_S)

    def _poll_once(self) -> InterviewTranscriptState:
        state = _read_transcript_state(self._state_file)
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
    def current_state(self) -> InterviewTranscriptState:
        with self._state_lock:
            return self._state

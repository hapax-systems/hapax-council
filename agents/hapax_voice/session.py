"""Voice conversation lifecycle state machine for Hapax Voice."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Literal

log = logging.getLogger(__name__)

SessionState = Literal["idle", "active"]


class VoiceLifecycle:
    """Manages voice conversation lifecycle state.

    Tracks whether a voice conversation is active, who is speaking
    (operator vs guest/child), and handles silence timeouts.
    Not an auth mechanism — the single operator is always authorized.
    """

    def __init__(self, silence_timeout_s: int = 30) -> None:
        self.silence_timeout_s = silence_timeout_s
        self.session_id: str | None = None
        self.state: SessionState = "idle"
        self.trigger: str | None = None
        self.speaker: str | None = None
        self.speaker_confidence: float = 0.0
        self._last_activity: float = 0.0
        self._opened_at: float = 0.0
        self._paused: bool = False

    @property
    def is_active(self) -> bool:
        return self.state == "active"

    @property
    def is_guest_mode(self) -> bool:
        return self.is_active and self.speaker not in ("ryan", None)

    @property
    def is_timed_out(self) -> bool:
        if not self.is_active or self._paused:
            return False
        return (time.monotonic() - self._last_activity) > self.silence_timeout_s

    def open(self, trigger: str) -> None:
        if self.is_active:
            return
        self.state = "active"
        self.session_id = uuid.uuid4().hex[:12]
        self.trigger = trigger
        self.speaker = None
        self.speaker_confidence = 0.0
        self._opened_at = time.monotonic()
        self._last_activity = self._opened_at
        log.info("Voice conversation opened (trigger=%s)", trigger)

    def close(self, reason: str = "explicit") -> None:
        if not self.is_active:
            return
        duration = time.monotonic() - self._opened_at
        log.info("Voice conversation closed (reason=%s, duration=%.1fs)", reason, duration)
        self.state = "idle"
        self.session_id = None
        self.trigger = None
        self.speaker = None
        self.speaker_confidence = 0.0
        self._paused = False

    def set_speaker(self, speaker: str, confidence: float) -> None:
        self.speaker = speaker
        self.speaker_confidence = confidence

    def mark_activity(self) -> None:
        self._last_activity = time.monotonic()

    @property
    def is_paused(self) -> bool:
        return self.is_active and self._paused

    def pause(self, reason: str = "") -> None:
        """Pause the timeout clock. Session stays active but won't time out."""
        if not self.is_active:
            return
        self._paused = True
        log.info("Session paused (reason=%s)", reason)

    def resume(self) -> None:
        """Resume the timeout clock, resetting activity timestamp."""
        if not self.is_active or not self._paused:
            return
        self._paused = False
        self._last_activity = time.monotonic()
        log.info("Session resumed")


# Public alias for backward compatibility with task spec
SessionManager = VoiceLifecycle

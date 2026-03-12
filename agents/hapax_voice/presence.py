"""Presence detection via sliding-window VAD event scoring."""

from __future__ import annotations

import json
import logging
import time
from collections import deque
from typing import Any

import numpy as np
import torch

try:
    from .watch_signals import WATCH_STATE_DIR, is_watch_connected, send_haptic_tap

    _WATCH_AVAILABLE = True
except ImportError:
    _WATCH_AVAILABLE = False

log = logging.getLogger(__name__)

# Audio format constants
SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000  # 480 samples


class PresenceDetector:
    """Detects operator presence using a sliding window of VAD events.

    Records voice activity detection events above a confidence threshold
    and scores presence based on event count within the window.
    """

    def __init__(self, window_minutes: float = 5, vad_threshold: float = 0.4) -> None:
        self.window_minutes = window_minutes
        self.vad_threshold = vad_threshold
        self._events: deque[float] = deque()
        self._vad_model: Any | None = None
        self._face_detected: bool = False
        self._face_count: int = 0
        self._last_face_time: float = 0.0
        self._face_decay_s: float = 30.0
        self._event_log: Any | None = None
        self._last_score: str = "likely_absent"
        self._latest_vad_confidence: float = 0.0

    def load_model(self) -> Any:
        """Lazily load and return the Silero VAD model (CPU-only)."""
        if self._vad_model is not None:
            return self._vad_model
        try:
            from silero_vad import load_silero_vad

            self._vad_model = load_silero_vad()
        except ImportError:
            log.info("silero_vad package not found, falling back to torch.hub")
            try:
                self._vad_model, _ = torch.hub.load(
                    "snakers4/silero-vad", "silero_vad", trust_repo=True
                )
            except Exception:
                log.warning("torch.hub.load failed; VAD model unavailable", exc_info=True)
                return None
        log.info("Silero VAD model loaded (CPU)")
        return self._vad_model

    def process_audio_frame(self, audio_chunk: bytes) -> float:
        """Run Silero VAD on a raw PCM int16 audio frame.

        Args:
            audio_chunk: Raw PCM bytes, 16kHz mono int16.
                         Expected length for 30ms: 960 bytes (480 samples * 2).

        Returns:
            Speech probability (0.0-1.0). Also feeds record_vad_event.
        """
        model = self.load_model()
        if model is None:
            return 0.0
        # Convert int16 PCM bytes to float32 tensor in [-1, 1]
        samples = np.frombuffer(audio_chunk, dtype=np.int16).astype(np.float32) / 32768.0
        tensor = torch.from_numpy(samples)

        with torch.no_grad():
            probability: float = model(tensor, SAMPLE_RATE).item()

        self._latest_vad_confidence = probability
        self.record_vad_event(probability)
        return probability

    def record_vad_event(self, confidence: float) -> None:
        """Record a VAD event if confidence meets threshold."""
        if confidence < self.vad_threshold:
            return
        self._events.append(time.monotonic())
        log.debug("VAD event recorded (confidence=%.2f, count=%d)", confidence, len(self._events))

    def set_event_log(self, event_log: Any) -> None:
        """Set the event log for emitting presence transition events."""
        self._event_log = event_log

    def record_face_event(self, detected: bool, count: int = 0) -> None:
        """Record a face detection result from the webcam."""
        self._face_detected = detected
        self._face_count = count if detected else 0
        if detected:
            self._last_face_time = time.monotonic()

    def try_watch_presence_check(self, timeout: float = 3.0, poll_interval: float = 0.5) -> bool | None:
        """Attempt presence verification via watch haptic tap.

        Sends a haptic tap to the watch and waits for a voice_trigger.json
        response file. Returns True if confirmed, None if watch unavailable
        or timed out (caller should fall back to audio chime).

        Args:
            timeout: Seconds to wait for trigger file response.
            poll_interval: Seconds between file existence checks.

        Returns:
            True if presence confirmed via watch, None to fall through.
        """
        if not _WATCH_AVAILABLE:
            return None

        if not is_watch_connected():
            log.debug("Watch not connected, skipping haptic presence check")
            return None

        trigger_path = WATCH_STATE_DIR / "voice_trigger.json"

        # Record time before sending haptic so we only accept fresh triggers
        sent_time = time.time()

        if not send_haptic_tap():
            log.debug("Failed to send haptic tap, falling through to audio chime")
            return None

        log.info("Haptic tap sent, waiting for watch trigger response")

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if trigger_path.exists():
                try:
                    mtime = trigger_path.stat().st_mtime
                    if mtime >= sent_time:
                        data = json.loads(trigger_path.read_text())
                        log.info("Watch presence confirmed via trigger file: %s", data)
                        return True
                except (json.JSONDecodeError, OSError):
                    pass
            time.sleep(poll_interval)

        log.debug("Watch presence check timed out after %.1fs", timeout)
        return None

    @property
    def face_detected(self) -> bool:
        """Whether a face was recently detected (within decay window)."""
        if not self._face_detected:
            return False
        if (time.monotonic() - self._last_face_time) > self._face_decay_s:
            self._face_detected = False
            return False
        return True

    @property
    def face_count(self) -> int:
        """Number of faces detected in the most recent frame."""
        return self._face_count if self.face_detected else 0

    def _prune_old_events(self) -> None:
        """Remove events older than the sliding window."""
        cutoff = time.monotonic() - (self.window_minutes * 60)
        while self._events and self._events[0] < cutoff:
            self._events.popleft()

    @property
    def score(self) -> str:
        """Return composite presence score fusing VAD events and face detection."""
        self._prune_old_events()
        count = len(self._events)
        face = self.face_detected

        if count >= 5:
            new_score = "definitely_present" if face else "likely_present"
        elif count >= 2:
            new_score = "likely_present" if face else "uncertain"
        elif face:
            new_score = "likely_present"
        else:
            new_score = "likely_absent"

        if new_score != self._last_score and self._event_log is not None:
            self._event_log.emit(
                "presence_transition",
                **{
                    "from": self._last_score,
                    "to": new_score,
                    "vad_count": count,
                    "face_detected": face,
                },
            )
        self._last_score = new_score
        return new_score

    @property
    def latest_vad_confidence(self) -> float:
        """Most recent VAD probability (0.0-1.0), regardless of threshold."""
        return self._latest_vad_confidence

    @property
    def event_count(self) -> int:
        """Return number of events in the current window."""
        self._prune_old_events()
        return len(self._events)

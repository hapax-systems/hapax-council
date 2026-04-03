"""Conversation buffer — continuous audio accumulation for STT.

Third consumer in _audio_loop(). Accumulates raw PCM frames during
detected speech and delivers complete utterances when silence is
detected. Runs inline — no extra task, no mic ownership.

Pre-roll: captures 1500ms of audio before speech onset so word
beginnings aren't clipped.

Echo handling: three-layer stack.
  Layer 1: PipeWire webrtc AEC (echo cancellation at audio server level)
  Layer 2: Energy-ratio classifier in audio_loop (residual echo discrimination)
  Layer 3: Adaptive VAD thresholds (0.8 during system speech, 0.15 otherwise)

The buffer NEVER goes deaf. Perception is continuous per CPAL spec §7.4.
Operator speech during system output is classified (backchannel vs floor
claim) by the CPAL runner, not dropped.
"""

from __future__ import annotations

import logging
import time
from collections import deque

log = logging.getLogger(__name__)

FRAME_SAMPLES = 480  # 16kHz, 30ms
SAMPLE_RATE = 16000
PRE_ROLL_FRAMES = 50  # 1500ms before speech onset — captures full wake word phrase

SPEECH_START_PROB = 0.15
SPEECH_START_CONSECUTIVE = 3  # ~90ms
SPEECH_END_PROB = 0.1
# Adaptive speech-end: calibrated for an operator who "processes voice
# slowly and has dysfluencies when thinking aloud" — natural mid-thought
# pauses of 600-1200ms are common and should NOT trigger emission.
# Short utterances get the same patience as default — no premature
# cutoff on incomplete thoughts.
SPEECH_END_SHORT = 30  # ~900ms — was 600ms, raised for dysfluent pauses
SPEECH_END_LONG = 40  # ~1200ms — for long utterances > 3s
SPEECH_END_DEFAULT = 33  # ~1000ms — was 750ms, raised for natural pauses


class ConversationBuffer:
    """Accumulates audio during speech for STT transcription.

    Usage in _audio_loop():
        buffer.feed_audio(frame_bytes)
        buffer.update_vad(vad_probability)
        utterance = buffer.get_utterance()
        if utterance is not None:
            transcript = await stt.transcribe(utterance)

    Barge-in is handled by the CPAL runner (not the buffer). The
    barge_in_detected property is kept for backward compatibility
    but always returns False.
    """

    def __init__(self, max_duration_s: float = 30.0) -> None:
        self._max_frames = int(max_duration_s * SAMPLE_RATE / FRAME_SAMPLES)
        self._pre_roll: deque[bytes] = deque(maxlen=PRE_ROLL_FRAMES)
        self._speech_frames: list[bytes] = []
        self._speech_active = False
        self._consecutive_speech = 0
        self._consecutive_silence = 0
        self._active = False
        self._speaking = False
        self._pending_utterance: bytes | None = None
        self._speaking_started_at: float = 0.0
        self._speaking_ended_at: float = 0.0

        # Adaptive speech-end: track speech duration for threshold adjustment
        self._speech_start_time: float = 0.0

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def speech_active(self) -> bool:
        """True when VAD has detected ongoing speech."""
        return self._speech_active

    @property
    def speech_duration_s(self) -> float:
        """Duration of current speech segment in seconds (0.0 if not speaking)."""
        if not self._speech_active or self._speech_start_time == 0.0:
            return 0.0
        return time.monotonic() - self._speech_start_time

    @property
    def is_speaking(self) -> bool:
        """True when TTS playback is active."""
        return self._speaking

    @property
    def barge_in_detected(self) -> bool:
        """Always False — barge-in is handled by CPAL runner, not the buffer.

        Kept as a read-only property for backward compatibility with
        conversation_pipeline and perception_state_writer readers.
        """
        return False

    @property
    def speech_frames_snapshot(self) -> list[bytes]:
        """Shallow copy of accumulated speech frames for speculative STT."""
        return list(self._speech_frames)

    def activate(self) -> None:
        self._active = True
        self._reset()

    def deactivate(self) -> None:
        self._active = False
        self._reset()

    def set_speaking(self, speaking: bool) -> None:
        """Track system speech state for adaptive VAD thresholds.

        No longer gates audio — perception is continuous.
        """
        self._speaking = speaking
        if speaking:
            self._speaking_started_at = time.monotonic()
            self._speaking_ended_at = 0.0
        else:
            self._speaking_ended_at = time.monotonic()

    def feed_audio(self, frame: bytes) -> None:
        if not self._active:
            return
        self._pre_roll.append(frame)

        # Always accumulate speech frames when speech is active.
        # Echo discrimination is handled upstream (PipeWire AEC + energy classifier).
        if self._speech_active:
            self._speech_frames.append(frame)
            if len(self._speech_frames) >= self._max_frames:
                self._emit_utterance()

    def update_vad(self, probability: float) -> None:
        if not self._active:
            return

        # Adaptive threshold: higher during system speech to filter
        # residual echo that passes through PipeWire AEC + energy classifier.
        # Three states: speaking (0.8), post-TTS 500ms (0.7), silent (0.15).
        _post_tts_window = 0.5  # seconds
        if self._speaking:
            start_threshold = 0.8
            consecutive_required = 7  # ~210ms sustained
        elif (
            self._speaking_ended_at > 0.0
            and (time.monotonic() - self._speaking_ended_at) < _post_tts_window
        ):
            start_threshold = 0.7  # post-TTS: residual echo decay
            consecutive_required = 5  # ~150ms sustained
        else:
            start_threshold = SPEECH_START_PROB  # 0.15
            consecutive_required = SPEECH_START_CONSECUTIVE  # 3

        if probability >= start_threshold:
            self._consecutive_speech += 1
            self._consecutive_silence = 0
            if not self._speech_active and self._consecutive_speech >= consecutive_required:
                self._speech_active = True
                self._speech_start_time = time.monotonic()
                self._speech_frames = list(self._pre_roll) + self._speech_frames
        elif probability < SPEECH_END_PROB:
            self._consecutive_silence += 1
            self._consecutive_speech = 0
            if self._speech_active:
                speech_duration = time.monotonic() - self._speech_start_time
                if speech_duration > 3.0:
                    threshold = SPEECH_END_LONG
                elif speech_duration < 1.0:
                    threshold = SPEECH_END_SHORT
                else:
                    threshold = SPEECH_END_DEFAULT
                if self._consecutive_silence >= threshold:
                    self._emit_utterance()

    def get_utterance(self) -> bytes | None:
        utterance = self._pending_utterance
        self._pending_utterance = None
        return utterance

    def _emit_utterance(self) -> None:
        if self._speech_frames:
            self._pending_utterance = b"".join(self._speech_frames)
            duration_s = len(self._speech_frames) * FRAME_SAMPLES / SAMPLE_RATE
            log.info("Utterance captured: %.1fs (%d frames)", duration_s, len(self._speech_frames))
        self._speech_active = False
        self._speech_frames = []
        self._consecutive_speech = 0
        self._consecutive_silence = 0

    def _reset(self) -> None:
        self._pre_roll.clear()
        self._speech_frames = []
        self._speech_active = False
        self._consecutive_speech = 0
        self._consecutive_silence = 0
        self._pending_utterance = None
        self._speaking = False

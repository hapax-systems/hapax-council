"""Conversation buffer — VAD-gated audio accumulation for STT.

Third consumer in _audio_loop(). Accumulates raw PCM frames during
detected speech and delivers complete utterances when silence is
detected. Runs inline — no extra task, no mic ownership.

Pre-roll: captures 300ms of audio before speech onset so word
beginnings aren't clipped.

Suppresses accumulation during SPEAKING state to prevent echo from
being transcribed (defense in depth behind PipeWire AEC).
"""

from __future__ import annotations

import logging
from collections import deque

log = logging.getLogger(__name__)

FRAME_SAMPLES = 480  # 16kHz, 30ms
SAMPLE_RATE = 16000
PRE_ROLL_FRAMES = 10  # 300ms before speech onset

SPEECH_START_PROB = 0.5
SPEECH_START_CONSECUTIVE = 3  # ~90ms
SPEECH_END_PROB = 0.3
SPEECH_END_CONSECUTIVE = 20  # ~600ms


class ConversationBuffer:
    """Accumulates audio during speech for STT transcription.

    Usage in _audio_loop():
        buffer.feed_audio(frame_bytes)
        buffer.update_vad(vad_probability)
        utterance = buffer.get_utterance()
        if utterance is not None:
            transcript = await stt.transcribe(utterance)
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

    @property
    def is_active(self) -> bool:
        return self._active

    def activate(self) -> None:
        self._active = True
        self._reset()

    def deactivate(self) -> None:
        self._active = False
        self._reset()

    def set_speaking(self, speaking: bool) -> None:
        self._speaking = speaking

    def feed_audio(self, frame: bytes) -> None:
        if not self._active:
            return
        self._pre_roll.append(frame)
        if self._speaking:
            return
        if self._speech_active:
            self._speech_frames.append(frame)
            if len(self._speech_frames) >= self._max_frames:
                self._emit_utterance()

    def update_vad(self, probability: float) -> None:
        if not self._active or self._speaking:
            return

        if probability >= SPEECH_START_PROB:
            self._consecutive_speech += 1
            self._consecutive_silence = 0
            if not self._speech_active and self._consecutive_speech >= SPEECH_START_CONSECUTIVE:
                self._speech_active = True
                self._speech_frames = list(self._pre_roll) + self._speech_frames
        elif probability < SPEECH_END_PROB:
            self._consecutive_silence += 1
            self._consecutive_speech = 0
            if self._speech_active and self._consecutive_silence >= SPEECH_END_CONSECUTIVE:
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

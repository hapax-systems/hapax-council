"""Conversation buffer — VAD-gated audio accumulation for STT.

Third consumer in _audio_loop(). Accumulates raw PCM frames during
detected speech and delivers complete utterances when silence is
detected. Runs inline — no extra task, no mic ownership.

Pre-roll: captures 300ms of audio before speech onset so word
beginnings aren't clipped.

Application-level AEC (echo_canceller.py) reduces echo but the
Yeti mic still picks up enough TTS bleed-through at close range
to trigger VAD. The speaking gate in feed_audio() remains as
primary defense; AEC is supplementary. Barge-in is enabled at a
high threshold (0.85) requiring clear operator speech over TTS.

Post-TTS cooldown removed — AEC handles the residual echo tail
that previously required 500ms of dead time.
"""

from __future__ import annotations

import logging
import time
from collections import deque

log = logging.getLogger(__name__)

FRAME_SAMPLES = 480  # 16kHz, 30ms
SAMPLE_RATE = 16000
PRE_ROLL_FRAMES = 10  # 300ms before speech onset

SPEECH_START_PROB = 0.5
SPEECH_START_CONSECUTIVE = 3  # ~90ms
SPEECH_END_PROB = 0.3
# Operator talks a lot and pauses mid-thought. 750ms of silence before
# deciding they're done (was 450ms — too aggressive, cut mid-sentence).
SPEECH_END_CONSECUTIVE = 25  # ~750ms

# Barge-in detection during TTS playback
BARGE_IN_PROB = 0.85
BARGE_IN_CONSECUTIVE = 8

# Post-TTS cooldown: only applies when TTS ends NORMALLY (no barge-in).
# On barge-in, cooldown is skipped — operator is definitely speaking.
POST_TTS_COOLDOWN_S = 2.0


class ConversationBuffer:
    """Accumulates audio during speech for STT transcription.

    Usage in _audio_loop():
        buffer.feed_audio(frame_bytes)
        buffer.update_vad(vad_probability)
        utterance = buffer.get_utterance()
        if utterance is not None:
            transcript = await stt.transcribe(utterance)

    Barge-in: while speaking, VAD still runs at a high threshold. If
    the operator talks over TTS output, barge_in_detected goes True.
    The pipeline can poll this to cut playback and switch to listening.
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
        self._speaking_ended_at: float = 0.0

        # Barge-in detection (active during SPEAKING state)
        self._barge_in_speech_count = 0
        self.barge_in_detected = False

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def in_cooldown(self) -> bool:
        """True while short post-TTS echo decay cooldown is active."""
        if self._speaking:
            return False
        if self._speaking_ended_at == 0.0:
            return False
        return (time.monotonic() - self._speaking_ended_at) < POST_TTS_COOLDOWN_S

    def activate(self) -> None:
        self._active = True
        self._reset()

    def deactivate(self) -> None:
        self._active = False
        self._reset()

    def set_speaking(self, speaking: bool) -> None:
        self._speaking = speaking
        if speaking:
            # Reset barge-in state when TTS starts
            self._barge_in_speech_count = 0
            self.barge_in_detected = False
            self._speaking_ended_at = 0.0
        else:
            if self.barge_in_detected:
                # Barge-in: operator spoke over TTS. Skip cooldown entirely —
                # they're definitely speaking, no echo ambiguity. Start
                # accumulating immediately from pre-roll (which contains
                # their voice during TTS, possibly mixed with Hapax's output).
                self._speaking_ended_at = 0.0  # no cooldown
                if not self._speech_active:
                    self._speech_active = True
                    self._speech_frames = list(self._pre_roll)
                    self._consecutive_speech = SPEECH_START_CONSECUTIVE  # already speaking
                    self._consecutive_silence = 0
                log.debug("Barge-in: capturing operator speech from pre-roll, no cooldown")
            else:
                # Normal TTS end — start cooldown for residual mic pickup
                self._speaking_ended_at = time.monotonic()

    def feed_audio(self, frame: bytes) -> None:
        if not self._active:
            return
        self._pre_roll.append(frame)

        # During normal TTS (no barge-in): pre-roll only
        if self._speaking and not self.barge_in_detected:
            return
        # During cooldown (normal TTS end): pre-roll only
        if self.in_cooldown:
            return
        # During TTS with barge-in active, OR after TTS: accumulate speech
        if self._speech_active:
            self._speech_frames.append(frame)
            if len(self._speech_frames) >= self._max_frames:
                self._emit_utterance()

    def update_vad(self, probability: float) -> None:
        if not self._active:
            return

        # During TTS: detect barge-in, then switch to normal speech tracking
        if self._speaking:
            if not self.barge_in_detected:
                # Phase 1: detecting barge-in (high threshold)
                if probability >= BARGE_IN_PROB:
                    self._barge_in_speech_count += 1
                    if self._barge_in_speech_count >= BARGE_IN_CONSECUTIVE:
                        log.info("Barge-in detected: operator speaking over TTS")
                        self.barge_in_detected = True
                        # Immediately start speech accumulation
                        if not self._speech_active:
                            self._speech_active = True
                            self._speech_frames = list(self._pre_roll)
                            self._consecutive_speech = SPEECH_START_CONSECUTIVE
                            self._consecutive_silence = 0
                else:
                    self._barge_in_speech_count = max(0, self._barge_in_speech_count - 1)
                return
            # Phase 2: barge-in active, track speech normally (fall through to main VAD logic below)

        # During short post-TTS cooldown: track VAD state so speech detection
        # begins immediately when cooldown ends, but don't emit utterances.
        if self.in_cooldown:
            if probability >= SPEECH_START_PROB:
                self._consecutive_speech += 1
                self._consecutive_silence = 0
            else:
                self._consecutive_speech = 0
                self._consecutive_silence += 1
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
        self._speaking_ended_at = 0.0
        self._barge_in_speech_count = 0
        self.barge_in_detected = False

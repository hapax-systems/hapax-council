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

# Post-TTS cooldown: wait after TTS ends before listening again.
# In dampened studio, room echo decays within 1-2s. Echo rejection
# catches any residual TTS text that leaks through.
POST_TTS_COOLDOWN_S = 2.0


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
        self._speaking_ended_at: float = 0.0
        self._speaking_started_at: float = 0.0

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

    @property
    def in_cooldown(self) -> bool:
        """True while post-TTS echo decay cooldown is active.

        Cooldown scales with response length: longer responses produce
        more room echo. Base 2s + 0.3s per second of TTS, capped at 5s.
        """
        if self._speaking:
            return False
        if self._speaking_ended_at == 0.0:
            return False
        cooldown = getattr(self, "_dynamic_cooldown_s", POST_TTS_COOLDOWN_S)
        return (time.monotonic() - self._speaking_ended_at) < cooldown

    def activate(self) -> None:
        self._active = True
        self._reset()

    def deactivate(self) -> None:
        self._active = False
        self._reset()

    def set_speaking(self, speaking: bool) -> None:
        self._speaking = speaking
        if speaking:
            self._speaking_ended_at = 0.0
            self._speaking_started_at = time.monotonic()
        else:
            # TTS ended — start cooldown for residual echo decay.
            # Cooldown scales with how long Hapax was speaking: longer
            # responses produce more room echo that persists longer.
            self._speaking_ended_at = time.monotonic()
            speaking_duration = self._speaking_ended_at - self._speaking_started_at
            # Base 2s + 0.3s per second of TTS, capped at 5s
            self._dynamic_cooldown_s = min(5.0, POST_TTS_COOLDOWN_S + speaking_duration * 0.3)

    def feed_audio(self, frame: bytes) -> None:
        if not self._active:
            return
        self._pre_roll.append(frame)

        # During TTS playback: pre-roll only (barge-in handled by CPAL runner)
        if self._speaking:
            return
        # During cooldown (normal TTS end): pre-roll only
        if self.in_cooldown:
            return
        # After TTS: accumulate speech
        if self._speech_active:
            self._speech_frames.append(frame)
            if len(self._speech_frames) >= self._max_frames:
                self._emit_utterance()

    def update_vad(self, probability: float) -> None:
        if not self._active:
            return

        # During TTS: completely ignore VAD. The AEC can't attenuate TTS
        # echo from studio monitors — echo sustains above any VAD threshold
        # for the full duration of playback, making interrupt detection
        # impossible to distinguish from echo. Operator speaks AFTER TTS
        # finishes + cooldown (natural turn-taking).
        if self._speaking:
            return

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
                self._speech_start_time = time.monotonic()
                self._speech_frames = list(self._pre_roll) + self._speech_frames
        elif probability < SPEECH_END_PROB:
            self._consecutive_silence += 1
            self._consecutive_speech = 0
            if self._speech_active:
                # Adaptive threshold: long utterances get more patience
                speech_duration = time.monotonic() - self._speech_start_time
                if speech_duration > 3.0:
                    threshold = SPEECH_END_LONG  # ~1050ms
                elif speech_duration < 1.0:
                    threshold = SPEECH_END_SHORT  # ~600ms
                else:
                    threshold = SPEECH_END_DEFAULT  # ~750ms
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
        self._speaking_ended_at = 0.0

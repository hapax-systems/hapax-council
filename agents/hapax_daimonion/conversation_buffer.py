"""Conversation buffer — VAD-gated audio accumulation for STT.

Third consumer in _audio_loop(). Accumulates raw PCM frames during
detected speech and delivers complete utterances when silence is
detected. Runs inline — no extra task, no mic ownership.

Pre-roll: keeps PRE_ROLL_DURATION_S (1.5s) of audio from before speech
onset so word beginnings aren't clipped (derivation in turn_budget).

Application-level AEC (echo_canceller.py) reduces echo but the
Yeti mic still picks up enough TTS bleed-through at close range
to trigger VAD. The speaking gate in feed_audio() remains as
primary defense; AEC is supplementary.

Post-TTS cooldown is LIVE: after playback the buffer stays deaf for
dynamic_cooldown_s(speaking_duration) while room echo decays. All
timing constants are owned by turn_budget (audit v2 §5e SSOT).
"""

from __future__ import annotations

import logging
import time
from collections import deque

from agents.hapax_daimonion.turn_budget import (
    FRAME_SAMPLES,
    POST_TTS_COOLDOWN_S,
    PRE_ROLL_FRAMES,
    SAMPLE_RATE,
    dynamic_cooldown_s,
)

log = logging.getLogger(__name__)

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

INTERVIEW_SPEECH_END_SHORT = 50  # ~1500ms — interviewees pause to think
INTERVIEW_SPEECH_END_LONG = 70  # ~2100ms — deep reflection mid-answer
INTERVIEW_SPEECH_END_DEFAULT = 60  # ~1800ms — deliberate considered speech

# POST_TTS_COOLDOWN_S / dynamic_cooldown_s are imported from turn_budget:
# wait after TTS ends before listening again, scaled by speech duration.


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
        self._interview_mode = False

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
    def interview_mode(self) -> bool:
        return self._interview_mode

    @interview_mode.setter
    def interview_mode(self, value: bool) -> None:
        self._interview_mode = value

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
            # responses produce more room echo that persists longer
            # (derivation owned by turn_budget.dynamic_cooldown_s).
            self._speaking_ended_at = time.monotonic()
            speaking_duration = self._speaking_ended_at - self._speaking_started_at
            self._dynamic_cooldown_s = dynamic_cooldown_s(speaking_duration)

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
                if self._interview_mode:
                    if speech_duration > 3.0:
                        threshold = INTERVIEW_SPEECH_END_LONG
                    elif speech_duration < 1.0:
                        threshold = INTERVIEW_SPEECH_END_SHORT
                    else:
                        threshold = INTERVIEW_SPEECH_END_DEFAULT
                elif speech_duration > 3.0:
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
        self._speaking_ended_at = 0.0

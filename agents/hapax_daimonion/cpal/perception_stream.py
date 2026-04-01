"""Perception stream -- continuous audio analysis at ~30ms resolution.

Wraps the existing ConversationBuffer and adds continuous signal
extraction: VAD confidence, energy, and TRP (transition relevance
place) projection. Published signals drive the control law evaluator.

Stream 1 of 3 in the CPAL temporal architecture.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass


@dataclass(frozen=True)
class PerceptionSignals:
    """Snapshot of perception stream state. Immutable."""

    vad_confidence: float = 0.0
    speech_active: bool = False
    speech_duration_s: float = 0.0
    is_speaking: bool = False
    energy_rms: float = 0.0
    trp_probability: float = 0.0


_TRP_ONSET = 0.7
_TRP_DECAY = 0.85


class PerceptionStream:
    """Continuous audio perception at frame resolution."""

    def __init__(self, buffer: object) -> None:
        self._buffer = buffer
        self._signals = PerceptionSignals()
        self._prev_speech_active = False
        self._trp = 0.0

    @property
    def signals(self) -> PerceptionSignals:
        return self._signals

    def update(self, frame: bytes, *, vad_prob: float) -> None:
        speech_active = self._buffer.speech_active
        speech_duration_s = self._buffer.speech_duration_s
        is_speaking = self._buffer.is_speaking

        n_samples = len(frame) // 2
        if n_samples > 0:
            samples = struct.unpack(f"<{n_samples}h", frame)
            rms = math.sqrt(sum(s * s for s in samples) / n_samples) / 32768.0
        else:
            rms = 0.0

        if self._prev_speech_active and not speech_active:
            self._trp = _TRP_ONSET
        elif speech_active:
            self._trp = 0.0
        else:
            self._trp *= _TRP_DECAY
            if self._trp < 0.01:
                self._trp = 0.0

        self._prev_speech_active = speech_active

        self._signals = PerceptionSignals(
            vad_confidence=vad_prob,
            speech_active=speech_active,
            speech_duration_s=speech_duration_s,
            is_speaking=is_speaking,
            energy_rms=rms,
            trp_probability=self._trp,
        )

    def get_utterance(self) -> bytes | None:
        return self._buffer.get_utterance()

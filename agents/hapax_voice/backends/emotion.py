"""Emotion perception backend — valence, arousal, and dominant emotion.

Stub backend: reserves behavior names and proves the protocol.
Actual implementation requires audio/video emotion model inference.
"""

from __future__ import annotations

import logging

from agents.hapax_voice.perception import PerceptionTier
from agents.hapax_voice.primitives import Behavior

log = logging.getLogger(__name__)


class EmotionBackend:
    """PerceptionBackend for emotion analysis.

    Provides:
      - emotion_valence: float (-1.0 to 1.0)
      - emotion_arousal: float (0.0 to 1.0)
      - emotion_dominant: str (e.g. "neutral", "happy", "tense")
    """

    @property
    def name(self) -> str:
        return "emotion"

    @property
    def provides(self) -> frozenset[str]:
        return frozenset({"emotion_valence", "emotion_arousal", "emotion_dominant"})

    @property
    def tier(self) -> PerceptionTier:
        return PerceptionTier.SLOW

    def available(self) -> bool:
        return False

    def contribute(self, behaviors: dict[str, Behavior]) -> None:
        pass

    def start(self) -> None:
        log.info("Emotion backend started (stub)")

    def stop(self) -> None:
        log.info("Emotion backend stopped (stub)")

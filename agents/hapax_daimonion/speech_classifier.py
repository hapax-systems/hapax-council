"""Classify operator speech detected during system output.

Primary: speculative STT -> phatic token match -> backchannel vs substantive.
Fallback: duration < 1s -> backchannel, >= 1s -> floor claim.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

FRAME_SAMPLES = 480
SAMPLE_RATE = 16000
_FRAME_DURATION_S = FRAME_SAMPLES / SAMPLE_RATE  # 0.03s

# Phatic tokens that signal backchannel, not floor claim.
# Lowercase, stripped of punctuation.
PHATIC_TOKENS: frozenset[str] = frozenset(
    {
        "yeah",
        "yep",
        "yup",
        "yes",
        "mm-hm",
        "mm",
        "mhm",
        "mmhm",
        "uh-huh",
        "uh huh",
        "right",
        "okay",
        "ok",
        "sure",
        "got it",
        "i see",
        "go on",
        "hmm",
        "hm",
        "ah",
    }
)

_FLOOR_CLAIM_DURATION_S = 1.0
_STT_TIMEOUT_S = 2.0


@dataclass
class BackchannelSignal:
    """Operator backchannel during system speech — grounding evidence."""

    transcript: str
    confidence: float = 1.0


@dataclass
class FloorClaim:
    """Operator claiming the floor — Hapax should yield."""

    utterance_bytes: bytes
    transcript: str


def _is_phatic(text: str) -> bool:
    """Check if transcript matches a known phatic/backchannel token."""
    normalized = text.lower().strip().rstrip(".,!?")
    return normalized in PHATIC_TOKENS


class DuringProductionClassifier:
    """Classify operator speech detected during system output.

    Primary path: run STT on speech frames, match against phatic token set.
    Fallback: if STT fails or times out, use duration heuristic.
    """

    def __init__(self, stt: object) -> None:
        self._stt = stt

    async def classify(self, speech_frames: list[bytes]) -> BackchannelSignal | FloorClaim:
        """Classify accumulated speech frames from during production.

        Returns BackchannelSignal (grounding) or FloorClaim (yield).
        """
        utterance_bytes = b"".join(speech_frames)
        # Compute duration from total byte length, not frame count —
        # callers may pass a single concatenated blob or individual frames.
        duration_s = len(utterance_bytes) / (SAMPLE_RATE * 2)  # int16 = 2 bytes/sample

        # Try STT classification (primary)
        try:
            transcript = await asyncio.wait_for(self._stt(utterance_bytes), timeout=_STT_TIMEOUT_S)
            transcript = (transcript or "").strip()

            if not transcript or _is_phatic(transcript):
                log.info(
                    "Backchannel (STT): %r (%.1fs)",
                    transcript or "(empty)",
                    duration_s,
                )
                return BackchannelSignal(transcript=transcript)

            log.info(
                "Floor claim (STT): %r (%.1fs)",
                transcript[:60],
                duration_s,
            )
            return FloorClaim(utterance_bytes=utterance_bytes, transcript=transcript)

        except (TimeoutError, Exception):
            # Fallback: duration-based classification
            log.info(
                "STT failed/timeout — fallback to duration (%.1fs)",
                duration_s,
            )

        if duration_s < _FLOOR_CLAIM_DURATION_S:
            return BackchannelSignal(transcript="", confidence=0.5)
        return FloorClaim(utterance_bytes=utterance_bytes, transcript="")

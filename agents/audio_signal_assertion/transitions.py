"""Hysteresis state machine — re-export shim.

All implementation has moved to :mod:`agents.audio_health.transitions`.
This module re-exports every public name so existing imports continue
to work unchanged.
"""

from agents.audio_health.transitions import (  # noqa: F401
    DEFAULT_CLIPPING_SUSTAIN_S,
    DEFAULT_NOISE_SUSTAIN_S,
    DEFAULT_RECOVERY_SUSTAIN_S,
    DEFAULT_SILENCE_SUSTAIN_S,
    StageObservation,
    StageState,
    TransitionDetector,
    TransitionEvent,
    now_seconds,
)

__all__ = [
    "DEFAULT_CLIPPING_SUSTAIN_S",
    "DEFAULT_NOISE_SUSTAIN_S",
    "DEFAULT_RECOVERY_SUSTAIN_S",
    "DEFAULT_SILENCE_SUSTAIN_S",
    "StageObservation",
    "StageState",
    "TransitionDetector",
    "TransitionEvent",
    "now_seconds",
]

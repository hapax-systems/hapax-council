"""Signal classification — re-export shim.

All implementation has moved to :mod:`agents.audio_health.classifier`.
This module re-exports every public name so existing imports continue
to work unchanged.
"""

from agents.audio_health.classifier import (  # noqa: F401
    BAD_STEADY_STATES,
    Classification,
    ClassifierConfig,
    ProbeMeasurement,
    classify,
    measure_pcm,
)

__all__ = [
    "BAD_STEADY_STATES",
    "Classification",
    "ClassifierConfig",
    "ProbeMeasurement",
    "classify",
    "measure_pcm",
]

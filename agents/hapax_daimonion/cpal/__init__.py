"""Conversational Perception-Action Loop (CPAL).

The 15th S1 component in the Stigmergic Cognitive Mesh.
Models conversation as a perceptual control loop with continuous
intensity (loop gain) replacing the binary session model.
"""

from agents.hapax_daimonion.cpal.types import (
    ConversationalRegion,
    CorrectionTier,
    ErrorDimension,
    ErrorSignal,
    GainUpdate,
)

__all__ = [
    "ConversationalRegion",
    "CorrectionTier",
    "ErrorDimension",
    "ErrorSignal",
    "GainUpdate",
]

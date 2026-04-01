"""Conversational Perception-Action Loop (CPAL).

The 15th S1 component in the Stigmergic Cognitive Mesh.
Models conversation as a perceptual control loop with continuous
intensity (loop gain) replacing the binary session model.
"""

from agents.hapax_daimonion.cpal.control_law import ControlLawResult, ConversationControlLaw
from agents.hapax_daimonion.cpal.loop_gain import LoopGainController
from agents.hapax_daimonion.cpal.shm_publisher import publish_cpal_state
from agents.hapax_daimonion.cpal.types import (
    ConversationalRegion,
    CorrectionTier,
    ErrorDimension,
    ErrorSignal,
    GainUpdate,
)

__all__ = [
    "ConversationalRegion",
    "ConversationControlLaw",
    "ControlLawResult",
    "CorrectionTier",
    "ErrorDimension",
    "ErrorSignal",
    "GainUpdate",
    "LoopGainController",
    "publish_cpal_state",
]

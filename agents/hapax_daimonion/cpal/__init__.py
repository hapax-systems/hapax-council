"""Conversational Perception-Action Loop (CPAL).

The 15th S1 component in the Stigmergic Cognitive Mesh.
Models conversation as a perceptual control loop with continuous
intensity (loop gain) replacing the binary session model.
"""

from agents.hapax_daimonion.cpal.control_law import ControlLawResult, ConversationControlLaw
from agents.hapax_daimonion.cpal.evaluator import CpalEvaluator, EvaluatorResult
from agents.hapax_daimonion.cpal.formulation_stream import (
    BackchannelDecision,
    FormulationState,
    FormulationStream,
)
from agents.hapax_daimonion.cpal.loop_gain import LoopGainController
from agents.hapax_daimonion.cpal.perception_stream import PerceptionSignals, PerceptionStream
from agents.hapax_daimonion.cpal.production_stream import ProductionStream
from agents.hapax_daimonion.cpal.shm_publisher import publish_cpal_state
from agents.hapax_daimonion.cpal.signal_cache import SignalCache
from agents.hapax_daimonion.cpal.tier_composer import ComposedAction, TierComposer
from agents.hapax_daimonion.cpal.types import (
    ConversationalRegion,
    CorrectionTier,
    ErrorDimension,
    ErrorSignal,
    GainUpdate,
)

__all__ = [
    "BackchannelDecision",
    "ComposedAction",
    "ConversationalRegion",
    "ConversationControlLaw",
    "ControlLawResult",
    "CorrectionTier",
    "CpalEvaluator",
    "ErrorDimension",
    "ErrorSignal",
    "EvaluatorResult",
    "FormulationState",
    "FormulationStream",
    "GainUpdate",
    "LoopGainController",
    "PerceptionSignals",
    "PerceptionStream",
    "ProductionStream",
    "SignalCache",
    "TierComposer",
    "publish_cpal_state",
]

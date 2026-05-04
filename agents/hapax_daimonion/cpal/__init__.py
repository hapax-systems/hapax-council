"""Conversational Perception-Action Loop (CPAL).

The 15th S1 component in the Stigmergic Cognitive Mesh.
Models conversation as a perceptual control loop with continuous
intensity (loop gain) replacing the binary session model.
"""

from agents.hapax_daimonion.cpal.chat_destination import (
    SHORT_RESPONSE_CHAR_LIMIT,
    ChatDestination,
    ResponseModality,
    classify_response_modality,
)
from agents.hapax_daimonion.cpal.control_law import ControlLawResult, ConversationControlLaw
from agents.hapax_daimonion.cpal.evaluator import CpalEvaluator, EvaluatorResult
from agents.hapax_daimonion.cpal.formulation_stream import (
    BackchannelDecision,
    FormulationState,
    FormulationStream,
)
from agents.hapax_daimonion.cpal.grounding_bridge import GroundingBridge, GroundingState
from agents.hapax_daimonion.cpal.impingement_adapter import ImpingementAdapter, ImpingementEffect
from agents.hapax_daimonion.cpal.loop_gain import LoopGainController
from agents.hapax_daimonion.cpal.perception_stream import PerceptionSignals, PerceptionStream
from agents.hapax_daimonion.cpal.production_stream import ProductionStream
from agents.hapax_daimonion.cpal.register_bridge import (
    VoiceRegisterBridge,
    current_register,
    frame_text_for_register,
    textmode_prompt_prefix,
)
from agents.hapax_daimonion.cpal.response_dispatch import (
    ResponseDispatch,
    dispatch_response,
)
from agents.hapax_daimonion.cpal.runner import CpalRunner
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
    "SHORT_RESPONSE_CHAR_LIMIT",
    "BackchannelDecision",
    "ChatDestination",
    "ComposedAction",
    "ConversationalRegion",
    "ConversationControlLaw",
    "ControlLawResult",
    "CorrectionTier",
    "CpalEvaluator",
    "CpalRunner",
    "ErrorDimension",
    "ErrorSignal",
    "EvaluatorResult",
    "FormulationState",
    "FormulationStream",
    "GainUpdate",
    "GroundingBridge",
    "GroundingState",
    "ImpingementAdapter",
    "ImpingementEffect",
    "LoopGainController",
    "PerceptionSignals",
    "PerceptionStream",
    "ProductionStream",
    "ResponseDispatch",
    "ResponseModality",
    "SignalCache",
    "TierComposer",
    "VoiceRegisterBridge",
    "classify_response_modality",
    "current_register",
    "dispatch_response",
    "frame_text_for_register",
    "publish_cpal_state",
    "textmode_prompt_prefix",
]

"""Formulation stream -- speculative response preparation.

Begins processing while the operator is still speaking. Manages
speculative STT, salience pre-routing, and backchannel selection.
All formulation is speculative until the evaluator commits it.

Stream 2 of 3 in the CPAL temporal architecture.
"""

from __future__ import annotations

import enum
import logging
import time
from dataclasses import dataclass

from agents.hapax_daimonion.cpal.types import ConversationalRegion, CorrectionTier

log = logging.getLogger(__name__)

_MIN_SPEECH_FOR_SPECULATION_S = 1.0
_SPECULATION_INTERVAL_S = 1.2
_BACKCHANNEL_MIN_SPEECH_S = 3.0
_BACKCHANNEL_COOLDOWN_S = 5.0

_BACKCHANNEL_REGIONS = frozenset(
    {
        ConversationalRegion.ATTENTIVE,
        ConversationalRegion.CONVERSATIONAL,
        ConversationalRegion.INTENSIVE,
    }
)


class FormulationState(enum.Enum):
    IDLE = "idle"
    SPECULATING = "speculating"
    COMMITTED = "committed"
    PRODUCING = "producing"


@dataclass(frozen=True)
class BackchannelDecision:
    tier: CorrectionTier
    signal_type: str


class FormulationStream:
    def __init__(self, stt: object, salience_router: object) -> None:
        self._stt = stt
        self._salience_router = salience_router
        self._state = FormulationState.IDLE
        self._partial_transcript: str | None = None
        self._routing_result: object | None = None
        self._last_speculation_at: float = 0.0
        self._last_backchannel_at: float = 0.0
        self._hapax_speaking: bool = False
        self._speculating: bool = False

    @property
    def state(self) -> FormulationState:
        return self._state

    @property
    def partial_transcript(self) -> str | None:
        return self._partial_transcript

    @property
    def routing_result(self) -> object | None:
        return self._routing_result

    def set_hapax_speaking(self, speaking: bool) -> None:
        self._hapax_speaking = speaking

    async def speculate(self, frames: list[bytes], *, speech_duration_s: float) -> None:
        if speech_duration_s < _MIN_SPEECH_FOR_SPECULATION_S:
            return
        if self._speculating:
            return
        now = time.monotonic()
        if now - self._last_speculation_at < _SPECULATION_INTERVAL_S:
            return

        self._speculating = True
        try:
            audio = b"".join(frames)
            transcript = await self._stt.transcribe(audio, _speculative=True)
            if transcript:
                self._partial_transcript = transcript
                self._state = FormulationState.SPECULATING
                try:
                    self._routing_result = self._salience_router.route(transcript)
                except Exception:
                    pass
            self._last_speculation_at = now
        finally:
            self._speculating = False

    def commit(self) -> None:
        if self._state == FormulationState.SPECULATING:
            self._state = FormulationState.COMMITTED
            log.info("Formulation committed: %s", (self._partial_transcript or "")[:50])

    def discard(self) -> None:
        self._state = FormulationState.IDLE
        self._partial_transcript = None
        self._routing_result = None

    def mark_producing(self) -> None:
        self._state = FormulationState.PRODUCING

    def reset(self) -> None:
        self._state = FormulationState.IDLE
        self._partial_transcript = None
        self._routing_result = None
        self._speculating = False

    def select_backchannel(
        self,
        *,
        region: ConversationalRegion,
        speech_active: bool,
        speech_duration_s: float,
        trp_probability: float,
    ) -> BackchannelDecision | None:
        if self._hapax_speaking:
            return None

        if region not in _BACKCHANNEL_REGIONS:
            return None

        now = time.monotonic()
        if now - self._last_backchannel_at < _BACKCHANNEL_COOLDOWN_S:
            return None

        if speech_active and speech_duration_s >= _BACKCHANNEL_MIN_SPEECH_S:
            if region in (ConversationalRegion.CONVERSATIONAL, ConversationalRegion.INTENSIVE):
                self._last_backchannel_at = now
                return BackchannelDecision(
                    tier=CorrectionTier.T1_PRESYNTHESIZED,
                    signal_type="vocal_backchannel",
                )

        if not speech_active and trp_probability >= 0.5:
            if region in (ConversationalRegion.CONVERSATIONAL, ConversationalRegion.INTENSIVE):
                self._last_backchannel_at = now
                return BackchannelDecision(
                    tier=CorrectionTier.T1_PRESYNTHESIZED,
                    signal_type="acknowledgment",
                )

        if not speech_active and trp_probability >= 0.3:
            self._last_backchannel_at = now
            return BackchannelDecision(
                tier=CorrectionTier.T0_VISUAL,
                signal_type="visual",
            )

        return None

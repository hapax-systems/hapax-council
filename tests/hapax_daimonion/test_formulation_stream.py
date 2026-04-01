"""Tests for CPAL formulation stream."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.hapax_daimonion.cpal.formulation_stream import (
    BackchannelDecision,
    FormulationState,
    FormulationStream,
)
from agents.hapax_daimonion.cpal.types import ConversationalRegion, CorrectionTier


class TestFormulationState:
    def test_initial_state_idle(self):
        fs = FormulationStream(stt=MagicMock(), salience_router=MagicMock())
        assert fs.state == FormulationState.IDLE

    def test_states_defined(self):
        assert len(FormulationState) == 4


class TestBackchannelSelection:
    def test_no_backchannel_at_ambient(self):
        fs = FormulationStream(stt=MagicMock(), salience_router=MagicMock())
        decision = fs.select_backchannel(
            region=ConversationalRegion.AMBIENT,
            speech_active=True,
            speech_duration_s=3.0,
            trp_probability=0.0,
        )
        assert decision is None

    def test_backchannel_at_attentive_with_speech(self):
        fs = FormulationStream(stt=MagicMock(), salience_router=MagicMock())
        decision = fs.select_backchannel(
            region=ConversationalRegion.ATTENTIVE,
            speech_active=True,
            speech_duration_s=4.0,
            trp_probability=0.0,
        )
        assert decision is None or isinstance(decision, BackchannelDecision)

    def test_acknowledgment_after_speech_end(self):
        fs = FormulationStream(stt=MagicMock(), salience_router=MagicMock())
        decision = fs.select_backchannel(
            region=ConversationalRegion.CONVERSATIONAL,
            speech_active=False,
            speech_duration_s=0.0,
            trp_probability=0.6,
        )
        if decision is not None:
            assert decision.tier in (CorrectionTier.T0_VISUAL, CorrectionTier.T1_PRESYNTHESIZED)

    def test_no_backchannel_while_hapax_speaking(self):
        fs = FormulationStream(stt=MagicMock(), salience_router=MagicMock())
        fs._hapax_speaking = True
        decision = fs.select_backchannel(
            region=ConversationalRegion.INTENSIVE,
            speech_active=True,
            speech_duration_s=5.0,
            trp_probability=0.0,
        )
        assert decision is None


class TestSpeculativeFormulation:
    @pytest.mark.asyncio
    async def test_begin_speculation_on_speech(self):
        stt = MagicMock()
        stt.transcribe = AsyncMock(return_value="hello how are")
        router = MagicMock()
        router.route.return_value = MagicMock(tier="CAPABLE", activation_score=0.5)

        fs = FormulationStream(stt=stt, salience_router=router)
        frames = [b"\x00\x00" * 480] * 50

        await fs.speculate(frames, speech_duration_s=1.5)
        assert fs.state == FormulationState.SPECULATING
        assert fs.partial_transcript is not None

    @pytest.mark.asyncio
    async def test_no_speculation_if_too_short(self):
        stt = MagicMock()
        fs = FormulationStream(stt=stt, salience_router=MagicMock())
        frames = [b"\x00\x00" * 480] * 10

        await fs.speculate(frames, speech_duration_s=0.3)
        assert fs.state == FormulationState.IDLE
        stt.transcribe.assert_not_called()

    @pytest.mark.asyncio
    async def test_commit_transitions_state(self):
        stt = MagicMock()
        stt.transcribe = AsyncMock(return_value="hello")
        fs = FormulationStream(stt=stt, salience_router=MagicMock())
        frames = [b"\x00\x00" * 480] * 50

        await fs.speculate(frames, speech_duration_s=1.5)
        fs.commit()
        assert fs.state == FormulationState.COMMITTED

    def test_discard_resets_state(self):
        fs = FormulationStream(stt=MagicMock(), salience_router=MagicMock())
        fs._state = FormulationState.SPECULATING
        fs._partial_transcript = "hello"
        fs.discard()
        assert fs.state == FormulationState.IDLE
        assert fs.partial_transcript is None

    def test_cannot_commit_from_idle(self):
        fs = FormulationStream(stt=MagicMock(), salience_router=MagicMock())
        fs.commit()
        assert fs.state == FormulationState.IDLE

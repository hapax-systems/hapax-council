"""Tests for the cognitive loop — Batches 1-6.

Self-contained, unittest.mock only, asyncio_mode="auto".
Covers: CognitiveLoop, TurnPhase, SpeculativeTranscriber,
ConversationalModel, PerceptionBackend interface, active silence.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

from agents.hapax_voice.cognitive_loop import (
    TICK_INTERVAL_S,
    CognitiveLoop,
    TurnPhase,
)
from agents.hapax_voice.conversational_model import ConversationalModel
from agents.hapax_voice.speculative_stt import SpeculativeTranscriber

# ── Helpers ────────────────────────────────────────────────────────────


def _mock_buffer(*, speech_active=False, is_speaking=False, speech_duration_s=0.0):
    """Create a mock ConversationBuffer with controllable state."""
    buf = MagicMock()
    type(buf).speech_active = PropertyMock(return_value=speech_active)
    type(buf).is_speaking = PropertyMock(return_value=is_speaking)
    type(buf).speech_duration_s = PropertyMock(return_value=speech_duration_s)
    buf.speech_frames_snapshot = []
    buf.get_utterance.return_value = None
    return buf


def _mock_pipeline(*, state="listening", is_active=True, turn_count=0):
    """Create a mock ConversationPipeline."""
    from agents.hapax_voice.conversation_pipeline import ConvState

    pipe = MagicMock()
    state_map = {
        "idle": ConvState.IDLE,
        "listening": ConvState.LISTENING,
        "transcribing": ConvState.TRANSCRIBING,
        "thinking": ConvState.THINKING,
        "speaking": ConvState.SPEAKING,
    }
    type(pipe).state = PropertyMock(return_value=state_map.get(state, ConvState.LISTENING))
    type(pipe).is_active = PropertyMock(return_value=is_active)
    type(pipe).turn_count = PropertyMock(return_value=turn_count)
    pipe._activity_mode = "idle"
    pipe.process_utterance = AsyncMock()
    return pipe


def _mock_session():
    """Create a mock SessionManager."""
    session = MagicMock()
    session.is_active = True
    session.is_timed_out = False
    session.mark_activity = MagicMock()
    session.set_speaker = MagicMock()
    return session


def _make_loop(**overrides):
    """Create a CognitiveLoop with sensible mocked defaults."""
    defaults = dict(
        buffer=_mock_buffer(),
        pipeline=_mock_pipeline(),
        session=_mock_session(),
        event_log=MagicMock(),
    )
    defaults.update(overrides)
    return CognitiveLoop(**defaults)


# ── Batch 1: Mechanical Extraction ────────────────────────────────────


class TestCognitiveLoopBasic:
    """Batch 1: CognitiveLoop created and can start/stop."""

    def test_initial_state(self):
        loop = _make_loop()
        assert not loop.is_running
        assert loop.turn_phase == TurnPhase.MUTUAL_SILENCE

    @pytest.mark.asyncio
    async def test_run_stops_when_pipeline_inactive(self):
        pipeline = _mock_pipeline(is_active=False)
        loop = _make_loop(pipeline=pipeline)
        await asyncio.wait_for(loop.run(), timeout=1.0)
        assert not loop.is_running

    @pytest.mark.asyncio
    async def test_run_stops_on_stop_signal(self):
        loop = _make_loop()
        task = asyncio.create_task(loop.run())
        await asyncio.sleep(0.05)
        assert loop.is_running
        loop.stop_loop()
        await asyncio.wait_for(task, timeout=1.0)
        assert not loop.is_running

    @pytest.mark.asyncio
    async def test_run_stops_on_session_timeout(self):
        session = _mock_session()
        session.is_timed_out = True
        loop = _make_loop(session=session)
        await asyncio.wait_for(loop.run(), timeout=1.0)
        assert not loop.is_running

    @pytest.mark.asyncio
    async def test_utterance_dispatch(self):
        """Utterance from buffer is dispatched to pipeline."""
        buf = _mock_buffer()
        buf.get_utterance.return_value = b"\x00" * 3200  # 0.1s of audio
        pipeline = _mock_pipeline(state="listening")
        loop = _make_loop(buffer=buf, pipeline=pipeline)

        # Utterance dispatched directly via _handle_utterance
        loop._running = True
        await loop._handle_utterance(b"\x00" * 3200)
        pipeline.process_utterance.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_utterance_dispatched_during_mutual_silence(self):
        """Utterances are polled even during MUTUAL_SILENCE (not just TRANSITION)."""
        buf = _mock_buffer(speech_active=False, is_speaking=False)
        buf.get_utterance.return_value = b"\x00" * 3200
        pipeline = _mock_pipeline(state="listening")
        loop = _make_loop(buffer=buf, pipeline=pipeline)

        # Run a few ticks — phase will be MUTUAL_SILENCE
        task = asyncio.create_task(loop.run())
        await asyncio.sleep(TICK_INTERVAL_S * 3)
        loop.stop_loop()
        await asyncio.wait_for(task, timeout=1.0)

        # Utterance should have been picked up and dispatched
        pipeline.process_utterance.assert_awaited()

    @pytest.mark.asyncio
    async def test_utterance_dispatched_during_operator_pausing(self):
        """Utterances are polled during OPERATOR_PAUSING phase."""
        buf = _mock_buffer(speech_active=False, is_speaking=False)
        buf.get_utterance.return_value = b"\x00" * 3200
        pipeline = _mock_pipeline(state="listening")
        loop = _make_loop(buffer=buf, pipeline=pipeline)

        # Set up pausing state
        loop._running = True
        loop._last_operator_speaking_at = time.monotonic() - 0.5
        assert loop._derive_phase() == TurnPhase.OPERATOR_PAUSING

        # Simulate one tick's utterance poll
        utterance = loop._buffer.get_utterance()
        assert utterance is not None
        await loop._handle_utterance(utterance)
        pipeline.process_utterance.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_utterance_not_dispatched_during_hapax_speaking(self):
        """Utterances are NOT polled during HAPAX_SPEAKING."""
        buf = _mock_buffer(speech_active=False, is_speaking=True)
        buf.get_utterance.return_value = b"\x00" * 3200
        pipeline = _mock_pipeline(state="listening")
        loop = _make_loop(buffer=buf, pipeline=pipeline)

        # Run a few ticks — phase will be HAPAX_SPEAKING
        task = asyncio.create_task(loop.run())
        await asyncio.sleep(TICK_INTERVAL_S * 3)
        loop.stop_loop()
        await asyncio.wait_for(task, timeout=1.0)

        # Utterance should NOT have been dispatched
        pipeline.process_utterance.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_speaker_verification_gates_first_utterance(self):
        """Speaker verification accumulates audio before processing."""
        speaker_id = MagicMock()
        buf = _mock_buffer()
        pipeline = _mock_pipeline(state="transcribing")
        session = _mock_session()

        loop = _make_loop(
            buffer=buf,
            pipeline=pipeline,
            session=session,
            speaker_identifier=speaker_id,
        )

        # Short audio — not enough for verification, but fail-open processes it
        short_audio = b"\x00" * 1000
        await loop._handle_utterance(short_audio)
        # Audio accumulated but not enough to verify — falls through to process
        pipeline.process_utterance.assert_awaited_once()


# ── Batch 2: Turn Phase Tracking ──────────────────────────────────────


class TestTurnPhaseTracking:
    """Batch 2: Phase derivation from buffer + pipeline state."""

    def test_operator_speaking(self):
        buf = _mock_buffer(speech_active=True, is_speaking=False)
        loop = _make_loop(buffer=buf)
        assert loop._derive_phase() == TurnPhase.OPERATOR_SPEAKING

    def test_hapax_speaking(self):
        buf = _mock_buffer(speech_active=False, is_speaking=True)
        loop = _make_loop(buffer=buf)
        assert loop._derive_phase() == TurnPhase.HAPAX_SPEAKING

    def test_barge_in_operator_priority(self):
        buf = _mock_buffer(speech_active=True, is_speaking=True)
        loop = _make_loop(buffer=buf)
        assert loop._derive_phase() == TurnPhase.OPERATOR_SPEAKING

    def test_transition_during_transcribing(self):
        buf = _mock_buffer(speech_active=False, is_speaking=False)
        pipeline = _mock_pipeline(state="transcribing")
        loop = _make_loop(buffer=buf, pipeline=pipeline)
        assert loop._derive_phase() == TurnPhase.TRANSITION

    def test_transition_during_thinking(self):
        buf = _mock_buffer(speech_active=False, is_speaking=False)
        pipeline = _mock_pipeline(state="thinking")
        loop = _make_loop(buffer=buf, pipeline=pipeline)
        assert loop._derive_phase() == TurnPhase.TRANSITION

    def test_operator_pausing_within_threshold(self):
        buf = _mock_buffer(speech_active=False, is_speaking=False)
        pipeline = _mock_pipeline(state="listening")
        loop = _make_loop(buffer=buf, pipeline=pipeline)
        loop._last_operator_speaking_at = time.monotonic() - 0.5  # 500ms ago
        assert loop._derive_phase() == TurnPhase.OPERATOR_PAUSING

    def test_mutual_silence_after_threshold(self):
        buf = _mock_buffer(speech_active=False, is_speaking=False)
        pipeline = _mock_pipeline(state="listening")
        loop = _make_loop(buffer=buf, pipeline=pipeline)
        loop._last_operator_speaking_at = time.monotonic() - 5.0  # 5s ago
        assert loop._derive_phase() == TurnPhase.MUTUAL_SILENCE

    def test_mutual_silence_no_prior_speech(self):
        buf = _mock_buffer(speech_active=False, is_speaking=False)
        pipeline = _mock_pipeline(state="listening")
        loop = _make_loop(buffer=buf, pipeline=pipeline)
        assert loop._derive_phase() == TurnPhase.MUTUAL_SILENCE


class TestPerceptionBackendInterface:
    """Batch 2: CognitiveLoop satisfies PerceptionBackend protocol."""

    def test_name(self):
        loop = _make_loop()
        assert loop.name == "cognitive_loop"

    def test_provides(self):
        loop = _make_loop()
        assert "turn_phase" in loop.provides
        assert "cognitive_readiness" in loop.provides
        assert "conversation_temperature" in loop.provides
        assert "predicted_tier" in loop.provides

    def test_tier_is_fast(self):
        from agents.hapax_voice.perception import PerceptionTier

        loop = _make_loop()
        assert loop.tier == PerceptionTier.FAST

    def test_available(self):
        loop = _make_loop()
        assert loop.available()

    def test_contribute_updates_behaviors(self):
        from agents.hapax_voice.primitives import Behavior

        loop = _make_loop()
        loop._turn_phase = TurnPhase.OPERATOR_SPEAKING

        behaviors = {
            "turn_phase": Behavior(""),
            "cognitive_readiness": Behavior(0.0),
            "conversation_temperature": Behavior(0.0),
            "predicted_tier": Behavior(""),
        }
        loop.contribute(behaviors)
        assert behaviors["turn_phase"].value == "operator_speaking"


# ── Batch 3: Speculative STT ─────────────────────────────────────────


class TestSpeculativeTranscriber:
    """Batch 3: Speculative partial STT during operator speech."""

    @pytest.mark.asyncio
    async def test_skips_short_speech(self):
        stt = MagicMock()
        stt.transcribe = AsyncMock(return_value="hello")
        spec = SpeculativeTranscriber(stt, interval_s=0.1)

        result = await spec.maybe_speculate([], 0.5)
        assert result is None
        stt.transcribe.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_transcribes_on_interval(self):
        stt = MagicMock()
        stt.transcribe = AsyncMock(return_value="hello world")
        spec = SpeculativeTranscriber(stt, interval_s=0.0)  # no interval gate

        frames = [b"\x00" * 960]
        result = await spec.maybe_speculate(frames, 1.5)
        assert result == "hello world"
        stt.transcribe.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_respects_interval(self):
        stt = MagicMock()
        stt.transcribe = AsyncMock(return_value="hello")
        spec = SpeculativeTranscriber(stt, interval_s=100.0)  # very long interval

        frames = [b"\x00" * 960]
        # First call works
        result = await spec.maybe_speculate(frames, 1.5)
        assert result == "hello"

        # Second call skipped (interval not elapsed)
        result = await spec.maybe_speculate(frames, 2.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_skips_duplicate_partial(self):
        stt = MagicMock()
        stt.transcribe = AsyncMock(return_value="hello")
        spec = SpeculativeTranscriber(stt, interval_s=0.0)

        frames = [b"\x00" * 960]
        result1 = await spec.maybe_speculate(frames, 1.5)
        assert result1 == "hello"

        # Same transcript — returns None
        result2 = await spec.maybe_speculate(frames, 2.0)
        assert result2 is None

    def test_reset_clears_state(self):
        stt = MagicMock()
        spec = SpeculativeTranscriber(stt, interval_s=1.2)
        spec._last_partial = "something"
        spec._last_speculate_at = 999.0
        spec.reset()
        assert spec._last_partial == ""
        assert spec._last_speculate_at == 0.0


class TestSpeculativePreRouting:
    """Batch 3: Speculative STT feeds salience router for pre-routing."""

    @pytest.mark.asyncio
    async def test_pre_routing_on_partial(self):
        stt = MagicMock()
        stt.transcribe = AsyncMock(return_value="what's the weather")

        router = MagicMock()
        decision = MagicMock()
        decision.tier.name = "FAST"
        router.route.return_value = decision

        spec = SpeculativeTranscriber(stt, interval_s=0.0)
        buf = _mock_buffer(speech_active=True, speech_duration_s=2.0)
        buf.speech_frames_snapshot = [b"\x00" * 960]

        loop = _make_loop(
            buffer=buf,
            salience_router=router,
            speculative_stt=spec,
        )
        loop._running = True
        await loop._tick_operator_speaking()
        assert loop.predicted_tier == "FAST"


# ── Batch 4: ConversationalModel ──────────────────────────────────────


class TestConversationalModel:
    """Batch 4: Persistent cross-turn conversation state."""

    def test_initial_state(self):
        model = ConversationalModel()
        assert model.turn_count == 0
        assert model.conversation_temperature == 0.0
        assert model.operator_engagement == 0.5

    def test_on_utterance_increments_turn_count(self):
        model = ConversationalModel()
        model.on_utterance("hello", "FAST", 1.0)
        assert model.turn_count == 1

    def test_rapid_turns_raise_temperature(self):
        model = ConversationalModel()
        model.on_utterance("hello", "FAST", 1.0)
        model.on_response("hi there", 0.5)
        # Simulate rapid turn (response just happened)
        model.on_utterance("how are you", "FAST", 1.0)
        assert model.conversation_temperature > 0

    def test_tier_escalation_raises_temperature(self):
        model = ConversationalModel()
        model.on_utterance("hello", "LOCAL", 1.0)
        model.on_response("hi", 0.3)
        model.on_utterance("explain quantum computing", "CAPABLE", 3.0)
        assert model.conversation_temperature > 0

    def test_silence_decays_temperature(self):
        model = ConversationalModel()
        model.conversation_temperature = 0.8
        # 15 seconds of silence
        for _ in range(100):
            model.on_silence_tick(0.15)
        assert model.conversation_temperature < 0.4

    def test_prolonged_silence_reaches_zero(self):
        model = ConversationalModel()
        model.conversation_temperature = 0.5
        for _ in range(1000):
            model.on_silence_tick(0.15)
        assert model.conversation_temperature == 0.0

    def test_engagement_tracks_speech_duration(self):
        model = ConversationalModel()
        model.operator_engagement = 0.5
        # Long speech = high engagement signal
        model.on_utterance("long utterance here", "FAST", 4.0)
        assert model.operator_engagement > 0.5

    def test_reset(self):
        model = ConversationalModel()
        model.on_utterance("hello", "FAST", 1.0)
        model.conversation_temperature = 0.8
        model.reset()
        assert model.turn_count == 0
        assert model.conversation_temperature == 0.0
        assert len(model.tier_history) == 0


# ── Batch 5: Pipeline Integration ────────────────────────────────────


class TestPipelineIntegration:
    """Batch 5: Cognitive loop drives everything."""

    @pytest.mark.asyncio
    async def test_model_updated_on_utterance_dispatch(self):
        model = ConversationalModel()
        pipeline = _mock_pipeline(state="listening")

        loop = _make_loop(
            pipeline=pipeline,
            conversational_model=model,
        )
        loop._running = True
        await loop._handle_utterance(b"\x00" * 32000)  # 1s audio
        assert model.turn_count == 1

    @pytest.mark.asyncio
    async def test_cognitive_readiness_increases_with_speaker_verified(self):
        loop = _make_loop()
        loop._running = True
        loop._speaker_verified = True
        readiness = loop._compute_readiness()
        assert readiness >= 0.7

    @pytest.mark.asyncio
    async def test_cognitive_readiness_low_during_transition(self):
        loop = _make_loop()
        loop._running = True
        loop._turn_phase = TurnPhase.TRANSITION
        readiness = loop._compute_readiness()
        assert readiness <= 0.2


# ── Batch 6: Active Silence Handling ──────────────────────────────────


class TestActiveSilence:
    """Batch 6: Contextual actions during mutual silence (feature-flagged)."""

    @pytest.mark.asyncio
    async def test_no_action_when_disabled(self):
        loop = _make_loop(active_silence_enabled=False)
        loop._running = True
        loop._turn_phase = TurnPhase.MUTUAL_SILENCE
        loop._mutual_silence_start = time.monotonic() - 30
        # Should not raise or do anything
        await loop._tick_mutual_silence()

    @pytest.mark.asyncio
    async def test_no_action_during_high_temperature(self):
        model = ConversationalModel()
        model.conversation_temperature = 0.8
        loop = _make_loop(
            active_silence_enabled=True,
            conversational_model=model,
        )
        loop._running = True
        loop._mutual_silence_start = time.monotonic() - 30
        await loop._handle_silence(30.0)
        # Wind-down should NOT be sent during high temperature
        assert not loop._wind_down_sent

    @pytest.mark.asyncio
    async def test_wind_down_on_extended_silence(self):
        model = ConversationalModel()
        model.conversation_temperature = 0.1
        loop = _make_loop(
            active_silence_enabled=True,
            conversational_model=model,
            silence_winddown_threshold_s=5.0,
        )
        loop._running = True
        await loop._handle_silence(10.0)
        assert loop._wind_down_sent

    @pytest.mark.asyncio
    async def test_wind_down_only_sent_once(self):
        model = ConversationalModel()
        model.conversation_temperature = 0.0
        loop = _make_loop(
            active_silence_enabled=True,
            conversational_model=model,
            silence_winddown_threshold_s=5.0,
        )
        loop._running = True
        await loop._handle_silence(10.0)
        assert loop._wind_down_sent
        loop._wind_down_sent = True  # already set
        # Second call should not crash or change state
        await loop._handle_silence(15.0)


# ── Response timing from phase transitions (#2) ──────────────────────


class TestResponseTiming:
    """on_response called when HAPAX_SPEAKING ends, using phase transition timing."""

    def test_transition_records_response_start(self):
        model = ConversationalModel()
        loop = _make_loop(conversational_model=model)
        loop._running = True

        # Transition to TRANSITION phase records start time
        loop._on_phase_transition(TurnPhase.OPERATOR_PAUSING, TurnPhase.TRANSITION)
        assert loop._response_start_at > 0

    def test_hapax_speaking_end_calls_on_response(self):
        model = ConversationalModel()
        loop = _make_loop(conversational_model=model)
        loop._running = True

        # Start timing
        loop._response_start_at = time.monotonic() - 1.5  # 1.5s ago
        # Transition from HAPAX_SPEAKING → triggers on_response
        loop._on_phase_transition(TurnPhase.HAPAX_SPEAKING, TurnPhase.MUTUAL_SILENCE)

        assert model.last_response_at > 0
        assert loop._response_start_at == 0.0  # cleared

    def test_no_on_response_without_start(self):
        model = ConversationalModel()
        loop = _make_loop(conversational_model=model)
        loop._running = True

        # No response_start_at set
        loop._on_phase_transition(TurnPhase.HAPAX_SPEAKING, TurnPhase.MUTUAL_SILENCE)
        assert model.last_response_at == 0.0  # not called


# ── PerceptionEngine.replace_backend (#3) ─────────────────────────────


class TestReplaceBackend:
    """replace_backend swaps an existing backend without conflict."""

    def test_replace_existing_backend(self):
        from agents.hapax_voice.perception import PerceptionEngine

        engine = PerceptionEngine(
            presence=MagicMock(
                latest_vad_confidence=0.0,
                face_detected=False,
                face_count=0,
                operator_visible=False,
                guest_count=0,
                score="likely_absent",
            ),
            workspace_monitor=MagicMock(latest_analysis=None),
        )

        loop1 = _make_loop()
        engine.register_backend(loop1)
        assert "cognitive_loop" in engine.registered_backends

        loop2 = _make_loop()
        engine.replace_backend(loop2)
        assert engine.registered_backends["cognitive_loop"] is loop2

    def test_replace_nonexistent_is_register(self):
        from agents.hapax_voice.perception import PerceptionEngine

        engine = PerceptionEngine(
            presence=MagicMock(
                latest_vad_confidence=0.0,
                face_detected=False,
                face_count=0,
                operator_visible=False,
                guest_count=0,
                score="likely_absent",
            ),
            workspace_monitor=MagicMock(latest_analysis=None),
        )

        loop = _make_loop()
        engine.replace_backend(loop)  # should not raise
        assert "cognitive_loop" in engine.registered_backends


# ── Speculative STT reset on utterance dispatch (#7) ──────────────────


class TestSpeculativeResetOnDispatch:
    """Speculative STT is reset before final utterance to avoid executor contention."""

    @pytest.mark.asyncio
    async def test_speculative_reset_before_process(self):
        spec = SpeculativeTranscriber(MagicMock(), interval_s=0.0)
        spec._last_partial = "some partial"
        spec._pending = False

        pipeline = _mock_pipeline(state="listening")
        loop = _make_loop(pipeline=pipeline, speculative_stt=spec)
        loop._running = True

        await loop._handle_utterance(b"\x00" * 3200)

        # Speculative state should be reset before pipeline.process_utterance
        assert spec._last_partial == ""
        assert spec._last_speculate_at == 0.0


# ── ConversationBuffer properties ─────────────────────────────────────


class TestConversationBufferProperties:
    """Batch 2-3: Read-only properties added to ConversationBuffer."""

    def test_speech_active_property(self):
        from agents.hapax_voice.conversation_buffer import ConversationBuffer

        buf = ConversationBuffer()
        assert buf.speech_active is False
        buf._speech_active = True
        assert buf.speech_active is True

    def test_is_speaking_property(self):
        from agents.hapax_voice.conversation_buffer import ConversationBuffer

        buf = ConversationBuffer()
        assert buf.is_speaking is False
        buf.set_speaking(True)
        assert buf.is_speaking is True

    def test_speech_duration_s_zero_when_not_speaking(self):
        from agents.hapax_voice.conversation_buffer import ConversationBuffer

        buf = ConversationBuffer()
        assert buf.speech_duration_s == 0.0

    def test_speech_duration_s_positive_during_speech(self):
        from agents.hapax_voice.conversation_buffer import ConversationBuffer

        buf = ConversationBuffer()
        buf._speech_active = True
        buf._speech_start_time = time.monotonic() - 2.0
        assert buf.speech_duration_s >= 1.5

    def test_speech_frames_snapshot_is_copy(self):
        from agents.hapax_voice.conversation_buffer import ConversationBuffer

        buf = ConversationBuffer()
        buf._speech_frames = [b"\x00", b"\x01"]
        snap = buf.speech_frames_snapshot
        assert snap == [b"\x00", b"\x01"]
        snap.append(b"\x02")
        assert len(buf._speech_frames) == 2  # original unchanged


# ── Config fields ─────────────────────────────────────────────────────


class TestConfigFields:
    """Batch 6: Active silence config fields."""

    def test_active_silence_defaults(self):
        from agents.hapax_voice.config import VoiceConfig

        cfg = VoiceConfig()
        assert cfg.active_silence_enabled is False
        assert cfg.silence_notification_threshold_s == 8.0
        assert cfg.silence_winddown_threshold_s == 20.0

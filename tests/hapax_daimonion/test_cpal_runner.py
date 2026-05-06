"""Tests for CPAL runner."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.hapax_daimonion.cpal.destination_channel import DestinationChannel
from agents.hapax_daimonion.cpal.runner import CpalRunner, SpeechEventKind
from agents.hapax_daimonion.cpal.types import ConversationalRegion
from shared.programme import ProgrammeContent


class TestCpalRunnerLifecycle:
    def _make_runner(self):
        buffer = MagicMock()
        buffer.speech_active = False
        buffer.speech_duration_s = 0.0
        buffer.is_speaking = False
        buffer.get_utterance.return_value = None
        buffer.speech_frames_snapshot = []

        stt = MagicMock()
        stt.transcribe = AsyncMock(return_value="")

        router = MagicMock()
        router.route.return_value = MagicMock(tier="CAPABLE")

        return CpalRunner(
            buffer=buffer,
            stt=stt,
            salience_router=router,
        )

    def test_initial_state(self):
        runner = self._make_runner()
        assert not runner.is_running
        assert runner.tick_count == 0

    @pytest.mark.asyncio
    async def test_run_and_stop(self):
        runner = self._make_runner()

        async def stop_after_ticks():
            while runner.tick_count < 3:
                await asyncio.sleep(0.05)
            runner.stop()

        await asyncio.gather(runner.run(), stop_after_ticks())
        assert not runner.is_running
        assert runner.tick_count >= 3

    @pytest.mark.asyncio
    async def test_gain_rises_during_speech(self):
        runner = self._make_runner()
        # Simulate operator speaking
        runner._buffer.speech_active = True

        async def stop_after():
            while runner.tick_count < 5:
                await asyncio.sleep(0.05)
            runner.stop()

        await asyncio.gather(runner.run(), stop_after())
        assert runner.evaluator.gain_controller.gain > 0.0

    @pytest.mark.asyncio
    async def test_utterance_detected(self):
        runner = self._make_runner()
        runner._buffer.get_utterance.return_value = b"\x00\x01" * 500

        async def stop_after():
            while runner.tick_count < 2:
                await asyncio.sleep(0.05)
            runner.stop()

        await asyncio.gather(runner.run(), stop_after())
        # Utterance was consumed (get_utterance called)
        runner._buffer.get_utterance.assert_called()

    @pytest.mark.asyncio
    async def test_t1_acknowledgement_uses_destination_gate(self):
        runner = self._make_runner()
        runner._audio_output = MagicMock()
        runner._pipeline = AsyncMock()
        runner._signal_cache.select = MagicMock(return_value=("ack", b"\x00\x01"))
        runner._last_speech_end = 0.0
        decision = SimpleNamespace(
            allowed=True,
            destination=DestinationChannel.PRIVATE,
            reason_code="private_assistant_monitor_bound",
            safety_gate={"context_default": "private_or_drop"},
            target="hapax-private",
            media_role="Assistant",
        )

        with (
            patch(
                "agents.hapax_daimonion.cpal.runner.resolve_playback_decision",
                return_value=decision,
            ),
            patch(
                "agents.hapax_daimonion.cpal.runner.ConversationalRegion.from_gain",
                return_value=ConversationalRegion.ATTENTIVE,
            ),
            patch("agents.hapax_daimonion.cpal.runner.record_destination_decision"),
        ):
            await runner._process_utterance(b"\x00\x01")

        runner._audio_output.write.assert_called_once_with(
            b"\x00\x01",
            target="hapax-private",
            media_role="Assistant",
        )

    @pytest.mark.asyncio
    async def test_t1_acknowledgement_drops_when_destination_blocked(self):
        runner = self._make_runner()
        runner._audio_output = MagicMock()
        runner._pipeline = AsyncMock()
        runner._signal_cache.select = MagicMock(return_value=("ack", b"\x00\x01"))
        runner._last_speech_end = 0.0
        blocked = SimpleNamespace(
            allowed=False,
            destination=DestinationChannel.PRIVATE,
            reason_code="private_monitor_status_missing",
            safety_gate={"context_default": "private_or_drop"},
            target=None,
            media_role=None,
        )

        with (
            patch(
                "agents.hapax_daimonion.cpal.runner.resolve_playback_decision",
                return_value=blocked,
            ),
            patch(
                "agents.hapax_daimonion.cpal.runner.ConversationalRegion.from_gain",
                return_value=ConversationalRegion.ATTENTIVE,
            ),
            patch("agents.hapax_daimonion.cpal.runner.record_destination_decision"),
            patch("agents.hapax_daimonion.cpal.runner.record_drop") as record_drop,
        ):
            await runner._process_utterance(b"\x00\x01")

        runner._audio_output.write.assert_not_called()
        assert record_drop.call_args_list[0].kwargs["reason"] == "private_monitor_status_missing"

    @pytest.mark.asyncio
    async def test_missing_pipeline_does_not_record_response_speech_event(self):
        runner = self._make_runner()
        runner._pipeline = None
        runner._signal_cache.select = MagicMock(return_value=None)
        runner._last_speech_end = 0.0

        await runner._process_utterance(b"\x00\x01")

        assert runner._last_speech_end == 0.0
        assert list(runner._recent_speech_events) == []

    @pytest.mark.asyncio
    async def test_pipeline_exception_does_not_record_response_speech_event(self):
        runner = self._make_runner()
        runner._signal_cache.select = MagicMock(return_value=None)
        pipeline = AsyncMock()
        pipeline._running = True
        pipeline.process_utterance.side_effect = RuntimeError("boom")
        runner._pipeline = pipeline

        await runner._process_utterance(b"\x00\x01")

        assert list(runner._recent_speech_events) == []

    @pytest.mark.asyncio
    async def test_successful_pipeline_records_response_speech_event(self):
        runner = self._make_runner()
        runner._signal_cache.select = MagicMock(return_value=None)
        pipeline = AsyncMock()
        pipeline._running = True
        runner._pipeline = pipeline

        await runner._process_utterance(b"\x00\x01")

        assert runner._last_speech_end > 0.0
        assert len(runner._recent_speech_events) == 1
        assert runner._recent_speech_events[0].kind is SpeechEventKind.RESPONSE

    @pytest.mark.asyncio
    async def test_session_timeout_goodbye_uses_destination_gate(self):
        runner = self._make_runner()
        daemon = MagicMock()
        daemon.session.is_active = True
        daemon.session.is_timed_out = True
        daemon.notifications.pending_count = 0
        daemon._conversation_pipeline._audio_output = MagicMock()
        daemon.tts.synthesize.return_value = b"\x00\x01"
        runner._daemon = daemon
        decision = SimpleNamespace(
            allowed=True,
            destination=DestinationChannel.PRIVATE,
            reason_code="private_assistant_monitor_bound",
            safety_gate={"context_default": "private_or_drop"},
            target="hapax-private",
            media_role="Assistant",
        )
        playback = SimpleNamespace(
            status="completed",
            completed=True,
            returncode=0,
            duration_s=0.1,
            timeout_s=5.0,
            error=None,
        )

        with (
            patch(
                "agents.hapax_daimonion.cpal.runner.resolve_playback_decision",
                return_value=decision,
            ),
            patch("agents.hapax_daimonion.cpal.runner.record_destination_decision"),
            patch("agents.hapax_daimonion.pw_audio_output.play_pcm", return_value=playback) as play,
            patch("agents.hapax_daimonion.cpal.runner.record_playback_result"),
            patch("agents.hapax_daimonion.session_events.close_session", new=AsyncMock()),
        ):
            await runner._tick(0.1)

        play.assert_called_once_with(b"\x00\x01", 24000, 1, "hapax-private", "Assistant")

    @pytest.mark.asyncio
    async def test_process_impingement(self):
        runner = self._make_runner()
        imp = MagicMock()
        imp.source = "stimmung"
        imp.strength = 0.9
        imp.content = {"metric": "stimmung_critical", "narrative": "System critical"}
        imp.interrupt_token = None

        await runner.process_impingement(imp)
        assert runner.evaluator.gain_controller.gain > 0.0

    @pytest.mark.asyncio
    async def test_inactive_pipeline_records_private_drop(self):
        runner = self._make_runner()
        runner._pipeline = None
        runner._impingement_adapter.adapt = MagicMock(
            return_value=SimpleNamespace(
                gain_update=None,
                should_surface=True,
                narrative="Surface this narration.",
                error_boost=0.5,
            )
        )
        imp = MagicMock()
        imp.source = "stimmung"
        imp.content = {"narrative": "Surface this narration."}
        decision = SimpleNamespace(
            allowed=True,
            destination=DestinationChannel.PRIVATE,
            reason_code="private_assistant_monitor_bound",
            safety_gate={"context_default": "private_or_drop"},
            target="hapax-private",
            media_role="Assistant",
        )

        with (
            patch(
                "agents.hapax_daimonion.cpal.runner.resolve_playback_decision",
                return_value=decision,
            ),
            patch("agents.hapax_daimonion.cpal.runner.record_destination_decision"),
            patch("agents.hapax_daimonion.cpal.runner.record_drop") as record_drop,
        ):
            await runner.process_impingement(imp)

        record_drop.assert_called_once()
        assert record_drop.call_args.kwargs["reason"] == "pipeline_unavailable"
        assert record_drop.call_args.kwargs["destination"] == "private"

    @pytest.mark.asyncio
    async def test_private_route_blocked_before_spontaneous_speech_pipeline(self):
        runner = self._make_runner()
        runner._pipeline = AsyncMock()
        runner._impingement_adapter.adapt = MagicMock(
            return_value=SimpleNamespace(
                gain_update=None,
                should_surface=True,
                narrative="Private sidechat response.",
                error_boost=0.5,
            )
        )
        imp = MagicMock()
        imp.source = "operator.sidechat"
        imp.content = {"channel": "sidechat", "narrative": "Private sidechat response."}
        blocked_decision = SimpleNamespace(
            allowed=False,
            destination=DestinationChannel.PRIVATE,
            reason_code="private_monitor_status_missing",
            safety_gate={"private_route_reason_code": "private_monitor_status_missing"},
            target=None,
            media_role=None,
        )

        with (
            patch(
                "agents.hapax_daimonion.cpal.runner.resolve_playback_decision",
                return_value=blocked_decision,
            ),
            patch("agents.hapax_daimonion.cpal.runner.record_destination_decision"),
            patch("agents.hapax_daimonion.cpal.runner.record_drop") as record_drop,
        ):
            await runner.process_impingement(imp)

        record_drop.assert_called_once()
        assert record_drop.call_args.kwargs["reason"] == "private_monitor_status_missing"
        assert record_drop.call_args.kwargs["destination"] == "private"
        runner._pipeline.generate_spontaneous_speech.assert_not_called()

    @pytest.mark.asyncio
    async def test_autonomous_narrative_timeout_not_marked_spoken(self, caplog):
        runner = self._make_runner()
        daemon = MagicMock()
        daemon.tts.synthesize.return_value = b"\x00" * 100
        runner._daemon = daemon
        runner._impingement_adapter.adapt = MagicMock(
            return_value=SimpleNamespace(
                gain_update=None,
                should_surface=False,
                narrative="Composed public narration.",
                error_boost=0.0,
            )
        )
        imp = MagicMock()
        imp.source = "autonomous_narrative"
        imp.content = {
            "narrative": "Composed public narration.",
            "impulse_id": "impulse-timeout-1",
        }
        playback_result = SimpleNamespace(
            status="timeout",
            completed=False,
            returncode=None,
            duration_s=30.0,
            timeout_s=35.0,
            error="timeout",
        )
        decision = SimpleNamespace(
            allowed=True,
            destination=DestinationChannel.LIVESTREAM,
            reason_code="broadcast_voice_authorized",
            safety_gate={"audio_safe_for_broadcast": {"safe": True}},
            target="hapax-voice-fx-capture",
            media_role="Broadcast",
        )

        with (
            patch(
                "agents.hapax_daimonion.cpal.runner.resolve_playback_decision",
                return_value=decision,
            ),
            patch("agents.hapax_daimonion.pw_audio_output.play_pcm", return_value=playback_result),
            patch("shared.programme_store.default_store") as default_store,
            patch("agents.hapax_daimonion.cpal.runner.record_destination_decision"),
            patch("agents.hapax_daimonion.cpal.runner.record_tts_synthesis"),
            patch("agents.hapax_daimonion.cpal.runner.record_playback_result") as record_playback,
            caplog.at_level("INFO", logger="agents.hapax_daimonion.cpal.runner"),
        ):
            default_store.return_value.active_programme.return_value = None
            await runner.process_impingement(imp)

        record_playback.assert_called_once()
        assert record_playback.call_args.kwargs["impulse_id"] == "impulse-timeout-1"
        assert "Autonomous narrative spoken" not in caplog.text
        assert "broadcast_bias_soft_prior" not in imp.content
        assert "voice_output_destination" not in imp.content
        assert "broadcast_intent" not in imp.content

    @pytest.mark.asyncio
    async def test_live_prior_prepared_segment_does_not_suppress_autonomous_narration(
        self,
        monkeypatch,
    ):
        runner = self._make_runner()
        daemon = MagicMock()
        daemon.tts.synthesize.return_value = b"\x00\x01" * 100
        runner._daemon = daemon
        runner._impingement_adapter.adapt = MagicMock(
            return_value=SimpleNamespace(
                gain_update=None,
                should_surface=False,
                narrative="Composed live-prior narration.",
                error_boost=0.0,
            )
        )
        imp = MagicMock()
        imp.source = "autonomous_narrative"
        imp.content = {
            "narrative": "Composed live-prior narration.",
            "impulse_id": "impulse-live-prior",
        }
        active = SimpleNamespace(
            content=ProgrammeContent(
                delivery_mode="live_prior",
                prepared_script=["Prepared text is prior context, not TTS ownership."],
            )
        )
        decision = SimpleNamespace(
            allowed=True,
            destination=DestinationChannel.PRIVATE,
            reason_code="private_assistant_monitor_bound",
            safety_gate={"context_default": "private_or_drop"},
            target="hapax-private",
            media_role="Assistant",
        )
        playback_result = SimpleNamespace(
            status="completed",
            completed=True,
            returncode=0,
            duration_s=0.1,
            timeout_s=5.0,
            error=None,
        )

        async def no_sleep(_delay: float) -> None:
            return None

        monkeypatch.delenv("HAPAX_PREP_VERBATIM_LEGACY", raising=False)
        monkeypatch.setattr(asyncio, "sleep", no_sleep)
        with (
            patch(
                "agents.hapax_daimonion.cpal.runner.resolve_playback_decision",
                return_value=decision,
            ),
            patch("shared.programme_store.default_store") as default_store,
            patch("agents.hapax_daimonion.pw_audio_output.play_pcm", return_value=playback_result),
            patch("agents.hapax_daimonion.cpal.runner.record_destination_decision"),
            patch("agents.hapax_daimonion.cpal.runner.record_tts_synthesis"),
            patch("agents.hapax_daimonion.cpal.runner.record_playback_result"),
        ):
            default_store.return_value.active_programme.return_value = active
            await runner.process_impingement(imp)

        daemon.tts.synthesize.assert_called_once_with(
            "Composed live-prior narration.",
            "proactive",
        )

    @pytest.mark.asyncio
    async def test_legacy_verbatim_prepared_segment_suppresses_autonomous_narration(
        self,
        monkeypatch,
    ):
        runner = self._make_runner()
        daemon = MagicMock()
        runner._daemon = daemon
        runner._impingement_adapter.adapt = MagicMock(
            return_value=SimpleNamespace(
                gain_update=None,
                should_surface=False,
                narrative="Composed narration.",
                error_boost=0.0,
            )
        )
        imp = MagicMock()
        imp.source = "autonomous_narrative"
        imp.content = {"narrative": "Composed narration."}
        active = SimpleNamespace(
            content=ProgrammeContent(
                delivery_mode="verbatim_legacy",
                prepared_script=["Legacy direct playback owns this TTS path."],
            )
        )

        monkeypatch.setenv("HAPAX_PREP_VERBATIM_LEGACY", "1")
        with (
            patch("shared.programme_store.default_store") as default_store,
            patch(
                "agents.hapax_daimonion.cpal.runner.resolve_playback_decision"
            ) as resolve_decision,
        ):
            default_store.return_value.active_programme.return_value = active
            await runner.process_impingement(imp)

        daemon.tts.synthesize.assert_not_called()
        resolve_decision.assert_not_called()

    def test_presynthesize_signals(self):
        runner = self._make_runner()
        tts = MagicMock()
        tts.synthesize.return_value = b"\x00\x01" * 100
        runner._tts_manager = tts
        runner.presynthesize_signals()
        assert runner.signal_cache.is_ready


class TestCpalRunnerTelemetry:
    """Queue #225: CPAL loop Prometheus telemetry."""

    def _make_runner(self):
        buffer = MagicMock()
        buffer.speech_active = False
        buffer.speech_duration_s = 0.0
        buffer.is_speaking = False
        buffer.get_utterance.return_value = None
        buffer.speech_frames_snapshot = []

        stt = MagicMock()
        stt.transcribe = AsyncMock(return_value="")

        router = MagicMock()
        router.route.return_value = MagicMock(tier="CAPABLE")

        return CpalRunner(buffer=buffer, stt=stt, salience_router=router)

    def test_classify_tick_idle(self):
        runner = self._make_runner()
        assert runner._classify_tick() == "idle"

    def test_classify_tick_utterance(self):
        runner = self._make_runner()
        runner._processing_utterance = True
        assert runner._classify_tick() == "utterance"

    def test_classify_tick_producing(self):
        runner = self._make_runner()
        # ProductionStream.is_producing is a read-only property; swap the
        # production stream for a mock with a writable attribute.
        prod = MagicMock()
        prod.is_producing = True
        runner._production = prod
        assert runner._classify_tick() == "producing"

    def test_classify_tick_impingement_dominates(self):
        runner = self._make_runner()
        # Impingement takes priority over utterance/producing; it's the most
        # information-dense signal the loop handles this tick.
        prod = MagicMock()
        prod.is_producing = True
        runner._production = prod
        runner._processing_utterance = True
        runner._impingement_since_last_tick = True
        assert runner._classify_tick() == "impingement"

    @pytest.mark.asyncio
    async def test_process_impingement_marks_tick(self):
        runner = self._make_runner()
        imp = MagicMock()
        imp.source = "stimmung"
        imp.strength = 0.9
        imp.content = {"metric": "stimmung_critical", "narrative": "System critical"}
        imp.interrupt_token = None

        assert runner._impingement_since_last_tick is False
        await runner.process_impingement(imp)
        assert runner._impingement_since_last_tick is True

    @pytest.mark.asyncio
    async def test_impingement_flag_resets_after_tick(self):
        runner = self._make_runner()
        runner._impingement_since_last_tick = True

        async def stop_after():
            while runner.tick_count < 1:
                await asyncio.sleep(0.01)
            runner.stop()

        await asyncio.gather(runner.run(), stop_after())
        # First full tick reclassifies as impingement, then clears the flag.
        assert runner._impingement_since_last_tick is False

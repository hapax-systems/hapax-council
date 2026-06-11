"""Regression tests for the pipeline_unavailable total-voice-outage death mode.

CASE-VOICE-FOUNDATION-20260610 / voice-p0-pipeline-unavailable-rootcause-20260610.

Death mode (witnessed 2026-06-10 13:06->17:55 local): the CPAL silence-timeout
session close runs stop_pipeline(), which nulls daemon._conversation_pipeline
AND the runner's reference via set_pipeline(None). The runner's documented
self-heal at the T3 utterance site only restarts a *stopped-but-bound*
pipeline, so it can never fire for the very case it names, and the
spontaneous-speech path has no recovery at all — every impingement drops at
record_drop(reason="pipeline_unavailable") at DEBUG until an engagement event
or a daemon restart rebinds the reference.

The fix: CpalRunner._ensure_pipeline() recreates the pipeline through
daemon._start_pipeline() (the canonical creator, which rebinds the runner via
start_conversation_pipeline) whenever the reference is missing or the bound
pipeline is stopped; set_pipeline() logs every bound/unbound transition at
WARNING with cause; the spontaneous-speech LLM call carries an explicit
timeout instead of litellm's 600s default.
"""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.hapax_daimonion.cpal.destination_channel import DestinationChannel
from agents.hapax_daimonion.cpal.runner import CpalRunner

_PRIVATE_DECISION = SimpleNamespace(
    allowed=True,
    destination=DestinationChannel.PRIVATE,
    reason_code="private_assistant_monitor_bound",
    safety_gate={"context_default": "private_or_drop"},
    target="hapax-private",
    media_role="Assistant",
)


def _make_runner(daemon=None):
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
        daemon=daemon,
    )


def _surfacing_effect(narrative="Surface this narration."):
    return SimpleNamespace(
        gain_update=None,
        should_surface=True,
        narrative=narrative,
        error_boost=0.5,
    )


def _exploration_impingement():
    imp = MagicMock()
    imp.source = "exploration.apperception"
    imp.content = {"narrative": "Surface this narration."}
    return imp


def _rebinding_daemon(runner_ref: list, fresh_pipeline) -> MagicMock:
    """Daemon mock whose _start_pipeline rebinds like start_conversation_pipeline."""
    daemon = MagicMock()

    async def _start_pipeline():
        runner_ref[0].set_pipeline(fresh_pipeline)

    daemon._start_pipeline = AsyncMock(side_effect=_start_pipeline)
    return daemon


class TestSpontaneousSpeechRebind:
    @pytest.mark.asyncio
    async def test_spontaneous_speech_recreates_pipeline_after_unwire(self):
        """The 13:06 death mode: unbound pipeline must be recreated, not dropped."""
        fresh = AsyncMock()
        fresh._running = True
        runner_ref: list = [None]
        daemon = _rebinding_daemon(runner_ref, fresh)
        runner = _make_runner(daemon=daemon)
        runner_ref[0] = runner

        # Simulate stop_pipeline()'s unwire after a silence-timeout close.
        runner.set_pipeline(None)
        runner._impingement_adapter.adapt = MagicMock(return_value=_surfacing_effect())

        with (
            patch(
                "agents.hapax_daimonion.cpal.runner.resolve_playback_decision",
                return_value=_PRIVATE_DECISION,
            ),
            patch("agents.hapax_daimonion.cpal.runner.record_destination_decision"),
            patch("agents.hapax_daimonion.cpal.runner.record_drop") as record_drop,
            patch("agents.hapax_daimonion.cpal.runner.asyncio.sleep", new=AsyncMock()),
        ):
            await runner.process_impingement(_exploration_impingement())

        daemon._start_pipeline.assert_awaited_once()
        # voice-p1-turnbudget: the runner now composes OUTSIDE the speech
        # lock and speaks inside it (two calls, not one monolith).
        fresh.compose_spontaneous_speech.assert_awaited_once()
        fresh.speak_spontaneous_text.assert_awaited_once()
        for call in record_drop.call_args_list:
            assert call.kwargs.get("reason") != "pipeline_unavailable"

    @pytest.mark.asyncio
    async def test_compose_runs_outside_speech_lock_speak_inside(self):
        """voice-p1-turnbudget acceptance: the spontaneous LLM leg cannot
        wedge the speech lock — composition runs unlocked, only the audio
        leg (speak) holds it."""
        fresh = AsyncMock()
        fresh._running = True
        runner_ref: list = [None]
        daemon = _rebinding_daemon(runner_ref, fresh)
        runner = _make_runner(daemon=daemon)
        runner_ref[0] = runner
        runner.set_pipeline(None)
        runner._impingement_adapter.adapt = MagicMock(return_value=_surfacing_effect())

        lock_during_compose: list[bool] = []
        lock_during_speak: list[bool] = []

        async def _compose(*args, **kwargs):
            lock_during_compose.append(runner._speech_lock.locked())
            return "composed text"

        async def _speak(*args, **kwargs):
            lock_during_speak.append(runner._speech_lock.locked())

        fresh.compose_spontaneous_speech = AsyncMock(side_effect=_compose)
        fresh.speak_spontaneous_text = AsyncMock(side_effect=_speak)

        with (
            patch(
                "agents.hapax_daimonion.cpal.runner.resolve_playback_decision",
                return_value=_PRIVATE_DECISION,
            ),
            patch("agents.hapax_daimonion.cpal.runner.record_destination_decision"),
            patch("agents.hapax_daimonion.cpal.runner.record_drop"),
            patch("agents.hapax_daimonion.cpal.runner.asyncio.sleep", new=AsyncMock()),
        ):
            await runner.process_impingement(_exploration_impingement())

        assert lock_during_compose == [False]
        assert lock_during_speak == [True]

    @pytest.mark.asyncio
    async def test_floor_claimed_during_compose_drops_with_witness(self):
        """If a conversational turn claims the floor while the LLM composes,
        the spontaneous utterance drops with a witness — never speaks."""
        fresh = AsyncMock()
        fresh._running = True
        runner_ref: list = [None]
        daemon = _rebinding_daemon(runner_ref, fresh)
        runner = _make_runner(daemon=daemon)
        runner_ref[0] = runner
        runner.set_pipeline(None)
        runner._impingement_adapter.adapt = MagicMock(return_value=_surfacing_effect())

        async def _compose(*args, **kwargs):
            runner._processing_utterance = True  # operator spoke mid-compose
            return "composed text"

        fresh.compose_spontaneous_speech = AsyncMock(side_effect=_compose)

        with (
            patch(
                "agents.hapax_daimonion.cpal.runner.resolve_playback_decision",
                return_value=_PRIVATE_DECISION,
            ),
            patch("agents.hapax_daimonion.cpal.runner.record_destination_decision"),
            patch("agents.hapax_daimonion.cpal.runner.record_drop") as record_drop,
            patch("agents.hapax_daimonion.cpal.runner.asyncio.sleep", new=AsyncMock()),
        ):
            await runner.process_impingement(_exploration_impingement())

        fresh.speak_spontaneous_text.assert_not_awaited()
        reasons = [c.kwargs.get("reason") for c in record_drop.call_args_list]
        assert "conversation_active_post_compose" in reasons

    @pytest.mark.asyncio
    async def test_spontaneous_speech_drops_when_rebind_fails(self, caplog):
        """If recreation fails the drop is preserved and surfaced at WARNING."""
        daemon = MagicMock()
        daemon._start_pipeline = AsyncMock(side_effect=RuntimeError("tabbyapi down"))
        runner = _make_runner(daemon=daemon)
        runner.set_pipeline(None)
        runner._impingement_adapter.adapt = MagicMock(return_value=_surfacing_effect())

        with (
            patch(
                "agents.hapax_daimonion.cpal.runner.resolve_playback_decision",
                return_value=_PRIVATE_DECISION,
            ),
            patch("agents.hapax_daimonion.cpal.runner.record_destination_decision"),
            patch("agents.hapax_daimonion.cpal.runner.record_drop") as record_drop,
            caplog.at_level(logging.WARNING, logger="agents.hapax_daimonion.cpal.runner"),
        ):
            await runner.process_impingement(_exploration_impingement())

        daemon._start_pipeline.assert_awaited_once()
        record_drop.assert_called_once()
        assert record_drop.call_args.kwargs["reason"] == "pipeline_unavailable"
        assert any(r.levelno == logging.WARNING for r in caplog.records)

    @pytest.mark.asyncio
    async def test_spontaneous_speech_drops_without_daemon(self):
        """No daemon -> no recovery possible -> existing drop contract holds."""
        runner = _make_runner(daemon=None)
        runner.set_pipeline(None)
        runner._impingement_adapter.adapt = MagicMock(return_value=_surfacing_effect())

        with (
            patch(
                "agents.hapax_daimonion.cpal.runner.resolve_playback_decision",
                return_value=_PRIVATE_DECISION,
            ),
            patch("agents.hapax_daimonion.cpal.runner.record_destination_decision"),
            patch("agents.hapax_daimonion.cpal.runner.record_drop") as record_drop,
        ):
            await runner.process_impingement(_exploration_impingement())

        record_drop.assert_called_once()
        assert record_drop.call_args.kwargs["reason"] == "pipeline_unavailable"


class TestUtteranceRebind:
    @pytest.mark.asyncio
    async def test_utterance_recreates_pipeline_after_unwire(self):
        """First utterance after a silence-timeout close must not be eaten."""
        fresh = AsyncMock()
        fresh._running = True
        runner_ref: list = [None]
        daemon = _rebinding_daemon(runner_ref, fresh)
        runner = _make_runner(daemon=daemon)
        runner_ref[0] = runner
        runner.set_pipeline(None)

        await runner._process_utterance(b"\x01\x02")

        daemon._start_pipeline.assert_awaited_once()
        fresh.process_utterance.assert_awaited_once_with(b"\x01\x02")

    @pytest.mark.asyncio
    async def test_utterance_restarts_stopped_pipeline_in_place(self):
        """Bound-but-stopped pipeline restarts without daemon recreation."""
        stopped = AsyncMock()
        stopped._running = False
        daemon = MagicMock()
        daemon._start_pipeline = AsyncMock()
        runner = _make_runner(daemon=daemon)
        runner.set_pipeline(stopped)

        await runner._process_utterance(b"\x01\x02")

        stopped.start.assert_awaited_once()
        daemon._start_pipeline.assert_not_awaited()
        stopped.process_utterance.assert_awaited_once_with(b"\x01\x02")


class TestSetPipelineTransitionLogging:
    def test_set_pipeline_logs_warning_transitions_with_cause(self, caplog):
        runner = _make_runner()
        pipeline = MagicMock()

        with caplog.at_level(logging.WARNING, logger="agents.hapax_daimonion.cpal.runner"):
            runner.set_pipeline(pipeline, cause="test_bind")
            runner.set_pipeline(None, cause="silence_timeout_close")

        messages = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert any("test_bind" in m for m in messages)
        assert any("silence_timeout_close" in m for m in messages)

    def test_set_pipeline_logs_transitions_without_explicit_cause(self, caplog):
        """Out-of-scope callers (pipeline_lifecycle, session_events) pass no
        cause — the transition must still be visible at WARNING."""
        runner = _make_runner()

        with caplog.at_level(logging.WARNING, logger="agents.hapax_daimonion.cpal.runner"):
            runner.set_pipeline(MagicMock())
            runner.set_pipeline(None)

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) >= 2


class TestSpontaneousLlmTimeout:
    @pytest.mark.asyncio
    async def test_spontaneous_llm_call_has_explicit_timeout(self):
        """The spontaneous LLM call must not ride litellm's 600s default while
        holding the runner's speech lock (audit H2)."""
        from agents.hapax_daimonion.conversation_pipeline import (
            ConversationPipeline,
            ConvState,
        )

        pipeline = ConversationPipeline.__new__(ConversationPipeline)
        pipeline._running = True
        pipeline.state = ConvState.IDLE
        pipeline._system_context = "system context"
        pipeline._update_system_context = MagicMock()

        msg = SimpleNamespace(content="[silence]")
        resp = SimpleNamespace(choices=[SimpleNamespace(message=msg)])
        acompletion = AsyncMock(return_value=resp)

        imp = MagicMock()
        imp.source = "exploration.apperception"
        imp.content = {"narrative": "Surface this narration."}
        imp.strength = 0.6

        with (
            patch("litellm.acompletion", new=acompletion),
            patch("agents.hapax_daimonion.conversation_pipeline.llm_call_span", None),
            patch("agents.hapax_daimonion.voice_output_witness.record_drop"),
        ):
            await pipeline.generate_spontaneous_speech(
                imp,
                destination_target="hapax-private",
                destination_role="Assistant",
                destination="private",
            )

        acompletion.assert_awaited_once()
        timeout = acompletion.await_args.kwargs.get("timeout")
        assert timeout is not None, "spontaneous LLM call must carry an explicit timeout"
        assert 0 < timeout <= 120

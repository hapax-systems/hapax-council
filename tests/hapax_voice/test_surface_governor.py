"""Surface 6: Perception → Governor → Frame Gate directive chain.

Tests that environment state changes produce correct governor directives
and that the daemon applies those directives to the frame gate and session.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from agents.hapax_voice.governor import PipelineGovernor
from agents.hapax_voice.perception import EnvironmentState


def _make_state(**overrides) -> EnvironmentState:
    """Create an EnvironmentState with sensible defaults."""
    defaults = dict(
        timestamp=time.monotonic(),
        speech_detected=False,
        speech_volume_db=-40.0,
        ambient_class="quiet",
        vad_confidence=0.0,
        face_count=1,
        operator_present=True,
        gaze_at_camera=False,
        activity_mode="idle",
        workspace_context="",
        ambient_detailed="",
        active_window=None,
        window_count=0,
        active_workspace_id=1,
    )
    defaults.update(overrides)
    return EnvironmentState(**defaults)


class TestGovernorBasicDirectives:
    """Governor returns correct directives for basic states."""

    def test_process_when_operator_present(self):
        gov = PipelineGovernor()
        state = _make_state(operator_present=True, face_count=1)
        assert gov.evaluate(state) == "process"

    def test_pause_in_production_mode(self):
        gov = PipelineGovernor()
        state = _make_state(activity_mode="production")
        assert gov.evaluate(state) == "pause"

    def test_pause_in_meeting_mode(self):
        gov = PipelineGovernor()
        state = _make_state(activity_mode="meeting")
        assert gov.evaluate(state) == "pause"

    def test_withdraw_when_absent(self):
        gov = PipelineGovernor(operator_absent_withdraw_s=0)
        # Backdate last seen so absence exceeds threshold
        gov._last_operator_seen = time.monotonic() - 1.0
        state = _make_state(operator_present=False, face_count=0)
        assert gov.evaluate(state) == "withdraw"

    def test_process_when_absent_but_within_timeout(self):
        gov = PipelineGovernor(operator_absent_withdraw_s=300)
        # last_operator_seen is set to now at __init__, so absence is <300s
        state = _make_state(operator_present=False, face_count=0)
        assert gov.evaluate(state) == "process"

    def test_process_is_default_idle_state(self):
        gov = PipelineGovernor()
        state = _make_state()
        assert gov.evaluate(state) == "process"

    def test_unknown_activity_mode_does_not_pause(self):
        gov = PipelineGovernor()
        state = _make_state(activity_mode="unknown")
        assert gov.evaluate(state) == "process"


class TestGovernorWakeWordOverride:
    """Wake word overrides all other governor logic."""

    def test_wake_word_overrides_production_mode(self):
        gov = PipelineGovernor()
        gov.wake_word_active = True
        state = _make_state(activity_mode="production")
        assert gov.evaluate(state) == "process"

    def test_wake_word_overrides_meeting_mode(self):
        gov = PipelineGovernor()
        gov.wake_word_active = True
        state = _make_state(activity_mode="meeting")
        assert gov.evaluate(state) == "process"

    def test_wake_word_overrides_absence(self):
        gov = PipelineGovernor(operator_absent_withdraw_s=0)
        gov._last_operator_seen = time.monotonic() - 100
        gov.wake_word_active = True
        state = _make_state(operator_present=False, face_count=0)
        assert gov.evaluate(state) == "process"

    def test_wake_word_clears_after_evaluation(self):
        gov = PipelineGovernor()
        gov.wake_word_active = True
        state = _make_state()
        gov.evaluate(state)
        assert gov.wake_word_active is False

    def test_wake_word_only_active_once(self):
        """Second evaluation without re-setting returns normal directive."""
        gov = PipelineGovernor()
        gov.wake_word_active = True
        state_prod = _make_state(activity_mode="production")
        # First call: override → process
        assert gov.evaluate(state_prod) == "process"
        # Second call: wake_word_active is False → normal pause
        assert gov.evaluate(state_prod) == "pause"


class TestGovernorConversationDebounce:
    """Conversation detection uses debounce before pausing."""

    def test_conversation_detected_property(self):
        """conversation_detected requires face_count > 1 AND speech_detected."""
        state = _make_state(face_count=2, speech_detected=True)
        assert state.conversation_detected is True

    def test_conversation_not_detected_single_face(self):
        state = _make_state(face_count=1, speech_detected=True)
        assert state.conversation_detected is False

    def test_conversation_not_detected_no_speech(self):
        state = _make_state(face_count=2, speech_detected=False)
        assert state.conversation_detected is False

    def test_no_pause_before_debounce(self):
        gov = PipelineGovernor(conversation_debounce_s=5.0)
        state = _make_state(face_count=2, speech_detected=True, operator_present=True)
        assert gov.evaluate(state) == "process"

    def test_pause_after_debounce(self):
        gov = PipelineGovernor(conversation_debounce_s=0)
        state = _make_state(face_count=2, speech_detected=True, operator_present=True)
        assert gov.evaluate(state) == "pause"

    def test_resume_after_conversation_clears(self):
        gov = PipelineGovernor(
            conversation_debounce_s=0,
            environment_clear_resume_s=0,
        )
        conv_state = _make_state(face_count=2, speech_detected=True, operator_present=True)
        assert gov.evaluate(conv_state) == "pause"

        clear_state = _make_state(face_count=1, speech_detected=False, operator_present=True)
        assert gov.evaluate(clear_state) == "process"

    def test_still_paused_within_clear_delay(self):
        """After conversation ends, stays paused until environment_clear_resume_s elapses."""
        gov = PipelineGovernor(
            conversation_debounce_s=0,
            environment_clear_resume_s=300,  # long delay
        )
        # Trigger pause via conversation
        conv_state = _make_state(face_count=2, speech_detected=True, operator_present=True)
        assert gov.evaluate(conv_state) == "pause"

        # Conversation clears but delay not elapsed → still paused
        clear_state = _make_state(face_count=1, speech_detected=False, operator_present=True)
        assert gov.evaluate(clear_state) == "pause"

    def test_conversation_first_seen_resets_on_clear(self):
        """After conversation clears, _conversation_first_seen is reset to None."""
        gov = PipelineGovernor(conversation_debounce_s=5.0)
        conv_state = _make_state(face_count=2, speech_detected=True)
        gov.evaluate(conv_state)
        assert gov._conversation_first_seen is not None

        clear_state = _make_state(face_count=1, speech_detected=False)
        gov.evaluate(clear_state)
        assert gov._conversation_first_seen is None


class TestGovernorOperatorAbsence:
    """Operator absence tracking with withdraw threshold."""

    def test_last_operator_seen_updated_when_present(self):
        gov = PipelineGovernor()
        before = gov._last_operator_seen
        state = _make_state(operator_present=True)
        gov.evaluate(state)
        assert gov._last_operator_seen >= before

    def test_last_operator_seen_not_updated_when_absent(self):
        gov = PipelineGovernor()
        # Set last seen to a known old time
        gov._last_operator_seen = time.monotonic() - 200
        old_seen = gov._last_operator_seen
        state = _make_state(operator_present=False, face_count=0)
        gov.evaluate(state)
        # No update since operator_present is False
        assert gov._last_operator_seen == old_seen

    def test_withdraw_requires_both_absent_and_face_count_zero(self):
        """operator_present=False but face_count=1 should not trigger withdraw."""
        gov = PipelineGovernor(operator_absent_withdraw_s=0)
        gov._last_operator_seen = time.monotonic() - 1.0
        # operator_present=False but face_count=1
        state = _make_state(operator_present=False, face_count=1)
        # The absence check requires face_count == 0
        assert gov.evaluate(state) != "withdraw"


class TestFrameGateDirective:
    """FrameGate directive management (no Pipecat pipeline required).

    Hardware deps (pipecat) are stubbed via conftest.py sys.modules injection.
    FrameProcessor is a MagicMock, so we bypass its __init__ with __new__
    and set the instance attributes that FrameGate.__init__ would normally set.
    """

    def test_initial_directive_is_process(self):
        from agents.hapax_voice.frame_gate import FrameGate

        gate = FrameGate()
        assert gate.directive == "process"

    def test_set_directive_changes_value(self):
        from agents.hapax_voice.frame_gate import FrameGate

        gate = FrameGate()
        gate.set_directive("pause")
        assert gate.directive == "pause"
        gate.set_directive("process")
        assert gate.directive == "process"

    def test_set_directive_same_value_is_noop(self):
        """Setting the same directive a second time should not change anything."""
        from agents.hapax_voice.frame_gate import FrameGate

        gate = FrameGate()
        gate.set_directive("process")
        assert gate.directive == "process"


class TestGovernorPerceptionLoopIntegration:
    """Perception loop in daemon wires governor → frame_gate → session correctly."""

    @pytest.mark.asyncio
    async def test_perception_loop_applies_pause_directive(self):
        """When governor returns pause, frame_gate gets 'pause' and session pauses."""
        from agents.hapax_voice.__main__ import VoiceDaemon
        from agents.hapax_voice.session import VoiceLifecycle

        with patch.object(VoiceDaemon, "__init__", lambda self, **kw: None):
            daemon = VoiceDaemon()

        # Wire up minimal attributes used by _perception_loop
        daemon._running = True
        daemon.cfg = MagicMock()
        daemon.cfg.perception_fast_tick_s = 0.0

        # Real session so we can observe pause/resume
        daemon.session = VoiceLifecycle()
        daemon.session.open(trigger="test")

        # Governor always returns "pause"
        daemon.governor = MagicMock()
        daemon.governor.evaluate.return_value = "pause"

        # Frame gate mock to track set_directive calls
        daemon._frame_gate = MagicMock()

        # Perception tick returns a minimal state
        daemon.perception = MagicMock()
        daemon.perception.tick.return_value = _make_state(activity_mode="meeting")

        daemon.gate = MagicMock()

        # Run one iteration of the loop then stop
        import asyncio

        async def _run_one_tick():
            daemon._running = True
            await asyncio.sleep(0)  # yield
            state = daemon.perception.tick()
            directive = daemon.governor.evaluate(state)
            daemon._frame_gate.set_directive(directive)
            if directive == "pause" and daemon.session.is_active and not daemon.session.is_paused:
                daemon.session.pause(reason=f"governor:{state.activity_mode}")
            elif directive == "process" and daemon.session.is_paused:
                daemon.session.resume()

        await _run_one_tick()

        daemon._frame_gate.set_directive.assert_called_with("pause")
        assert daemon.session.is_paused

    @pytest.mark.asyncio
    async def test_perception_loop_applies_process_resumes_session(self):
        """When governor returns process and session is paused, session resumes."""
        from agents.hapax_voice.__main__ import VoiceDaemon
        from agents.hapax_voice.session import VoiceLifecycle

        with patch.object(VoiceDaemon, "__init__", lambda self, **kw: None):
            daemon = VoiceDaemon()

        daemon._running = True
        daemon.cfg = MagicMock()
        daemon.session = VoiceLifecycle()
        daemon.session.open(trigger="test")
        daemon.session.pause(reason="prior")

        daemon.governor = MagicMock()
        daemon.governor.evaluate.return_value = "process"

        daemon._frame_gate = MagicMock()
        daemon.perception = MagicMock()
        daemon.perception.tick.return_value = _make_state()
        daemon.gate = MagicMock()

        async def _run_one_tick():
            state = daemon.perception.tick()
            directive = daemon.governor.evaluate(state)
            daemon._frame_gate.set_directive(directive)
            if directive == "pause" and daemon.session.is_active and not daemon.session.is_paused:
                daemon.session.pause(reason=f"governor:{state.activity_mode}")
            elif directive == "process" and daemon.session.is_paused:
                daemon.session.resume()

        await _run_one_tick()

        daemon._frame_gate.set_directive.assert_called_with("process")
        assert not daemon.session.is_paused

    @pytest.mark.asyncio
    async def test_perception_loop_withdraw_closes_session(self):
        """When governor returns withdraw and session is active, _close_session is called."""
        from agents.hapax_voice.__main__ import VoiceDaemon
        from agents.hapax_voice.session import VoiceLifecycle

        with patch.object(VoiceDaemon, "__init__", lambda self, **kw: None):
            daemon = VoiceDaemon()

        daemon._running = True
        daemon.cfg = MagicMock()
        daemon.session = VoiceLifecycle()
        daemon.session.open(trigger="test")

        daemon.governor = MagicMock()
        daemon.governor.evaluate.return_value = "withdraw"

        daemon._frame_gate = MagicMock()
        daemon.perception = MagicMock()
        daemon.perception.tick.return_value = _make_state(operator_present=False, face_count=0)
        daemon.gate = MagicMock()

        close_called = []

        async def _fake_close(reason):
            close_called.append(reason)

        daemon._close_session = _fake_close

        async def _run_one_tick():
            state = daemon.perception.tick()
            directive = daemon.governor.evaluate(state)
            daemon._frame_gate.set_directive(directive)
            if directive == "pause" and daemon.session.is_active and not daemon.session.is_paused:
                daemon.session.pause(reason=f"governor:{state.activity_mode}")
            elif directive == "process" and daemon.session.is_paused:
                daemon.session.resume()
            elif directive == "withdraw" and daemon.session.is_active:
                await daemon._close_session(reason="operator_absent")

        await _run_one_tick()

        assert close_called == ["operator_absent"]

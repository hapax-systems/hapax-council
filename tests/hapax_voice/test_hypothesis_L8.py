"""Hypothesis property tests for L8: PipelineGovernor, FrameGate."""

from __future__ import annotations

from unittest.mock import MagicMock

from hypothesis import given, settings
from hypothesis import strategies as st

from agents.hapax_voice.commands import Command
from agents.hapax_voice.frame_gate import FrameGate
from agents.hapax_voice.governor import PipelineGovernor
from agents.hapax_voice.perception import PerceptionEngine
from tests.hapax_voice.hypothesis_strategies import st_environment_state


class TestGovernorProperties:
    @given(state=st_environment_state())
    @settings(max_examples=100)
    def test_returns_valid_directive(self, state):
        """evaluate() always returns one of the three valid directives."""
        gov = PipelineGovernor()
        directive = gov.evaluate(state)
        assert directive in {"process", "pause", "withdraw"}

    @given(state=st_environment_state())
    @settings(max_examples=100)
    def test_veto_deny_implies_pause(self, state):
        """If veto_chain denies, governor returns 'pause' (not 'process')."""
        gov = PipelineGovernor()
        directive = gov.evaluate(state)
        if gov.last_veto_result is not None and not gov.last_veto_result.allowed:
            assert directive == "pause"

    @given(state=st_environment_state())
    @settings(max_examples=100)
    def test_evaluation_populates_observability(self, state):
        """After evaluate(), last_veto_result is populated."""
        gov = PipelineGovernor()
        gov.evaluate(state)
        assert gov.last_veto_result is not None


class TestFrameGateProperties:
    @given(
        action=st.sampled_from(["process", "pause", "withdraw"]),
    )
    @settings(max_examples=100)
    def test_idempotent(self, action):
        """apply_command(cmd); apply_command(cmd) yields same state as single apply."""
        gate = FrameGate()
        cmd = Command(action=action, trigger_source="test")
        gate.apply_command(cmd)
        state1 = gate.directive

        gate.apply_command(cmd)
        state2 = gate.directive

        assert state1 == state2 == action

    @given(
        action=st.sampled_from(["process", "pause", "withdraw"]),
    )
    @settings(max_examples=100)
    def test_apply_stores_command(self, action):
        """apply_command always stores the last command for provenance."""
        gate = FrameGate()
        cmd = Command(action=action, trigger_source="governor")
        gate.apply_command(cmd)
        assert gate.last_command is not None
        assert gate.last_command.action == action


class TestPerceptionProperties:
    @given(n_ticks=st.integers(min_value=2, max_value=5))
    @settings(max_examples=50)
    def test_watermarks_advance_monotonically(self, n_ticks):
        """After N ticks, min_watermark is non-decreasing."""
        presence = MagicMock()
        presence.latest_vad_confidence = 0.0
        presence.face_detected = False
        presence.face_count = 0
        engine = PerceptionEngine(presence=presence, workspace_monitor=MagicMock())

        prev_wm = 0.0
        for _ in range(n_ticks):
            engine.tick()
            wm = engine.min_watermark
            assert wm >= prev_wm
            prev_wm = wm

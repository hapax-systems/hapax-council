"""Tests for Directive primitives: Command and Schedule."""

from __future__ import annotations

import pytest

from agents.hapax_voice.commands import Command, Schedule
from agents.hapax_voice.governance import VetoResult

# ------------------------------------------------------------------
# Command
# ------------------------------------------------------------------


class TestCommand:
    def test_basic_construction(self):
        cmd = Command(action="process")
        assert cmd.action == "process"
        assert cmd.params == {}
        assert cmd.trigger_source == ""

    def test_full_provenance(self):
        veto = VetoResult(allowed=True)
        cmd = Command(
            action="play_sample",
            params={"sample": "kick.wav", "velocity": 0.8},
            trigger_time=100.0,
            trigger_source="midi_clock",
            min_watermark=99.5,
            governance_result=veto,
            selected_by="energy_threshold",
        )
        assert cmd.action == "play_sample"
        assert cmd.params["sample"] == "kick.wav"
        assert cmd.trigger_source == "midi_clock"
        assert cmd.min_watermark == 99.5
        assert cmd.governance_result.allowed is True
        assert cmd.selected_by == "energy_threshold"

    def test_frozen(self):
        cmd = Command(action="process")
        with pytest.raises(AttributeError):
            cmd.action = "pause"  # type: ignore[misc]

    def test_governance_result_carried(self):
        denied = VetoResult(allowed=False, denied_by=("conversation",))
        cmd = Command(action="pause", governance_result=denied)
        assert cmd.governance_result.allowed is False
        assert "conversation" in cmd.governance_result.denied_by


# ------------------------------------------------------------------
# Schedule
# ------------------------------------------------------------------


class TestSchedule:
    def test_basic_construction(self):
        cmd = Command(action="play_sample")
        sched = Schedule(command=cmd, domain="beat", target_time=4.0, wall_time=1000.5)
        assert sched.command.action == "play_sample"
        assert sched.domain == "beat"
        assert sched.target_time == 4.0
        assert sched.wall_time == 1000.5

    def test_default_tolerance(self):
        cmd = Command(action="speak_tts")
        sched = Schedule(command=cmd)
        assert sched.tolerance_ms == 50.0

    def test_custom_tolerance(self):
        cmd = Command(action="speak_tts")
        sched = Schedule(command=cmd, tolerance_ms=500.0)
        assert sched.tolerance_ms == 500.0

    def test_frozen(self):
        cmd = Command(action="process")
        sched = Schedule(command=cmd)
        with pytest.raises(AttributeError):
            sched.wall_time = 999.0  # type: ignore[misc]

    def test_wall_domain_default(self):
        cmd = Command(action="process")
        sched = Schedule(command=cmd, target_time=50.0, wall_time=50.0)
        assert sched.domain == "wall"


# ------------------------------------------------------------------
# FrameGate integration
# ------------------------------------------------------------------


class TestFrameGateCommand:
    def test_apply_command_sets_directive(self):
        from agents.hapax_voice.frame_gate import FrameGate

        gate = FrameGate()
        cmd = Command(action="pause", trigger_source="perception_tick")
        gate.apply_command(cmd)
        assert gate.directive == "pause"

    def test_apply_command_stores_provenance(self):
        from agents.hapax_voice.frame_gate import FrameGate

        gate = FrameGate()
        cmd = Command(
            action="process",
            trigger_time=42.0,
            trigger_source="perception_tick",
            min_watermark=41.5,
        )
        gate.apply_command(cmd)
        assert gate.last_command is not None
        assert gate.last_command.trigger_time == 42.0
        assert gate.last_command.min_watermark == 41.5

    def test_last_command_initially_none(self):
        from agents.hapax_voice.frame_gate import FrameGate

        gate = FrameGate()
        assert gate.last_command is None

    def test_set_directive_still_works(self):
        from agents.hapax_voice.frame_gate import FrameGate

        gate = FrameGate()
        gate.set_directive("pause")
        assert gate.directive == "pause"
        assert gate.last_command is None  # no command was applied


# ------------------------------------------------------------------
# E: Error paths — Command/Schedule as inert data carriers
# ------------------------------------------------------------------


class TestCommandErrorPaths:
    def test_empty_action_does_not_crash_frame_gate(self):
        """Commands with empty action are structurally valid frozen data."""
        from agents.hapax_voice.frame_gate import FrameGate

        gate = FrameGate()
        cmd = Command(action="")
        gate.apply_command(cmd)
        assert gate.directive == ""

    def test_denied_command_carries_denial_provenance(self):
        """A denied VetoResult on a Command preserves its denial chain."""
        denied = VetoResult(
            allowed=False,
            denied_by=("safety_veto", "staleness_veto"),
            axiom_ids=("single_user",),
        )
        cmd = Command(action="play_sample", governance_result=denied)
        assert not cmd.governance_result.allowed
        assert len(cmd.governance_result.denied_by) == 2

    def test_schedule_with_zero_tolerance_is_valid(self):
        """Zero tolerance is a valid edge — consumers decide expiry semantics."""
        cmd = Command(action="process")
        sched = Schedule(command=cmd, wall_time=100.0, tolerance_ms=0.0)
        assert sched.tolerance_ms == 0.0

    def test_schedule_with_past_wall_time_is_valid(self):
        """Schedule with wall_time in the past is structurally valid — queue decides expiry."""
        cmd = Command(action="process")
        sched = Schedule(command=cmd, wall_time=0.0)
        assert sched.wall_time == 0.0


# ------------------------------------------------------------------
# PerceptionEngine min_watermark
# ------------------------------------------------------------------


class TestPerceptionMinWatermark:
    def test_min_watermark_property(self):
        from unittest.mock import MagicMock

        from agents.hapax_voice.perception import PerceptionEngine

        presence = MagicMock()
        presence.latest_vad_confidence = 0.0
        presence.face_detected = False
        presence.face_count = 0
        engine = PerceptionEngine(presence=presence, workspace_monitor=MagicMock())
        engine.tick()
        # All behaviors have watermarks — min should be a positive number
        assert engine.min_watermark > 0

    def test_min_watermark_reflects_stalest(self):
        from unittest.mock import MagicMock

        from agents.hapax_voice.perception import PerceptionEngine

        presence = MagicMock()
        presence.latest_vad_confidence = 0.0
        presence.face_detected = False
        presence.face_count = 0
        engine = PerceptionEngine(presence=presence, workspace_monitor=MagicMock())

        # Tick once to establish watermarks
        engine.tick()
        initial_wm = engine.min_watermark

        # Update some slow fields — their watermarks advance
        engine.update_slow_fields(activity_mode="coding")

        # Tick again — fast behaviors advance
        engine.tick()

        # min_watermark should be >= initial since all have advanced
        assert engine.min_watermark >= initial_wm

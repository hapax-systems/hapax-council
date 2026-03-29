"""Hypothesis property tests for L9: VoiceDaemon composition pipeline."""

from __future__ import annotations

from unittest.mock import patch

from hypothesis import given, settings
from hypothesis import strategies as st

from agents.hapax_daimonion.commands import Command, Schedule
from agents.hapax_daimonion.config import DaimonionConfig
from agents.hapax_daimonion.executor import ScheduleQueue
from agents.hapax_daimonion.governance import VetoResult
from tests.hapax_daimonion.hypothesis_strategies import st_schedule


def _make_daemon():
    """Create a minimal VoiceDaemon with all hardware mocked."""
    from agents.hapax_daimonion.__main__ import VoiceDaemon

    cfg = DaimonionConfig(
        hotkey_socket="/tmp/test-hapax-hypothesis.sock",
        mc_enabled=False,
        obs_enabled=False,
        webcam_enabled=False,
        screen_monitor_enabled=False,
    )
    patches = [
        patch("agents.hapax_daimonion.__main__.PresenceDetector"),
        patch("agents.hapax_daimonion.__main__.ContextGate"),
        patch("agents.hapax_daimonion.__main__.HotkeyServer"),
        patch("agents.hapax_daimonion.__main__.WakeWordDetector"),
        patch("agents.hapax_daimonion.__main__.PorcupineWakeWord"),
        patch("agents.hapax_daimonion.__main__.AudioInputStream"),
        patch("agents.hapax_daimonion.__main__.TTSManager"),
        patch("agents.hapax_daimonion.__main__.ChimePlayer"),
        patch("agents.hapax_daimonion.__main__.WorkspaceMonitor"),
        patch("agents.hapax_daimonion.__main__.EventLog"),
    ]
    for p in patches:
        p.start()
    try:
        daemon = VoiceDaemon(cfg=cfg)
    finally:
        for p in reversed(patches):
            p.stop()
    return daemon


class TestDaemonPipelineProperties:
    @given(n_ticks=st.integers(min_value=1, max_value=5))
    @settings(max_examples=50, deadline=None)
    def test_pipeline_produces_valid_output(self, n_ticks):
        """perception.tick() → governor.evaluate() always produces valid directive."""
        daemon = _make_daemon()
        daemon.presence.latest_vad_confidence = 0.0
        daemon.presence.face_detected = False
        daemon.presence.face_count = 0
        daemon.presence.guest_count = 0
        daemon.presence.operator_visible = False

        for _ in range(n_ticks):
            state = daemon.perception.tick()
            directive = daemon.governor.evaluate(state)
            assert directive in {"process", "pause", "withdraw"}

    @given(schedules=st.lists(st_schedule(), min_size=1, max_size=5))
    @settings(max_examples=50)
    def test_queue_drain_dispatch_lossless(self, schedules):
        """Non-expired schedules are not lost through drain."""
        q = ScheduleQueue()
        for s in schedules:
            q.enqueue(s)

        # Drain at earliest wall_time (all with wall_time <= min_wt are ready)
        min_wt = min(s.wall_time for s in schedules)
        drained = q.drain(min_wt)
        remaining = q.pending_count

        # Count expired at this time
        expired = sum(
            1
            for s in schedules
            if s.wall_time <= min_wt and min_wt > s.wall_time + s.tolerance_ms / 1000.0
        )
        assert len(drained) + expired + remaining == len(schedules)

    @given(
        action=st.text(min_size=1, max_size=20),
        wall_time=st.floats(allow_nan=False, allow_infinity=False, min_value=0.0, max_value=1e6),
    )
    @settings(max_examples=100)
    def test_denied_command_carries_denial(self, action, wall_time):
        """Command with governance_result.allowed == False preserves denial provenance."""
        denied = VetoResult(allowed=False, denied_by=("safety",))
        cmd = Command(action=action, governance_result=denied)
        sched = Schedule(command=cmd, wall_time=wall_time, tolerance_ms=1000.0)

        q = ScheduleQueue()
        q.enqueue(sched)
        drained = q.drain(wall_time)

        if drained:
            assert not drained[0].command.governance_result.allowed
            assert "safety" in drained[0].command.governance_result.denied_by

    @given(n_ticks=st.integers(min_value=1, max_value=5))
    @settings(max_examples=50)
    def test_pipeline_state_consistency(self, n_ticks):
        """After N ticks, governor's observability state is populated."""
        daemon = _make_daemon()
        daemon.presence.latest_vad_confidence = 0.0
        daemon.presence.face_detected = False
        daemon.presence.face_count = 0
        daemon.presence.guest_count = 0
        daemon.presence.operator_visible = False

        for _ in range(n_ticks):
            state = daemon.perception.tick()
            daemon.governor.evaluate(state)

        assert daemon.governor.last_veto_result is not None

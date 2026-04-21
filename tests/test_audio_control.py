"""Tests for SlotAudioControl PipeWire volume management."""

from __future__ import annotations

import json
import math
from unittest.mock import MagicMock, call, patch

from agents.studio_compositor.audio_control import SlotAudioControl


def _make_pw_dump_output(nodes: dict[int, str]) -> str:
    """Build minimal pw-dump JSON with node entries.

    Args:
        nodes: mapping of node_id -> media.name
    """
    return json.dumps(
        [
            {
                "id": nid,
                "type": "PipeWire:Interface:Node",
                "info": {
                    "props": {"media.name": name, "node.name": "Lavf62.12.100"},
                    "state": "running",
                },
            }
            for nid, name in nodes.items()
        ]
    )


PW_DUMP_3_SLOTS = _make_pw_dump_output(
    {241: "youtube-audio-0", 258: "youtube-audio-1", 285: "youtube-audio-2"}
)


class TestNodeDiscovery:
    @patch("subprocess.run")
    def test_discovers_node_by_media_name(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout=PW_DUMP_3_SLOTS, returncode=0)
        ctrl = SlotAudioControl(slot_count=3)
        assert ctrl.discover_node("youtube-audio-0") == 241
        assert ctrl.discover_node("youtube-audio-2") == 285

    @patch("subprocess.run")
    def test_caches_node_ids(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout=PW_DUMP_3_SLOTS, returncode=0)
        ctrl = SlotAudioControl(slot_count=3)
        ctrl.discover_node("youtube-audio-0")
        ctrl.discover_node("youtube-audio-0")
        # pw-dump called once, cached on second call
        assert mock_run.call_count == 1

    @patch("subprocess.run")
    def test_returns_none_for_missing_stream(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout=PW_DUMP_3_SLOTS, returncode=0)
        ctrl = SlotAudioControl(slot_count=3)
        assert ctrl.discover_node("youtube-audio-99") is None


class TestSetVolume:
    @patch("subprocess.run")
    def test_set_volume_calls_wpctl(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout=PW_DUMP_3_SLOTS, returncode=0)
        ctrl = SlotAudioControl(slot_count=3)
        ctrl.set_volume(0, 0.5)
        # First call is pw-dump (discovery), second is wpctl
        wpctl_call = mock_run.call_args_list[-1]
        assert wpctl_call == call(
            ["wpctl", "set-volume", "241", "0.5"],
            timeout=2,
            capture_output=True,
        )

    @patch("subprocess.run")
    def test_set_volume_invalidates_cache_on_failure(self, mock_run: MagicMock) -> None:
        # First pw-dump succeeds, wpctl fails, second pw-dump re-discovers
        pw_dump_result = MagicMock(stdout=PW_DUMP_3_SLOTS, returncode=0)
        wpctl_fail = MagicMock(returncode=1)
        mock_run.side_effect = [pw_dump_result, wpctl_fail, pw_dump_result, MagicMock(returncode=0)]
        ctrl = SlotAudioControl(slot_count=3)
        ctrl.set_volume(0, 1.0)  # discover + fail + re-discover + retry
        assert mock_run.call_count == 4


class TestMuteAllExcept:
    @patch("subprocess.run")
    def test_mutes_inactive_unmutes_active(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout=PW_DUMP_3_SLOTS, returncode=0)
        ctrl = SlotAudioControl(slot_count=3)
        ctrl.mute_all_except(1)
        # After pw-dump, expect 3 wpctl calls: slot 0 muted, 1 unmuted, 2 muted
        wpctl_calls = [c for c in mock_run.call_args_list if "wpctl" in str(c)]
        volumes = {c.args[0][2]: c.args[0][3] for c in wpctl_calls}
        assert volumes["241"] == "0.0"  # slot 0 muted
        assert volumes["258"] == "1.0"  # slot 1 active
        assert volumes["285"] == "0.0"  # slot 2 muted


class TestMuteAll:
    @patch("subprocess.run")
    def test_mutes_all_slots(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout=PW_DUMP_3_SLOTS, returncode=0)
        ctrl = SlotAudioControl(slot_count=3)
        ctrl.mute_all()
        wpctl_calls = [c for c in mock_run.call_args_list if "wpctl" in str(c)]
        for c in wpctl_calls:
            assert c.args[0][3] == "0.0"


def _wpctl_calls(mock_run: MagicMock) -> list:
    return [c for c in mock_run.call_args_list if "wpctl" in str(c)]


class TestDuckRestore:
    @patch("time.sleep")
    @patch("subprocess.run")
    def test_initial_state_is_idle(self, mock_run: MagicMock, _sleep: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout=PW_DUMP_3_SLOTS, returncode=0)
        ctrl = SlotAudioControl(slot_count=3)
        assert ctrl._ramp_state == "idle"
        assert ctrl._pre_duck_volumes == {}
        assert ctrl._ramp_thread is None

    @patch("time.sleep")
    @patch("subprocess.run")
    def test_duck_attenuates_to_target(self, mock_run: MagicMock, _sleep: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout=PW_DUMP_3_SLOTS, returncode=0)
        ctrl = SlotAudioControl(slot_count=3)
        ctrl.duck()
        assert ctrl._ramp_thread is not None
        ctrl._ramp_thread.join(timeout=2)
        assert ctrl._ramp_state == "ducked"
        # Default pre-duck 1.0 × 0.4 attenuation = 0.4 final.
        for slot in range(3):
            assert math.isclose(ctrl._volume_cache[slot], 0.4, abs_tol=1e-6)

    @patch("time.sleep")
    @patch("subprocess.run")
    def test_duck_idempotent_when_already_ducked(
        self, mock_run: MagicMock, _sleep: MagicMock
    ) -> None:
        mock_run.return_value = MagicMock(stdout=PW_DUMP_3_SLOTS, returncode=0)
        ctrl = SlotAudioControl(slot_count=3)
        ctrl.duck()
        ctrl._ramp_thread.join(timeout=2)
        first_count = len(_wpctl_calls(mock_run))
        ctrl.duck()
        # Second duck while already ducked is a no-op — no new ramp, no new wpctl.
        assert len(_wpctl_calls(mock_run)) == first_count

    @patch("time.sleep")
    @patch("subprocess.run")
    def test_restore_idempotent_when_idle(self, mock_run: MagicMock, _sleep: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout=PW_DUMP_3_SLOTS, returncode=0)
        ctrl = SlotAudioControl(slot_count=3)
        ctrl.restore()
        # No ramp spawned at idle, no wpctl traffic.
        assert ctrl._ramp_thread is None
        assert ctrl._ramp_state == "idle"
        assert _wpctl_calls(mock_run) == []

    @patch("time.sleep")
    @patch("subprocess.run")
    def test_round_trip_returns_to_pre_duck_volumes(
        self, mock_run: MagicMock, _sleep: MagicMock
    ) -> None:
        mock_run.return_value = MagicMock(stdout=PW_DUMP_3_SLOTS, returncode=0)
        ctrl = SlotAudioControl(slot_count=3)
        ctrl.set_volume(0, 0.8)
        ctrl.set_volume(1, 0.6)
        ctrl.set_volume(2, 0.9)
        ctrl.duck()
        ctrl._ramp_thread.join(timeout=2)
        assert ctrl._ramp_state == "ducked"
        assert math.isclose(ctrl._volume_cache[0], 0.8 * 0.4, abs_tol=1e-6)

        ctrl.restore()
        ctrl._ramp_thread.join(timeout=2)
        assert ctrl._ramp_state == "idle"
        assert ctrl._pre_duck_volumes == {}
        assert math.isclose(ctrl._volume_cache[0], 0.8, abs_tol=1e-6)
        assert math.isclose(ctrl._volume_cache[1], 0.6, abs_tol=1e-6)
        assert math.isclose(ctrl._volume_cache[2], 0.9, abs_tol=1e-6)

    @patch("time.sleep")
    @patch("subprocess.run")
    def test_ramp_thread_is_daemon(self, mock_run: MagicMock, _sleep: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout=PW_DUMP_3_SLOTS, returncode=0)
        ctrl = SlotAudioControl(slot_count=3)
        ctrl.duck()
        assert ctrl._ramp_thread.daemon is True
        ctrl._ramp_thread.join(timeout=2)

    @patch("time.sleep")
    @patch("subprocess.run")
    def test_ramp_executes_eight_steps_per_slot(
        self, mock_run: MagicMock, _sleep: MagicMock
    ) -> None:
        mock_run.return_value = MagicMock(stdout=PW_DUMP_3_SLOTS, returncode=0)
        ctrl = SlotAudioControl(slot_count=3)
        ctrl.duck()
        ctrl._ramp_thread.join(timeout=2)
        # 8 ramp steps × 3 slots = 24 set_volume calls → 24 wpctl invocations.
        assert len(_wpctl_calls(mock_run)) == 24

    @patch("time.sleep")
    @patch("subprocess.run")
    def test_duck_snapshots_pre_duck_state_once(
        self, mock_run: MagicMock, _sleep: MagicMock
    ) -> None:
        mock_run.return_value = MagicMock(stdout=PW_DUMP_3_SLOTS, returncode=0)
        ctrl = SlotAudioControl(slot_count=3)
        ctrl.set_volume(0, 0.7)
        ctrl.duck()
        ctrl._ramp_thread.join(timeout=2)
        # Pre-duck snapshot survives until restore() clears it.
        assert math.isclose(ctrl._pre_duck_volumes[0], 0.7, abs_tol=1e-6)
        # Calling duck() again must not clobber the snapshot with the
        # ducked-state cache.
        ctrl.duck()
        assert math.isclose(ctrl._pre_duck_volumes[0], 0.7, abs_tol=1e-6)


class TestDuckingMetricsGauge:
    """W3.3: COMP_MUSIC_DUCKED gauge transitions through the envelope."""

    @patch("agents.studio_compositor.audio_control.metrics.set_music_ducked")
    @patch("time.sleep")
    @patch("subprocess.run")
    def test_duck_publishes_music_ducked_true(
        self,
        mock_run: MagicMock,
        _sleep: MagicMock,
        mock_set: MagicMock,
    ) -> None:
        mock_run.return_value = MagicMock(stdout=PW_DUMP_3_SLOTS, returncode=0)
        ctrl = SlotAudioControl(slot_count=3)
        ctrl.duck()
        ctrl._ramp_thread.join(timeout=2)
        # duck() publishes True at the start of the attack ramp.
        # The terminal state is "ducked" (still ducked), so no False
        # is published until restore() finishes.
        assert mock_set.call_args_list[0] == call(True)
        assert call(False) not in mock_set.call_args_list

    @patch("agents.studio_compositor.audio_control.metrics.set_music_ducked")
    @patch("time.sleep")
    @patch("subprocess.run")
    def test_round_trip_publishes_true_then_false(
        self,
        mock_run: MagicMock,
        _sleep: MagicMock,
        mock_set: MagicMock,
    ) -> None:
        mock_run.return_value = MagicMock(stdout=PW_DUMP_3_SLOTS, returncode=0)
        ctrl = SlotAudioControl(slot_count=3)
        ctrl.duck()
        ctrl._ramp_thread.join(timeout=2)
        ctrl.restore()
        ctrl._ramp_thread.join(timeout=2)
        # Sequence must include True (from duck) followed by False (from
        # restore's terminal state). Order matters.
        calls = mock_set.call_args_list
        assert call(True) in calls
        assert call(False) in calls
        true_idx = calls.index(call(True))
        false_idx = calls.index(call(False))
        assert true_idx < false_idx

    @patch("agents.studio_compositor.audio_control.metrics.set_music_ducked")
    @patch("time.sleep")
    @patch("subprocess.run")
    def test_idempotent_duck_publishes_only_once(
        self,
        mock_run: MagicMock,
        _sleep: MagicMock,
        mock_set: MagicMock,
    ) -> None:
        mock_run.return_value = MagicMock(stdout=PW_DUMP_3_SLOTS, returncode=0)
        ctrl = SlotAudioControl(slot_count=3)
        ctrl.duck()
        ctrl._ramp_thread.join(timeout=2)
        first_count = mock_set.call_count
        ctrl.duck()  # No-op while already ducked.
        # The second duck() returns at the state==ducked guard before
        # touching any metrics, so the call count must not increase.
        assert mock_set.call_count == first_count

    @patch("agents.studio_compositor.audio_control.metrics.set_music_ducked")
    @patch("time.sleep")
    @patch("subprocess.run")
    def test_idle_restore_publishes_nothing(
        self,
        mock_run: MagicMock,
        _sleep: MagicMock,
        mock_set: MagicMock,
    ) -> None:
        mock_run.return_value = MagicMock(stdout=PW_DUMP_3_SLOTS, returncode=0)
        ctrl = SlotAudioControl(slot_count=3)
        ctrl.restore()
        # No envelope state change → no metric publish at all.
        assert mock_set.call_count == 0


# ── FINDING-D + FINDING-E: gate-poll wiring tests (2026-04-21 audit) ──


class _FakeGate:
    """Duck-typed YouTubeGateState stand-in."""

    def __init__(self, *, enabled: bool, active_slot: int = 0) -> None:
        self.enabled = enabled
        self.active_slot = active_slot


class TestApplyGateState:
    @patch("subprocess.run")
    def test_enabled_gate_calls_mute_all_except(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout=PW_DUMP_3_SLOTS, returncode=0)
        ctrl = SlotAudioControl(slot_count=3)
        ctrl.apply_gate_state(_FakeGate(enabled=True, active_slot=1))
        wpctl_calls = [c for c in mock_run.call_args_list if "wpctl" in str(c)]
        volumes = {c.args[0][2]: c.args[0][3] for c in wpctl_calls}
        assert volumes["241"] == "0.0"
        assert volumes["258"] == "1.0"
        assert volumes["285"] == "0.0"

    @patch("subprocess.run")
    def test_disabled_gate_calls_mute_all(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout=PW_DUMP_3_SLOTS, returncode=0)
        ctrl = SlotAudioControl(slot_count=3)
        ctrl.apply_gate_state(_FakeGate(enabled=False))
        wpctl_calls = [c for c in mock_run.call_args_list if "wpctl" in str(c)]
        for c in wpctl_calls:
            assert c.args[0][3] == "0.0"

    @patch("subprocess.run")
    def test_apply_refreshes_node_cache(self, mock_run: MagicMock) -> None:
        """Cache invalidation each call catches respawned ffmpeg node IDs."""
        mock_run.return_value = MagicMock(stdout=PW_DUMP_3_SLOTS, returncode=0)
        ctrl = SlotAudioControl(slot_count=3)
        ctrl.apply_gate_state(_FakeGate(enabled=True, active_slot=0))
        ctrl.apply_gate_state(_FakeGate(enabled=True, active_slot=0))
        # pw-dump should have fired twice (once per apply_gate_state)
        pw_dump_calls = [c for c in mock_run.call_args_list if "pw-dump" in str(c)]
        assert len(pw_dump_calls) == 2


class TestStartGatePoll:
    @patch("subprocess.run")
    def test_poll_thread_calls_gate_reader(self, mock_run: MagicMock) -> None:
        import time as _time

        mock_run.return_value = MagicMock(stdout=PW_DUMP_3_SLOTS, returncode=0)
        ctrl = SlotAudioControl(slot_count=3)

        call_count = {"n": 0}

        def fake_gate_reader() -> _FakeGate:
            call_count["n"] += 1
            return _FakeGate(enabled=True, active_slot=0)

        ctrl.start_gate_poll(interval_s=0.05, gate_reader=fake_gate_reader)
        _time.sleep(0.18)  # let it tick a few times
        ctrl.stop_gate_poll()
        assert call_count["n"] >= 2

    @patch("subprocess.run")
    def test_start_is_idempotent(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout=PW_DUMP_3_SLOTS, returncode=0)
        ctrl = SlotAudioControl(slot_count=3)

        ctrl.start_gate_poll(interval_s=0.5, gate_reader=lambda: _FakeGate(enabled=False))
        first = ctrl._gate_poll_thread
        ctrl.start_gate_poll(interval_s=0.5, gate_reader=lambda: _FakeGate(enabled=False))
        second = ctrl._gate_poll_thread
        ctrl.stop_gate_poll()
        assert first is second  # same thread object, no respawn

    @patch("subprocess.run")
    def test_poll_continues_when_reader_raises(self, mock_run: MagicMock) -> None:
        import time as _time

        mock_run.return_value = MagicMock(stdout=PW_DUMP_3_SLOTS, returncode=0)
        ctrl = SlotAudioControl(slot_count=3)

        call_count = {"n": 0}

        def boom() -> _FakeGate:
            call_count["n"] += 1
            raise RuntimeError("director-intent.jsonl missing")

        ctrl.start_gate_poll(interval_s=0.05, gate_reader=boom)
        _time.sleep(0.18)
        ctrl.stop_gate_poll()
        # The loop continues after each exception — at least 2 calls
        assert call_count["n"] >= 2

    @patch("subprocess.run")
    def test_stop_gate_poll_when_never_started_is_noop(self, mock_run: MagicMock) -> None:
        ctrl = SlotAudioControl(slot_count=3)
        # No start_gate_poll call; stop should not raise.
        ctrl.stop_gate_poll()

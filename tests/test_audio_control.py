"""Tests for SlotAudioControl PipeWire volume management."""

from __future__ import annotations

import json
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

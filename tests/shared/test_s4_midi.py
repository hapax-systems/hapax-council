"""Tests for shared.s4_midi — port discovery + program-change + CC bursts."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from shared.s4_midi import (
    DEFAULT_CC_DELAY_MS,
    S4_MIDI_CHANNEL,
    emit_cc,
    emit_cc_burst,
    emit_program_change,
    find_s4_midi_output,
    is_s4_reachable,
    list_midi_outputs,
)

# ── Port discovery ──────────────────────────────────────────────────


def test_list_midi_outputs_returns_empty_when_mido_unavailable() -> None:
    with patch("shared.s4_midi._MIDO_AVAILABLE", False):
        assert list_midi_outputs() == []


def test_list_midi_outputs_calls_mido_get_output_names() -> None:
    fake_names = ["Torso S-4 MIDI 1", "MIDI Dispatch MIDI 1"]
    with patch("shared.s4_midi._MIDO_AVAILABLE", True), patch("shared.s4_midi.mido") as mido_mock:
        mido_mock.get_output_names.return_value = fake_names
        assert list_midi_outputs() == fake_names


def test_find_s4_midi_output_returns_none_when_no_match() -> None:
    with patch("shared.s4_midi._MIDO_AVAILABLE", True), patch("shared.s4_midi.mido") as mido_mock:
        mido_mock.get_output_names.return_value = ["Some unrelated MIDI device"]
        assert find_s4_midi_output() is None


def test_find_s4_midi_output_prefers_direct_s4_port() -> None:
    """When both Torso S-4 and Dispatch are present, S-4 port wins."""
    with patch("shared.s4_midi._MIDO_AVAILABLE", True), patch("shared.s4_midi.mido") as mido_mock:
        mido_mock.get_output_names.return_value = [
            "MIDI Dispatch MIDI 2",
            "Torso S-4 MIDI 1",
        ]
        port = MagicMock(name="s4_port")
        mido_mock.open_output.return_value = port
        assert find_s4_midi_output() is port
        mido_mock.open_output.assert_called_once_with("Torso S-4 MIDI 1")


def test_find_s4_midi_output_falls_back_to_dispatch_lane_2() -> None:
    """When direct S-4 absent, Erica Dispatch OUT 2 is the canonical lane."""
    with patch("shared.s4_midi._MIDO_AVAILABLE", True), patch("shared.s4_midi.mido") as mido_mock:
        mido_mock.get_output_names.return_value = [
            "MIDI Dispatch MIDI 1",  # OUT 1 — Evil Pet
            "MIDI Dispatch MIDI 2",  # OUT 2 — S-4 fallback
        ]
        port = MagicMock(name="dispatch_port")
        mido_mock.open_output.return_value = port
        assert find_s4_midi_output() is port
        mido_mock.open_output.assert_called_once_with("MIDI Dispatch MIDI 2")


def test_find_s4_midi_output_does_not_use_dispatch_midi_1() -> None:
    """Spec §6.1 — Dispatch MIDI 1 is Evil Pet; only MIDI 2 routes to S-4."""
    with patch("shared.s4_midi._MIDO_AVAILABLE", True), patch("shared.s4_midi.mido") as mido_mock:
        mido_mock.get_output_names.return_value = ["MIDI Dispatch MIDI 1"]
        assert find_s4_midi_output() is None


def test_is_s4_reachable_true_when_s4_port_present() -> None:
    with patch("shared.s4_midi._MIDO_AVAILABLE", True), patch("shared.s4_midi.mido") as mido_mock:
        mido_mock.get_output_names.return_value = ["Torso Electronics S-4"]
        assert is_s4_reachable() is True


def test_is_s4_reachable_false_when_only_unrelated_ports() -> None:
    with patch("shared.s4_midi._MIDO_AVAILABLE", True), patch("shared.s4_midi.mido") as mido_mock:
        mido_mock.get_output_names.return_value = ["Yamaha-CC-USB"]
        assert is_s4_reachable() is False


def test_is_s4_reachable_false_when_mido_unavailable() -> None:
    with patch("shared.s4_midi._MIDO_AVAILABLE", False):
        assert is_s4_reachable() is False


# ── Program change ──────────────────────────────────────────────────


def test_emit_program_change_returns_false_for_none_output() -> None:
    assert emit_program_change(None, program=1) is False


def test_emit_program_change_sends_message_to_port() -> None:
    port = MagicMock()
    fake_msg = MagicMock()
    with (
        patch("shared.s4_midi._MIDO_AVAILABLE", True),
        patch("shared.s4_midi.Message", return_value=fake_msg) as msg_cls,
    ):
        result = emit_program_change(port, program=5, channel=2)
    assert result is True
    msg_cls.assert_called_once_with("program_change", program=5, channel=2)
    port.send.assert_called_once_with(fake_msg)


def test_emit_program_change_uses_default_channel_when_unspecified() -> None:
    port = MagicMock()
    with patch("shared.s4_midi._MIDO_AVAILABLE", True), patch("shared.s4_midi.Message") as msg_cls:
        emit_program_change(port, program=0)
    args, kwargs = msg_cls.call_args
    assert kwargs["channel"] == S4_MIDI_CHANNEL


def test_emit_program_change_rejects_out_of_range_program() -> None:
    port = MagicMock()
    with patch("shared.s4_midi._MIDO_AVAILABLE", True):
        assert emit_program_change(port, program=128) is False
        assert emit_program_change(port, program=-1) is False
    port.send.assert_not_called()


def test_emit_program_change_rejects_out_of_range_channel() -> None:
    port = MagicMock()
    with patch("shared.s4_midi._MIDO_AVAILABLE", True):
        assert emit_program_change(port, program=0, channel=16) is False
    port.send.assert_not_called()


def test_emit_program_change_swallows_send_exceptions() -> None:
    """Hot-path discipline: failures must not bubble to the router tick."""
    port = MagicMock()
    port.send.side_effect = RuntimeError("MIDI bus error")
    with patch("shared.s4_midi._MIDO_AVAILABLE", True), patch("shared.s4_midi.Message"):
        assert emit_program_change(port, program=0) is False


# ── CC emit + burst ─────────────────────────────────────────────────


def test_emit_cc_returns_false_for_none_output() -> None:
    assert emit_cc(None, cc=1, value=64) is False


def test_emit_cc_sends_message_with_post_emit_delay() -> None:
    port = MagicMock()
    fake_msg = MagicMock()
    with (
        patch("shared.s4_midi._MIDO_AVAILABLE", True),
        patch("shared.s4_midi.Message", return_value=fake_msg) as msg_cls,
        patch("shared.s4_midi.time.sleep") as sleep_mock,
    ):
        result = emit_cc(port, cc=12, value=80, channel=1, delay_ms=15.0)
    assert result is True
    msg_cls.assert_called_once_with("control_change", control=12, value=80, channel=1)
    port.send.assert_called_once_with(fake_msg)
    sleep_mock.assert_called_once_with(15.0 / 1000.0)


def test_emit_cc_skips_sleep_when_delay_zero() -> None:
    port = MagicMock()
    with (
        patch("shared.s4_midi._MIDO_AVAILABLE", True),
        patch("shared.s4_midi.Message"),
        patch("shared.s4_midi.time.sleep") as sleep_mock,
    ):
        emit_cc(port, cc=1, value=0, delay_ms=0.0)
    sleep_mock.assert_not_called()


def test_emit_cc_rejects_out_of_range_values() -> None:
    port = MagicMock()
    with patch("shared.s4_midi._MIDO_AVAILABLE", True):
        assert emit_cc(port, cc=128, value=0) is False
        assert emit_cc(port, cc=0, value=128) is False
        assert emit_cc(port, cc=-1, value=0) is False
    port.send.assert_not_called()


def test_emit_cc_burst_returns_count_of_successful_emits() -> None:
    port = MagicMock()
    with (
        patch("shared.s4_midi._MIDO_AVAILABLE", True),
        patch("shared.s4_midi.Message"),
        patch("shared.s4_midi.time.sleep"),
    ):
        n = emit_cc_burst(port, {1: 10, 2: 20, 3: 30})
    assert n == 3
    assert port.send.call_count == 3


def test_emit_cc_burst_returns_zero_for_none_output() -> None:
    assert emit_cc_burst(None, {1: 10}) == 0


def test_emit_cc_burst_returns_zero_for_empty_dict() -> None:
    port = MagicMock()
    with patch("shared.s4_midi._MIDO_AVAILABLE", True):
        assert emit_cc_burst(port, {}) == 0


def test_emit_cc_burst_default_delay_is_20ms() -> None:
    """Spec §4.2 — 20 ms inter-message delay protects S-4 firmware drops."""
    assert DEFAULT_CC_DELAY_MS == 20.0

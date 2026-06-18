"""Tests for shared.s4_midi — port discovery + program-change + CC bursts."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

from shared.s4_midi import (
    DEFAULT_CC_DELAY_MS,
    S4_MIDI_CHANNEL,
    emit_cc,
    emit_cc_burst,
    emit_cc_commands,
    emit_note_on,
    emit_program_change,
    find_s4_midi_output,
    is_s4_reachable,
    list_midi_outputs,
    resolve_s4_midi_output_name,
)
from shared.s4_scenes import EMPIRICAL_S4_GAIN_LADDER

REPO_ROOT = Path(__file__).resolve().parents[2]
S4_CONFIGURE_BASE = REPO_ROOT / "scripts" / "s4-configure-base.py"


def _load_s4_configure_base(monkeypatch, fake_mido: MagicMock):
    monkeypatch.setitem(sys.modules, "mido", fake_mido)
    loader = importlib.machinery.SourceFileLoader(
        "s4_configure_base_under_test",
        str(S4_CONFIGURE_BASE),
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


# ── Port discovery ──────────────────────────────────────────────────


def test_list_midi_outputs_returns_empty_when_mido_unavailable() -> None:
    with patch("shared.s4_midi._MIDO_AVAILABLE", False):
        assert list_midi_outputs() == []


def test_list_midi_outputs_calls_mido_get_output_names() -> None:
    fake_names = ["Retrokits RK-006 MIDI 1", "Torso S-4 MIDI 1"]
    with patch("shared.s4_midi._MIDO_AVAILABLE", True), patch("shared.s4_midi.mido") as mido_mock:
        mido_mock.get_output_names.return_value = fake_names
        assert list_midi_outputs() == fake_names


def test_find_s4_midi_output_returns_none_when_no_match() -> None:
    with patch("shared.s4_midi._MIDO_AVAILABLE", True), patch("shared.s4_midi.mido") as mido_mock:
        mido_mock.get_output_names.return_value = ["Some unrelated MIDI device"]
        assert find_s4_midi_output() is None


def test_resolve_s4_midi_output_name_prefers_s4_usb_regardless_list_order() -> None:
    assert (
        resolve_s4_midi_output_name(
            [
                "Retrokits RK-006 MIDI 1",
                "S-4:S-4 MIDI 1 48:0",
            ]
        )
        == "S-4:S-4 MIDI 1 48:0"
    )


def test_find_s4_midi_output_prefers_s4_usb_control_plane() -> None:
    """The current live S-4 input is the device's own USB-MIDI port."""
    with patch("shared.s4_midi._MIDO_AVAILABLE", True), patch("shared.s4_midi.mido") as mido_mock:
        mido_mock.get_output_names.return_value = [
            "MIDI Dispatch MIDI 2",
            "Retrokits RK-006 MIDI 1",
            "S-4:S-4 MIDI 1 48:0",
        ]
        port = MagicMock(name="s4_usb_port")
        mido_mock.open_output.return_value = port
        assert find_s4_midi_output() is port
        mido_mock.open_output.assert_called_once_with("S-4:S-4 MIDI 1 48:0")


def test_find_s4_midi_output_uses_rk006_fallback_when_usb_absent() -> None:
    with patch("shared.s4_midi._MIDO_AVAILABLE", True), patch("shared.s4_midi.mido") as mido_mock:
        mido_mock.get_output_names.return_value = [
            "MIDI Dispatch MIDI 2",
            "Retrokits RK-006 MIDI 1",
        ]
        port = MagicMock(name="rk006_port")
        mido_mock.open_output.return_value = port
        assert find_s4_midi_output() is port
        mido_mock.open_output.assert_called_once_with("Retrokits RK-006 MIDI 1")


def test_find_s4_midi_output_does_not_fall_back_when_s4_usb_open_fails(caplog) -> None:
    with patch("shared.s4_midi._MIDO_AVAILABLE", True), patch("shared.s4_midi.mido") as mido_mock:
        mido_mock.get_output_names.return_value = [
            "Retrokits RK-006 MIDI 1",
            "S-4:S-4 MIDI 1 48:0",
        ]
        mido_mock.open_output.side_effect = OSError("busy")
        with caplog.at_level(logging.WARNING, logger="shared.s4_midi"):
            assert find_s4_midi_output() is None
        mido_mock.open_output.assert_called_once_with("S-4:S-4 MIDI 1 48:0")
    assert "Next action: check ALSA/mido port ownership" in caplog.text


def test_find_s4_midi_output_retries_same_priority_s4_usb_candidates() -> None:
    with patch("shared.s4_midi._MIDO_AVAILABLE", True), patch("shared.s4_midi.mido") as mido_mock:
        mido_mock.get_output_names.return_value = [
            "S-4:S-4 MIDI 1 48:0",
            "Torso Electronics S-4",
            "Retrokits RK-006 MIDI 1",
        ]
        port = MagicMock(name="second_s4_usb_port")
        mido_mock.open_output.side_effect = [OSError("busy"), port]
        assert find_s4_midi_output() is port
        assert mido_mock.open_output.mock_calls == [
            call("S-4:S-4 MIDI 1 48:0"),
            call("Torso Electronics S-4"),
        ]


def test_find_s4_midi_output_stops_before_rk006_after_all_s4_usb_candidates_fail() -> None:
    with patch("shared.s4_midi._MIDO_AVAILABLE", True), patch("shared.s4_midi.mido") as mido_mock:
        mido_mock.get_output_names.return_value = [
            "S-4:S-4 MIDI 1 48:0",
            "Torso Electronics S-4",
            "Retrokits RK-006 MIDI 1",
        ]
        mido_mock.open_output.side_effect = OSError("busy")
        assert find_s4_midi_output() is None
        assert mido_mock.open_output.mock_calls == [
            call("S-4:S-4 MIDI 1 48:0"),
            call("Torso Electronics S-4"),
        ]


def test_find_s4_midi_output_does_not_use_retired_dispatch_port() -> None:
    """The retired Erica Dispatch lane must not claim S-4 reachability."""
    with patch("shared.s4_midi._MIDO_AVAILABLE", True), patch("shared.s4_midi.mido") as mido_mock:
        mido_mock.get_output_names.return_value = [
            "MIDI Dispatch MIDI 1",
        ]
        assert find_s4_midi_output() is None
        mido_mock.open_output.assert_not_called()


def test_find_s4_midi_output_ignores_unrelated_dispatch_names() -> None:
    with patch("shared.s4_midi._MIDO_AVAILABLE", True), patch("shared.s4_midi.mido") as mido_mock:
        mido_mock.get_output_names.return_value = ["MIDI Dispatch Control"]
        assert find_s4_midi_output() is None


def test_is_s4_reachable_true_when_s4_port_present() -> None:
    with patch("shared.s4_midi._MIDO_AVAILABLE", True), patch("shared.s4_midi.mido") as mido_mock:
        mido_mock.get_output_names.return_value = ["S-4:S-4 MIDI 1 48:0"]
        assert is_s4_reachable() is True


def test_is_s4_reachable_true_for_rk006_fallback() -> None:
    with patch("shared.s4_midi._MIDO_AVAILABLE", True), patch("shared.s4_midi.mido") as mido_mock:
        mido_mock.get_output_names.return_value = ["Retrokits RK006 MIDI 1"]
        assert is_s4_reachable() is True


def test_is_s4_reachable_true_for_s4_usb_name_variant() -> None:
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


# ── Configure script integration ────────────────────────────────────


def test_s4_configure_base_main_prefers_s4_usb(monkeypatch, capsys) -> None:
    fake_mido = MagicMock()
    fake_mido.get_output_names.return_value = [
        "Retrokits RK-006 MIDI 1",
        "S-4:S-4 MIDI 1 48:0",
    ]
    fake_port = MagicMock()
    fake_mido.open_output.return_value.__enter__.return_value = fake_port
    module = _load_s4_configure_base(monkeypatch, fake_mido)
    monkeypatch.setattr(module.time, "sleep", MagicMock())

    assert module.main() == 0

    fake_mido.open_output.assert_called_once_with("S-4:S-4 MIDI 1 48:0")
    assert fake_port.send.call_count == len(EMPIRICAL_S4_GAIN_LADDER)
    captured = capsys.readouterr()
    assert "Opening MIDI port: S-4:S-4 MIDI 1 48:0" in captured.out


def test_s4_configure_base_main_no_match_prints_next_action(monkeypatch, capsys) -> None:
    fake_mido = MagicMock()
    fake_mido.get_output_names.return_value = ["Unrelated MIDI 1"]
    module = _load_s4_configure_base(monkeypatch, fake_mido)

    assert module.main() == 1

    fake_mido.open_output.assert_not_called()
    captured = capsys.readouterr()
    assert "S-4 MIDI port not found among ['Unrelated MIDI 1']." in captured.err
    assert "Next action: verify S-4 USB-MIDI enumeration" in captured.err


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


# ── Note emit ───────────────────────────────────────────────────────


def test_emit_note_on_sends_message_with_post_emit_delay() -> None:
    port = MagicMock()
    fake_msg = MagicMock()
    with (
        patch("shared.s4_midi._MIDO_AVAILABLE", True),
        patch("shared.s4_midi.Message", return_value=fake_msg) as msg_cls,
        patch("shared.s4_midi.time.sleep") as sleep_mock,
    ):
        result = emit_note_on(port, note=41, velocity=127, channel=15, delay_ms=10.0)
    assert result is True
    msg_cls.assert_called_once_with("note_on", note=41, velocity=127, channel=15)
    port.send.assert_called_once_with(fake_msg)
    sleep_mock.assert_called_once_with(10.0 / 1000.0)


def test_emit_note_on_rejects_out_of_range_values() -> None:
    port = MagicMock()
    with patch("shared.s4_midi._MIDO_AVAILABLE", True):
        assert emit_note_on(port, note=128) is False
        assert emit_note_on(port, note=1, velocity=128) is False
        assert emit_note_on(port, note=1, channel=16) is False
    port.send.assert_not_called()


def test_emit_cc_commands_respects_per_command_channels() -> None:
    port = MagicMock()
    with (
        patch("shared.s4_midi._MIDO_AVAILABLE", True),
        patch("shared.s4_midi.Message") as msg_cls,
        patch("shared.s4_midi.time.sleep"),
    ):
        n = emit_cc_commands(port, EMPIRICAL_S4_GAIN_LADDER)
    assert n == len(EMPIRICAL_S4_GAIN_LADDER)
    emitted = [
        (call.kwargs["channel"], call.kwargs["control"], call.kwargs["value"])
        for call in msg_cls.call_args_list
    ]
    assert emitted == [(c.channel, c.cc, c.value) for c in EMPIRICAL_S4_GAIN_LADDER]

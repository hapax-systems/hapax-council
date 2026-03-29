"""Tests for MidiOutput — thin mido wrapper for MIDI CC sending."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agents.hapax_daimonion.midi_output import MidiOutput


class TestMidiOutputInit:
    def test_lazy_init_no_port_opened(self) -> None:
        out = MidiOutput()
        assert out._port is None

    def test_port_name_stored(self) -> None:
        out = MidiOutput(port_name="Evil Pet")
        assert out._port_name == "Evil Pet"


class TestMidiOutputSendCC:
    def test_send_cc_opens_port_and_sends(self) -> None:
        mock_port = MagicMock()
        with patch("agents.hapax_daimonion.midi_output.mido") as mock_mido:
            mock_mido.open_output.return_value = mock_port
            mock_msg = MagicMock()
            mock_mido.Message.return_value = mock_msg

            out = MidiOutput(port_name="Evil Pet")
            out.send_cc(channel=0, cc=42, value=64)

            mock_mido.open_output.assert_called_once_with("Evil Pet")
            mock_mido.Message.assert_called_once_with(
                "control_change", channel=0, control=42, value=64
            )
            mock_port.send.assert_called_once_with(mock_msg)

    def test_send_cc_reuses_port(self) -> None:
        mock_port = MagicMock()
        with patch("agents.hapax_daimonion.midi_output.mido") as mock_mido:
            mock_mido.open_output.return_value = mock_port
            mock_mido.Message.return_value = MagicMock()

            out = MidiOutput(port_name="Test")
            out.send_cc(channel=0, cc=1, value=10)
            out.send_cc(channel=0, cc=2, value=20)

            mock_mido.open_output.assert_called_once()

    def test_send_cc_clamps_value(self) -> None:
        mock_port = MagicMock()
        with patch("agents.hapax_daimonion.midi_output.mido") as mock_mido:
            mock_mido.open_output.return_value = mock_port
            mock_mido.Message.return_value = MagicMock()

            out = MidiOutput()
            out.send_cc(channel=0, cc=42, value=200)

            mock_mido.Message.assert_called_once_with(
                "control_change", channel=0, control=42, value=127
            )

    def test_send_cc_clamps_negative(self) -> None:
        mock_port = MagicMock()
        with patch("agents.hapax_daimonion.midi_output.mido") as mock_mido:
            mock_mido.open_output.return_value = mock_port
            mock_mido.Message.return_value = MagicMock()

            out = MidiOutput()
            out.send_cc(channel=0, cc=42, value=-5)

            mock_mido.Message.assert_called_once_with(
                "control_change", channel=0, control=42, value=0
            )


class TestMidiOutputGracefulDegradation:
    def test_port_unavailable_logs_warning(self) -> None:
        with patch("agents.hapax_daimonion.midi_output.mido") as mock_mido:
            mock_mido.open_output.side_effect = OSError("No MIDI devices")

            out = MidiOutput(port_name="Nonexistent")
            out.send_cc(channel=0, cc=42, value=64)
            assert out._port is None

    def test_send_after_failed_init_is_noop(self) -> None:
        with patch("agents.hapax_daimonion.midi_output.mido") as mock_mido:
            mock_mido.open_output.side_effect = OSError("No MIDI")

            out = MidiOutput()
            out.send_cc(channel=0, cc=1, value=10)
            out.send_cc(channel=0, cc=2, value=20)

            mock_mido.open_output.assert_called_once()


class TestMidiOutputClose:
    def test_close_closes_port(self) -> None:
        mock_port = MagicMock()
        with patch("agents.hapax_daimonion.midi_output.mido") as mock_mido:
            mock_mido.open_output.return_value = mock_port
            mock_mido.Message.return_value = MagicMock()

            out = MidiOutput()
            out.send_cc(channel=0, cc=1, value=1)
            out.close()

            mock_port.close.assert_called_once()
            assert out._port is None

"""Phase 1 integration — MIDI port resolution + consumer-loop wiring.

Ships together with the wiring change in run_loops_aux.py and the
config default update in config.py. Verifies:

  - MIDI port default resolves to "MIDI Dispatch:MIDI Dispatch MIDI 1" (not "" / loopback)
  - MidiOutput degrades fail-closed on missing port (one attempt, latched off)
  - MidiOutput.is_open() returns False in the failed-latch state
  - send_cc reaches mido.Message with correct CC parameters

The consumer-loop wiring integration (activate_from_impingement + decay)
is exercised by the existing test_vocal_chain_wiring.py and the live
restart smoke; keeping this module focused on the port-resolution +
fail-open guard seam so callers can depend on it.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


class TestMidiPortResolution(unittest.TestCase):
    def test_default_port_name_is_studio_24c(self) -> None:
        from agents.hapax_daimonion.config import DaimonionConfig

        cfg = DaimonionConfig()
        assert cfg.midi_output_port == "MIDI Dispatch:MIDI Dispatch MIDI 1"

    def test_midi_output_opens_named_port(self) -> None:
        from agents.hapax_daimonion.midi_output import MidiOutput

        fake_mido = MagicMock()
        fake_port = MagicMock()
        fake_port.name = "MIDI Dispatch:MIDI Dispatch MIDI 1 56:0"
        fake_mido.get_output_names.return_value = ["MIDI Dispatch:MIDI Dispatch MIDI 1 56:0"]
        fake_mido.open_output.return_value = fake_port

        with patch("agents.hapax_daimonion.midi_output.mido", fake_mido):
            out = MidiOutput(port_name="MIDI Dispatch:MIDI Dispatch MIDI 1")
            out.send_cc(channel=0, cc=40, value=42)

        # Resolver expanded the bare name to the live "NAME N:M" form.
        fake_mido.open_output.assert_called_once_with("MIDI Dispatch:MIDI Dispatch MIDI 1 56:0")
        fake_port.send.assert_called_once()
        fake_mido.Message.assert_called_once_with("control_change", channel=0, control=40, value=42)

    def test_resolver_tolerates_alsa_client_id_drift(self) -> None:
        """The configured name must keep matching after ALSA renumbering."""
        from agents.hapax_daimonion.midi_output import MidiOutput

        fake_mido = MagicMock()
        fake_mido.get_output_names.return_value = ["MIDI Dispatch:MIDI Dispatch MIDI 1 62:0"]
        fake_mido.open_output.return_value = MagicMock()

        with patch("agents.hapax_daimonion.midi_output.mido", fake_mido):
            out = MidiOutput(port_name="MIDI Dispatch:MIDI Dispatch MIDI 1 56:0")
            out.send_cc(channel=0, cc=40, value=42)

        fake_mido.open_output.assert_called_once_with("MIDI Dispatch:MIDI Dispatch MIDI 1 62:0")

    def test_missing_port_degrades_to_noop_no_crash(self) -> None:
        from agents.hapax_daimonion.midi_output import MidiOutput

        fake_mido = MagicMock()
        fake_mido.get_output_names.return_value = ["SomeOther:Port 40:0"]

        with patch("agents.hapax_daimonion.midi_output.mido", fake_mido):
            out = MidiOutput(port_name="MIDI Dispatch:MIDI Dispatch MIDI 1")
            out.send_cc(channel=0, cc=40, value=42)
            out.send_cc(channel=0, cc=40, value=43)

        fake_mido.open_output.assert_not_called()  # resolver rejected the port, never opened
        assert out.is_open() is False

    def test_is_open_true_after_successful_open(self) -> None:
        from agents.hapax_daimonion.midi_output import MidiOutput

        fake_mido = MagicMock()
        fake_mido.get_output_names.return_value = ["MIDI Dispatch:MIDI Dispatch MIDI 1 56:0"]
        fake_mido.open_output.return_value = MagicMock(name="port")

        with patch("agents.hapax_daimonion.midi_output.mido", fake_mido):
            out = MidiOutput(port_name="MIDI Dispatch:MIDI Dispatch MIDI 1")
            assert out.is_open() is False  # pre-send, not yet opened
            out.send_cc(channel=0, cc=40, value=42)
            assert out.is_open() is True


if __name__ == "__main__":
    unittest.main()

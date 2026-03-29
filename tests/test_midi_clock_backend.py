"""Tests for MidiClockBackend — mocked mido, tempo detection, transport state."""

from __future__ import annotations

import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agents.hapax_daimonion.backends.midi_clock import _PPQN, MidiClockBackend
from agents.hapax_daimonion.primitives import Behavior
from agents.hapax_daimonion.timeline import TransportState


def _msg(msg_type: str) -> SimpleNamespace:
    """Create a minimal mido-like message."""
    return SimpleNamespace(type=msg_type)


class TestMidiClockBackend(unittest.TestCase):
    def _make_backend(self) -> MidiClockBackend:
        backend = MidiClockBackend(port_name="Test Port")
        # Manually set available since we won't actually open a port
        backend._available = True
        return backend

    def test_transport_state_machine(self):
        """STOPPED → start → PLAYING → stop → STOPPED → continue → PLAYING."""
        b = self._make_backend()
        self.assertEqual(b._transport, TransportState.STOPPED)

        b._on_message(_msg("start"))
        self.assertEqual(b._transport, TransportState.PLAYING)

        b._on_message(_msg("stop"))
        self.assertEqual(b._transport, TransportState.STOPPED)

        b._on_message(_msg("continue"))
        self.assertEqual(b._transport, TransportState.PLAYING)

    def test_tempo_detection_from_ticks(self):
        """Inject 24 clock ticks at known intervals → detect tempo."""
        b = self._make_backend()
        b._on_message(_msg("start"))

        # 120 BPM = 2 beats/sec = 48 ticks/sec → tick interval = 1/48 ≈ 0.020833s
        tick_interval = 60.0 / (120.0 * _PPQN)

        base_time = time.monotonic()
        for i in range(_PPQN + 1):
            t = base_time + i * tick_interval
            b._tick_times.append(t)
            if b._transport is TransportState.PLAYING:
                b._tick_count += 1
            b._update_tempo()

        # Tempo should be approximately 120 BPM
        self.assertAlmostEqual(b._tempo, 120.0, delta=1.0)

    def test_contribute_updates_behaviors(self):
        b = self._make_backend()
        b._on_message(_msg("start"))

        behaviors: dict[str, Behavior] = {}
        b.contribute(behaviors)

        self.assertIn("timeline_mapping", behaviors)
        self.assertIn("beat_position", behaviors)
        self.assertIn("bar_position", behaviors)

    def test_contribute_transport_stopped(self):
        b = self._make_backend()
        behaviors: dict[str, Behavior] = {}
        b.contribute(behaviors)

        mapping = behaviors["timeline_mapping"].value
        self.assertEqual(mapping.transport, TransportState.STOPPED)

    def test_beat_position_monotonic_during_playing(self):
        """beat_position should be monotonically non-decreasing during PLAYING."""
        b = self._make_backend()
        b._on_message(_msg("start"))

        positions = []
        for i in range(10):
            # Simulate time passing with ticks
            b._tick_count = i * 6  # 6 ticks per sample
            behaviors: dict[str, Behavior] = {}
            b.contribute(behaviors)
            positions.append(behaviors["beat_position"].value)

        for i in range(1, len(positions)):
            self.assertGreaterEqual(positions[i], positions[i - 1])

    @patch("agents.hapax_daimonion.backends.midi_clock.mido", create=True)
    def test_start_opens_port(self, mock_mido):
        b = MidiClockBackend(port_name="Test Port")
        b.start()
        mock_mido.open_input.assert_called_once_with("Test Port", callback=b._on_message)
        self.assertTrue(b._available)

    @patch("agents.hapax_daimonion.backends.midi_clock.mido", create=True)
    def test_start_unavailable_port(self, mock_mido):
        mock_mido.open_input.side_effect = OSError("No such port")
        b = MidiClockBackend(port_name="Missing Port")
        b.start()
        self.assertFalse(b._available)

    def test_stop_cleans_up(self):
        b = self._make_backend()
        mock_port = MagicMock()
        b._port = mock_port
        b.stop()
        mock_port.close.assert_called_once()
        self.assertFalse(b._available)

    def test_tick_count_reset_on_start(self):
        b = self._make_backend()
        b._tick_count = 100
        b._on_message(_msg("start"))
        self.assertEqual(b._tick_count, 0)

    def test_bar_position(self):
        b = self._make_backend()
        b._on_message(_msg("start"))
        b._tick_count = _PPQN * 8  # 8 beats = 2 bars at 4/4
        behaviors: dict[str, Behavior] = {}
        b.contribute(behaviors)
        self.assertAlmostEqual(behaviors["bar_position"].value, 2.0, delta=0.1)


if __name__ == "__main__":
    unittest.main()

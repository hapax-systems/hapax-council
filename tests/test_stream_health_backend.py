"""Tests for StreamHealthBackend — mocked obs-websocket stats polling."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from agents.hapax_daimonion.backends.stream_health import StreamHealthBackend
from agents.hapax_daimonion.primitives import Behavior


class TestStreamHealthBackend(unittest.TestCase):
    def test_name_and_provides(self):
        b = StreamHealthBackend()
        self.assertEqual(b.name, "stream_health")
        self.assertEqual(
            b.provides,
            frozenset({"stream_bitrate", "stream_dropped_frames", "stream_encoding_lag"}),
        )

    def test_contribute_updates_behaviors(self):
        b = StreamHealthBackend()
        mock_client = MagicMock()
        mock_client.get_stats.return_value = SimpleNamespace(average_frame_render_time=5.0)
        mock_client.get_stream_status.return_value = SimpleNamespace(
            output_bytes=500000,
            output_total_frames=1000,
            output_skipped_frames=10,
        )
        b._client = mock_client

        behaviors: dict[str, Behavior] = {}
        b.contribute(behaviors)

        self.assertIn("stream_bitrate", behaviors)
        self.assertIn("stream_dropped_frames", behaviors)
        self.assertIn("stream_encoding_lag", behaviors)
        self.assertAlmostEqual(behaviors["stream_dropped_frames"].value, 1.0, delta=0.1)
        self.assertAlmostEqual(behaviors["stream_encoding_lag"].value, 5.0)

    def test_contribute_without_client(self):
        b = StreamHealthBackend()
        behaviors: dict[str, Behavior] = {}
        b.contribute(behaviors)
        # Should not raise, behaviors may be empty (default values in Behavior)
        # Just ensure no exception
        self.assertNotIn("stream_bitrate", behaviors)

    def test_client_error_resets(self):
        b = StreamHealthBackend()
        mock_client = MagicMock()
        mock_client.get_stats.side_effect = RuntimeError("connection lost")
        b._client = mock_client

        behaviors: dict[str, Behavior] = {}
        b.contribute(behaviors)
        self.assertIsNone(b._client)

    def test_stop_disconnects(self):
        b = StreamHealthBackend()
        mock_client = MagicMock()
        b._client = mock_client
        b.stop()
        mock_client.disconnect.assert_called_once()
        self.assertIsNone(b._client)


if __name__ == "__main__":
    unittest.main()

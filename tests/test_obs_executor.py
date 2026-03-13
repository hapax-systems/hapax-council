"""Tests for OBSExecutor — mocked obs-websocket, scene switching, transitions."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from agents.hapax_voice.commands import Command
from agents.hapax_voice.executor import Executor
from agents.hapax_voice.obs_executor import OBSExecutor


class TestOBSExecutor(unittest.TestCase):
    def test_satisfies_executor_protocol(self):
        ex = OBSExecutor()
        self.assertIsInstance(ex, Executor)

    def test_handles(self):
        ex = OBSExecutor()
        self.assertEqual(
            ex.handles, frozenset({"wide_ambient", "gear_closeup", "face_cam", "rapid_cut"})
        )

    def test_scene_switch_dispatched(self):
        ex = OBSExecutor()
        mock_client = MagicMock()
        ex._client = mock_client

        cmd = Command(action="face_cam", params={"transition": "cut"})
        ex.execute(cmd)

        mock_client.set_current_scene_transition.assert_called_once_with(transitionName="Cut")
        mock_client.set_current_scene_transition_duration.assert_called_once_with(
            transitionDuration=0
        )
        mock_client.set_current_program_scene.assert_called_once_with(sceneName="face_cam")

    def test_dissolve_transition(self):
        ex = OBSExecutor()
        mock_client = MagicMock()
        ex._client = mock_client

        cmd = Command(action="wide_ambient", params={"transition": "dissolve"})
        ex.execute(cmd)

        mock_client.set_current_scene_transition_duration.assert_called_once_with(
            transitionDuration=500
        )

    def test_fade_transition(self):
        ex = OBSExecutor()
        mock_client = MagicMock()
        ex._client = mock_client

        cmd = Command(action="gear_closeup", params={"transition": "fade"})
        ex.execute(cmd)

        mock_client.set_current_scene_transition_duration.assert_called_once_with(
            transitionDuration=1000
        )

    def test_no_client_skips(self):
        ex = OBSExecutor()
        # No client set → should not raise
        cmd = Command(action="face_cam", params={"transition": "cut"})
        ex.execute(cmd)  # should not raise

    def test_client_error_resets_connection(self):
        ex = OBSExecutor()
        mock_client = MagicMock()
        mock_client.set_current_scene_transition.side_effect = RuntimeError("disconnected")
        ex._client = mock_client

        cmd = Command(action="face_cam", params={"transition": "cut"})
        ex.execute(cmd)
        self.assertIsNone(ex._client)  # connection reset

    def test_close(self):
        ex = OBSExecutor()
        mock_client = MagicMock()
        ex._client = mock_client
        ex.close()
        mock_client.disconnect.assert_called_once()
        self.assertIsNone(ex._client)

    def test_name(self):
        self.assertEqual(OBSExecutor().name, "obs")


if __name__ == "__main__":
    unittest.main()

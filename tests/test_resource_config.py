"""Tests for resource_config module."""

from __future__ import annotations

import unittest

from agents.hapax_voice.resource_config import DEFAULT_PRIORITIES, RESOURCE_MAP, resource_for


class TestResourceFor(unittest.TestCase):
    def test_vocal_throw(self):
        self.assertEqual(resource_for("vocal_throw"), "audio_output")

    def test_face_cam(self):
        self.assertEqual(resource_for("face_cam"), "obs_scene")

    def test_all_mapped_actions(self):
        for action, resource in RESOURCE_MAP.items():
            self.assertEqual(resource_for(action), resource)

    def test_unknown_raises_key_error(self):
        with self.assertRaises(KeyError):
            resource_for("nonexistent_action")


class TestPriorityMapIntegrity(unittest.TestCase):
    def test_all_priorities_positive(self):
        for key, priority in DEFAULT_PRIORITIES.items():
            self.assertGreater(priority, 0, f"Priority for {key} must be positive")

    def test_conversation_highest_on_audio(self):
        audio_priorities = {
            k: v for k, v in DEFAULT_PRIORITIES.items() if k[0] == "audio_output"
        }
        max_chain = max(audio_priorities, key=lambda k: audio_priorities[k])
        self.assertEqual(max_chain[1], "conversation")


if __name__ == "__main__":
    unittest.main()

"""Tests for mode-driven grounding activation."""

from __future__ import annotations

import unittest
from unittest.mock import patch


class TestModeGroundingActivation(unittest.TestCase):
    """Verify R&D mode enables grounding flags, research mode uses config."""

    def test_rnd_mode_enables_grounding_flags(self):
        flags: dict = {}
        from agents.hapax_daimonion.pipeline_start import _apply_mode_grounding_defaults

        with patch("agents._working_mode.get_working_mode") as mock_mode:
            mock_mode.return_value.value = "rnd"
            _apply_mode_grounding_defaults(flags)

        assert flags["grounding_directive"] is True
        assert flags["effort_modulation"] is True
        assert flags["cross_session"] is True
        assert flags["stable_frame"] is True
        assert flags["message_drop"] is True

    def test_research_mode_preserves_config_flags(self):
        flags: dict = {"grounding_directive": False, "experiment_mode": True}
        from agents.hapax_daimonion.pipeline_start import _apply_mode_grounding_defaults

        with patch("agents._working_mode.get_working_mode") as mock_mode:
            mock_mode.return_value.value = "research"
            _apply_mode_grounding_defaults(flags)

        assert flags["grounding_directive"] is False

    def test_rnd_mode_does_not_override_explicit_experiment(self):
        flags: dict = {"grounding_directive": False, "experiment_mode": True}
        from agents.hapax_daimonion.pipeline_start import _apply_mode_grounding_defaults

        with patch("agents._working_mode.get_working_mode") as mock_mode:
            mock_mode.return_value.value = "rnd"
            _apply_mode_grounding_defaults(flags)

        assert flags["grounding_directive"] is False


if __name__ == "__main__":
    unittest.main()

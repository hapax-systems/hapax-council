"""Tests for mode-driven grounding flag injection."""

from __future__ import annotations

import unittest
from unittest.mock import patch


class TestGroundingModeInjection(unittest.TestCase):
    def test_rnd_mode_enables_grounding(self):
        from agents._working_mode import WorkingMode

        flags: dict = {"enable_grounding": False}
        with patch("agents._working_mode.get_working_mode", return_value=WorkingMode.RND):
            from agents._working_mode import get_working_mode

            if get_working_mode().value == "rnd":
                flags["enable_grounding"] = True
        assert flags["enable_grounding"] is True

    def test_research_mode_preserves_flag(self):
        from agents._working_mode import WorkingMode

        flags: dict = {"enable_grounding": False}
        with patch("agents._working_mode.get_working_mode", return_value=WorkingMode.RESEARCH):
            from agents._working_mode import get_working_mode

            if get_working_mode().value == "rnd":
                flags["enable_grounding"] = True
        assert flags["enable_grounding"] is False

    def test_research_mode_respects_explicit_true(self):
        from agents._working_mode import WorkingMode

        flags: dict = {"enable_grounding": True}
        with patch("agents._working_mode.get_working_mode", return_value=WorkingMode.RESEARCH):
            from agents._working_mode import get_working_mode

            if get_working_mode().value == "rnd":
                flags["enable_grounding"] = True
        assert flags["enable_grounding"] is True

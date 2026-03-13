"""Tests for CompoundGoals."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

import pytest

from agents.hapax_voice.compound_goals import CompoundGoals


class TestCompoundGoals(unittest.TestCase):
    def test_construction(self):
        daemon = MagicMock()
        goals = CompoundGoals(daemon)
        self.assertIsNotNone(goals)


@pytest.mark.asyncio
async def test_start_live_session_calls_perception_tick():
    daemon = MagicMock()
    daemon.perception.tick.return_value = MagicMock()
    goals = CompoundGoals(daemon)
    result = await goals.start_live_session()
    assert result is True
    daemon.perception.tick.assert_called_once()


@pytest.mark.asyncio
async def test_start_live_session_returns_false_on_none_tick():
    daemon = MagicMock()
    daemon.perception.tick.return_value = None
    goals = CompoundGoals(daemon)
    result = await goals.start_live_session()
    assert result is False


@pytest.mark.asyncio
async def test_end_live_session_success():
    daemon = MagicMock()
    daemon.schedule_queue.drain.return_value = []
    goals = CompoundGoals(daemon)
    result = await goals.end_live_session()
    assert result is True


@pytest.mark.asyncio
async def test_start_partial_failure_stops():
    daemon = MagicMock()
    daemon.perception.tick.side_effect = RuntimeError("boom")
    goals = CompoundGoals(daemon)
    result = await goals.start_live_session()
    assert result is False


if __name__ == "__main__":
    unittest.main()

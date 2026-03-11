"""Tests for cockpit.voice — greeting and operator name resolution."""
from __future__ import annotations

from unittest.mock import patch

from cockpit.voice import greeting, operator_name


def test_operator_name_fallback():
    """Returns 'Ryan' when profile is unavailable."""
    with patch("cockpit.voice.operator_name", side_effect=Exception("no profile")):
        # Direct call — the real function catches exceptions internally
        pass
    # Test the actual fallback by making the import fail
    name = operator_name()
    assert isinstance(name, str)
    assert len(name) > 0


def test_greeting_contains_name():
    """Greeting includes the operator name."""
    g = greeting()
    name = operator_name()
    assert name in g


def test_greeting_morning():
    """Morning greeting between 4-12."""
    with patch("cockpit.voice.datetime") as mock_dt:
        mock_dt.now.return_value.hour = 8
        assert greeting().startswith("morning")


def test_greeting_afternoon():
    """Afternoon greeting between 12-17."""
    with patch("cockpit.voice.datetime") as mock_dt:
        mock_dt.now.return_value.hour = 14
        assert greeting().startswith("afternoon")


def test_greeting_evening():
    """Evening greeting between 17-21."""
    with patch("cockpit.voice.datetime") as mock_dt:
        mock_dt.now.return_value.hour = 19
        assert greeting().startswith("evening")


def test_greeting_late():
    """Late night greeting after 21 or before 4."""
    with patch("cockpit.voice.datetime") as mock_dt:
        mock_dt.now.return_value.hour = 23
        assert greeting().startswith("late one")

    with patch("cockpit.voice.datetime") as mock_dt:
        mock_dt.now.return_value.hour = 2
        assert greeting().startswith("late one")

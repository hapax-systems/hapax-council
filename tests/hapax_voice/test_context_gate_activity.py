"""Tests for ContextGate activity mode integration."""

from unittest.mock import MagicMock

from agents.hapax_voice.context_gate import ContextGate


def test_gate_blocks_during_production():
    session = MagicMock()
    session.is_active = False
    gate = ContextGate(session=session)
    gate._activity_mode = "production"
    result = gate.check()
    assert result.eligible is False
    assert "production" in result.reason.lower()


def test_gate_blocks_during_meeting():
    session = MagicMock()
    session.is_active = False
    gate = ContextGate(session=session)
    gate._activity_mode = "meeting"
    result = gate.check()
    assert result.eligible is False
    assert "meeting" in result.reason.lower()


def test_gate_allows_during_coding():
    session = MagicMock()
    session.is_active = False
    gate = ContextGate(session=session)
    gate._activity_mode = "coding"
    # Should pass the activity check (may fail on other checks like volume)
    # Just verify activity mode doesn't block
    assert gate._check_activity_mode().eligible is True

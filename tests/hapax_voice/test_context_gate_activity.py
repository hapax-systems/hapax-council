"""Tests for ContextGate activity mode integration and Behavior-based reads."""

from unittest.mock import MagicMock

from agents.hapax_voice.context_gate import ContextGate
from agents.hapax_voice.primitives import Behavior


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
    assert gate._allow_activity_mode(None) is True


# ------------------------------------------------------------------
# Behavior-based reads (Batch 8)
# ------------------------------------------------------------------


def _gate_with_behaviors(
    *,
    volume: float = 0.3,
    midi_active: bool = False,
) -> ContextGate:
    """Create a ContextGate with Behaviors set, bypassing subprocess."""
    session = MagicMock()
    session.is_active = False
    gate = ContextGate(session=session, ambient_classification=False)
    gate._activity_mode = "idle"

    import time

    now = time.monotonic()
    b_volume: Behavior[float] = Behavior(volume, watermark=now)
    b_midi: Behavior[bool] = Behavior(midi_active, watermark=now)
    gate.set_behaviors({"sink_volume": b_volume, "midi_active": b_midi})
    return gate


def test_behavior_volume_allows_low():
    gate = _gate_with_behaviors(volume=0.3)
    result = gate.check()
    assert result.eligible is True


def test_behavior_volume_blocks_high():
    gate = _gate_with_behaviors(volume=0.9)
    result = gate.check()
    assert result.eligible is False
    assert "volume" in result.reason.lower()


def test_behavior_midi_allows_inactive():
    gate = _gate_with_behaviors(midi_active=False)
    result = gate.check()
    assert result.eligible is True


def test_behavior_midi_blocks_active():
    gate = _gate_with_behaviors(midi_active=True)
    result = gate.check()
    assert result.eligible is False
    assert "midi" in result.reason.lower()


def test_behavior_overrides_subprocess():
    """When behaviors are set, subprocess should not be called."""
    gate = _gate_with_behaviors(volume=0.2, midi_active=False)
    # If subprocess were called and failed, gate would block (fail-closed)
    # Since behaviors are set, it reads from them directly
    result = gate.check()
    assert result.eligible is True


def test_set_behaviors_method():
    session = MagicMock()
    session.is_active = False
    gate = ContextGate(session=session)
    import time

    now = time.monotonic()
    behaviors = {"sink_volume": Behavior(0.5, watermark=now)}
    gate.set_behaviors(behaviors)
    assert gate._behaviors["sink_volume"].value == 0.5

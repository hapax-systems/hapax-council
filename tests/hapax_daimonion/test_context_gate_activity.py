"""Tests for ContextGate activity mode integration and Behavior-based reads."""

from unittest.mock import MagicMock

from agents.hapax_daimonion.context_gate import ContextGate
from agents.hapax_daimonion.primitives import Behavior


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


# ------------------------------------------------------------------
# Fullscreen app veto (H2: Desktop Behaviors → ContextGate)
# ------------------------------------------------------------------


def _gate_with_window_class(
    window_class: str | None = None,
    *,
    volume: float = 0.3,
) -> ContextGate:
    """Create a ContextGate with active_window_class Behavior set."""
    session = MagicMock()
    session.is_active = False
    gate = ContextGate(session=session, ambient_classification=False)
    gate._activity_mode = "idle"

    import time

    now = time.monotonic()
    behaviors: dict[str, Behavior] = {
        "sink_volume": Behavior(volume, watermark=now),
        "midi_active": Behavior(False, watermark=now),
    }
    if window_class is not None:
        behaviors["active_window_class"] = Behavior(window_class, watermark=now)
    gate.set_behaviors(behaviors)
    return gate


def test_fullscreen_blocks_zoom():
    gate = _gate_with_window_class("zoom")
    result = gate.check()
    assert result.eligible is False
    assert "fullscreen" in result.reason.lower() or "zoom" in result.reason.lower()


def test_fullscreen_blocks_teams():
    gate = _gate_with_window_class("microsoft teams")
    result = gate.check()
    assert result.eligible is False


def test_fullscreen_blocks_discord():
    gate = _gate_with_window_class("discord")
    result = gate.check()
    assert result.eligible is False


def test_fullscreen_allows_browser():
    gate = _gate_with_window_class("firefox")
    result = gate.check()
    assert result.eligible is True


def test_fullscreen_allows_terminal():
    gate = _gate_with_window_class("kitty")
    result = gate.check()
    assert result.eligible is True


def test_fullscreen_failopen_no_behavior():
    """When active_window_class Behavior is not set, veto passes (fail-open)."""
    gate = _gate_with_window_class(None)
    result = gate.check()
    assert result.eligible is True


def test_fullscreen_case_insensitive():
    gate = _gate_with_window_class("Zoom")
    result = gate.check()
    assert result.eligible is False


# ------------------------------------------------------------------
# System health veto
# ------------------------------------------------------------------


def _gate_with_health(status: str | None) -> ContextGate:
    """Create a ContextGate with system_health_status Behavior."""
    session = MagicMock()
    session.is_active = False
    gate = ContextGate(session=session, ambient_classification=False)
    gate._activity_mode = "idle"

    import time

    now = time.monotonic()
    behaviors: dict[str, Behavior] = {
        "sink_volume": Behavior(0.3, watermark=now),
        "midi_active": Behavior(False, watermark=now),
    }
    if status is not None:
        behaviors["system_health_status"] = Behavior(status, watermark=now)
    gate.set_behaviors(behaviors)
    return gate


def test_system_health_healthy_passes():
    gate = _gate_with_health("healthy")
    result = gate.check()
    assert result.eligible is True


def test_system_health_degraded_blocks():
    gate = _gate_with_health("degraded")
    result = gate.check()
    assert result.eligible is False
    assert "system health" in result.reason.lower()


def test_system_health_missing_failopen():
    gate = _gate_with_health(None)
    result = gate.check()
    assert result.eligible is True


# ------------------------------------------------------------------
# Watch activity veto
# ------------------------------------------------------------------


def _gate_with_watch_activity(activity: str | None) -> ContextGate:
    """Create a ContextGate with watch_activity_state Behavior."""
    session = MagicMock()
    session.is_active = False
    gate = ContextGate(session=session, ambient_classification=False)
    gate._activity_mode = "idle"

    import time

    now = time.monotonic()
    behaviors: dict[str, Behavior] = {
        "sink_volume": Behavior(0.3, watermark=now),
        "midi_active": Behavior(False, watermark=now),
    }
    if activity is not None:
        behaviors["watch_activity_state"] = Behavior(activity, watermark=now)
    gate.set_behaviors(behaviors)
    return gate


def test_watch_activity_still_passes():
    gate = _gate_with_watch_activity("still")
    result = gate.check()
    assert result.eligible is True


def test_watch_activity_exercise_blocks():
    gate = _gate_with_watch_activity("exercise")
    result = gate.check()
    assert result.eligible is False
    assert "activity" in result.reason.lower()


def test_watch_activity_sleep_blocks():
    gate = _gate_with_watch_activity("sleep")
    result = gate.check()
    assert result.eligible is False
    assert "activity" in result.reason.lower()


def test_watch_activity_missing_failopen():
    gate = _gate_with_watch_activity(None)
    result = gate.check()
    assert result.eligible is True

"""Tests for the perception layer."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from agents.hapax_voice.perception import EnvironmentState


def test_environment_state_is_frozen():
    """EnvironmentState should be immutable."""
    state = EnvironmentState(timestamp=time.monotonic())
    with pytest.raises(AttributeError):
        state.speech_detected = True


def test_environment_state_defaults():
    """Default state: nothing detected, process directive."""
    state = EnvironmentState(timestamp=time.monotonic())
    assert state.speech_detected is False
    assert state.face_count == 0
    assert state.operator_present is False
    assert state.gaze_at_camera is False
    assert state.conversation_detected is False
    assert state.activity_mode == "unknown"
    assert state.ambient_class == "silence"
    assert state.directive == "process"


def test_environment_state_conversation_detected():
    """conversation_detected is True when face_count > 1 AND speech_detected."""
    state = EnvironmentState(
        timestamp=time.monotonic(),
        face_count=2,
        speech_detected=True,
    )
    assert state.conversation_detected is True


def test_environment_state_no_conversation_single_face():
    """Single face + speech is NOT conversation."""
    state = EnvironmentState(
        timestamp=time.monotonic(),
        face_count=1,
        speech_detected=True,
    )
    assert state.conversation_detected is False


def test_environment_state_no_conversation_no_speech():
    """Multiple faces without speech is NOT conversation."""
    state = EnvironmentState(
        timestamp=time.monotonic(),
        face_count=3,
        speech_detected=False,
    )
    assert state.conversation_detected is False


from agents.hapax_voice.perception import PerceptionEngine


def _make_mock_presence(**overrides):
    """Create a mock PresenceDetector with sensible defaults."""
    defaults = dict(
        score="likely_present",
        face_detected=True,
        face_count=1,
        latest_vad_confidence=0.0,
    )
    defaults.update(overrides)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


def _make_mock_workspace_monitor():
    m = MagicMock()
    m.latest_analysis = None
    m.has_camera.return_value = True
    return m


def test_engine_produces_state():
    """Engine tick produces an EnvironmentState."""
    presence = _make_mock_presence()
    engine = PerceptionEngine(
        presence=presence,
        workspace_monitor=_make_mock_workspace_monitor(),
    )
    state = engine.tick()
    assert isinstance(state, EnvironmentState)
    assert state.operator_present is True
    assert state.face_count == 1


def test_engine_detects_speech():
    """High VAD confidence → speech_detected."""
    presence = _make_mock_presence(latest_vad_confidence=0.85)
    engine = PerceptionEngine(
        presence=presence,
        workspace_monitor=_make_mock_workspace_monitor(),
    )
    state = engine.tick()
    assert state.speech_detected is True
    assert state.vad_confidence == 0.85


def test_engine_carries_forward_slow_fields():
    """Slow-tick fields carry forward between fast ticks."""
    engine = PerceptionEngine(
        presence=_make_mock_presence(),
        workspace_monitor=_make_mock_workspace_monitor(),
    )
    engine.update_slow_fields(activity_mode="coding", ambient_detailed="keyboard_typing")
    state = engine.tick()
    assert state.activity_mode == "coding"
    assert state.ambient_detailed == "keyboard_typing"


def test_engine_notifies_subscribers():
    """Subscribers receive each new state."""
    received = []
    engine = PerceptionEngine(
        presence=_make_mock_presence(),
        workspace_monitor=_make_mock_workspace_monitor(),
    )
    engine.subscribe(received.append)
    engine.tick()
    assert len(received) == 1
    assert isinstance(received[0], EnvironmentState)


def test_engine_gaze_defaults_false():
    """Gaze detection defaults to False (b-path: proper model later)."""
    engine = PerceptionEngine(
        presence=_make_mock_presence(),
        workspace_monitor=_make_mock_workspace_monitor(),
    )
    state = engine.tick()
    assert state.gaze_at_camera is False


# ------------------------------------------------------------------
# PerceptionBackend Protocol + Registration (Batch 3)
# ------------------------------------------------------------------

from agents.hapax_voice.perception import (
    PerceptionBackend,
    PerceptionTier,
    compute_interruptibility,
)
from agents.hapax_voice.primitives import Behavior


class StubBackend:
    """A minimal PerceptionBackend implementation for testing."""

    def __init__(
        self,
        name: str = "stub",
        provides: frozenset[str] | None = None,
        tier: PerceptionTier = PerceptionTier.FAST,
        is_available: bool = True,
    ):
        self._name = name
        self._provides = provides or frozenset({"stub_signal"})
        self._tier = tier
        self._is_available = is_available
        self.started = False
        self.stopped = False

    @property
    def name(self) -> str:
        return self._name

    @property
    def provides(self) -> frozenset[str]:
        return self._provides

    @property
    def tier(self) -> PerceptionTier:
        return self._tier

    def available(self) -> bool:
        return self._is_available

    def contribute(self, behaviors: dict[str, Behavior]) -> None:
        pass

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


class TestPerceptionBackendProtocol:
    def test_stub_satisfies_protocol(self):
        backend = StubBackend()
        assert isinstance(backend, PerceptionBackend)

    def test_register_backend(self):
        engine = PerceptionEngine(
            presence=_make_mock_presence(),
            workspace_monitor=_make_mock_workspace_monitor(),
        )
        backend = StubBackend(name="test_backend", provides=frozenset({"custom_signal"}))
        engine.register_backend(backend)
        assert "test_backend" in engine.registered_backends
        assert backend.started is True

    def test_register_duplicate_name_raises(self):
        engine = PerceptionEngine(
            presence=_make_mock_presence(),
            workspace_monitor=_make_mock_workspace_monitor(),
        )
        engine.register_backend(StubBackend(name="dup", provides=frozenset({"sig_a"})))
        with pytest.raises(ValueError, match="already registered"):
            engine.register_backend(StubBackend(name="dup", provides=frozenset({"sig_b"})))

    def test_register_conflicting_provides_raises(self):
        engine = PerceptionEngine(
            presence=_make_mock_presence(),
            workspace_monitor=_make_mock_workspace_monitor(),
        )
        engine.register_backend(StubBackend(name="a", provides=frozenset({"shared_signal"})))
        with pytest.raises(ValueError, match="conflicts"):
            engine.register_backend(StubBackend(name="b", provides=frozenset({"shared_signal"})))

    def test_unavailable_backend_skipped(self):
        engine = PerceptionEngine(
            presence=_make_mock_presence(),
            workspace_monitor=_make_mock_workspace_monitor(),
        )
        backend = StubBackend(name="unavail", is_available=False)
        engine.register_backend(backend)
        assert "unavail" not in engine.registered_backends
        assert backend.started is False


class TestEnvironmentStateNewFields:
    def test_in_voice_session_default(self):
        state = EnvironmentState(timestamp=time.monotonic())
        assert state.in_voice_session is False

    def test_interruptibility_score_default(self):
        state = EnvironmentState(timestamp=time.monotonic())
        assert state.interruptibility_score == 1.0

    def test_voice_session_fields(self):
        state = EnvironmentState(
            timestamp=time.monotonic(),
            in_voice_session=True,
            interruptibility_score=0.1,
        )
        assert state.in_voice_session is True
        assert state.interruptibility_score == 0.1


class TestComputeInterruptibility:
    def test_not_present(self):
        assert compute_interruptibility(
            vad_confidence=0.0, activity_mode="idle", in_voice_session=False, operator_present=False
        ) == 0.0

    def test_in_voice_session(self):
        score = compute_interruptibility(
            vad_confidence=0.0, activity_mode="idle", in_voice_session=True, operator_present=True
        )
        assert score == 0.1

    def test_idle_fully_interruptible(self):
        score = compute_interruptibility(
            vad_confidence=0.0, activity_mode="idle", in_voice_session=False, operator_present=True
        )
        assert score == 1.0

    def test_production_reduces_score(self):
        score = compute_interruptibility(
            vad_confidence=0.0,
            activity_mode="production",
            in_voice_session=False,
            operator_present=True,
        )
        assert score == 0.5

    def test_speech_reduces_score(self):
        score = compute_interruptibility(
            vad_confidence=0.9, activity_mode="idle", in_voice_session=False, operator_present=True
        )
        assert score < 1.0

    def test_score_clamped_to_zero(self):
        score = compute_interruptibility(
            vad_confidence=1.0,
            activity_mode="meeting",
            in_voice_session=False,
            operator_present=True,
        )
        assert score >= 0.0

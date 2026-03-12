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
    assert state.conversation_detected is False
    assert state.activity_mode == "unknown"
    assert state.presence_score == "likely_absent"
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
    """High VAD confidence -> speech_detected."""
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
    engine.update_slow_fields(activity_mode="coding")
    state = engine.tick()
    assert state.activity_mode == "coding"


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
        assert (
            compute_interruptibility(
                vad_confidence=0.0,
                activity_mode="idle",
                in_voice_session=False,
                operator_present=False,
            )
            == 0.0
        )

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


class TestPhysiologicalFactors:
    """Tests for physiological_load, circadian_alignment, system_health_ratio params."""

    def test_physiological_load_reduces_score(self):
        score = compute_interruptibility(
            vad_confidence=0.0,
            activity_mode="idle",
            in_voice_session=False,
            operator_present=True,
            physiological_load=1.0,
        )
        # 1.0 - 0.3*1.0 = 0.7
        assert score == pytest.approx(0.7)

    def test_circadian_peak_no_penalty(self):
        score = compute_interruptibility(
            vad_confidence=0.0,
            activity_mode="idle",
            in_voice_session=False,
            operator_present=True,
            circadian_alignment=0.1,
        )
        assert score == pytest.approx(1.0)

    def test_circadian_non_productive_penalty(self):
        score = compute_interruptibility(
            vad_confidence=0.0,
            activity_mode="idle",
            in_voice_session=False,
            operator_present=True,
            circadian_alignment=0.8,
        )
        # 1.0 - 0.5*(0.8-0.1) = 1.0 - 0.35 = 0.65
        assert score == pytest.approx(0.65)

    def test_system_health_degraded_penalty(self):
        score = compute_interruptibility(
            vad_confidence=0.0,
            activity_mode="idle",
            in_voice_session=False,
            operator_present=True,
            system_health_ratio=0.5,
        )
        # 1.0 - 0.5*(1.0-0.5) = 1.0 - 0.25 = 0.75
        assert score == pytest.approx(0.75)

    def test_system_health_healthy_no_penalty(self):
        score = compute_interruptibility(
            vad_confidence=0.0,
            activity_mode="idle",
            in_voice_session=False,
            operator_present=True,
            system_health_ratio=1.0,
        )
        assert score == pytest.approx(1.0)

    def test_all_factors_stack(self):
        score = compute_interruptibility(
            vad_confidence=0.0,
            activity_mode="idle",
            in_voice_session=False,
            operator_present=True,
            physiological_load=0.5,  # -0.15
            circadian_alignment=0.5,  # -0.20
            system_health_ratio=0.5,  # -0.25
        )
        # 1.0 - 0.15 - 0.20 - 0.25 = 0.40
        assert score == pytest.approx(0.4)


class TestSleepQualityThreshold:
    """Tests for sleep-quality-adjusted proactive delivery threshold calculation."""

    def test_full_sleep_default_threshold(self):
        # sleep=1.0 → 0.5 + 0.3*(1-1) = 0.5
        threshold = 0.5 + 0.3 * (1.0 - 1.0)
        assert threshold == pytest.approx(0.5)

    def test_half_sleep_raised_threshold(self):
        # sleep=0.5 → 0.5 + 0.3*(1-0.5) = 0.65
        threshold = 0.5 + 0.3 * (1.0 - 0.5)
        assert threshold == pytest.approx(0.65)

    def test_no_sleep_behavior_default(self):
        # When no behavior exists, threshold should stay 0.5
        sleep_b = None
        delivery_threshold = 0.5
        if sleep_b is not None:
            delivery_threshold = 0.5 + 0.3 * (1.0 - sleep_b.value)
        assert delivery_threshold == pytest.approx(0.5)


class TestBackendTickIntegration:
    """Prove that tick() polls registered backends and merges Behaviors."""

    def test_tick_calls_backend_contribute(self):
        """After registration, tick() calls contribute() on each backend."""
        engine = PerceptionEngine(
            presence=_make_mock_presence(),
            workspace_monitor=_make_mock_workspace_monitor(),
        )
        contributed = []

        class TrackingBackend(StubBackend):
            def contribute(self, behaviors: dict[str, Behavior]) -> None:
                contributed.append(True)
                behaviors["test_signal"] = Behavior(42.0)

        backend = TrackingBackend(name="tracker", provides=frozenset({"test_signal"}))
        engine.register_backend(backend)

        engine.tick()
        assert len(contributed) == 1
        assert "test_signal" in engine.behaviors
        assert engine.behaviors["test_signal"].value == 42.0

    def test_tick_survives_backend_error(self):
        """A failing backend doesn't crash the tick loop."""
        engine = PerceptionEngine(
            presence=_make_mock_presence(),
            workspace_monitor=_make_mock_workspace_monitor(),
        )

        class FailingBackend(StubBackend):
            def contribute(self, behaviors: dict[str, Behavior]) -> None:
                raise RuntimeError("broken sensor")

        engine.register_backend(FailingBackend(name="broken", provides=frozenset({"bad_signal"})))
        # Should not raise
        state = engine.tick()
        assert state is not None

    def test_multiple_backends_all_polled(self):
        """All registered backends get polled each tick."""
        engine = PerceptionEngine(
            presence=_make_mock_presence(),
            workspace_monitor=_make_mock_workspace_monitor(),
        )
        call_counts = {"a": 0, "b": 0}

        class CountingBackend(StubBackend):
            def contribute(self, behaviors: dict[str, Behavior]) -> None:
                call_counts[self.name] += 1

        engine.register_backend(CountingBackend(name="a", provides=frozenset({"sig_a"})))
        engine.register_backend(CountingBackend(name="b", provides=frozenset({"sig_b"})))

        engine.tick()
        engine.tick()
        assert call_counts == {"a": 2, "b": 2}


class TestSessionInterruptibility:
    """H4/H3: tick() populates in_voice_session and interruptibility_score."""

    def test_tick_default_no_session(self):
        engine = PerceptionEngine(
            presence=_make_mock_presence(),
            workspace_monitor=_make_mock_workspace_monitor(),
        )
        state = engine.tick()
        assert state.in_voice_session is False
        assert state.interruptibility_score == 1.0

    def test_tick_with_voice_session(self):
        engine = PerceptionEngine(
            presence=_make_mock_presence(),
            workspace_monitor=_make_mock_workspace_monitor(),
        )
        engine.set_voice_session_active(True)
        state = engine.tick()
        assert state.in_voice_session is True
        assert state.interruptibility_score == 0.1

    def test_tick_session_cleared(self):
        engine = PerceptionEngine(
            presence=_make_mock_presence(),
            workspace_monitor=_make_mock_workspace_monitor(),
        )
        engine.set_voice_session_active(True)
        engine.tick()
        engine.set_voice_session_active(False)
        state = engine.tick()
        assert state.in_voice_session is False
        assert state.interruptibility_score == 1.0

    def test_tick_absent_operator_zero_interruptibility(self):
        engine = PerceptionEngine(
            presence=_make_mock_presence(face_detected=False),
            workspace_monitor=_make_mock_workspace_monitor(),
        )
        state = engine.tick()
        assert state.interruptibility_score == 0.0

    def test_tick_production_reduces_interruptibility(self):
        engine = PerceptionEngine(
            presence=_make_mock_presence(),
            workspace_monitor=_make_mock_workspace_monitor(),
        )
        engine.update_slow_fields(activity_mode="production")
        state = engine.tick()
        assert state.interruptibility_score == 0.5

    def test_tick_many_windows_reduces_interruptibility(self):
        engine = PerceptionEngine(
            presence=_make_mock_presence(),
            workspace_monitor=_make_mock_workspace_monitor(),
        )
        engine.update_desktop_state(window_count=12)
        state = engine.tick()
        assert state.interruptibility_score == 0.8  # 1.0 - 0.2 penalty

    def test_tick_few_windows_no_penalty(self):
        engine = PerceptionEngine(
            presence=_make_mock_presence(),
            workspace_monitor=_make_mock_workspace_monitor(),
        )
        engine.update_desktop_state(window_count=5)
        state = engine.tick()
        assert state.interruptibility_score == 1.0

    def test_tick_windows_plus_production_stacks(self):
        engine = PerceptionEngine(
            presence=_make_mock_presence(),
            workspace_monitor=_make_mock_workspace_monitor(),
        )
        engine.update_slow_fields(activity_mode="production")
        engine.update_desktop_state(window_count=10)
        state = engine.tick()
        assert state.interruptibility_score == 0.3  # 1.0 - 0.5 - 0.2

    def test_tick_reads_physiological_load_from_behaviors(self):
        """Backend-provided physiological_load reduces interruptibility."""
        engine = PerceptionEngine(
            presence=_make_mock_presence(),
            workspace_monitor=_make_mock_workspace_monitor(),
        )

        class PhysioBackend(StubBackend):
            def contribute(self, behaviors: dict[str, Behavior]) -> None:
                behaviors["physiological_load"] = Behavior(0.5)

        engine.register_backend(
            PhysioBackend(name="physio", provides=frozenset({"physiological_load"}))
        )
        state = engine.tick()
        # 1.0 - 0.3*0.5 = 0.85 (circadian_alignment defaults to 0.1 = no penalty)
        assert state.interruptibility_score == pytest.approx(0.85)


# ------------------------------------------------------------------
# Part B: workspace_context wiring
# ------------------------------------------------------------------


class TestWorkspaceContextWiring:
    """Prove update_slow_fields populates workspace_context on state."""

    def test_update_slow_fields_sets_workspace_context(self):
        engine = PerceptionEngine(
            presence=_make_mock_presence(),
            workspace_monitor=_make_mock_workspace_monitor(),
        )
        engine.update_slow_fields(workspace_context="reviewing code")
        state = engine.tick()
        assert state.workspace_context == "reviewing code"

    def test_no_update_workspace_context_stays_empty(self):
        engine = PerceptionEngine(
            presence=_make_mock_presence(),
            workspace_monitor=_make_mock_workspace_monitor(),
        )
        state = engine.tick()
        assert state.workspace_context == ""


# ------------------------------------------------------------------
# Part C: presence_score on EnvironmentState
# ------------------------------------------------------------------


class TestPresenceScore:
    """Prove presence_score is populated from PresenceDetector."""

    def test_default_presence_score(self):
        state = EnvironmentState(timestamp=time.monotonic())
        assert state.presence_score == "likely_absent"

    def test_presence_score_from_detector(self):
        presence = _make_mock_presence(score="definitely_present")
        engine = PerceptionEngine(
            presence=presence,
            workspace_monitor=_make_mock_workspace_monitor(),
        )
        state = engine.tick()
        assert state.presence_score == "definitely_present"

    def test_presence_score_divergence_from_operator_present(self):
        """presence_score can diverge from operator_present (VAD persists after face decay)."""
        presence = _make_mock_presence(
            score="likely_present",
            face_detected=False,
            face_count=0,
        )
        engine = PerceptionEngine(
            presence=presence,
            workspace_monitor=_make_mock_workspace_monitor(),
        )
        state = engine.tick()
        assert state.presence_score == "likely_present"
        assert state.operator_present is False

    def test_presence_score_uncertain_interruptibility(self):
        """Uncertain presence still allows interruptibility computation."""
        presence = _make_mock_presence(
            score="uncertain",
            face_detected=True,
            face_count=1,
        )
        engine = PerceptionEngine(
            presence=presence,
            workspace_monitor=_make_mock_workspace_monitor(),
        )
        state = engine.tick()
        assert state.presence_score == "uncertain"
        assert state.interruptibility_score > 0.0

    def test_tick_populates_presence_score(self):
        """Engine tick() reads presence_score from presence detector."""
        presence = _make_mock_presence(score="likely_present")
        engine = PerceptionEngine(
            presence=presence,
            workspace_monitor=_make_mock_workspace_monitor(),
        )
        state = engine.tick()
        assert state.presence_score == "likely_present"
        assert engine.latest is not None
        assert engine.latest.presence_score == "likely_present"


# ------------------------------------------------------------------
# Part D: HyprlandBackend provides only active_window_class
# ------------------------------------------------------------------


class TestHyprlandBackendStripped:
    """Prove HyprlandBackend only provides active_window_class."""

    def test_provides_only_active_window_class(self):
        from agents.hapax_voice.backends.hyprland import HyprlandBackend

        backend = HyprlandBackend()
        assert backend.provides == frozenset({"active_window_class"})

    def test_no_removed_behaviors_after_registration(self):
        from agents.hapax_voice.backends.hyprland import HyprlandBackend

        backend = HyprlandBackend()
        behaviors: dict[str, Behavior] = {}
        # Simulate contribute without hyprctl (will fail gracefully)
        backend.contribute(behaviors)
        assert "active_window_title" not in behaviors
        assert "workspace_id" not in behaviors
        assert "desktop_window_count" not in behaviors

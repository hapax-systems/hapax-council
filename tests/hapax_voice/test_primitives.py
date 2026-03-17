"""Tests for perception primitive types: Stamped, Behavior, Event."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from agents.hapax_voice.primitives import Behavior, Event, Stamped

# ------------------------------------------------------------------
# Stamped
# ------------------------------------------------------------------


class TestStamped:
    def test_fields_accessible(self):
        s = Stamped(value=42, watermark=1.0)
        assert s.value == 42
        assert s.watermark == 1.0

    def test_frozen(self):
        s = Stamped(value="hello", watermark=1.0)
        with pytest.raises(AttributeError):
            s.value = "nope"  # type: ignore[misc]

    def test_equality(self):
        a = Stamped(value=1, watermark=2.0)
        b = Stamped(value=1, watermark=2.0)
        assert a == b

    def test_inequality(self):
        a = Stamped(value=1, watermark=2.0)
        b = Stamped(value=1, watermark=3.0)
        assert a != b

    # -- D: Boundaries --

    def test_none_value(self):
        s = Stamped(value=None, watermark=1.0)
        assert s.value is None

    def test_zero_watermark(self):
        s = Stamped(value="x", watermark=0.0)
        assert s.watermark == 0.0

    def test_negative_watermark(self):
        s = Stamped(value="x", watermark=-1.0)
        assert s.watermark == -1.0

    def test_nan_watermark(self):
        import math

        s = Stamped(value="x", watermark=float("nan"))
        assert math.isnan(s.watermark)

    # -- G: Composition contract (L0 → L1) --

    def test_stamped_is_valid_behavior_sample(self):
        """Behavior.sample() returns a Stamped — proving L0 is L1's output type."""
        b = Behavior(42, watermark=5.0)
        s = b.sample()
        assert isinstance(s, Stamped)
        assert s.value == 42
        assert s.watermark == 5.0


# ------------------------------------------------------------------
# Behavior
# ------------------------------------------------------------------


class TestBehavior:
    def test_initial_value(self):
        b = Behavior("hello")
        assert b.value == "hello"

    def test_sample_returns_stamped(self):
        b = Behavior(42, watermark=10.0)
        s = b.sample()
        assert isinstance(s, Stamped)
        assert s.value == 42
        assert s.watermark == 10.0

    def test_update_advances_watermark(self):
        b = Behavior(0, watermark=1.0)
        b.update(1, 2.0)
        assert b.value == 1
        assert b.watermark == 2.0

    def test_equal_timestamp_allowed(self):
        b = Behavior(0, watermark=5.0)
        b.update(1, 5.0)
        assert b.value == 1

    def test_regression_rejected(self):
        b = Behavior(0, watermark=10.0)
        with pytest.raises(ValueError, match="Watermark regression"):
            b.update(1, 9.0)

    def test_value_property(self):
        b = Behavior("x", watermark=1.0)
        b.update("y", 2.0)
        assert b.value == "y"

    def test_watermark_property(self):
        b = Behavior(0, watermark=3.0)
        assert b.watermark == 3.0
        b.update(1, 4.0)
        assert b.watermark == 4.0

    def test_default_watermark_uses_monotonic(self):
        before = time.monotonic()
        b = Behavior(0)
        after = time.monotonic()
        assert before <= b.watermark <= after

    def test_behavior_with_none_value(self):
        b = Behavior(None, watermark=1.0)
        assert b.value is None
        s = b.sample()
        assert s.value is None
        assert s.watermark == 1.0


# ------------------------------------------------------------------
# Event
# ------------------------------------------------------------------


class TestEvent:
    def test_subscribe_and_emit(self):
        ev = Event()
        received = []
        ev.subscribe(lambda ts, v: received.append((ts, v)))
        ev.emit(1.0, "ping")
        assert received == [(1.0, "ping")]

    def test_unsubscribe(self):
        ev = Event()
        received = []
        unsub = ev.subscribe(lambda ts, v: received.append(v))
        ev.emit(1.0, "a")
        unsub()
        ev.emit(2.0, "b")
        assert received == ["a"]

    def test_no_history_for_late_subscribers(self):
        ev = Event()
        ev.emit(1.0, "early")
        received = []
        ev.subscribe(lambda ts, v: received.append(v))
        assert received == []

    def test_subscriber_exception_isolation(self):
        ev = Event()
        good = []
        ev.subscribe(lambda ts, v: (_ for _ in ()).throw(RuntimeError("boom")))
        ev.subscribe(lambda ts, v: good.append(v))
        ev.emit(1.0, "ok")
        assert good == ["ok"]

    def test_emit_with_no_subscribers(self):
        ev = Event()
        ev.emit(1.0, "ping")  # should not raise

    def test_double_unsubscribe_safe(self):
        ev = Event()
        unsub = ev.subscribe(lambda ts, v: None)
        unsub()
        unsub()  # second call should not raise
        assert ev.subscriber_count == 0

    def test_subscriber_count(self):
        ev = Event()
        assert ev.subscriber_count == 0
        unsub1 = ev.subscribe(lambda ts, v: None)
        assert ev.subscriber_count == 1
        unsub2 = ev.subscribe(lambda ts, v: None)
        assert ev.subscriber_count == 2
        unsub1()
        assert ev.subscriber_count == 1
        unsub2()
        assert ev.subscriber_count == 0


# ------------------------------------------------------------------
# Behavior integration with PerceptionEngine
# ------------------------------------------------------------------


class TestBehaviorWithPerceptionEngine:
    def test_behaviors_dict_populated(self):
        from agents.hapax_voice.perception import PerceptionEngine

        presence = MagicMock()
        presence.latest_vad_confidence = 0.0
        presence.face_detected = False
        presence.face_count = 0
        engine = PerceptionEngine(presence=presence, workspace_monitor=MagicMock())
        assert isinstance(engine.behaviors, dict)
        assert len(engine.behaviors) == 11

    def test_tick_updates_fast_behaviors(self):
        from agents.hapax_voice.perception import PerceptionEngine

        presence = MagicMock()
        presence.latest_vad_confidence = 0.8
        presence.face_detected = True
        presence.face_count = 2
        presence.guest_count = 1
        presence.operator_visible = True
        engine = PerceptionEngine(presence=presence, workspace_monitor=MagicMock())
        engine.tick()
        assert engine.behaviors["vad_confidence"].value == 0.8
        assert engine.behaviors["operator_present"].value is True
        assert engine.behaviors["face_count"].value == 2

    def test_slow_update_works(self):
        from agents.hapax_voice.perception import PerceptionEngine

        presence = MagicMock()
        presence.latest_vad_confidence = 0.0
        presence.face_detected = False
        presence.face_count = 0
        engine = PerceptionEngine(presence=presence, workspace_monitor=MagicMock())
        engine.update_slow_fields(activity_mode="meeting")
        assert engine.behaviors["activity_mode"].value == "meeting"

    def test_desktop_update_works(self):
        from agents.hapax_voice.perception import PerceptionEngine
        from shared.hyprland import WindowInfo

        presence = MagicMock()
        presence.latest_vad_confidence = 0.0
        presence.face_detected = False
        presence.face_count = 0
        engine = PerceptionEngine(presence=presence, workspace_monitor=MagicMock())
        win = WindowInfo(
            address="0x1",
            app_class="foot",
            title="term",
            workspace_id=1,
            pid=1,
            x=0,
            y=0,
            width=800,
            height=600,
            floating=False,
            fullscreen=False,
        )
        engine.update_desktop_state(active_window=win, window_count=5, active_workspace_id=2)
        assert engine.behaviors["active_window"].value == win
        assert engine.behaviors["window_count"].value == 5
        assert engine.behaviors["active_workspace_id"].value == 2

    def test_watermarks_advance_monotonically(self):
        from agents.hapax_voice.perception import PerceptionEngine

        presence = MagicMock()
        presence.latest_vad_confidence = 0.0
        presence.face_detected = False
        presence.face_count = 0
        engine = PerceptionEngine(presence=presence, workspace_monitor=MagicMock())
        engine.tick()
        w1 = engine.behaviors["vad_confidence"].watermark
        engine.tick()
        w2 = engine.behaviors["vad_confidence"].watermark
        assert w2 >= w1

    def test_environment_state_matches_behavior_values(self):
        from agents.hapax_voice.perception import PerceptionEngine

        presence = MagicMock()
        presence.latest_vad_confidence = 0.6
        presence.face_detected = True
        presence.face_count = 1
        engine = PerceptionEngine(presence=presence, workspace_monitor=MagicMock())
        engine.update_slow_fields(activity_mode="coding")
        state = engine.tick()
        assert state.vad_confidence == engine.behaviors["vad_confidence"].value
        assert state.activity_mode == engine.behaviors["activity_mode"].value


# ------------------------------------------------------------------
# Event integration with VoiceDaemon
# ------------------------------------------------------------------


class TestEventIntegration:
    def test_daemon_has_wake_word_event(self):

        with _mock_daemon() as daemon:
            assert isinstance(daemon.wake_word_event, Event)

    def test_daemon_has_focus_event(self):

        with _mock_daemon() as daemon:
            assert isinstance(daemon.focus_event, Event)


def _mock_daemon():
    """Context manager yielding a VoiceDaemon with mocked subsystems."""
    from unittest.mock import patch

    from agents.hapax_voice.__main__ import VoiceDaemon

    class _Ctx:
        def __enter__(self):
            self._patches = [
                patch("agents.hapax_voice.__main__.load_config"),
                patch("agents.hapax_voice.__main__.SessionManager"),
                patch("agents.hapax_voice.__main__.PresenceDetector"),
                patch("agents.hapax_voice.__main__.ContextGate"),
                patch("agents.hapax_voice.__main__.NotificationQueue"),
                patch("agents.hapax_voice.__main__.HotkeyServer"),
                patch("agents.hapax_voice.__main__.WakeWordDetector"),
                patch("agents.hapax_voice.__main__.PorcupineWakeWord"),
                patch("agents.hapax_voice.__main__.AudioInputStream"),
                patch("agents.hapax_voice.__main__.TTSManager"),
                patch("agents.hapax_voice.__main__.ChimePlayer"),
                patch("agents.hapax_voice.__main__.WorkspaceMonitor"),
                patch("agents.hapax_voice.__main__.PipelineGovernor"),
                patch("agents.hapax_voice.__main__.FrameGate"),
                patch("agents.hapax_voice.__main__.EventLog"),
            ]
            for p in self._patches:
                p.start()
            daemon = VoiceDaemon.__new__(VoiceDaemon)
            # Minimal init to get the attributes we care about
            daemon.cfg = MagicMock()
            daemon.cfg.wake_word_engine = "porcupine"
            daemon.cfg.porcupine_sensitivity = 0.5
            VoiceDaemon.__init__(daemon, cfg=daemon.cfg)
            return daemon

        def __exit__(self, *args):
            for p in reversed(self._patches):
                p.stop()

    return _Ctx()

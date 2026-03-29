"""Tests for shared signal bus."""

from __future__ import annotations

import unittest

from shared.signal_bus import SignalBus, SignalModulationBinding


class TestSignalBus(unittest.TestCase):
    def test_publish_and_get(self):
        bus = SignalBus()
        bus.publish("energy", 0.7)
        assert bus.get("energy") == 0.7

    def test_get_default(self):
        bus = SignalBus()
        assert bus.get("missing") == 0.0
        assert bus.get("missing", 0.5) == 0.5

    def test_publish_many(self):
        bus = SignalBus()
        bus.publish_many({"a": 1.0, "b": 2.0})
        assert bus.get("a") == 1.0
        assert bus.get("b") == 2.0

    def test_snapshot_returns_copy(self):
        bus = SignalBus()
        bus.publish("x", 1.0)
        snap = bus.snapshot()
        snap["x"] = 999.0  # mutate copy
        assert bus.get("x") == 1.0  # original unchanged

    def test_publish_overwrites(self):
        bus = SignalBus()
        bus.publish("x", 1.0)
        bus.publish("x", 2.0)
        assert bus.get("x") == 2.0

    def test_clear(self):
        bus = SignalBus()
        bus.publish("x", 1.0)
        bus.clear()
        assert bus.get("x") == 0.0

    def test_snapshot_empty(self):
        bus = SignalBus()
        assert bus.snapshot() == {}


class TestSignalModulationBinding(unittest.TestCase):
    def test_apply_binding_simple(self):
        bus = SignalBus()
        bus.publish("energy", 0.8)
        bindings = [SignalModulationBinding(target="bloom.alpha", signal="energy")]
        result = bus.apply_bindings(bindings)
        assert result["bloom.alpha"] == 0.8

    def test_apply_binding_scale_offset(self):
        bus = SignalBus()
        bus.publish("density", 0.5)
        bindings = [
            SignalModulationBinding(target="word_limit", signal="density", scale=-30.0, offset=50.0)
        ]
        result = bus.apply_bindings(bindings)
        assert result["word_limit"] == 35.0  # 0.5 * -30 + 50

    def test_apply_binding_smoothing(self):
        bus = SignalBus()
        bus.publish("energy", 1.0)
        bindings = [SignalModulationBinding(target="bloom", signal="energy", smoothing=0.5)]
        current = {"bloom": 0.0}
        result = bus.apply_bindings(bindings, current=current)
        assert result["bloom"] == 0.5  # 0.5 * 0.0 + 0.5 * 1.0

    def test_apply_binding_missing_signal(self):
        bus = SignalBus()
        bindings = [SignalModulationBinding(target="x", signal="missing")]
        result = bus.apply_bindings(bindings)
        assert result["x"] == 0.0

    def test_multiple_bindings(self):
        bus = SignalBus()
        bus.publish("a", 0.5)
        bus.publish("b", 0.8)
        bindings = [
            SignalModulationBinding(target="x", signal="a"),
            SignalModulationBinding(target="y", signal="b", scale=2.0),
        ]
        result = bus.apply_bindings(bindings)
        assert result["x"] == 0.5
        assert result["y"] == 1.6

    def test_thread_safety(self):
        """Verify bus works across threads without crash."""
        import threading

        bus = SignalBus()
        errors: list[Exception] = []

        def writer():
            try:
                for i in range(100):
                    bus.publish(f"sig_{i % 10}", float(i))
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(100):
                    bus.snapshot()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0

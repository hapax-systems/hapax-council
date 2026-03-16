"""Tests for the perception ring buffer — temporal depth for ambient perception."""

from __future__ import annotations

import pytest

from agents.hapax_voice.perception_ring import PerceptionRing


class TestBasicOperations:
    def test_empty_ring(self):
        ring = PerceptionRing()
        assert len(ring) == 0
        assert ring.current() is None
        assert ring.window(10) == []
        assert ring.delta("flow_score") == 0.0
        assert ring.trend("flow_score") == 0.0

    def test_push_and_current(self):
        ring = PerceptionRing()
        ring.push({"flow_score": 0.5, "ts": 100.0})
        assert len(ring) == 1
        assert ring.current()["flow_score"] == 0.5

    def test_push_adds_ts_if_missing(self):
        ring = PerceptionRing()
        ring.push({"flow_score": 0.3})
        assert "ts" in ring.current()

    def test_maxlen_respected(self):
        ring = PerceptionRing(maxlen=5)
        for i in range(10):
            ring.push({"ts": float(i), "val": i})
        assert len(ring) == 5
        assert ring.current()["val"] == 9


class TestWindow:
    def test_window_returns_recent(self):
        ring = PerceptionRing()
        for i in range(10):
            ring.push({"ts": float(i), "val": i})
        result = ring.window(3.0)
        # Last ts=9, window from 6.0+
        assert len(result) == 4  # ts=6,7,8,9
        assert all(s["ts"] >= 6.0 for s in result)

    def test_window_full_range(self):
        ring = PerceptionRing()
        for i in range(5):
            ring.push({"ts": float(i), "val": i})
        result = ring.window(100.0)
        assert len(result) == 5


class TestDelta:
    def test_delta_two_snapshots(self):
        ring = PerceptionRing()
        ring.push({"ts": 1.0, "flow_score": 0.3})
        ring.push({"ts": 2.0, "flow_score": 0.7})
        assert ring.delta("flow_score") == pytest.approx(0.4)

    def test_delta_missing_key(self):
        ring = PerceptionRing()
        ring.push({"ts": 1.0, "flow_score": 0.3})
        ring.push({"ts": 2.0, "flow_score": 0.7})
        assert ring.delta("nonexistent") == 0.0

    def test_delta_single_snapshot(self):
        ring = PerceptionRing()
        ring.push({"ts": 1.0, "flow_score": 0.5})
        assert ring.delta("flow_score") == 0.0


class TestTrend:
    def test_rising_trend(self):
        ring = PerceptionRing()
        for i in range(10):
            ring.push({"ts": float(i) * 2.5, "flow_score": 0.1 * i})
        trend = ring.trend("flow_score", window_s=50.0)
        assert trend > 0  # positive slope

    def test_falling_trend(self):
        ring = PerceptionRing()
        for i in range(10):
            ring.push({"ts": float(i) * 2.5, "flow_score": 1.0 - 0.1 * i})
        trend = ring.trend("flow_score", window_s=50.0)
        assert trend < 0  # negative slope

    def test_flat_trend(self):
        ring = PerceptionRing()
        for i in range(10):
            ring.push({"ts": float(i) * 2.5, "flow_score": 0.5})
        trend = ring.trend("flow_score", window_s=50.0)
        assert abs(trend) < 0.001

    def test_trend_insufficient_data(self):
        ring = PerceptionRing()
        ring.push({"ts": 1.0, "flow_score": 0.5})
        assert ring.trend("flow_score") == 0.0


class TestSnapshots:
    def test_snapshots_ordered(self):
        ring = PerceptionRing()
        for i in range(5):
            ring.push({"ts": float(i), "val": i})
        snaps = ring.snapshots
        assert [s["val"] for s in snaps] == [0, 1, 2, 3, 4]

    def test_snapshots_is_copy(self):
        ring = PerceptionRing()
        ring.push({"ts": 1.0})
        snaps = ring.snapshots
        snaps.clear()
        assert len(ring) == 1

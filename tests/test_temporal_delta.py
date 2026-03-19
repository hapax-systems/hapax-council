"""Tests for temporal delta correlator — Batch 2.

Covers:
- Stationary entity → velocity ~0, direction None
- Moving right → direction ~0°, positive velocity
- Entry detection → is_entering True
- Exit detection → is_exiting True
- Empty/single sightings → safe defaults
- No NaN/Inf for edge cases
"""

from __future__ import annotations

import math

from agents.temporal_delta import TemporalDelta, compute_temporal_delta

# ── Helpers ────────────────────────────────────────────────────────────


def _make_sighting(
    x1: float, y1: float, x2: float, y2: float, conf: float = 0.9, ts: float = 0.0
) -> dict:
    return {"box": [x1, y1, x2, y2], "conf": conf, "ts": ts}


# ── Stationary entity ─────────────────────────────────────────────────


class TestStationary:
    def test_same_position_gives_zero_velocity(self):
        sightings = [
            _make_sighting(0.3, 0.3, 0.5, 0.5, ts=100.0),
            _make_sighting(0.3, 0.3, 0.5, 0.5, ts=101.0),
            _make_sighting(0.3, 0.3, 0.5, 0.5, ts=102.0),
        ]
        delta = compute_temporal_delta(sightings, first_seen=100.0, last_seen=102.0, now=103.0)
        assert delta.velocity < 0.001
        assert delta.direction_deg is None

    def test_stationary_entity_has_dwell(self):
        sightings = [
            _make_sighting(0.3, 0.3, 0.5, 0.5, ts=100.0),
            _make_sighting(0.3, 0.3, 0.5, 0.5, ts=101.0),
        ]
        delta = compute_temporal_delta(sightings, first_seen=50.0, last_seen=101.0, now=103.0)
        assert delta.dwell_s > 0


# ── Moving entity ─────────────────────────────────────────────────────


class TestMoving:
    def test_moving_right_gives_zero_degree_direction(self):
        sightings = [
            _make_sighting(0.1, 0.5, 0.2, 0.6, ts=100.0),
            _make_sighting(0.3, 0.5, 0.4, 0.6, ts=101.0),
            _make_sighting(0.5, 0.5, 0.6, 0.6, ts=102.0),
        ]
        delta = compute_temporal_delta(sightings, first_seen=100.0, last_seen=102.0, now=103.0)
        assert delta.velocity > 0.01
        assert delta.direction_deg is not None
        # Should be approximately 0° (rightward)
        assert abs(delta.direction_deg) < 15 or abs(delta.direction_deg - 360) < 15

    def test_moving_down_gives_ninety_degree_direction(self):
        sightings = [
            _make_sighting(0.5, 0.1, 0.6, 0.2, ts=100.0),
            _make_sighting(0.5, 0.3, 0.6, 0.4, ts=101.0),
            _make_sighting(0.5, 0.5, 0.6, 0.6, ts=102.0),
        ]
        delta = compute_temporal_delta(sightings, first_seen=100.0, last_seen=102.0, now=103.0)
        assert delta.velocity > 0.01
        assert delta.direction_deg is not None
        assert abs(delta.direction_deg - 90) < 15

    def test_moving_left_gives_180_degree_direction(self):
        sightings = [
            _make_sighting(0.8, 0.5, 0.9, 0.6, ts=100.0),
            _make_sighting(0.5, 0.5, 0.6, 0.6, ts=101.0),
            _make_sighting(0.2, 0.5, 0.3, 0.6, ts=102.0),
        ]
        delta = compute_temporal_delta(sightings, first_seen=100.0, last_seen=102.0, now=103.0)
        assert delta.direction_deg is not None
        assert abs(delta.direction_deg - 180) < 15


# ── Entry/exit detection ──────────────────────────────────────────────


class TestEntryExit:
    def test_new_entity_is_entering(self):
        sightings = [
            _make_sighting(0.5, 0.5, 0.6, 0.6, ts=100.0),
        ]
        delta = compute_temporal_delta(sightings, first_seen=100.0, last_seen=100.0, now=101.0)
        assert delta.is_entering is True
        assert delta.is_exiting is False

    def test_old_entity_not_entering(self):
        sightings = [
            _make_sighting(0.5, 0.5, 0.6, 0.6, ts=50.0),
            _make_sighting(0.5, 0.5, 0.6, 0.6, ts=100.0),
            _make_sighting(0.5, 0.5, 0.6, 0.6, ts=101.0),
        ]
        delta = compute_temporal_delta(sightings, first_seen=50.0, last_seen=101.0, now=102.0)
        assert delta.is_entering is False

    def test_stale_entity_is_exiting(self):
        sightings = [
            _make_sighting(0.5, 0.5, 0.6, 0.6, ts=80.0),
            _make_sighting(0.5, 0.5, 0.6, 0.6, ts=85.0),
        ]
        delta = compute_temporal_delta(sightings, first_seen=80.0, last_seen=85.0, now=100.0)
        assert delta.is_exiting is True

    def test_recent_entity_not_exiting(self):
        sightings = [
            _make_sighting(0.5, 0.5, 0.6, 0.6, ts=99.0),
            _make_sighting(0.5, 0.5, 0.6, 0.6, ts=100.0),
        ]
        delta = compute_temporal_delta(sightings, first_seen=99.0, last_seen=100.0, now=101.0)
        assert delta.is_exiting is False


# ── Empty/edge cases ──────────────────────────────────────────────────


class TestEdgeCases:
    def test_empty_sightings(self):
        delta = compute_temporal_delta([], first_seen=100.0, last_seen=100.0, now=101.0)
        assert delta.velocity == 0.0
        assert delta.direction_deg is None

    def test_single_sighting(self):
        sightings = [_make_sighting(0.5, 0.5, 0.6, 0.6, ts=100.0)]
        delta = compute_temporal_delta(sightings, first_seen=100.0, last_seen=100.0, now=101.0)
        assert delta.velocity == 0.0
        assert delta.direction_deg is None

    def test_zero_dt_no_crash(self):
        """Two sightings at same timestamp should not divide by zero."""
        sightings = [
            _make_sighting(0.1, 0.1, 0.2, 0.2, ts=100.0),
            _make_sighting(0.5, 0.5, 0.6, 0.6, ts=100.0),
        ]
        delta = compute_temporal_delta(sightings, first_seen=100.0, last_seen=100.0, now=101.0)
        assert not math.isnan(delta.velocity)
        assert not math.isinf(delta.velocity)

    def test_malformed_box_skipped(self):
        sightings = [
            {"box": [0.1], "conf": 0.9, "ts": 100.0},  # too short
            _make_sighting(0.5, 0.5, 0.6, 0.6, ts=101.0),
        ]
        delta = compute_temporal_delta(sightings, first_seen=100.0, last_seen=101.0, now=102.0)
        assert delta.velocity == 0.0  # only 1 valid centroid


# ── Confidence stability ──────────────────────────────────────────────


class TestConfidenceStability:
    def test_constant_confidence_gives_zero_stability(self):
        sightings = [
            _make_sighting(0.3, 0.3, 0.5, 0.5, conf=0.9, ts=100.0),
            _make_sighting(0.3, 0.3, 0.5, 0.5, conf=0.9, ts=101.0),
        ]
        delta = compute_temporal_delta(sightings, first_seen=100.0, last_seen=101.0, now=102.0)
        assert delta.confidence_stability == 0.0

    def test_varying_confidence_gives_nonzero_stability(self):
        sightings = [
            _make_sighting(0.3, 0.3, 0.5, 0.5, conf=0.5, ts=100.0),
            _make_sighting(0.3, 0.3, 0.5, 0.5, conf=0.9, ts=101.0),
        ]
        delta = compute_temporal_delta(sightings, first_seen=100.0, last_seen=101.0, now=102.0)
        assert delta.confidence_stability > 0.1


# ── Return type ───────────────────────────────────────────────────────


class TestReturnType:
    def test_returns_frozen_dataclass(self):
        delta = compute_temporal_delta([], first_seen=0, last_seen=0, now=1)
        assert isinstance(delta, TemporalDelta)
        # Frozen — should not be mutable
        try:
            delta.velocity = 1.0  # type: ignore[misc]
            raise AssertionError("Should have raised AttributeError")
        except AttributeError:
            pass

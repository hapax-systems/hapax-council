"""Tests for cockpit.data.momentum — domain momentum tracking."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from cockpit.data.momentum import (
    MomentumVector,
    DomainMomentum,
    compute_activity_rate,
    compute_regularity,
    compute_alignment_slope,
    classify_direction,
    classify_regularity,
    collect_domain_momentum,
)


class TestActivityRate:
    def test_no_events_returns_zero(self) -> None:
        """No events produces rate 0.0."""
        assert compute_activity_rate([], days_short=7, days_long=30) == 0.0

    def test_uniform_events_returns_near_one(self) -> None:
        """Uniform daily events over 30 days produce ratio near 1.0."""
        now = datetime.now(timezone.utc)
        events = [now - timedelta(days=i) for i in range(30)]
        rate = compute_activity_rate(events, days_short=7, days_long=30)
        assert 0.8 <= rate <= 1.2

    def test_recent_burst_returns_high(self) -> None:
        """Events only in last 7 days produce ratio > 1.2."""
        now = datetime.now(timezone.utc)
        events = [now - timedelta(hours=i * 6) for i in range(28)]  # 28 events in 7 days
        rate = compute_activity_rate(events, days_short=7, days_long=30)
        assert rate > 1.2

    def test_old_events_only_returns_low(self) -> None:
        """Events only 20+ days ago produce ratio < 0.8."""
        now = datetime.now(timezone.utc)
        events = [now - timedelta(days=20 + i) for i in range(10)]
        rate = compute_activity_rate(events, days_short=7, days_long=30)
        assert rate < 0.8


class TestRegularity:
    def test_no_events_returns_high_cv(self) -> None:
        """No events => sporadic."""
        cv = compute_regularity([])
        assert cv > 1.0

    def test_regular_daily_events(self) -> None:
        """Daily events have low CV."""
        now = datetime.now(timezone.utc)
        events = [now - timedelta(days=i) for i in range(30)]
        cv = compute_regularity(events)
        assert cv < 0.5

    def test_bursty_events(self) -> None:
        """Events clustered in bursts have moderate CV."""
        now = datetime.now(timezone.utc)
        events = (
            [now - timedelta(days=i) for i in range(3)]  # burst 1
            + [now - timedelta(days=15 + i) for i in range(3)]  # burst 2
        )
        cv = compute_regularity(events)
        assert cv >= 0.5


class TestAlignmentSlope:
    def test_improving(self) -> None:
        """Increasing scores produce positive slope."""
        scores = [0.3, 0.4, 0.5, 0.6]
        slope = compute_alignment_slope(scores)
        assert slope > 0

    def test_regressing(self) -> None:
        """Decreasing scores produce negative slope."""
        scores = [0.6, 0.5, 0.4, 0.3]
        slope = compute_alignment_slope(scores)
        assert slope < 0

    def test_flat(self) -> None:
        """Constant scores produce near-zero slope."""
        scores = [0.5, 0.5, 0.5, 0.5]
        slope = compute_alignment_slope(scores)
        assert abs(slope) < 0.01

    def test_insufficient_data(self) -> None:
        """Fewer than 2 scores return 0.0."""
        assert compute_alignment_slope([0.5]) == 0.0
        assert compute_alignment_slope([]) == 0.0


class TestClassifiers:
    def test_direction_accelerating(self) -> None:
        assert classify_direction(1.5) == "accelerating"

    def test_direction_steady(self) -> None:
        assert classify_direction(1.0) == "steady"

    def test_direction_decelerating(self) -> None:
        assert classify_direction(0.5) == "decelerating"

    def test_direction_dormant(self) -> None:
        assert classify_direction(0.05) == "dormant"

    def test_regularity_regular(self) -> None:
        assert classify_regularity(0.3) == "regular"

    def test_regularity_irregular(self) -> None:
        assert classify_regularity(0.7) == "irregular"

    def test_regularity_sporadic(self) -> None:
        assert classify_regularity(1.5) == "sporadic"


class TestDomainMomentum:
    def test_dataclass_fields(self) -> None:
        """MomentumVector has all required fields."""
        v = MomentumVector(
            domain_id="test",
            direction="steady",
            regularity="regular",
            alignment="plateaued",
            activity_rate=1.0,
            regularity_cv=0.3,
            alignment_slope=0.0,
            computed_at="2026-03-04T00:00:00Z",
        )
        assert v.domain_id == "test"
        assert v.direction == "steady"

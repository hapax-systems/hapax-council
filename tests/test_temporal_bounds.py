"""Tests for temporal bounds — consent formalism #6.

Verifies interval logic, temporal validity, renewal, grace periods,
and Allen's interval relations.
"""

from __future__ import annotations

import time

from hypothesis import given, settings
from hypothesis import strategies as st

from shared.governance.temporal import ConsentInterval, TemporalConsent

# ── Strategies ───────────────────────────────────────────────────────────────

reasonable_times = st.floats(min_value=1e9, max_value=2e9)
durations = st.floats(min_value=0.1, max_value=1e7)


# ── ConsentInterval Tests ────────────────────────────────────────────────────


class TestConsentInterval:
    def test_active_within_bounds(self):
        now = time.time()
        iv = ConsentInterval(start=now - 100, end=now + 100)
        assert iv.active_at(now) is True

    def test_inactive_before_start(self):
        now = time.time()
        iv = ConsentInterval(start=now + 100, end=now + 200)
        assert iv.active_at(now) is False

    def test_inactive_after_end(self):
        now = time.time()
        iv = ConsentInterval(start=now - 200, end=now - 100)
        assert iv.active_at(now) is False

    def test_indefinite_always_active_after_start(self):
        now = time.time()
        iv = ConsentInterval(start=now - 100, end=None)
        assert iv.active_at(now) is True
        assert iv.active_at(now + 1e9) is True

    def test_expired(self):
        now = time.time()
        iv = ConsentInterval(start=now - 200, end=now - 100)
        assert iv.expired_at(now) is True

    def test_not_expired_indefinite(self):
        iv = ConsentInterval(start=0, end=None)
        assert iv.expired_at() is False

    def test_remaining(self):
        now = time.time()
        iv = ConsentInterval(start=now - 100, end=now + 50)
        remaining = iv.remaining_at(now)
        assert remaining is not None
        assert 49 < remaining < 51

    def test_remaining_indefinite(self):
        iv = ConsentInterval(start=0, end=None)
        assert iv.remaining_at() is None

    def test_remaining_expired_is_zero(self):
        now = time.time()
        iv = ConsentInterval(start=now - 200, end=now - 100)
        assert iv.remaining_at(now) == 0.0

    def test_near_expiry(self):
        now = time.time()
        iv = ConsentInterval(start=now - 100, end=now + 300)  # 5min left
        assert iv.near_expiry(grace_s=600, t=now) is True  # within 10min grace
        assert iv.near_expiry(grace_s=60, t=now) is False  # not within 1min grace

    def test_near_expiry_indefinite(self):
        iv = ConsentInterval(start=0, end=None)
        assert iv.near_expiry() is False


class TestIntervalOperations:
    def test_extend(self):
        now = time.time()
        iv = ConsentInterval(start=now, end=now + 100)
        extended = iv.extend(50)
        assert extended.end == now + 150

    def test_extend_indefinite(self):
        iv = ConsentInterval(start=0, end=None)
        assert iv.extend(100) is iv  # unchanged

    def test_renew(self):
        now = time.time()
        iv = ConsentInterval(start=now - 1000, end=now - 500)
        renewed = iv.renew(3600, from_time=now)
        assert renewed.start == now
        assert renewed.end == now + 3600
        assert renewed.active_at(now) is True

    def test_intersect_overlapping(self):
        iv1 = ConsentInterval(start=0, end=100)
        iv2 = ConsentInterval(start=50, end=150)
        result = iv1.intersect(iv2)
        assert result is not None
        assert result.start == 50
        assert result.end == 100

    def test_intersect_disjoint(self):
        iv1 = ConsentInterval(start=0, end=50)
        iv2 = ConsentInterval(start=100, end=150)
        assert iv1.intersect(iv2) is None

    def test_intersect_one_indefinite(self):
        iv1 = ConsentInterval(start=0, end=100)
        iv2 = ConsentInterval(start=50, end=None)
        result = iv1.intersect(iv2)
        assert result is not None
        assert result.start == 50
        assert result.end == 100

    def test_intersect_both_indefinite(self):
        iv1 = ConsentInterval(start=0, end=None)
        iv2 = ConsentInterval(start=50, end=None)
        result = iv1.intersect(iv2)
        assert result is not None
        assert result.start == 50
        assert result.end is None

    def test_contains(self):
        iv1 = ConsentInterval(start=0, end=100)
        iv2 = ConsentInterval(start=25, end=75)
        assert iv1.contains(iv2) is True
        assert iv2.contains(iv1) is False

    def test_before(self):
        iv1 = ConsentInterval(start=0, end=50)
        iv2 = ConsentInterval(start=100, end=150)
        assert iv1.before(iv2) is True
        assert iv2.before(iv1) is False

    def test_overlaps(self):
        iv1 = ConsentInterval(start=0, end=100)
        iv2 = ConsentInterval(start=50, end=150)
        assert iv1.overlaps(iv2) is True

    def test_fixed(self):
        now = time.time()
        iv = ConsentInterval.fixed(3600, start=now)
        assert iv.start == now
        assert iv.end == now + 3600

    def test_indefinite_constructor(self):
        now = time.time()
        iv = ConsentInterval.indefinite(start=now)
        assert iv.start == now
        assert iv.end is None


class TestIntervalAlgebraProperties:
    @given(start=reasonable_times, dur=durations)
    @settings(max_examples=50)
    def test_active_within_duration(self, start, dur):
        """Interval is always active at its midpoint."""
        iv = ConsentInterval(start=start, end=start + dur)
        mid = start + dur / 2
        assert iv.active_at(mid) is True

    @given(start=reasonable_times, dur=durations)
    @settings(max_examples=50)
    def test_expired_after_end(self, start, dur):
        """Interval is always expired after its end."""
        iv = ConsentInterval(start=start, end=start + dur)
        assert iv.expired_at(start + dur + 1) is True

    @given(start=reasonable_times, dur=durations)
    @settings(max_examples=50)
    def test_self_contains_self(self, start, dur):
        """Every interval contains itself."""
        iv = ConsentInterval(start=start, end=start + dur)
        assert iv.contains(iv) is True

    @given(start=reasonable_times, dur=durations)
    @settings(max_examples=50)
    def test_self_overlaps_self(self, start, dur):
        """Every interval overlaps itself."""
        iv = ConsentInterval(start=start, end=start + dur)
        assert iv.overlaps(iv) is True


# ── TemporalConsent Tests ────────────────────────────────────────────────────


class TestTemporalConsent:
    def test_valid_consent(self):
        now = time.time()
        tc = TemporalConsent(
            contract_id="c1",
            interval=ConsentInterval(start=now - 100, end=now + 100),
            person_id="alice",
        )
        assert tc.valid_at(now) is True

    def test_expired_consent(self):
        now = time.time()
        tc = TemporalConsent(
            contract_id="c1",
            interval=ConsentInterval(start=now - 200, end=now - 100),
        )
        assert tc.valid_at(now) is False

    def test_needs_renewal(self):
        now = time.time()
        tc = TemporalConsent(
            contract_id="c1",
            interval=ConsentInterval(start=now - 100, end=now + 300),
        )
        assert tc.needs_renewal(grace_s=600, t=now) is True
        assert tc.needs_renewal(grace_s=60, t=now) is False

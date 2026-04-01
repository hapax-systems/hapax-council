"""Test imagination loop skips ticks when observations are stale."""

import time


def test_observations_freshness_check():
    """Imagination should detect stale observations."""
    from agents.imagination_loop import observations_are_fresh

    assert observations_are_fresh(published_at=time.time() - 2, cadence_s=12.0) is True
    assert observations_are_fresh(published_at=time.time() - 30, cadence_s=12.0) is False
    assert observations_are_fresh(published_at=time.time() - 23, cadence_s=12.0) is True

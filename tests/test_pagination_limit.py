"""Tests for Langfuse pagination limits in activity_analyzer and profiler_sources."""

from datetime import UTC, datetime
from unittest.mock import patch


def _make_page(n_items: int, total: int) -> dict:
    """Create a fake Langfuse API response page."""
    return {
        "data": [{"id": f"item-{i}"} for i in range(n_items)],
        "meta": {"totalItems": total},
    }


def test_activity_analyzer_traces_pagination_limit():
    """collect_langfuse stops after MAX_PAGES even if more data exists."""
    from agents.activity_analyzer import MAX_PAGES, collect_langfuse

    since = datetime(2025, 1, 1, tzinfo=UTC)

    # Mock returns 100 items per page, claims 5000 total (50 pages needed)
    call_count = 0

    def fake_api(path, params=None, *, timeout=10):
        nonlocal call_count
        call_count += 1
        return _make_page(100, 5000)

    with patch("agents.activity_analyzer._langfuse_api", side_effect=fake_api):
        with patch("agents.activity_analyzer.LANGFUSE_PK", "pk-test"):
            collect_langfuse(since)

    # Should have fetched MAX_PAGES pages of traces + MAX_PAGES of observations
    # Each pagination loop is capped at MAX_PAGES
    assert call_count <= MAX_PAGES * 2 + 2  # Some slack for boundary


def test_profiler_sources_traces_pagination_limit():
    """read_langfuse stops after MAX_PAGES even if more data exists."""
    call_count = 0

    def fake_get(path, params=None):
        nonlocal call_count
        call_count += 1
        if "/traces" in path:
            return _make_page(100, 5000)
        if "/observations" in path:
            return _make_page(100, 5000)
        return {}

    with patch("agents.profiler_sources._langfuse_get", side_effect=fake_get):
        with patch("agents.profiler_sources._LANGFUSE_PK", "pk-test"):
            from agents.profiler_sources import read_langfuse

            read_langfuse(lookback_days=7)

    # MAX_PAGES is 20 in profiler_sources, so traces + observations <= 40 calls
    assert call_count <= 42  # 20 traces + 20 observations + slack

"""Tests for Phase 3 cross-system cascade wires."""

from unittest.mock import MagicMock, patch

# ── Wire 2: correction facts bridge ─────────────────────────────────────────


def test_read_correction_facts_empty_when_no_qdrant():
    """Graceful degradation when Qdrant is unavailable."""
    with patch("shared.config.get_qdrant", side_effect=Exception("no qdrant")):
        from agents.profiler_sources import read_correction_facts

        assert read_correction_facts() == []


def test_read_correction_facts_empty_when_no_results():
    """Empty list when no corrections in time window."""
    mock_client = MagicMock()
    mock_client.scroll.return_value = ([], None)

    with patch("shared.config.get_qdrant", return_value=mock_client):
        from agents.profiler_sources import read_correction_facts

        assert read_correction_facts() == []


def test_read_correction_facts_filters_below_threshold():
    """Dimensions with < 2 corrections are excluded."""
    mock_point = MagicMock()
    mock_point.payload = {
        "dimension": "activity",
        "original_value": "coding",
        "corrected_value": "writing",
        "timestamp": 9999999999.0,
    }
    mock_client = MagicMock()
    mock_client.scroll.return_value = ([mock_point], None)

    with patch("shared.config.get_qdrant", return_value=mock_client):
        from agents.profiler_sources import read_correction_facts

        facts = read_correction_facts()
        assert facts == []  # Only 1 correction for "activity" — below threshold


def test_read_correction_facts_produces_facts_above_threshold():
    """Dimensions with >= 2 corrections produce profile facts."""
    points = []
    for i in range(3):
        p = MagicMock()
        p.payload = {
            "dimension": "activity",
            "original_value": f"orig_{i}",
            "corrected_value": f"corr_{i}",
            "timestamp": 9999999999.0,
        }
        points.append(p)

    mock_client = MagicMock()
    mock_client.scroll.return_value = (points, None)

    with patch("shared.config.get_qdrant", return_value=mock_client):
        from agents.profiler_sources import read_correction_facts

        facts = read_correction_facts()
        assert len(facts) == 1
        fact = facts[0]
        assert fact["key"] == "correction.activity.frequency"
        assert fact["dimension"] == "energy_and_attention"
        assert "3 corrections" in fact["value"]
        assert fact["confidence"] == 3 / 20  # min(0.8, 3/20)


def test_read_correction_facts_multiple_dimensions():
    """Multiple dimensions each produce their own fact."""
    points = []
    for dim in ("activity", "activity", "flow", "flow", "flow"):
        p = MagicMock()
        p.payload = {
            "dimension": dim,
            "original_value": "x",
            "corrected_value": "y",
            "timestamp": 9999999999.0,
        }
        points.append(p)

    mock_client = MagicMock()
    mock_client.scroll.return_value = (points, None)

    with patch("shared.config.get_qdrant", return_value=mock_client):
        from agents.profiler_sources import read_correction_facts

        facts = read_correction_facts()
        dims = {f["key"] for f in facts}
        assert dims == {"correction.activity.frequency", "correction.flow.frequency"}


# ── Wire 4: voice_active → PRESENTING density ───────────────────────────────


def test_voice_active_suppresses_ambient_density():
    """When voice_active=True, density should be PRESENTING."""
    from agents.content_scheduler import (
        ContentScheduler,
        DisplayDensity,
        SchedulerContext,
    )

    scheduler = ContentScheduler()
    ctx = SchedulerContext(voice_active=True, activity="present")
    density = scheduler._compute_density(ctx)
    assert density == DisplayDensity.PRESENTING


def test_voice_inactive_allows_normal_density():
    """When voice_active=False, density follows normal rules."""
    from agents.content_scheduler import (
        ContentScheduler,
        DisplayDensity,
        SchedulerContext,
    )

    scheduler = ContentScheduler()
    ctx = SchedulerContext(voice_active=False, activity="present")
    density = scheduler._compute_density(ctx)
    # Should be AMBIENT or RECEPTIVE, not PRESENTING
    assert density != DisplayDensity.PRESENTING

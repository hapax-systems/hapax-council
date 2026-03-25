"""Tests for Phase 4 compliance upgrades — staleness enforcement and source separation."""

import time
from pathlib import Path
from unittest.mock import patch

# ── Fix 1: Briefing per-source staleness ─────────────────────────────────────


def test_source_freshness_from_existing_file(tmp_path: Path):
    """SourceFreshness computes age from file mtime."""
    from agents.briefing import _source_freshness

    f = tmp_path / "test.json"
    f.write_text("{}")
    sf = _source_freshness("test_source", f)
    assert sf.source == "test_source"
    assert sf.age_s is not None
    assert sf.age_s >= 0.0
    assert sf.stale is False  # just created, well within any threshold


def test_source_freshness_missing_file():
    """SourceFreshness marks missing files as stale."""
    from agents.briefing import _source_freshness

    sf = _source_freshness("test_source", Path("/nonexistent/path.json"))
    assert sf.age_s is None
    assert sf.stale is True


def test_source_freshness_stale_file(tmp_path: Path):
    """SourceFreshness detects stale files based on threshold."""
    import os

    from agents.briefing import SOURCE_STALENESS_THRESHOLDS, _source_freshness

    f = tmp_path / "old.json"
    f.write_text("{}")
    # Set mtime to 2 hours ago
    old_time = time.time() - 7200
    os.utime(f, (old_time, old_time))

    # Use health_snapshot threshold (300s) — file at 7200s is stale
    sf = _source_freshness("health_snapshot", f)
    assert sf.stale is True
    assert sf.age_s is not None
    assert sf.age_s > SOURCE_STALENESS_THRESHOLDS["health_snapshot"]


def test_briefing_model_has_source_freshness():
    """Briefing model includes source_freshness field."""
    from agents.briefing import Briefing, SourceFreshness

    b = Briefing(
        generated_at="2026-01-01T00:00:00Z",
        hours=24,
        headline="test",
        body="test",
        source_freshness=[
            SourceFreshness(source="health_snapshot", age_s=5.0, stale=False),
            SourceFreshness(source="scout_report", age_s=None, stale=True),
        ],
    )
    assert len(b.source_freshness) == 2
    assert b.source_freshness[0].source == "health_snapshot"
    assert b.source_freshness[1].stale is True


# ── Fix 2: Nudges fast/slow separation ───────────────────────────────────────


def test_nudge_staleness_thresholds_consolidated():
    """Staleness thresholds are in a central dict."""
    from logos.data.nudges import STALENESS_THRESHOLDS_H

    assert "briefing" in STALENESS_THRESHOLDS_H
    assert "scout" in STALENESS_THRESHOLDS_H
    assert "drift" in STALENESS_THRESHOLDS_H
    assert STALENESS_THRESHOLDS_H["briefing"] == 26
    assert STALENESS_THRESHOLDS_H["scout"] == 192


def test_slow_tier_cache_returns_cached_on_second_call():
    """Slow tier returns cached results within TTL."""
    import logos.data.nudges as nudges_mod

    # Reset cache
    nudges_mod._slow_cache = []
    nudges_mod._slow_cache_time = 0.0

    # First call populates cache
    with patch.object(nudges_mod, "_collect_briefing_nudges"):
        with patch.object(nudges_mod, "_collect_scout_nudges"):
            with patch.object(nudges_mod, "_collect_drift_nudges"):
                nudges_mod._collect_slow_tier(None)
                # Record the cache time
                cache_time_1 = nudges_mod._slow_cache_time
                assert cache_time_1 > 0

                # Second call should use cache (no collectors called again)
                nudges_mod._collect_slow_tier(None)
                assert nudges_mod._slow_cache_time == cache_time_1  # unchanged


def test_collect_nudges_includes_fast_collectors():
    """collect_nudges always runs health and goal collectors (fast tier)."""
    import logos.data.nudges as nudges_mod

    # Pre-fill slow cache so slow tier doesn't run
    nudges_mod._slow_cache = []
    nudges_mod._slow_cache_time = time.monotonic()

    health_called = False
    goals_called = False

    orig_health = nudges_mod._collect_health_nudges
    orig_goals = nudges_mod._collect_goal_nudges

    def track_health(nudges):
        nonlocal health_called
        health_called = True
        return orig_health(nudges)

    def track_goals(nudges):
        nonlocal goals_called
        goals_called = True
        return orig_goals(nudges)

    with patch.object(nudges_mod, "_collect_health_nudges", track_health):
        with patch.object(nudges_mod, "_collect_goal_nudges", track_goals):
            nudges_mod.collect_nudges()

    assert health_called, "Health collector (fast tier) should always run"
    assert goals_called, "Goal collector (fast tier) should always run"


# ── Fix 3: Content scheduler staleness veto ──────────────────────────────────


def test_content_pools_has_pool_age():
    """ContentPools model includes pool_age_s field."""
    from agents.content_scheduler import ContentPools

    pools = ContentPools(facts=["test"], pool_age_s=60.0)
    assert pools.pool_age_s == 60.0

    # Default is 0.0
    pools2 = ContentPools()
    assert pools2.pool_age_s == 0.0


def test_stale_pools_vetoed():
    """Pool-backed sources are rejected when pool_age_s exceeds MAX_POOL_AGE_S."""
    from agents.content_scheduler import (
        MAX_POOL_AGE_S,
        ContentPools,
        ContentScheduler,
        ContentSource,
        SchedulerContext,
    )

    scheduler = ContentScheduler()
    ctx = SchedulerContext()

    # Fresh pools — facts should be available
    fresh_pools = ContentPools(facts=["fact1"], pool_age_s=10.0)
    available = scheduler._available_sources(ctx, fresh_pools)
    assert ContentSource.PROFILE_FACT in available

    # Stale pools — facts should be vetoed
    stale_pools = ContentPools(facts=["fact1"], pool_age_s=MAX_POOL_AGE_S + 1)
    available = scheduler._available_sources(ctx, stale_pools)
    assert ContentSource.PROFILE_FACT not in available


def test_non_pool_sources_unaffected_by_staleness():
    """Shader, time_of_day, activity_label are not pool-backed and always available."""
    from agents.content_scheduler import (
        MAX_POOL_AGE_S,
        ContentPools,
        ContentScheduler,
        ContentSource,
        SchedulerContext,
    )

    scheduler = ContentScheduler()
    ctx = SchedulerContext()

    stale_pools = ContentPools(pool_age_s=MAX_POOL_AGE_S + 100)
    available = scheduler._available_sources(ctx, stale_pools)

    # Non-pool sources always present
    assert ContentSource.SHADER_VARIATION in available
    assert ContentSource.TIME_OF_DAY in available
    assert ContentSource.ACTIVITY_LABEL in available
    assert ContentSource.BIOMETRIC_MOD in available


def test_max_pool_age_is_two_minutes():
    """MAX_POOL_AGE_S is 120 seconds (2 minutes)."""
    from agents.content_scheduler import MAX_POOL_AGE_S

    assert MAX_POOL_AGE_S == 120.0

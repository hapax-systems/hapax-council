"""Tests for shared.service_tiers."""

from shared.service_tiers import (
    TIER_NUDGE_SCORES,
    ServiceTier,
    tier_for_check,
)


def test_explicit_tier_map():
    """Checks in TIER_MAP return their explicit tier."""
    assert tier_for_check("docker.qdrant") == ServiceTier.CRITICAL
    assert tier_for_check("connectivity.tailscale") == ServiceTier.OPTIONAL
    assert tier_for_check("docker.open-webui") == ServiceTier.OBSERVABILITY


def test_group_default_fallback():
    """Unknown check names fall back to their group default."""
    assert tier_for_check("docker.unknown-container", "docker") == ServiceTier.IMPORTANT
    assert tier_for_check("connectivity.unknown", "connectivity") == ServiceTier.OPTIONAL
    assert tier_for_check("memory.global_ram_pressure", "memory") == ServiceTier.IMPORTANT


def test_inferred_group_from_name():
    """Group is inferred from check_name prefix when not provided."""
    assert tier_for_check("disk.usage") == ServiceTier.IMPORTANT
    assert tier_for_check("profiles.staleness") == ServiceTier.OBSERVABILITY


def test_nudge_scores_cover_all_tiers():
    """Every tier has a nudge score."""
    for tier in ServiceTier:
        assert tier in TIER_NUDGE_SCORES

"""Tests for the WCS health degraded blocker bus."""

from __future__ import annotations

from shared.wcs_health_blocker_bus import (
    WcsHealthBlockerBus,
)


def _bus_with_mixed_state() -> WcsHealthBlockerBus:
    bus = WcsHealthBlockerBus()
    bus.emit("temporal_bands", "healthy", authority_ceiling="public_live")
    bus.emit(
        "perceptual_field",
        "degraded",
        authority_ceiling="private_only",
        blocked_reason="stale PerceptualField",
    )
    bus.emit(
        "audio_egress",
        "blocked",
        authority_ceiling="blocked",
        blocked_reason="audio chain broken",
        false_grounding_causes=["spanless_media"],
    )
    bus.emit("monetization", "healthy", authority_ceiling="public_monetizable")
    return bus


class TestBusEmit:
    def test_emit_returns_event(self):
        bus = WcsHealthBlockerBus()
        e = bus.emit("temporal_bands", "healthy", authority_ceiling="public_live")
        assert e.capability == "temporal_bands"
        assert e.state == "healthy"
        assert e.event_id == "wcs-health-1"
        assert e.emitted_at

    def test_emit_increments_ids(self):
        bus = WcsHealthBlockerBus()
        e1 = bus.emit("a", "healthy", authority_ceiling="public_live")
        e2 = bus.emit("b", "degraded", authority_ceiling="private_only")
        assert e1.event_id != e2.event_id

    def test_emit_with_false_grounding_causes(self):
        bus = WcsHealthBlockerBus()
        e = bus.emit(
            "temporal_bands",
            "stale",
            authority_ceiling="dry_run_only",
            false_grounding_causes=["stale_temporal_band", "protention_only_evidence"],
        )
        assert len(e.false_grounding_causes) == 2
        assert "stale_temporal_band" in e.false_grounding_causes


class TestPublicLiveBlocking:
    def test_public_live_blocked_when_private_only(self):
        bus = WcsHealthBlockerBus()
        e = bus.emit("perceptual_field", "degraded", authority_ceiling="private_only")
        assert e.blocks_public_live()

    def test_public_live_allowed_when_public(self):
        bus = WcsHealthBlockerBus()
        e = bus.emit("temporal_bands", "healthy", authority_ceiling="public_live")
        assert not e.blocks_public_live()

    def test_monetized_blocked_when_not_monetizable(self):
        bus = WcsHealthBlockerBus()
        e = bus.emit("audio", "healthy", authority_ceiling="public_live")
        assert e.blocks_monetized()

    def test_monetized_allowed_when_monetizable(self):
        bus = WcsHealthBlockerBus()
        e = bus.emit("audio", "healthy", authority_ceiling="public_monetizable")
        assert not e.blocks_monetized()


class TestSnapshot:
    def test_snapshot_counts(self):
        bus = _bus_with_mixed_state()
        snap = bus.snapshot()
        assert snap.total_capabilities == 4
        assert snap.healthy == 2
        assert snap.degraded == 1
        assert snap.blocked == 1

    def test_snapshot_not_all_healthy(self):
        bus = _bus_with_mixed_state()
        assert not bus.snapshot().all_healthy

    def test_all_healthy_snapshot(self):
        bus = WcsHealthBlockerBus()
        bus.emit("a", "healthy", authority_ceiling="public_live")
        bus.emit("b", "healthy", authority_ceiling="public_live")
        assert bus.snapshot().all_healthy

    def test_snapshot_blocked_reasons(self):
        bus = _bus_with_mixed_state()
        reasons = bus.snapshot().blocked_reasons()
        assert "stale PerceptualField" in reasons
        assert "audio chain broken" in reasons

    def test_snapshot_public_live_blocked(self):
        bus = _bus_with_mixed_state()
        assert bus.snapshot().public_live_blocked()

    def test_snapshot_monetized_blocked(self):
        bus = _bus_with_mixed_state()
        assert bus.snapshot().monetized_blocked()

    def test_latest_per_capability_dedupes(self):
        bus = WcsHealthBlockerBus()
        bus.emit("temporal_bands", "stale", authority_ceiling="blocked", blocked_reason="stale")
        bus.emit("temporal_bands", "recovered", authority_ceiling="public_live")
        snap = bus.snapshot()
        assert snap.healthy == 0
        assert snap.blocked == 0
        assert snap.total_capabilities == 1


class TestRefusalStillProducible:
    def test_refusal_artifacts_when_public_safe(self):
        bus = WcsHealthBlockerBus()
        bus.emit("temporal_bands", "degraded", authority_ceiling="public_archive")
        snap = bus.snapshot()
        assert not snap.public_live_blocked()


class TestClear:
    def test_clear_resets(self):
        bus = _bus_with_mixed_state()
        bus.clear()
        snap = bus.snapshot()
        assert snap.total_capabilities == 0

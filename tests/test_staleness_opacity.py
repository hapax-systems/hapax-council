"""Tests for staleness-weighted opacity decay (Phase 3)."""

from __future__ import annotations

from agents.visual_layer_state import (
    SEVERITY_MEDIUM,
    DisplayStateMachine,
    SignalCategory,
    SignalEntry,
    SignalStaleness,
    _apply_staleness_decay,
)


def _signal(
    cat: SignalCategory = SignalCategory.HEALTH_INFRA, severity: float = 0.5
) -> SignalEntry:
    return SignalEntry(category=cat, severity=severity, title="test", source_id="test")


class TestStalenessDecay:
    def test_fresh_data_no_decay(self):
        opacities = {SignalCategory.HEALTH_INFRA: 0.7}
        staleness = SignalStaleness(health_s=0.0)
        _apply_staleness_decay(opacities, staleness)
        assert opacities[SignalCategory.HEALTH_INFRA] == 0.7

    def test_stale_data_decays(self):
        opacities = {SignalCategory.HEALTH_INFRA: 0.7}
        staleness = SignalStaleness(health_s=30.0)  # half of 60s max
        _apply_staleness_decay(opacities, staleness)
        assert opacities[SignalCategory.HEALTH_INFRA] < 0.7
        assert opacities[SignalCategory.HEALTH_INFRA] > 0.2  # floor at 0.3*0.7

    def test_very_stale_hits_floor(self):
        opacities = {SignalCategory.HEALTH_INFRA: 0.7}
        staleness = SignalStaleness(health_s=120.0)  # way past 60s max
        _apply_staleness_decay(opacities, staleness)
        # Floor: 0.3 * 0.7 = 0.21
        assert opacities[SignalCategory.HEALTH_INFRA] == round(0.7 * 0.3, 3)

    def test_zero_opacity_unaffected(self):
        opacities = {SignalCategory.HEALTH_INFRA: 0.0}
        staleness = SignalStaleness(health_s=30.0)
        _apply_staleness_decay(opacities, staleness)
        assert opacities[SignalCategory.HEALTH_INFRA] == 0.0

    def test_perception_staleness_affects_sensors(self):
        opacities = {SignalCategory.AMBIENT_SENSOR: 0.5}
        staleness = SignalStaleness(perception_s=15.0)  # half of 30s max
        _apply_staleness_decay(opacities, staleness)
        assert opacities[SignalCategory.AMBIENT_SENSOR] < 0.5

    def test_voice_staleness_fast_decay(self):
        opacities = {SignalCategory.VOICE_SESSION: 0.6}
        staleness = SignalStaleness(perception_s=10.0)  # 2/3 of 15s max
        _apply_staleness_decay(opacities, staleness)
        # decay = max(0.3, 1.0 - 10/15) = max(0.3, 0.333) = 0.333
        expected = round(0.6 * (1.0 - 10.0 / 15.0), 3)
        assert opacities[SignalCategory.VOICE_SESSION] == expected


class TestStalenessInStateMachine:
    def test_staleness_affects_opacity_output(self):
        sm = DisplayStateMachine()
        signals = [_signal(SignalCategory.HEALTH_INFRA, SEVERITY_MEDIUM)]

        # Fresh
        sm.set_staleness(SignalStaleness(health_s=0.0))
        fresh = sm.tick(signals=signals, now=0)
        fresh_opacity = fresh.zone_opacities.get(SignalCategory.HEALTH_INFRA, 0)

        # Stale
        sm2 = DisplayStateMachine()
        sm2.set_staleness(SignalStaleness(health_s=50.0))
        stale = sm2.tick(signals=signals, now=0)
        stale_opacity = stale.zone_opacities.get(SignalCategory.HEALTH_INFRA, 0)

        assert stale_opacity < fresh_opacity

    def test_no_staleness_same_as_before(self):
        """Without staleness set, behavior is unchanged."""
        sm = DisplayStateMachine()
        signals = [_signal(SignalCategory.HEALTH_INFRA, SEVERITY_MEDIUM)]
        result = sm.tick(signals=signals, now=0)
        # Should have positive opacity for health infra
        assert result.zone_opacities.get(SignalCategory.HEALTH_INFRA, 0) > 0

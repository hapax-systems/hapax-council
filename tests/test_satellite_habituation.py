"""Tests for satellite habituation — diminishing refresh via Carandini-Heeger gain control."""

import json
from pathlib import Path

from agents.reverie._satellites import (
    SatelliteManager,
)


def _core_vocab() -> dict:
    path = Path(__file__).resolve().parents[1] / "presets" / "reverie_vocabulary.json"
    return json.loads(path.read_text())


class TestHabituatingRefresh:
    def test_first_recruitment_full_strength(self):
        """First recruitment sets full strength (no habituation)."""
        mgr = SatelliteManager(_core_vocab())
        mgr.recruit("bloom", 0.5)
        assert mgr.recruited["bloom"] == 0.5

    def test_repeated_recruitment_diminishes(self):
        """Re-recruiting an active satellite applies diminishing gain."""
        mgr = SatelliteManager(_core_vocab())
        mgr.recruit("bloom", 0.5)
        mgr.recruit("bloom", 0.5)
        # Second recruitment at same strength should NOT fully refresh
        assert mgr.recruited["bloom"] < 0.5

    def test_stronger_signal_still_boosts(self):
        """A genuinely stronger signal should increase strength, even with habituation."""
        mgr = SatelliteManager(_core_vocab())
        mgr.recruit("bloom", 0.4)
        strength_before = mgr.recruited["bloom"]
        mgr.recruit("bloom", 0.65)
        assert mgr.recruited["bloom"] > strength_before

    def test_decay_eventually_dismisses_despite_refresh(self):
        """With diminishing refresh, decay eventually wins and satellite dismisses."""
        mgr = SatelliteManager(_core_vocab())
        mgr.recruit("bloom", 0.35)
        # Simulate 30 cycles: recruit at same strength, then decay
        for _ in range(30):
            mgr.recruit("bloom", 0.35)
            mgr.decay(dt=1.0)
        assert "bloom" not in mgr.recruited

    def test_no_habituation_after_dismissal(self):
        """After a satellite is dismissed and re-recruited, habituation resets."""
        mgr = SatelliteManager(_core_vocab())
        mgr.recruit("bloom", 0.5)
        mgr.decay(dt=100.0)  # Force dismissal
        assert "bloom" not in mgr.recruited
        mgr.recruit("bloom", 0.5)
        assert mgr.recruited["bloom"] == 0.5  # Full strength again

"""Tests for instrument zone mapping."""

from __future__ import annotations

from shared.cameras import OVERHEAD_ZONES, InstrumentZone, point_in_zone


class TestInstrumentZone:
    def test_zone_count(self):
        assert len(OVERHEAD_ZONES) == 4

    def test_zone_names(self):
        names = {z.name for z in OVERHEAD_ZONES}
        assert names == {"turntable", "pads", "mixer", "keyboard"}

    def test_frozen(self):
        z = OVERHEAD_ZONES[0]
        assert isinstance(z, InstrumentZone)


class TestPointInZone:
    def test_turntable_center(self):
        assert point_in_zone(200, 300) == "turntable"

    def test_pads_center(self):
        assert point_in_zone(600, 350) == "pads"

    def test_keyboard_center(self):
        assert point_in_zone(1000, 450) == "keyboard"

    def test_outside_all_zones(self):
        assert point_in_zone(1279, 0) == "unknown"

    def test_boundary_inclusive(self):
        z = OVERHEAD_ZONES[0]  # turntable
        assert point_in_zone(z.x1, z.y1) == "turntable"
        assert point_in_zone(z.x2, z.y2) == "turntable"

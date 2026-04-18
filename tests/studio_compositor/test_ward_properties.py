"""Tests for ward properties cache + SHM I/O."""

from __future__ import annotations

import time

import pytest

from agents.studio_compositor import ward_properties as wp


@pytest.fixture(autouse=True)
def _redirect_path(monkeypatch, tmp_path):
    monkeypatch.setattr(wp, "WARD_PROPERTIES_PATH", tmp_path / "ward-properties.json")
    wp.clear_ward_properties_cache()
    yield
    wp.clear_ward_properties_cache()


class TestDefaults:
    def test_no_file_returns_defaults(self):
        props = wp.resolve_ward_properties("nonexistent")
        assert props.visible is True
        assert props.alpha == 1.0
        assert props.scale == 1.0
        assert props.position_offset_x == 0.0
        assert props.color_override_rgba is None

    def test_unknown_ward_returns_default(self):
        wp.set_ward_properties("known", wp.WardProperties(alpha=0.5), ttl_s=10.0)
        wp.clear_ward_properties_cache()
        assert wp.resolve_ward_properties("unrelated").alpha == 1.0


class TestSetAndResolve:
    def test_set_then_resolve_returns_value(self):
        wp.set_ward_properties("album", wp.WardProperties(alpha=0.4, scale=1.2), ttl_s=10.0)
        wp.clear_ward_properties_cache()
        props = wp.resolve_ward_properties("album")
        assert props.alpha == 0.4
        assert props.scale == 1.2

    def test_all_fallback_applies_to_other_wards(self):
        wp.set_ward_properties("all", wp.WardProperties(alpha=0.7), ttl_s=10.0)
        wp.clear_ward_properties_cache()
        assert wp.resolve_ward_properties("anything").alpha == 0.7

    def test_specific_ward_overrides_all_fallback(self):
        # Specific entries are *full takes* — they don't merge with the
        # ``all`` fallback because the dataclass cannot distinguish
        # "deliberately set to default" from "not specified". Operators
        # wanting the all-fallback on a ward should not register a
        # per-ward entry at all.
        wp.set_ward_properties("all", wp.WardProperties(alpha=0.7), ttl_s=10.0)
        wp.set_ward_properties("album", wp.WardProperties(alpha=1.0, scale=1.5), ttl_s=10.0)
        wp.clear_ward_properties_cache()
        album = wp.resolve_ward_properties("album")
        assert album.alpha == 1.0  # specific full-take wins
        assert album.scale == 1.5
        # An unrelated ward gets the all-fallback alpha.
        other = wp.resolve_ward_properties("token_pole")
        assert other.alpha == 0.7

    def test_invisible_ward(self):
        wp.set_ward_properties("hothouse", wp.WardProperties(visible=False), ttl_s=10.0)
        wp.clear_ward_properties_cache()
        assert wp.resolve_ward_properties("hothouse").visible is False


class TestExpiry:
    def test_expired_entries_dropped_at_read(self):
        # Generous TTL + sleep margin so CI runners with coarse clock
        # resolution still observe the expiry.
        wp.set_ward_properties("album", wp.WardProperties(alpha=0.3), ttl_s=0.1)
        wp.clear_ward_properties_cache()
        time.sleep(0.3)
        props = wp.resolve_ward_properties("album")
        assert props.alpha == 1.0  # back to defaults

    def test_negative_ttl_rejected(self):
        wp.set_ward_properties("album", wp.WardProperties(alpha=0.3), ttl_s=0.0)
        # nothing written — file doesn't exist
        assert not wp.WARD_PROPERTIES_PATH.exists()


class TestAllResolved:
    def test_returns_every_ward_with_an_entry(self):
        wp.set_ward_properties("a", wp.WardProperties(alpha=0.1), ttl_s=10.0)
        wp.set_ward_properties("b", wp.WardProperties(alpha=0.2), ttl_s=10.0)
        wp.clear_ward_properties_cache()
        out = wp.all_resolved_properties()
        assert set(out.keys()) == {"a", "b"}
        assert out["a"].alpha == 0.1
        assert out["b"].alpha == 0.2


class TestColorRoundtrip:
    def test_color_override_round_trips(self):
        red = (1.0, 0.0, 0.0, 1.0)
        wp.set_ward_properties("album", wp.WardProperties(color_override_rgba=red), ttl_s=10.0)
        wp.clear_ward_properties_cache()
        assert wp.resolve_ward_properties("album").color_override_rgba == red

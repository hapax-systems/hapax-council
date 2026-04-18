"""Tests for the new ward.* dispatchers added to compositional_consumer."""

from __future__ import annotations

import json
import time

import pytest

from agents.studio_compositor import animation_engine as ae
from agents.studio_compositor import compositional_consumer as cc
from agents.studio_compositor import ward_properties as wp


@pytest.fixture(autouse=True)
def _redirect_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(cc, "_HERO_CAMERA_OVERRIDE", tmp_path / "hero-camera-override.json")
    monkeypatch.setattr(cc, "_OVERLAY_ALPHA_OVERRIDES", tmp_path / "overlay-alpha-overrides.json")
    monkeypatch.setattr(cc, "_RECENT_RECRUITMENT", tmp_path / "recent-recruitment.json")
    monkeypatch.setattr(cc, "_YOUTUBE_DIRECTION", tmp_path / "youtube-direction.json")
    monkeypatch.setattr(cc, "_STREAM_MODE_INTENT", tmp_path / "stream-mode-intent.json")
    monkeypatch.setattr(wp, "WARD_PROPERTIES_PATH", tmp_path / "ward-properties.json")
    monkeypatch.setattr(ae, "WARD_ANIMATION_STATE_PATH", tmp_path / "ward-animation-state.json")
    wp.clear_ward_properties_cache()
    ae.clear_animation_cache()
    yield


class TestWardSize:
    def test_shrink_writes_scale_below_one(self):
        assert cc.dispatch_ward_size("ward.size.album.shrink-20pct", 10.0)
        wp.clear_ward_properties_cache()
        props = wp.resolve_ward_properties("album")
        assert props.scale == pytest.approx(0.80)

    def test_grow_writes_scale_above_one(self):
        assert cc.dispatch_ward_size("ward.size.token_pole.grow-110pct", 10.0)
        wp.clear_ward_properties_cache()
        assert wp.resolve_ward_properties("token_pole").scale == pytest.approx(1.10)

    def test_unknown_modifier_falls_back_to_one(self):
        assert cc.dispatch_ward_size("ward.size.album.fast-zoom", 10.0)
        wp.clear_ward_properties_cache()
        assert wp.resolve_ward_properties("album").scale == 1.0

    def test_malformed_returns_false(self):
        assert not cc.dispatch_ward_size("ward.size.album", 10.0)
        assert not cc.dispatch_ward_size("ward.size", 10.0)

    def test_ward_id_with_hyphens(self):
        assert cc.dispatch_ward_size("ward.size.overlay-zone:main.shrink-50pct", 10.0)
        wp.clear_ward_properties_cache()
        assert wp.resolve_ward_properties("overlay-zone:main").scale == pytest.approx(0.50)


class TestWardPosition:
    def test_drift_sine_writes_drift_fields(self):
        assert cc.dispatch_ward_position("ward.position.album.drift-sine-1hz", 10.0)
        wp.clear_ward_properties_cache()
        props = wp.resolve_ward_properties("album")
        assert props.drift_type == "sine"
        assert props.drift_hz == 1.0
        assert props.drift_amplitude_px == 12.0


class TestWardStaging:
    def test_hide_sets_visible_false(self):
        assert cc.dispatch_ward_staging("ward.staging.thinking_indicator.hide", 10.0)
        wp.clear_ward_properties_cache()
        assert wp.resolve_ward_properties("thinking_indicator").visible is False

    def test_top_sets_z_order_high(self):
        assert cc.dispatch_ward_staging("ward.staging.album.top", 10.0)
        wp.clear_ward_properties_cache()
        assert wp.resolve_ward_properties("album").z_order_override == 90


class TestWardHighlight:
    def test_dim_sets_low_alpha(self):
        assert cc.dispatch_ward_highlight("ward.highlight.captions.dim", 10.0)
        wp.clear_ward_properties_cache()
        assert wp.resolve_ward_properties("captions").alpha == pytest.approx(0.35)

    def test_glow_sets_glow_radius(self):
        assert cc.dispatch_ward_highlight("ward.highlight.album.glow", 10.0)
        wp.clear_ward_properties_cache()
        assert wp.resolve_ward_properties("album").glow_radius_px == 12.0


class TestWardAppearance:
    def test_tint_warm_sets_warm_color(self):
        assert cc.dispatch_ward_appearance("ward.appearance.album.tint-warm", 10.0)
        wp.clear_ward_properties_cache()
        color = wp.resolve_ward_properties("album").color_override_rgba
        assert color is not None
        # warm tint has higher red than blue
        assert color[0] > color[2]


class TestWardCadence:
    def test_pulse_2hz_sets_rate(self):
        assert cc.dispatch_ward_cadence("ward.cadence.thinking_indicator.pulse-2hz", 10.0)
        wp.clear_ward_properties_cache()
        assert wp.resolve_ward_properties("thinking_indicator").rate_hz_override == 2.0


class TestWardChoreography:
    def test_album_emphasize_writes_transitions(self):
        assert cc.dispatch_ward_choreography("ward.choreography.album-emphasize", 1.0)
        ae.clear_animation_cache()
        # Album should have at least one active transition
        out = ae.evaluate_all(now=time.time() + 0.05)
        assert "album" in out

    def test_unknown_sequence_fails(self):
        assert not cc.dispatch_ward_choreography("ward.choreography.no-such-sequence", 1.0)


class TestTopLevelDispatch:
    def test_dispatch_routes_ward_size(self):
        rec = cc.RecruitmentRecord(name="ward.size.album.shrink-20pct", ttl_s=10.0)
        assert cc.dispatch(rec) == "ward.size"

    def test_dispatch_routes_ward_choreography(self):
        rec = cc.RecruitmentRecord(name="ward.choreography.album-emphasize", ttl_s=1.0)
        assert cc.dispatch(rec) == "ward.choreography"

    def test_dispatch_unknown_family_returns_unknown(self):
        rec = cc.RecruitmentRecord(name="completely.made.up.thing", ttl_s=10.0)
        assert cc.dispatch(rec) == "unknown"


class TestRecruitmentMarker:
    def test_ward_size_dispatch_records_in_marker(self):
        cc.dispatch_ward_size("ward.size.album.shrink-20pct", 10.0)
        marker_path = cc._RECENT_RECRUITMENT
        data = json.loads(marker_path.read_text())
        assert "ward.size" in data["families"]

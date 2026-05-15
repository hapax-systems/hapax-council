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
    monkeypatch.setattr(cc, "_SEGMENT_CUE_HOLD", tmp_path / "segment-cue-hold.json")
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

    def test_unknown_modifier_returns_false_and_does_not_write(self):
        # Unknown modifiers must not silently clobber a prior valid override.
        assert not cc.dispatch_ward_size("ward.size.album.fast-zoom", 10.0)
        # No specific entry written
        assert wp.get_specific_ward_properties("album") is None

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
        # Phase B2: the aggressive modifiers (glow/pulse/flash/foreground)
        # now share the B1 in-your-face envelope (glow=14, pulse=2,
        # bump=0.06, alpha=1.0). Updated from the prior 12.0 value per
        # homage-completion-plan §2.
        assert cc.dispatch_ward_highlight("ward.highlight.album.glow", 10.0)
        wp.clear_ward_properties_cache()
        assert wp.resolve_ward_properties("album").glow_radius_px == 14.0


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


class TestAuditRegression:
    """Regression tests for bugs surfaced in the 2026-04-18 PR review."""

    def test_unknown_modifier_does_not_clobber_existing_override(self):
        # Bug #3: a typo'd modifier should NOT wipe a prior valid override.
        cc.dispatch_ward_size("ward.size.album.shrink-20pct", 30.0)
        wp.clear_ward_properties_cache()
        assert wp.resolve_ward_properties("album").scale == pytest.approx(0.80)
        # Now dispatch with a typo modifier
        result = cc.dispatch_ward_size("ward.size.album.typo-modifier", 30.0)
        assert result is False
        wp.clear_ward_properties_cache()
        # Album scale must STILL be 0.80, not reset to 1.0
        assert wp.resolve_ward_properties("album").scale == pytest.approx(0.80)

    def test_unknown_cadence_modifier_no_clobber(self):
        cc.dispatch_ward_cadence("ward.cadence.thinking_indicator.pulse-2hz", 30.0)
        wp.clear_ward_properties_cache()
        assert wp.resolve_ward_properties("thinking_indicator").rate_hz_override == 2.0
        result = cc.dispatch_ward_cadence("ward.cadence.thinking_indicator.invalid", 30.0)
        assert result is False
        wp.clear_ward_properties_cache()
        assert wp.resolve_ward_properties("thinking_indicator").rate_hz_override == 2.0

    def test_unknown_appearance_modifier_no_clobber(self):
        cc.dispatch_ward_appearance("ward.appearance.album.tint-warm", 30.0)
        wp.clear_ward_properties_cache()
        assert wp.resolve_ward_properties("album").color_override_rgba is not None
        result = cc.dispatch_ward_appearance("ward.appearance.album.invalid", 30.0)
        assert result is False
        wp.clear_ward_properties_cache()
        # Color override should STILL be the warm tint
        assert wp.resolve_ward_properties("album").color_override_rgba is not None

    def test_dispatch_does_not_absorb_all_fallback(self):
        # Bug #1: dispatching against a ward with no specific entry while
        # an "all" fallback exists should NOT bake the fallback's values
        # into the new specific entry.
        wp.set_ward_properties("all", wp.WardProperties(alpha=0.5), ttl_s=30.0)
        wp.clear_ward_properties_cache()
        # Dispatch ward.size.album.shrink-20pct
        cc.dispatch_ward_size("ward.size.album.shrink-20pct", 30.0)
        wp.clear_ward_properties_cache()
        # The album entry should have scale=0.8 AND alpha=1.0 (default),
        # NOT alpha=0.5 absorbed from the fallback. Otherwise, when the
        # all-fallback expires, album would still be dimmed.
        specific = wp.get_specific_ward_properties("album")
        assert specific is not None
        assert specific.scale == pytest.approx(0.80)
        assert specific.alpha == 1.0  # default, not the 0.5 fallback

    def test_consecutive_dispatches_within_cache_window_preserve_all_fields(self):
        # Bug #2: a second dispatch within the 200ms cache window must
        # see the first dispatch's write, not a stale cache.
        cc.dispatch_ward_size("ward.size.album.grow-110pct", 30.0)
        # Do NOT manually clear cache here — the production code should
        # invalidate it inside set_ward_properties.
        cc.dispatch_ward_highlight("ward.highlight.album.glow", 30.0)
        wp.clear_ward_properties_cache()
        props = wp.resolve_ward_properties("album")
        # Both fields should be present. Phase B2 bumped the aggressive
        # glow envelope to 14.0.
        assert props.scale == pytest.approx(1.10)
        assert props.glow_radius_px == 14.0

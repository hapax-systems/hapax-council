"""Phase-3 tests for CompositionalConsumer dispatch."""

from __future__ import annotations

import json

import pytest

from agents.studio_compositor import compositional_consumer as cc


@pytest.fixture
def tmp_shm(monkeypatch, tmp_path):
    """Redirect every compositor-read SHM path to tmp_path.

    Also resets module-level dispatcher state (camera role history) so one
    test's dwell/variety gates don't falsely reject the next test's
    dispatch. Without this reset, the catalog-consistency test and the
    ordered camera-hero tests collide on shared module state.
    """
    monkeypatch.setattr(cc, "_HERO_CAMERA_OVERRIDE", tmp_path / "hero-camera-override.json")
    monkeypatch.setattr(cc, "_OVERLAY_ALPHA_OVERRIDES", tmp_path / "overlay-alpha-overrides.json")
    monkeypatch.setattr(cc, "_RECENT_RECRUITMENT", tmp_path / "recent-recruitment.json")
    monkeypatch.setattr(cc, "_YOUTUBE_DIRECTION", tmp_path / "youtube-direction.json")
    monkeypatch.setattr(cc, "_STREAM_MODE_INTENT", tmp_path / "stream-mode-intent.json")
    monkeypatch.setattr(cc, "_CAMERA_ROLE_HISTORY", [])
    return tmp_path


class TestCameraHero:
    def test_overhead_maps_to_c920_overhead(self, tmp_shm):
        assert cc.dispatch_camera_hero("cam.hero.overhead.vinyl-spinning", 30.0)
        data = json.loads((tmp_shm / "hero-camera-override.json").read_text())
        assert data["camera_role"] == "c920-overhead"
        assert data["ttl_s"] == 30.0
        assert data["source_capability"] == "cam.hero.overhead.vinyl-spinning"

    def test_unknown_role_slug_fails_cleanly(self, tmp_shm):
        assert not cc.dispatch_camera_hero("cam.hero.nonexistent.ctx", 10.0)
        assert not (tmp_shm / "hero-camera-override.json").exists()

    def test_malformed_name_fails_cleanly(self, tmp_shm):
        assert not cc.dispatch_camera_hero("cam.hero", 10.0)
        assert not (tmp_shm / "hero-camera-override.json").exists()


class TestPresetBias:
    def test_family_recorded_in_recruitment_file(self, tmp_shm):
        assert cc.dispatch_preset_bias("fx.family.audio-reactive", 60.0)
        data = json.loads((tmp_shm / "recent-recruitment.json").read_text())
        preset = data["families"]["preset.bias"]
        assert preset["family"] == "audio-reactive"
        assert preset["ttl_s"] == 60.0
        assert "last_recruited_ts" in preset

    def test_malformed_fails(self, tmp_shm):
        assert not cc.dispatch_preset_bias("fx.bad", 10.0)


class TestOverlayEmphasis:
    def test_foreground_sets_alpha_1(self, tmp_shm):
        assert cc.dispatch_overlay_emphasis("overlay.foreground.album", 20.0)
        data = json.loads((tmp_shm / "overlay-alpha-overrides.json").read_text())
        assert data["overrides"]["album"]["alpha"] == 1.0
        assert data["overrides"]["album"]["source_capability"] == "overlay.foreground.album"

    def test_dim_sets_alpha_0_3(self, tmp_shm):
        assert cc.dispatch_overlay_emphasis("overlay.dim.all-chrome", 10.0)
        data = json.loads((tmp_shm / "overlay-alpha-overrides.json").read_text())
        assert data["overrides"]["all-chrome"]["alpha"] == 0.3

    def test_multiple_overrides_merge(self, tmp_shm):
        cc.dispatch_overlay_emphasis("overlay.foreground.album", 20.0)
        cc.dispatch_overlay_emphasis("overlay.foreground.captions", 20.0)
        data = json.loads((tmp_shm / "overlay-alpha-overrides.json").read_text())
        assert set(data["overrides"].keys()) == {"album", "captions"}

    def test_unknown_action(self, tmp_shm):
        assert not cc.dispatch_overlay_emphasis("overlay.flicker.album", 10.0)


class TestYoutubeDirection:
    def test_cut_to_writes_action(self, tmp_shm):
        assert cc.dispatch_youtube_direction("youtube.cut-to", 15.0)
        data = json.loads((tmp_shm / "youtube-direction.json").read_text())
        assert data["action"] == "cut-to"
        assert data["ttl_s"] == 15.0

    def test_advance_queue_writes_action(self, tmp_shm):
        assert cc.dispatch_youtube_direction("youtube.advance-queue", 60.0)
        data = json.loads((tmp_shm / "youtube-direction.json").read_text())
        assert data["action"] == "advance-queue"


class TestAttentionWinner:
    def test_unwired_dispatcher_records_pending(self, tmp_shm):
        # agents.attention_bids.dispatcher.dispatch_recruited_winner is not
        # yet defined in this branch — should log a pending marker without
        # raising.
        cc.dispatch_attention_winner("attention.winner.briefing")
        data = json.loads((tmp_shm / "recent-recruitment.json").read_text())
        assert "attention.winner" in data["families"]


class TestStreamModeTransition:
    def test_public_research_transition_request(self, tmp_shm):
        assert cc.dispatch_stream_mode_transition("stream.mode.public-research.transition")
        data = json.loads((tmp_shm / "stream-mode-intent.json").read_text())
        assert data["target_mode"] == "public-research"


class TestTopLevelDispatch:
    def test_dispatch_routes_each_family(self, tmp_shm):
        for name, expected_family in [
            ("cam.hero.overhead.vinyl-spinning", "camera.hero"),
            ("fx.family.audio-reactive", "preset.bias"),
            ("overlay.foreground.album", "overlay.emphasis"),
            ("youtube.cut-to", "youtube.direction"),
            ("stream.mode.public-research.transition", "stream_mode.transition"),
        ]:
            rec = cc.RecruitmentRecord(name=name)
            assert cc.dispatch(rec) == expected_family

    def test_dispatch_unknown_returns_unknown(self, tmp_shm):
        rec = cc.RecruitmentRecord(name="bogus.family.foo")
        assert cc.dispatch(rec) == "unknown"


class TestRecruitmentHistory:
    def test_age_s_returns_none_when_never_recruited(self, tmp_shm):
        assert cc.recent_recruitment_age_s("preset.bias") is None

    def test_age_s_after_recruitment(self, tmp_shm):
        cc.dispatch_preset_bias("fx.family.audio-reactive", 60.0)
        age = cc.recent_recruitment_age_s("preset.bias")
        assert age is not None
        assert age >= 0


class TestCatalogConsistency:
    def test_every_catalog_capability_has_a_dispatcher(self, tmp_shm, monkeypatch):
        """Every name in COMPOSITIONAL_CAPABILITIES must be routable.

        Resets camera role history before each dispatch so the dwell /
        variety gates (which legitimately reject repeated picks at
        runtime) don't cause false "no dispatcher" assertions when the
        catalog contains many cam.hero.<role>.* entries sharing the
        same role slug.
        """
        from shared.compositional_affordances import COMPOSITIONAL_CAPABILITIES

        for cap in COMPOSITIONAL_CAPABILITIES:
            monkeypatch.setattr(cc, "_CAMERA_ROLE_HISTORY", [])
            rec = cc.RecruitmentRecord(name=cap.name)
            family = cc.dispatch(rec)
            assert family != "unknown", f"no dispatcher for {cap.name}"

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
    monkeypatch.setattr(cc, "_GEM_FRAMES", tmp_path / "hapax-gem" / "gem-frames.json")
    monkeypatch.setattr(cc, "_GEM_RECRUITMENT", tmp_path / "hapax-gem" / "recruitment.json")
    monkeypatch.setattr(
        cc,
        "_GEM_LEGACY_FRAMES",
        tmp_path / "hapax-compositor" / "gem-frames.json",
    )
    monkeypatch.setattr(cc, "_PARAMETRIC_ENVELOPES", tmp_path / "parametric-envelopes.json")
    monkeypatch.setattr(cc, "_SEGMENT_CUE_HOLD", tmp_path / "segment-cue-hold.json")
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


class TestGemDispatch:
    def test_gem_dispatch_writes_recruited_mural_frames(self, tmp_shm):
        assert cc.dispatch_gem(
            "gem.emphasis.event-marker",
            ttl_s=4.0,
            narrative="patch pressure becomes critique",
            score=0.8,
        )

        payload = json.loads((tmp_shm / "hapax-gem" / "gem-frames.json").read_text())
        assert any(
            "patch pressure becomes critique" in frame["text"] for frame in payload["frames"]
        )
        assert all(len(frame["layers"]) >= 2 for frame in payload["frames"])
        assert all(
            len({layer["opacity"] for layer in frame["layers"]}) >= 2 for frame in payload["frames"]
        )
        assert (tmp_shm / "hapax-compositor" / "gem-frames.json").exists()

        recruitment = json.loads((tmp_shm / "hapax-gem" / "recruitment.json").read_text())
        assert recruitment["capability"] == "gem.emphasis.event-marker"
        assert recruitment["score"] == 0.8

    def test_top_level_dispatch_threads_impingement_narrative_to_gem(self, tmp_shm):
        rec = cc.RecruitmentRecord(
            name="gem.spawn.fresh-mural",
            ttl_s=2.0,
            score=0.6,
            impingement_narrative="fresh studio pressure",
        )

        assert cc.dispatch(rec) == "gem"
        payload = json.loads((tmp_shm / "hapax-gem" / "gem-frames.json").read_text())
        assert any("fresh studio pressure" in frame["text"] for frame in payload["frames"])


class TestTopLevelDispatch:
    def test_dispatch_routes_each_family(self, tmp_shm):
        for name, expected_family in [
            ("cam.hero.overhead.vinyl-spinning", "camera.hero"),
            ("fx.family.audio-reactive", "preset.bias"),
            ("overlay.foreground.album", "overlay.emphasis"),
            ("youtube.cut-to", "youtube.direction"),
            ("stream.mode.public-research.transition", "stream_mode.transition"),
            ("gem.emphasis.event-marker", "gem"),
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
            rec = cc.RecruitmentRecord(name=cap.name)
            family = cc.dispatch(rec)
            assert family != "unknown", f"no dispatcher for {cap.name}"


class TestStructuralIntentAggressiveEmphasis:
    """Phase B1 (homage-completion-plan §2 / reckoning §3.4): emphasis
    dispatches must write the aggressive "in-your-face" envelope
    (glow_radius_px=14, border_pulse_hz=2.0, scale_bump_pct=0.06) with
    a salience-scaled TTL.

    Pins the operator directive that pre-B1 emphasis values were
    near-no-ops once multiplied by salience. The fix: fixed envelope,
    salience drives TTL instead. Border pulses in the active HOMAGE
    package's per-domain accent colour.
    """

    @pytest.fixture
    def wired(self, monkeypatch, tmp_path):
        """Redirect the ward-properties writer + the narrative-structural
        -intent.json write target into tmp_path; leave the HOMAGE package
        registry alone so :func:`domain_accent_rgba` falls back to the
        BitchX default package (always registered as the consent-safe
        baseline)."""
        import agents.studio_compositor.ward_properties as wp

        monkeypatch.setattr(wp, "WARD_PROPERTIES_PATH", tmp_path / "ward-properties.json")
        monkeypatch.setattr(cc, "_SEGMENT_CUE_HOLD", tmp_path / "segment-cue-hold.json")
        wp.clear_ward_properties_cache()

        original_atomic = cc._atomic_write_json

        def _capture_write(target, payload):
            if str(target).endswith("narrative-structural-intent.json"):
                p = tmp_path / "narrative-structural-intent.json"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps(payload), encoding="utf-8")
                return
            original_atomic(target, payload)

        monkeypatch.setattr(cc, "_atomic_write_json", _capture_write)
        return tmp_path

    def _read_ward(self, tmp_path, ward_id):
        import agents.studio_compositor.ward_properties as wp

        wp.clear_ward_properties_cache()
        return wp.get_specific_ward_properties(ward_id)

    def test_emphasis_produces_aggressive_glow_radius(self, wired):
        """``glow_radius_px >= 12.0`` is the legibility floor per the
        success criterion in homage-completion-plan §B1."""
        from shared.director_intent import NarrativeStructuralIntent

        si = NarrativeStructuralIntent(ward_emphasis=["album_overlay"])
        tally = cc.dispatch_structural_intent(si)
        assert tally["emphasized"] == 1

        props = self._read_ward(wired, "album_overlay")
        assert props is not None
        assert props.glow_radius_px >= 12.0

    def test_emphasis_sets_full_b1_envelope(self, wired):
        """Border pulse at 2.0 Hz, scale bump > 0.04, alpha = 1.0 — the
        full "in-your-face" envelope mandated by the plan."""
        from shared.director_intent import NarrativeStructuralIntent

        si = NarrativeStructuralIntent(ward_emphasis=["album_overlay"])
        cc.dispatch_structural_intent(si)

        props = self._read_ward(wired, "album_overlay")
        assert props is not None
        assert props.border_pulse_hz == pytest.approx(2.0)
        assert props.scale_bump_pct > 0.04
        assert props.alpha == pytest.approx(1.0)

    def test_emphasis_ttl_scales_with_full_salience(self, wired):
        """salience=1.0 → ttl_s ≥ 5.0 (five narrative-director ticks at
        default 1s cadence). Read back via the raw JSON file since TTL
        is not surfaced on ``WardProperties`` — it lives in the JSON
        ``expires_at`` field alongside the dataclass view."""
        import time as _time

        from shared.director_intent import NarrativeStructuralIntent

        before_write = _time.time()
        si = NarrativeStructuralIntent(ward_emphasis=["album_overlay"])
        cc.dispatch_structural_intent(si)

        raw = json.loads((wired / "ward-properties.json").read_text())
        expires_at = raw["wards"]["album_overlay"]["expires_at"]
        ttl_s = expires_at - before_write
        assert ttl_s >= 5.0, f"expected ttl_s >= 5.0 at salience=1.0, got {ttl_s:.3f}"

    def test_emphasis_ttl_floor_for_low_salience(self, wired):
        """Low-salience emphasis must still persist long enough to be
        visibly perceived (ttl floor 1.5s). Direct ``_apply_emphasis``
        call since :func:`dispatch_structural_intent` always uses
        salience=1.0 today — the floor is a helper-level invariant."""
        import time as _time

        before_write = _time.time()
        cc._apply_emphasis("album_overlay", salience=0.1)

        raw = json.loads((wired / "ward-properties.json").read_text())
        expires_at = raw["wards"]["album_overlay"]["expires_at"]
        ttl_s = expires_at - before_write
        # Floor is 1.5s; salience=0.1 would otherwise yield 0.5s and
        # leave the ward flicker below perception.
        assert ttl_s >= 1.5, f"expected ttl floor >= 1.5s, got {ttl_s:.3f}"

    def test_emphasis_writes_domain_accent_border(self, wired):
        """``border_color_rgba`` is resolved through the active HOMAGE
        package's per-domain accent role so the emphasis pulses in the
        ward's identity colour rather than pure white."""
        from shared.director_intent import NarrativeStructuralIntent

        si = NarrativeStructuralIntent(ward_emphasis=["album_overlay"])
        cc.dispatch_structural_intent(si)

        props = self._read_ward(wired, "album_overlay")
        assert props is not None
        # Not the default (1, 1, 1, 1) — must have been rewritten by
        # domain_accent_rgba, even if the BitchX fallback values differ
        # from the default white the dataclass initializer uses.
        assert props.border_color_rgba != (1.0, 1.0, 1.0, 1.0)
        # All four channels are well-formed floats in [0, 1].
        for channel in props.border_color_rgba:
            assert 0.0 <= channel <= 1.0

    def test_multiple_wards_all_land_aggressive(self, wired):
        """All wards nominated in ward_emphasis must land on the full
        envelope — the live-session success criterion is ``>= 4`` wards
        with glow_radius_px >= 12.0 in ward-properties.json."""
        from shared.director_intent import NarrativeStructuralIntent

        si = NarrativeStructuralIntent(
            ward_emphasis=[
                "album_overlay",
                "sierpinski",
                "pressure_gauge",
                "stream_overlay",
            ],
        )
        tally = cc.dispatch_structural_intent(si)
        assert tally["emphasized"] == 4

        import agents.studio_compositor.ward_properties as wp

        wp.clear_ward_properties_cache()
        for ward_id in (
            "album_overlay",
            "sierpinski",
            "pressure_gauge",
            "stream_overlay",
        ):
            props = wp.get_specific_ward_properties(ward_id)
            assert props is not None, f"{ward_id} missing"
            assert props.glow_radius_px >= 12.0, (
                f"{ward_id} glow below legibility floor: {props.glow_radius_px}"
            )

    def test_placement_foreground_zeroes_offsets(self, wired):
        """``placement_bias = {ward: "foreground"}`` → alpha=1.0 +
        position offsets zero, no positional shift."""
        from shared.director_intent import NarrativeStructuralIntent

        si = NarrativeStructuralIntent(
            placement_bias={"album_overlay": "foreground"},
        )
        cc.dispatch_structural_intent(si)

        props = self._read_ward(wired, "album_overlay")
        assert props is not None
        assert props.alpha == pytest.approx(1.0)
        assert props.position_offset_x == pytest.approx(0.0)
        assert props.position_offset_y == pytest.approx(0.0)

    def test_placement_left_edge_shifts_x(self, wired):
        """``"left-edge"`` → position_offset_x=-50."""
        from shared.director_intent import NarrativeStructuralIntent

        si = NarrativeStructuralIntent(
            placement_bias={"album_overlay": "left-edge"},
        )
        cc.dispatch_structural_intent(si)

        props = self._read_ward(wired, "album_overlay")
        assert props is not None
        assert props.position_offset_x == pytest.approx(-50.0)

    def test_placement_recede_dims_alpha(self, wired):
        """``"recede"`` → alpha=0.55 (legible but subordinate)."""
        from shared.director_intent import NarrativeStructuralIntent

        si = NarrativeStructuralIntent(
            placement_bias={"album_overlay": "recede"},
        )
        cc.dispatch_structural_intent(si)

        props = self._read_ward(wired, "album_overlay")
        assert props is not None
        assert props.alpha == pytest.approx(0.55)


class TestDomainAccentRgba:
    """Pin the new :func:`domain_accent_rgba` helper's fail-open
    behaviour and resolution path."""

    def test_returns_tuple_of_four_floats(self):
        rgba = cc.domain_accent_rgba("album_overlay")
        assert isinstance(rgba, tuple)
        assert len(rgba) == 4
        for channel in rgba:
            assert isinstance(channel, (int, float))
            assert 0.0 <= channel <= 1.0

    def test_unknown_ward_id_returns_safe_default(self):
        """Unknown ward_id falls through domain_for_ward to "perception"
        and then to the package's ``accent_green`` role. Must not raise."""
        rgba = cc.domain_accent_rgba("nonexistent_ward_id_xyz")
        assert isinstance(rgba, tuple)
        assert len(rgba) == 4


class TestB2IntentFamilyRoutingAggressiveEnvelope:
    """Phase B2 (homage-completion-plan §2): ``ward.highlight.<id>.*`` and
    ``overlay.foreground.<target>`` recruitments must land the B1
    aggressive envelope on the ward-properties file, not the prior mild
    modifier-table values. This closes the second half of reckoning §3.4
    ("the wire was present; signal was silent").

    The invariant the live livestream cares about: at steady state, more
    than just HARDM + album should carry glow_radius_px >= 12 over a
    60s window of rotating dispatches — i.e. the surface must visibly
    shift rather than staying pinned to the two wards that were
    previously hard-wired via the legacy ward_fx coupling path.
    """

    @pytest.fixture
    def wired(self, monkeypatch, tmp_path):
        """Redirect ward-properties + overlay-alpha SHM writes to tmp_path.

        Leaves the HOMAGE package registry alone so
        :func:`domain_accent_rgba` falls back to BitchX's default
        accents (always registered). Also resets the camera-hero
        history so unrelated tests can't cross-contaminate the
        dispatcher's module-level state.
        """
        import agents.studio_compositor.ward_properties as wp

        monkeypatch.setattr(wp, "WARD_PROPERTIES_PATH", tmp_path / "ward-properties.json")
        wp.clear_ward_properties_cache()

        monkeypatch.setattr(cc, "_HERO_CAMERA_OVERRIDE", tmp_path / "hero-camera-override.json")
        monkeypatch.setattr(
            cc, "_OVERLAY_ALPHA_OVERRIDES", tmp_path / "overlay-alpha-overrides.json"
        )
        monkeypatch.setattr(cc, "_RECENT_RECRUITMENT", tmp_path / "recent-recruitment.json")
        monkeypatch.setattr(cc, "_SEGMENT_CUE_HOLD", tmp_path / "segment-cue-hold.json")
        return tmp_path

    def _read_ward(self, tmp_path, ward_id):
        import agents.studio_compositor.ward_properties as wp

        wp.clear_ward_properties_cache()
        return wp.get_specific_ward_properties(ward_id)

    def test_ward_highlight_pulse_lands_aggressive_envelope(self, wired):
        """``ward.highlight.album_overlay.pulse`` → glow=14, pulse_hz=2,
        bump=0.06, alpha=1.0. Matches the B1 aggressive envelope."""
        ok = cc.dispatch_ward_highlight(
            "ward.highlight.album_overlay.pulse", ttl_s=2.0, salience=1.0
        )
        assert ok
        props = self._read_ward(wired, "album_overlay")
        assert props is not None
        assert props.glow_radius_px == pytest.approx(14.0)
        assert props.border_pulse_hz == pytest.approx(2.0)
        assert props.scale_bump_pct == pytest.approx(0.06)
        assert props.alpha == pytest.approx(1.0)

    def test_ward_highlight_glow_lands_aggressive_envelope(self, wired):
        """``ward.highlight.<id>.glow`` used to emit only glow=12 — now
        it lands the full in-your-face envelope like the other
        aggressive modifiers."""
        ok = cc.dispatch_ward_highlight("ward.highlight.captions.glow", ttl_s=2.0, salience=1.0)
        assert ok
        props = self._read_ward(wired, "captions")
        assert props is not None
        assert props.glow_radius_px == pytest.approx(14.0)
        assert props.border_pulse_hz == pytest.approx(2.0)

    def test_ward_highlight_foreground_gets_domain_accent(self, wired):
        """Aggressive modifiers (``foreground`` here) paint the border in
        the ward's domain-accent colour rather than the default white."""
        cc.dispatch_ward_highlight(
            "ward.highlight.album_overlay.foreground", ttl_s=2.0, salience=1.0
        )
        props = self._read_ward(wired, "album_overlay")
        assert props is not None
        assert props.border_color_rgba != (1.0, 1.0, 1.0, 1.0)

    def test_ward_highlight_dim_preserves_mild_semantics(self, wired):
        """``dim`` means "recede, not emphasize". Its envelope must NOT
        be tightened to the aggressive values — otherwise the operator's
        explicit dim intent gets silently inverted."""
        ok = cc.dispatch_ward_highlight("ward.highlight.captions.dim", ttl_s=2.0, salience=1.0)
        assert ok
        props = self._read_ward(wired, "captions")
        assert props is not None
        assert props.alpha == pytest.approx(0.35)
        # Dim explicitly does NOT pulse — pulse_hz stays at the default.
        assert props.border_pulse_hz != pytest.approx(2.0)

    def test_ward_highlight_salience_drives_ttl_floor(self, wired):
        """salience=0.1 should still produce a TTL >= 1.5s (the floor
        from B1's ``_apply_emphasis``). Below this threshold the ward
        flickers faster than the reader's fovea can fixate on it."""
        import time as _time

        before = _time.time()
        cc.dispatch_ward_highlight("ward.highlight.album_overlay.pulse", ttl_s=0.5, salience=0.1)
        raw = json.loads((wired / "ward-properties.json").read_text())
        expires_at = raw["wards"]["album_overlay"]["expires_at"]
        assert expires_at - before >= 1.5

    def test_ward_highlight_full_salience_gets_five_second_ttl(self, wired):
        """salience=1.0 → ttl_s >= 5.0 (five narrative-director ticks
        at the default 1s cadence — "deeply felt" per the operator
        directive in the plan)."""
        import time as _time

        before = _time.time()
        cc.dispatch_ward_highlight("ward.highlight.album_overlay.pulse", ttl_s=0.5, salience=1.0)
        raw = json.loads((wired / "ward-properties.json").read_text())
        expires_at = raw["wards"]["album_overlay"]["expires_at"]
        assert expires_at - before >= 5.0

    def test_overlay_foreground_writes_ward_properties_on_known_target(self, wired):
        """``overlay.foreground.album`` recruitments should *also* fire
        the aggressive ward-properties envelope on the ``album_overlay``
        ward (not just the legacy alpha-overrides file) so the
        compositor's ward-property consumers visibly react."""
        ok = cc.dispatch_overlay_emphasis("overlay.foreground.album", ttl_s=2.0, salience=1.0)
        assert ok
        props = self._read_ward(wired, "album_overlay")
        assert props is not None
        assert props.glow_radius_px == pytest.approx(14.0)
        assert props.border_pulse_hz == pytest.approx(2.0)

    def test_overlay_foreground_preserves_legacy_alpha_overrides_write(self, wired):
        """The ward-properties write is *additive*; the alpha-overrides
        SHM file must still carry the same entry so the legacy layout
        mutator is not silently starved."""
        cc.dispatch_overlay_emphasis("overlay.foreground.album", ttl_s=2.0)
        data = json.loads((wired / "overlay-alpha-overrides.json").read_text())
        assert data["overrides"]["album"]["alpha"] == 1.0
        assert data["overrides"]["album"]["source_capability"] == "overlay.foreground.album"

    def test_overlay_dim_skips_aggressive_envelope(self, wired):
        """``overlay.dim.*`` means "recede". Must NOT fire the aggressive
        ward-properties envelope — otherwise a dim directive would
        visibly invert into a pulse."""
        cc.dispatch_overlay_emphasis("overlay.dim.all-chrome", ttl_s=2.0, salience=1.0)
        # "all-chrome" is not a ward_id — no ward entry should exist at all.
        raw_path = wired / "ward-properties.json"
        if raw_path.exists():
            raw = json.loads(raw_path.read_text())
            assert "all-chrome" not in (raw.get("wards") or {})

    def test_overlay_foreground_unknown_target_only_writes_legacy(self, wired):
        """Unknown overlay targets (e.g. ``all-chrome``) must not write
        a bogus ward-properties entry — the alpha-overrides file is the
        only legitimate sink for broad/unmapped overlay names."""
        cc.dispatch_overlay_emphasis("overlay.foreground.all-chrome", ttl_s=2.0)
        raw_path = wired / "ward-properties.json"
        if raw_path.exists():
            raw = json.loads(raw_path.read_text())
            assert "all-chrome" not in (raw.get("wards") or {})

    def test_top_level_dispatch_passes_salience_to_ward_highlight(self, wired):
        """Integration: :func:`dispatch` must thread ``RecruitmentRecord.score``
        into the aggressive-envelope TTL computation so a low-score
        recruitment doesn't get artificially stretched to 5s."""
        import time as _time

        before = _time.time()
        rec = cc.RecruitmentRecord(name="ward.highlight.album_overlay.pulse", score=0.5, ttl_s=0.5)
        family = cc.dispatch(rec)
        assert family == "ward.highlight"
        raw = json.loads((wired / "ward-properties.json").read_text())
        expires_at = raw["wards"]["album_overlay"]["expires_at"]
        ttl_s = expires_at - before
        # salience=0.5 → ttl_s = max(1.5, 0.5 * 5.0) = 2.5
        assert 2.0 <= ttl_s <= 3.5, f"expected ~2.5s at salience=0.5, got {ttl_s:.3f}"

    def test_multi_ward_rotation_not_stuck_on_single_ward(self, wired):
        """60s-simulated rotation: recruit ward.highlight.<id>.pulse for
        four wards in sequence and verify each one lands the aggressive
        envelope. Closes the plan's "rotate across wards, don't stick"
        invariant (originally phrased as "not stuck on HARDM + album";
        HARDM retired 2026-04-23).
        """
        import agents.studio_compositor.ward_properties as wp

        rotation = [
            "ward.highlight.sierpinski.pulse",
            "ward.highlight.stream_overlay.glow",
            "ward.highlight.captions.flash",
            "ward.highlight.album_overlay.foreground",
        ]
        for cap in rotation:
            rec = cc.RecruitmentRecord(name=cap, score=1.0, ttl_s=1.0)
            assert cc.dispatch(rec) == "ward.highlight"

        # Every rotated ward must now carry a glow_radius_px above the
        # legibility floor (>= 12) — the plan's explicit success
        # criterion.
        wp.clear_ward_properties_cache()
        for ward_id in ("sierpinski", "stream_overlay", "captions", "album_overlay"):
            props = wp.get_specific_ward_properties(ward_id)
            assert props is not None, f"{ward_id} missing after rotation"
            assert props.glow_radius_px >= 12.0, (
                f"{ward_id} glow below legibility floor: {props.glow_radius_px}"
            )
        # Sanity: we rotated through 4 distinct wards; at least 3
        # non-album wards carry aggressive-envelope properties
        # (sierpinski + stream_overlay + captions = 3).
        non_album_rotated = [
            w
            for w in ("sierpinski", "stream_overlay", "captions")
            if wp.get_specific_ward_properties(w) is not None
        ]
        assert len(non_album_rotated) >= 3

    def test_catalog_overlay_foregrounds_land_ward_properties(self, wired):
        """Every overlay.foreground.<target> in the capability catalog
        whose target maps to a known ward_id must land a ward-properties
        entry. Pins the mapping table against silent catalog drift."""
        import agents.studio_compositor.ward_properties as wp
        from shared.compositional_affordances import COMPOSITIONAL_CAPABILITIES

        expected = []
        for cap in COMPOSITIONAL_CAPABILITIES:
            if not cap.name.startswith("overlay.foreground."):
                continue
            target = cap.name.split(".", 2)[2]
            ward_id = cc._OVERLAY_TARGET_TO_WARD_ID.get(target)
            if ward_id is None:
                continue
            expected.append((cap.name, ward_id))
            rec = cc.RecruitmentRecord(name=cap.name, score=1.0, ttl_s=1.0)
            assert cc.dispatch(rec) == "overlay.emphasis"

        assert expected, "catalog drift: no overlay.foreground.* with a mapped ward_id"
        wp.clear_ward_properties_cache()
        for _, ward_id in expected:
            props = wp.get_specific_ward_properties(ward_id)
            assert props is not None, f"{ward_id} missing after overlay.foreground dispatch"
            assert props.glow_radius_px == pytest.approx(14.0)

"""BitchX package authenticity pins.

Every element in HOMAGE spec §5.1-§5.3 that is load-bearing for BitchX
authenticity is pinned here. Decorative elements (specific quit-quip
content, specific MOTD text) are NOT pinned — those are expected to
evolve.
"""

from __future__ import annotations

import pytest

from agents.studio_compositor.homage import (
    BITCHX_PACKAGE,
    get_active_package,
    get_package,
    registered_package_names,
)
from shared.voice_register import VoiceRegister


class TestGrammarLoadBearing:
    """Spec §5.1."""

    def test_grey_punctuation_skeleton(self):
        assert BITCHX_PACKAGE.grammar.punctuation_colour_role == "muted"

    def test_bright_identity_colouring(self):
        assert BITCHX_PACKAGE.grammar.identity_colour_role == "bright"

    def test_angle_bracket_container(self):
        assert BITCHX_PACKAGE.grammar.container_shape == "angle-bracket"

    def test_cp437_raster_required(self):
        assert BITCHX_PACKAGE.grammar.raster_cell_required is True

    def test_three_chevron_line_start_marker(self):
        assert BITCHX_PACKAGE.grammar.line_start_marker == "»»»"

    def test_zero_frame_transitions(self):
        assert BITCHX_PACKAGE.grammar.transition_frame_count == 0

    def test_event_rhythm_as_texture(self):
        assert BITCHX_PACKAGE.grammar.event_rhythm_as_texture is True

    def test_signed_artefacts_required(self):
        assert BITCHX_PACKAGE.grammar.signed_artefacts_required is True


class TestTypographyLoadBearing:
    """Spec §5.2."""

    def test_primary_font_is_cp437_capable(self):
        # Px437 IBM VGA 8x16 is the canonical CP437 raster font.
        assert "Px437" in BITCHX_PACKAGE.typography.primary_font_family

    def test_monospaced_enforced(self):
        assert BITCHX_PACKAGE.typography.monospaced is True

    def test_discrete_size_classes(self):
        """All four discrete classes present (spec §4.3)."""
        classes = BITCHX_PACKAGE.typography.size_classes
        assert set(classes.keys()) == {"compact", "normal", "large", "banner"}
        # Ascending sizes.
        assert classes["compact"] < classes["normal"] < classes["large"] < classes["banner"]

    def test_single_weight(self):
        assert BITCHX_PACKAGE.typography.weight == "single"


class TestPaletteMIRCContract:
    """Spec §5.3: mIRC-16 colour role assignments."""

    def test_muted_is_grey(self):
        r, g, b, _ = BITCHX_PACKAGE.palette.muted
        assert r == g == b
        assert 0.3 < r < 0.5

    def test_bright_is_near_white(self):
        r, g, b, _ = BITCHX_PACKAGE.palette.bright
        assert r > 0.85 and g > 0.85 and b > 0.85

    def test_accent_cyan_matches_mirc_11(self):
        # mIRC 11 is bright cyan.
        _, g, b, _ = BITCHX_PACKAGE.palette.accent_cyan
        assert g > 0.5 and b > 0.5

    def test_accent_magenta_matches_mirc_6(self):
        r, g, b, _ = BITCHX_PACKAGE.palette.accent_magenta
        assert r > 0.5 and g < 0.2 and b > 0.5


class TestTransitionVocab:
    def test_supports_all_nine_named_transitions(self):
        """Spec §4.5 load-bearing transition vocabulary."""
        required = {
            "zero-cut-in",
            "zero-cut-out",
            "join-message",
            "part-message",
            "topic-change",
            "netsplit-burst",
            "mode-change",
            "ticker-scroll-in",
            "ticker-scroll-out",
        }
        assert required.issubset(BITCHX_PACKAGE.transition_vocabulary.supported)

    def test_default_entry_exit_are_ticker_scroll(self):
        assert BITCHX_PACKAGE.transition_vocabulary.default_entry == "ticker-scroll-in"
        assert BITCHX_PACKAGE.transition_vocabulary.default_exit == "ticker-scroll-out"


class TestCouplingRulesShaderSlot:
    def test_custom_slot_index_is_4(self):
        """Spec §4.6 reserves uniforms.custom[4] for HOMAGE."""
        assert BITCHX_PACKAGE.coupling_rules.custom_slot_index == 4

    def test_payload_channels_ordered(self):
        assert BITCHX_PACKAGE.coupling_rules.payload_channels == (
            "active_transition_energy",
            "palette_accent_hue_deg",
            "signature_artefact_intensity",
            "rotation_phase",
        )


class TestSignatureCorpus:
    def test_corpus_contains_all_four_forms(self):
        """Spec §5.4: at least one artefact of each form."""
        forms = {a.form for a in BITCHX_PACKAGE.signature_artefacts}
        assert forms == {"quit-quip", "join-banner", "motd-block", "kick-reason"}

    def test_corpus_carries_author_tags(self):
        for artefact in BITCHX_PACKAGE.signature_artefacts:
            assert artefact.author_tag.startswith("by Hapax")

    def test_generated_content_only_flagged(self):
        assert BITCHX_PACKAGE.signature_conventions.generated_content_only is True

    @pytest.mark.parametrize("form", ["quit-quip", "join-banner", "motd-block", "kick-reason"])
    def test_each_form_has_at_least_one_entry(self, form):
        artefacts = BITCHX_PACKAGE.artefacts_by_form(form)
        assert len(artefacts) >= 1, f"no artefacts of form {form!r}"


class TestVoiceRegisterDefault:
    def test_textmode_register(self):
        assert BITCHX_PACKAGE.voice_register_default == VoiceRegister.TEXTMODE


class TestAntiPatternRefusals:
    """Spec §5.5 — the hard-refuse list."""

    @pytest.mark.parametrize(
        "kind",
        [
            "emoji",
            "anti-aliased",
            "proportional-font",
            "flat-ui-chrome",
            "iso-8601-timestamp",
            "rounded-corners",
            "right-aligned-timestamp",
            "fade-transition",
            "swiss-grid-motd",
            "box-draw-inline-rule",
        ],
    )
    def test_each_anti_pattern_refused(self, kind):
        assert kind in BITCHX_PACKAGE.refuses_anti_patterns


class TestRegistry:
    def test_bitchx_auto_registered(self):
        assert "bitchx" in registered_package_names()
        assert get_package("bitchx") is BITCHX_PACKAGE

    def test_get_active_package_returns_authentic_v1_by_default(self, tmp_path, monkeypatch):
        from agents.studio_compositor import homage
        from agents.studio_compositor.homage.bitchx_authentic import (
            BITCHX_AUTHENTIC_PACKAGE,
        )

        monkeypatch.setattr(homage, "_ACTIVE_FILE", tmp_path / "homage-active.json")
        # No file → default. Post AUTH-HOMAGE flip, default is the
        # library-sourced ``bitchx-authentic-v1`` (session-callable per
        # workstream-realignment v3 §1.4).
        active = homage.get_active_package()
        assert active is BITCHX_AUTHENTIC_PACKAGE

    def test_consent_safe_returns_none(self):
        assert get_active_package(consent_safe=True) is None

    def test_unknown_active_name_falls_back_to_default(self, tmp_path, monkeypatch):
        import json as _json

        from agents.studio_compositor import homage
        from agents.studio_compositor.homage.bitchx_authentic import (
            BITCHX_AUTHENTIC_PACKAGE,
        )

        active_file = tmp_path / "homage-active.json"
        active_file.write_text(_json.dumps({"package": "no-such-package"}), encoding="utf-8")
        monkeypatch.setattr(homage, "_ACTIVE_FILE", active_file)
        active = homage.get_active_package()
        # Post AUTH-HOMAGE flip, default is bitchx-authentic-v1.
        assert active is BITCHX_AUTHENTIC_PACKAGE

    def test_set_active_package_round_trip(self, tmp_path, monkeypatch):
        from agents.studio_compositor import homage

        active_file = tmp_path / "homage-active.json"
        monkeypatch.setattr(homage, "_ACTIVE_FILE", active_file)
        homage.set_active_package("bitchx")
        assert active_file.exists()
        assert homage.get_active_package() is BITCHX_PACKAGE

    def test_set_active_unknown_raises(self, tmp_path, monkeypatch):
        from agents.studio_compositor import homage

        monkeypatch.setattr(homage, "_ACTIVE_FILE", tmp_path / "homage-active.json")
        with pytest.raises(ValueError):
            homage.set_active_package("no-such-package")


class TestVoiceRegisterEnum:
    def test_enum_values(self):
        assert VoiceRegister.ANNOUNCING.value == "announcing"
        assert VoiceRegister.CONVERSING.value == "conversing"
        assert VoiceRegister.TEXTMODE.value == "textmode"

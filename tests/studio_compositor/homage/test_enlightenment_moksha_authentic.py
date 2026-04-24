"""enlightenment-moksha-authentic-v1 HomagePackage pins.

Phase 2 of ytb-AUTH-ENLIGHTENMENT. The authentic variant is built at
import time from the in-repo Moksha EDC placeholder (Phase 1 of
ytb-AUTH-PALETTE, shipped as #1331). EDC-mapped palette roles carry
byte-exact LAB-to-RGB values from the EDC; non-EDC roles fall back to
the inline ``enlightenment_moksha`` values to preserve the Moksha
aesthetic register.

Spec: ytb-AUTH-ENLIGHTENMENT (Phase 2).
"""

from __future__ import annotations

from agents.studio_compositor.homage import (
    ENLIGHTENMENT_MOKSHA_AUTHENTIC_PACKAGE,
    ENLIGHTENMENT_MOKSHA_PACKAGE,
    get_package,
    registered_package_names,
)
from agents.studio_compositor.homage.enlightenment_moksha_authentic import (
    build_enlightenment_moksha_authentic_package,
)
from shared.aesthetic_library_loader import load_default_moksha
from shared.homage_package import HomagePackage
from shared.palette_curve_evaluator import lab_to_rgb
from shared.voice_register import VoiceRegister


class TestPackageShape:
    def test_is_homage_package(self) -> None:
        assert isinstance(ENLIGHTENMENT_MOKSHA_AUTHENTIC_PACKAGE, HomagePackage)

    def test_name_includes_authentic_and_version(self) -> None:
        assert ENLIGHTENMENT_MOKSHA_AUTHENTIC_PACKAGE.name == "enlightenment-moksha-authentic-v1"
        assert ENLIGHTENMENT_MOKSHA_AUTHENTIC_PACKAGE.version == "v1"

    def test_has_asset_library_ref(self) -> None:
        """Authentic variant records its library provenance for traceability."""
        assert (
            ENLIGHTENMENT_MOKSHA_AUTHENTIC_PACKAGE.asset_library_ref
            == "enlightenment-moksha-authentic-v1"
        )

    def test_voice_register_is_textmode(self) -> None:
        assert (
            ENLIGHTENMENT_MOKSHA_AUTHENTIC_PACKAGE.voice_register_default == VoiceRegister.TEXTMODE
        )


class TestGrammarReusedFromInline:
    """Structural rules match the inline package — only the palette
    differs between inline and authentic variants."""

    def test_grammar_shared(self) -> None:
        assert (
            ENLIGHTENMENT_MOKSHA_AUTHENTIC_PACKAGE.grammar is ENLIGHTENMENT_MOKSHA_PACKAGE.grammar
        )

    def test_typography_shared(self) -> None:
        assert (
            ENLIGHTENMENT_MOKSHA_AUTHENTIC_PACKAGE.typography
            is ENLIGHTENMENT_MOKSHA_PACKAGE.typography
        )

    def test_transitions_shared(self) -> None:
        assert (
            ENLIGHTENMENT_MOKSHA_AUTHENTIC_PACKAGE.transition_vocabulary
            is ENLIGHTENMENT_MOKSHA_PACKAGE.transition_vocabulary
        )


class TestPaletteFromLibrary:
    """EDC-mapped roles carry values traceable to the in-repo EDC."""

    def test_all_roles_populated(self) -> None:
        p = ENLIGHTENMENT_MOKSHA_AUTHENTIC_PACKAGE.palette
        for role in (
            "muted",
            "bright",
            "accent_cyan",
            "accent_magenta",
            "accent_green",
            "accent_yellow",
            "accent_red",
            "accent_blue",
            "terminal_default",
            "background",
        ):
            rgba = getattr(p, role)
            assert len(rgba) == 4
            for channel in rgba:
                assert 0.0 <= channel <= 1.0

    def test_background_comes_from_edc_with_alpha(self) -> None:
        """bg_color #252525 → LAB → RGB, alpha 0.88 (matches inline
        composite-with-shader convention)."""
        p = ENLIGHTENMENT_MOKSHA_AUTHENTIC_PACKAGE.palette
        edc = load_default_moksha()
        assert edc is not None
        expected_r, expected_g, expected_b = lab_to_rgb(*edc["bg_color"])
        r, g, b, a = p.background
        assert abs(r - expected_r) < 1e-6
        assert abs(g - expected_g) < 1e-6
        assert abs(b - expected_b) < 1e-6
        assert a == 0.88

    def test_accent_red_from_alert_class(self) -> None:
        """alert_color #cc6060 → accent_red."""
        p = ENLIGHTENMENT_MOKSHA_AUTHENTIC_PACKAGE.palette
        edc = load_default_moksha()
        assert edc is not None
        expected = lab_to_rgb(*edc["alert_color"])
        assert abs(p.accent_red[0] - expected[0]) < 1e-6

    def test_accent_green_from_success_class(self) -> None:
        """success_color #60b860 → accent_green."""
        p = ENLIGHTENMENT_MOKSHA_AUTHENTIC_PACKAGE.palette
        edc = load_default_moksha()
        assert edc is not None
        expected = lab_to_rgb(*edc["success_color"])
        assert abs(p.accent_green[0] - expected[0]) < 1e-6

    def test_fallback_roles_match_inline(self) -> None:
        """accent_magenta / accent_yellow / accent_blue have no EDC class —
        carry inline Moksha values."""
        p = ENLIGHTENMENT_MOKSHA_AUTHENTIC_PACKAGE.palette
        inline = ENLIGHTENMENT_MOKSHA_PACKAGE.palette
        assert p.accent_magenta == inline.accent_magenta
        assert p.accent_yellow == inline.accent_yellow
        assert p.accent_blue == inline.accent_blue

    def test_authentic_differs_from_inline_on_edc_roles(self) -> None:
        """At least one EDC-sourced role should differ from the inline
        Phase 1 approximation — proves routing is live."""
        p = ENLIGHTENMENT_MOKSHA_AUTHENTIC_PACKAGE.palette
        inline = ENLIGHTENMENT_MOKSHA_PACKAGE.palette
        differing = [
            p.muted != inline.muted,
            p.bright != inline.bright,
            p.accent_cyan != inline.accent_cyan,
            p.accent_green != inline.accent_green,
            p.accent_red != inline.accent_red,
            p.terminal_default != inline.terminal_default,
            p.background != inline.background,
        ]
        assert any(differing), (
            "Authentic and inline palettes are identical — library routing is not active"
        )


class TestRegistration:
    def test_registered_by_name(self) -> None:
        assert (
            get_package("enlightenment-moksha-authentic-v1")
            is ENLIGHTENMENT_MOKSHA_AUTHENTIC_PACKAGE
        )

    def test_coexists_with_inline_and_bitchx_family(self) -> None:
        names = registered_package_names()
        assert "enlightenment-moksha-authentic-v1" in names
        assert "enlightenment-moksha-v1" in names
        assert "bitchx" in names
        assert "bitchx-authentic-v1" in names


class TestBuildIsPure:
    def test_build_returns_equivalent_package(self) -> None:
        """Calling the builder a second time yields a package with the same
        palette — pure function, no hidden state."""
        second = build_enlightenment_moksha_authentic_package("v1")
        assert (
            second.palette.background == ENLIGHTENMENT_MOKSHA_AUTHENTIC_PACKAGE.palette.background
        )

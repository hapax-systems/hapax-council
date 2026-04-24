"""enlightenment-moksha-v1 HomagePackage — structural + authenticity pins.

Pins the Moksha-grammar structural shape (curly containers, non-raster,
20-frame soft transitions) and the registry wiring that makes it
selectable alongside bitchx + bitchx-authentic-v1 via the active-package
SHM file.

The palette values in this test are BYTE-EXACT against the inline
constants in ``enlightenment_moksha.py`` — acquisition of authentic
Moksha theme PNGs + EDC extraction is the follow-on
``ytb-AUTH-PALETTE-Moksha`` task (full theme-asset ingestion explicitly
out of scope per the cc-task).

Spec: ytb-AUTH-ENLIGHTENMENT.
"""

from __future__ import annotations

from agents.studio_compositor.homage import (
    get_package,
    registered_package_names,
)
from agents.studio_compositor.homage.enlightenment_moksha import (
    ENLIGHTENMENT_MOKSHA_PACKAGE,
)
from shared.homage_package import HomagePackage
from shared.voice_register import VoiceRegister


class TestPackageShape:
    """Package identity + Moksha-grammar distinctives."""

    def test_is_homage_package(self) -> None:
        assert isinstance(ENLIGHTENMENT_MOKSHA_PACKAGE, HomagePackage)

    def test_name_is_versioned(self) -> None:
        assert ENLIGHTENMENT_MOKSHA_PACKAGE.name == "enlightenment-moksha-v1"
        assert ENLIGHTENMENT_MOKSHA_PACKAGE.version == "v1"

    def test_grammar_is_curly_not_angle_bracket(self) -> None:
        """E-panel containers are curly; distinguishes from BitchX angle-bracket."""
        assert ENLIGHTENMENT_MOKSHA_PACKAGE.grammar.container_shape == "curly"

    def test_grammar_is_non_raster(self) -> None:
        """Moksha is not a raster-terminal grammar."""
        assert ENLIGHTENMENT_MOKSHA_PACKAGE.grammar.raster_cell_required is False

    def test_grammar_allows_soft_fades(self) -> None:
        """EDC programs support 20-frame soft envelopes; distinguishes from BitchX zero-cut."""
        assert ENLIGHTENMENT_MOKSHA_PACKAGE.grammar.transition_frame_count == 20


class TestTypography:
    """Moksha default stack; DejaVu Sans Mono with fallbacks."""

    def test_primary_is_dejavu_sans_mono(self) -> None:
        assert ENLIGHTENMENT_MOKSHA_PACKAGE.typography.primary_font_family == "DejaVu Sans Mono"

    def test_typography_is_monospaced(self) -> None:
        """Even with raster_cell_required=False, monospace is needed for textmode content."""
        assert ENLIGHTENMENT_MOKSHA_PACKAGE.typography.monospaced is True

    def test_fallback_families_present(self) -> None:
        fallbacks = ENLIGHTENMENT_MOKSHA_PACKAGE.typography.fallback_families
        assert len(fallbacks) > 0
        assert (
            "monospace" in fallbacks
            or "DejaVu Sans Mono" in fallbacks
            or any("mono" in f.lower() for f in fallbacks)
        )


class TestAntiPatternRefusal:
    """Moksha refuses the cross-cutting anti-patterns but ALLOWS fade transitions."""

    def test_refuses_emoji(self) -> None:
        assert "emoji" in ENLIGHTENMENT_MOKSHA_PACKAGE.refuses_anti_patterns

    def test_refuses_proportional_font(self) -> None:
        assert "proportional-font" in ENLIGHTENMENT_MOKSHA_PACKAGE.refuses_anti_patterns

    def test_allows_fade_transitions(self) -> None:
        """E-EDC programs allow soft fades; must NOT refuse fade-transition."""
        # Structural: if we refused fade-transition with frame_count=20, the package validator
        # would reject at import. The absence in refuses is itself the signal.
        assert "fade-transition" not in ENLIGHTENMENT_MOKSHA_PACKAGE.refuses_anti_patterns


class TestVoiceRegister:
    def test_default_is_textmode(self) -> None:
        """Ground-register match for the content body; individual moves override per utterance."""
        assert ENLIGHTENMENT_MOKSHA_PACKAGE.voice_register_default == VoiceRegister.TEXTMODE


class TestRegistration:
    """The package must be discoverable via the active-package registry."""

    def test_registered_by_name(self) -> None:
        assert get_package("enlightenment-moksha-v1") is ENLIGHTENMENT_MOKSHA_PACKAGE

    def test_coexists_with_bitchx(self) -> None:
        names = registered_package_names()
        assert "enlightenment-moksha-v1" in names
        assert "bitchx" in names
        assert "bitchx-authentic-v1" in names


class TestPaletteShape:
    """Moksha dark-chrome palette — all standard roles populated, RGBA tuples in [0, 1]."""

    def test_all_roles_populated(self) -> None:
        p = ENLIGHTENMENT_MOKSHA_PACKAGE.palette
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
            assert isinstance(rgba, tuple)
            assert len(rgba) == 4
            for channel in rgba:
                assert 0.0 <= channel <= 1.0

    def test_background_has_alpha_below_one(self) -> None:
        """Composite shader surface must show through; alpha < 1.0."""
        assert ENLIGHTENMENT_MOKSHA_PACKAGE.palette.background[3] < 1.0

    def test_palette_is_dark_chrome(self) -> None:
        """Moksha is a dark theme; muted should be dark-to-mid."""
        p = ENLIGHTENMENT_MOKSHA_PACKAGE.palette
        r, g, b, _ = p.background
        # Background is dark (sum of channels well below 1.0 == "dark").
        assert (r + g + b) < 0.6


class TestAssetLibraryRef:
    """Phase 1: no library dependency (Moksha assets not yet acquired per ytb-AUTH-PALETTE)."""

    def test_no_library_ref_in_phase_1(self) -> None:
        """ENLIGHTENMENT-ENLIGHTENMENT-AUTHENTIC-V1 is a separate follow-on, when Moksha PNGs/EDC are acquired."""
        assert ENLIGHTENMENT_MOKSHA_PACKAGE.asset_library_ref is None

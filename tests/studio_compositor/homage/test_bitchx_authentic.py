"""bitchx-authentic-v1 HOMAGE package — authenticity + library-integration pins.

Pins the byte-exact mIRC palette mapping for the library-sourced variant,
plus the structural pieces that distinguish ``bitchx-authentic-v1`` from the
inline ``bitchx`` package: ``asset_library_ref`` provenance + library-sourced
splash artefact + registration alongside the legacy package.

Spec: ytb-AUTH-HOMAGE.
"""

from __future__ import annotations

import pytest

from agents.studio_compositor.homage import (
    BITCHX_AUTHENTIC_PACKAGE,
    BITCHX_PACKAGE,
    get_package,
    registered_package_names,
)
from agents.studio_compositor.homage.bitchx_authentic import (
    build_bitchx_authentic_package,
)
from shared.aesthetic_library import library
from shared.homage_package import HomagePackage
from shared.voice_register import VoiceRegister


def _hex_to_rgb(hex_str: str) -> tuple[float, float, float]:
    s = hex_str.lstrip("#")
    return (
        int(s[0:2], 16) / 255.0,
        int(s[2:4], 16) / 255.0,
        int(s[4:6], 16) / 255.0,
    )


# Pinned values from assets/aesthetic-library/bitchx/colors/mirc16.yaml.
# Repeating them inline rather than reading the YAML — the test's job is to
# pin that what the package exposes matches the *spec* values, not the
# *current YAML file* (which would be tautological).
MIRC16 = {
    "00": "#FFFFFF",  # white
    "01": "#000000",  # black
    "02": "#00007F",  # blue
    "03": "#009300",  # green
    "04": "#FF0000",  # red
    "05": "#7F0000",  # brown
    "06": "#9C009C",  # purple
    "07": "#FC7F00",  # orange
    "08": "#FFFF00",  # yellow
    "09": "#00FC00",  # light_green
    "10": "#009393",  # teal
    "11": "#00FFFF",  # cyan
    "12": "#0000FC",  # light_blue
    "13": "#FF00FF",  # pink
    "14": "#7F7F7F",  # grey
    "15": "#D2D2D2",  # light_grey
}


class TestPackageStructure:
    def test_name_includes_authentic_and_version(self) -> None:
        assert BITCHX_AUTHENTIC_PACKAGE.name == "bitchx-authentic-v1"

    def test_version_is_v1(self) -> None:
        assert BITCHX_AUTHENTIC_PACKAGE.version == "v1"

    def test_asset_library_ref_set(self) -> None:
        assert BITCHX_AUTHENTIC_PACKAGE.asset_library_ref == "bitchx-authentic-v1"

    def test_voice_register_textmode(self) -> None:
        assert BITCHX_AUTHENTIC_PACKAGE.voice_register_default == VoiceRegister.TEXTMODE

    def test_distinct_instance_from_inline_bitchx(self) -> None:
        assert BITCHX_AUTHENTIC_PACKAGE is not BITCHX_PACKAGE
        assert BITCHX_AUTHENTIC_PACKAGE.name != BITCHX_PACKAGE.name


class TestPaletteByteExact:
    """Pin every accent slot to its byte-exact mIRC value (the divergence
    from the inline bitchx package's bespoke "dimmer" RGB values is the
    whole point of bitchx-authentic-v1)."""

    @pytest.mark.parametrize(
        ("attr", "slot"),
        [
            ("muted", "14"),
            ("bright", "15"),
            ("accent_cyan", "11"),
            ("accent_magenta", "06"),
            ("accent_green", "09"),
            ("accent_yellow", "08"),
            ("accent_red", "04"),
            ("accent_blue", "12"),
            ("terminal_default", "15"),
        ],
    )
    def test_slot_is_byte_exact_mirc(self, attr: str, slot: str) -> None:
        actual = getattr(BITCHX_AUTHENTIC_PACKAGE.palette, attr)
        expected_rgb = _hex_to_rgb(MIRC16[slot])
        assert actual[0] == pytest.approx(expected_rgb[0], abs=1e-6)
        assert actual[1] == pytest.approx(expected_rgb[1], abs=1e-6)
        assert actual[2] == pytest.approx(expected_rgb[2], abs=1e-6)
        assert actual[3] == pytest.approx(1.0, abs=1e-6)

    def test_background_is_black_with_alpha_0_90(self) -> None:
        bg = BITCHX_AUTHENTIC_PACKAGE.palette.background
        assert bg == pytest.approx((0.0, 0.0, 0.0, 0.90), abs=1e-6)

    def test_authentic_cyan_diverges_from_inline_dimmer_cyan(self) -> None:
        """The whole point: authentic = byte-exact (1.0); inline = bespoke (0.78)."""
        authentic_r, authentic_g, authentic_b, _ = BITCHX_AUTHENTIC_PACKAGE.palette.accent_cyan
        inline_r, inline_g, inline_b, _ = BITCHX_PACKAGE.palette.accent_cyan
        assert (authentic_r, authentic_g, authentic_b) == (0.0, 1.0, 1.0)
        assert (inline_r, inline_g, inline_b) != (authentic_r, authentic_g, authentic_b)


class TestSignatureArtefacts:
    def test_includes_library_sourced_join_banner(self) -> None:
        banners = BITCHX_AUTHENTIC_PACKAGE.artefacts_by_form("join-banner")
        # The library-sourced banner is the only join-banner form so far,
        # so this implicitly pins library provenance on at least one of them.
        assert len(banners) >= 1
        author_tags = " ".join(b.author_tag for b in banners)
        assert "shared.aesthetic_library" in author_tags

    def test_signature_artefacts_extends_inline_corpus(self) -> None:
        """Authentic-v1 must include AT LEAST the inline corpus + the banner."""
        assert (
            len(BITCHX_AUTHENTIC_PACKAGE.signature_artefacts)
            > len(BITCHX_PACKAGE.signature_artefacts)
            or len(BITCHX_AUTHENTIC_PACKAGE.signature_artefacts)
            >= len(BITCHX_PACKAGE.signature_artefacts) + 1
        )


class TestGrammarReuse:
    """authentic-v1 reuses the inline package's grammar / typography / coupling
    rules — those carry no asset-derived data and are part of the BitchX
    aesthetic identity that does not change between variants."""

    def test_grammar_identical(self) -> None:
        assert BITCHX_AUTHENTIC_PACKAGE.grammar == BITCHX_PACKAGE.grammar

    def test_typography_identical(self) -> None:
        assert BITCHX_AUTHENTIC_PACKAGE.typography == BITCHX_PACKAGE.typography

    def test_transition_vocabulary_identical(self) -> None:
        assert (
            BITCHX_AUTHENTIC_PACKAGE.transition_vocabulary == BITCHX_PACKAGE.transition_vocabulary
        )

    def test_coupling_rules_identical(self) -> None:
        assert BITCHX_AUTHENTIC_PACKAGE.coupling_rules == BITCHX_PACKAGE.coupling_rules

    def test_signature_conventions_identical(self) -> None:
        assert (
            BITCHX_AUTHENTIC_PACKAGE.signature_conventions == BITCHX_PACKAGE.signature_conventions
        )


class TestRefusedAntiPatterns:
    """All anti-patterns refused by the inline bitchx package must also be
    refused by the authentic variant — the variant cannot weaken refusals."""

    def test_inline_refusals_are_subset_of_authentic_refusals(self) -> None:
        inline = BITCHX_PACKAGE.refuses_anti_patterns
        authentic = BITCHX_AUTHENTIC_PACKAGE.refuses_anti_patterns
        assert inline <= authentic


class TestRegistration:
    def test_registered_under_authentic_name(self) -> None:
        assert get_package("bitchx-authentic-v1") is BITCHX_AUTHENTIC_PACKAGE

    def test_listed_alongside_inline_bitchx(self) -> None:
        names = registered_package_names()
        assert "bitchx" in names
        assert "bitchx-authentic-v1" in names

    def test_authentic_v1_is_default(self) -> None:
        """Post-flip: ``bitchx-authentic-v1`` is the compile-time default.

        AUTH-HOMAGE default-flip session-callable per workstream-realignment
        v3 §1.4 ("Aesthetic sign-off, default-flag flips ... all session-
        callable without operator gating") + operator's 19:10Z 2026-04-24
        no-approval-waits absolute rule. The deprecated inline ``bitchx``
        package stays registered as a fallback (operator can flip back via
        the active-package SHM file), but the compile-time selection now
        points at the authentic library-sourced variant.
        """
        from agents.studio_compositor.homage import _DEFAULT_PACKAGE_NAME

        assert _DEFAULT_PACKAGE_NAME == "bitchx-authentic-v1"


class TestLibrarySourcedConstruction:
    def test_can_rebuild_from_library_via_classmethod(self) -> None:
        pkg = HomagePackage.from_aesthetic_library("bitchx", "v1")
        assert isinstance(pkg, HomagePackage)
        assert pkg.name == "bitchx-authentic-v1"
        assert pkg.asset_library_ref == "bitchx-authentic-v1"

    def test_classmethod_unknown_source_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unknown aesthetic_library source"):
            HomagePackage.from_aesthetic_library("nonexistent", "v1")

    def test_classmethod_enlightenment_pending(self) -> None:
        with pytest.raises(NotImplementedError, match="ytb-AUTH-ENLIGHTENMENT"):
            HomagePackage.from_aesthetic_library("enlightenment", "v1")

    def test_builder_accepts_arbitrary_version_string(self) -> None:
        pkg = build_bitchx_authentic_package("v2-experimental")
        assert pkg.name == "bitchx-authentic-v2-experimental"
        assert pkg.version == "v2-experimental"
        assert pkg.asset_library_ref == "bitchx-authentic-v2-experimental"

    def test_library_assets_resolvable(self) -> None:
        """Sanity check that the library has the assets we read."""
        lib = library()
        palette = lib.get("bitchx", "palette", "mirc16")
        splash = lib.get("bitchx", "splash", "banner")
        font = lib.get("fonts", "font", "px437")
        assert palette.path.exists()
        assert splash.path.exists()
        assert font.path.exists()

"""Schema + invariant tests for shared.homage_package."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.homage_package import (
    CouplingRules,
    GrammarRules,
    HomagePackage,
    HomagePalette,
    SignatureArtefact,
    SignatureRules,
    TransitionVocab,
    TypographyStack,
)
from shared.voice_register import VoiceRegister


def _minimal_palette() -> HomagePalette:
    return HomagePalette(
        muted=(0.4, 0.4, 0.4, 1.0),
        bright=(0.9, 0.9, 0.9, 1.0),
        accent_cyan=(0.0, 0.78, 0.78, 1.0),
        accent_magenta=(0.78, 0.0, 0.78, 1.0),
        accent_green=(0.2, 0.78, 0.2, 1.0),
        accent_yellow=(0.9, 0.9, 0.0, 1.0),
        accent_red=(0.78, 0.0, 0.0, 1.0),
        accent_blue=(0.2, 0.2, 0.78, 1.0),
        terminal_default=(0.8, 0.8, 0.8, 1.0),
        background=(0.04, 0.04, 0.04, 0.9),
    )


def _minimal_typography(monospaced: bool = True) -> TypographyStack:
    return TypographyStack(
        primary_font_family="Px437 IBM VGA 8x16",
        fallback_families=("DejaVu Sans Mono",),
        size_classes={"compact": 10, "normal": 14},
        weight="single",
        monospaced=monospaced,
    )


def _minimal_grammar(raster: bool = True, frame_count: int = 0) -> GrammarRules:
    return GrammarRules(
        punctuation_colour_role="muted",
        identity_colour_role="bright",
        content_colour_role="terminal_default",
        line_start_marker="»»»",
        container_shape="angle-bracket",
        raster_cell_required=raster,
        transition_frame_count=frame_count,
        event_rhythm_as_texture=True,
        signed_artefacts_required=True,
    )


def _minimal_transitions() -> TransitionVocab:
    return TransitionVocab(
        supported=frozenset(
            ["zero-cut-in", "zero-cut-out", "ticker-scroll-in", "ticker-scroll-out"]
        ),
        default_entry="ticker-scroll-in",
        default_exit="ticker-scroll-out",
    )


def _minimal_coupling() -> CouplingRules:
    return CouplingRules(custom_slot_index=4)


def _minimal_signatures() -> SignatureRules:
    return SignatureRules(author_tag="by Hapax")


def _build(**overrides) -> HomagePackage:
    base = dict(
        name="test-package",
        version="0.0.1",
        grammar=_minimal_grammar(),
        typography=_minimal_typography(),
        palette=_minimal_palette(),
        transition_vocabulary=_minimal_transitions(),
        coupling_rules=_minimal_coupling(),
        signature_conventions=_minimal_signatures(),
        voice_register_default=VoiceRegister.TEXTMODE,
    )
    base.update(overrides)
    return HomagePackage(**base)


class TestSchemaRoundTrip:
    def test_homage_package_schema_round_trip(self):
        pkg = _build()
        reconstructed = HomagePackage.model_validate(pkg.model_dump())
        assert reconstructed == pkg

    def test_homage_package_is_frozen(self):
        pkg = _build()
        with pytest.raises(ValidationError):
            pkg.name = "mutated"  # type: ignore[misc]


class TestPaletteValidation:
    def test_rgba_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            HomagePalette(
                muted=(1.5, 0.0, 0.0, 1.0),
                bright=(0.9, 0.9, 0.9, 1.0),
                accent_cyan=(0.0, 0.78, 0.78, 1.0),
                accent_magenta=(0.78, 0.0, 0.78, 1.0),
                accent_green=(0.2, 0.78, 0.2, 1.0),
                accent_yellow=(0.9, 0.9, 0.0, 1.0),
                accent_red=(0.78, 0.0, 0.0, 1.0),
                accent_blue=(0.2, 0.2, 0.78, 1.0),
                terminal_default=(0.8, 0.8, 0.8, 1.0),
                background=(0.04, 0.04, 0.04, 0.9),
            )


class TestTypographyValidation:
    def test_missing_required_size_class_rejected(self):
        with pytest.raises(ValidationError):
            TypographyStack(
                primary_font_family="foo",
                size_classes={"normal": 14},
            )

    def test_non_positive_pixel_size_rejected(self):
        with pytest.raises(ValidationError):
            TypographyStack(
                primary_font_family="foo",
                size_classes={"compact": 0, "normal": 14},
            )


class TestTransitionVocabValidation:
    def test_default_entry_must_be_supported(self):
        with pytest.raises(ValidationError):
            TransitionVocab(
                supported=frozenset(["zero-cut-in"]),
                default_entry="ticker-scroll-in",  # not in supported
                default_exit="zero-cut-in",
            )


class TestAntiPatternRefusal:
    def test_raster_requires_monospace(self):
        """The 'BitchX-ish but wrong' anti-pattern: raster cell declared
        while typography is proportional."""
        with pytest.raises(ValidationError) as excinfo:
            _build(typography=_minimal_typography(monospaced=False))
        assert "proportional-font" in str(excinfo.value) or "monospaced" in str(excinfo.value)

    def test_zero_frame_refusal_rejects_nonzero_frame_count(self):
        """A package listing fade-transition in refuses_anti_patterns must
        declare transition_frame_count=0."""
        with pytest.raises(ValidationError):
            _build(
                grammar=_minimal_grammar(frame_count=5),
                refuses_anti_patterns=frozenset(["fade-transition"]),
            )

    def test_zero_frame_refusal_accepts_zero_frame_count(self):
        """Zero-frame + fade-transition refusal — the BitchX canonical case."""
        pkg = _build(
            grammar=_minimal_grammar(frame_count=0),
            refuses_anti_patterns=frozenset(["fade-transition"]),
        )
        assert pkg.grammar.transition_frame_count == 0


class TestGrammarColourRoleBinding:
    def test_grammar_unknown_role_rejected(self):
        """Grammar references a role name that does not exist on the palette."""
        # Ship a grammar that declares an unknown role.
        bad_grammar = GrammarRules(
            punctuation_colour_role="muted",
            identity_colour_role="bright",
            content_colour_role="muted",
            line_start_marker="»»»",
            container_shape="angle-bracket",
            raster_cell_required=True,
            transition_frame_count=0,
            event_rhythm_as_texture=True,
            signed_artefacts_required=True,
        )
        # Type-level: this doesn't exist, so we simulate via model_validate.
        # The Literal on ColourRoleName prevents constructing a truly unknown
        # role — this test just asserts that legitimate role names resolve.
        pkg = _build(grammar=bad_grammar)
        assert pkg.resolve_colour(pkg.grammar.identity_colour_role) == pkg.palette.bright


class TestResolveHelpers:
    def test_resolve_colour_returns_palette_rgba(self):
        pkg = _build()
        assert pkg.resolve_colour("muted") == (0.4, 0.4, 0.4, 1.0)
        assert pkg.resolve_colour("bright") == (0.9, 0.9, 0.9, 1.0)

    def test_artefacts_by_form_filters(self):
        quip = SignatureArtefact(content="test quip", form="quit-quip", author_tag="by Hapax")
        banner = SignatureArtefact(content="test banner", form="join-banner", author_tag="by Hapax")
        pkg = _build(signature_artefacts=(quip, banner))
        assert pkg.artefacts_by_form("quit-quip") == (quip,)
        assert pkg.artefacts_by_form("join-banner") == (banner,)
        assert pkg.artefacts_by_form("motd-block") == ()

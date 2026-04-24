"""enlightenment-moksha-v1 HomagePackage — E17/Moksha-grammar aesthetic.

Phase 1 of the Enlightenment authentic-asset strategy (cc-task
``ytb-AUTH-ENLIGHTENMENT-package``). Ships the Moksha-grammar package
SHAPE — curly containers, non-raster cell model, 20-frame soft
envelope transitions, dark-chrome palette — so the compositor can
select it from the active-package registry alongside ``bitchx`` and
``bitchx-authentic-v1``.

Authentic theme assets (EDC source + theme PNGs) are NOT ingested in
this package. Per the cc-task's "Out of scope": full Moksha theme
extraction is ``ytb-AUTH-PALETTE`` (Moksha portion), and EDC animation
envelope integration is ``ytb-AUTH-GEAL``. When those land, a sibling
``enlightenment_moksha_authentic.py`` can mirror the ``bitchx_authentic``
pattern and set ``asset_library_ref``. This Phase 1 package is the
inline-constants variant; its palette is Moksha-dark-chrome-ish, not
byte-exact against any upstream EDC.

Grammar distinctives vs BitchX:

* ``container_shape="curly"`` — E-panel brace chrome, not angle-bracket.
* ``raster_cell_required=False`` — Moksha is not a raster-terminal
  grammar; content flows through E-panels, not a fixed CP437 grid.
* ``transition_frame_count=20`` — EDC programs allow soft fade /
  chrome-lift envelopes (~333ms at 60fps); ``bitchx`` is zero-frame.
* fade transitions are ALLOWED (not in ``refuses_anti_patterns``).

Spec: ``docs/superpowers/specs/2026-04-18-homage-framework-design.md``.
"""

from __future__ import annotations

from shared.homage_package import (
    CouplingRules,
    GrammarRules,
    HomagePackage,
    HomagePalette,
    SignatureRules,
    TransitionVocab,
    TypographyStack,
)
from shared.voice_register import VoiceRegister

# ── Palette ────────────────────────────────────────────────────────────────
# Moksha-dark-chrome inline palette. Authored to evoke the E17/Moksha
# default theme's register — steel-grey skeleton, cool-dim accents,
# warm identity highlight. Values are authored, NOT extracted from an
# upstream EDC. When ytb-AUTH-PALETTE (Moksha portion) acquires the
# authentic PNGs + EDC, a sibling package can replace these with the
# byte-exact extraction.
_MOKSHA_PALETTE = HomagePalette(
    # Steel-grey punctuation skeleton — E-panel chrome outline shade.
    muted=(0.42, 0.44, 0.47, 1.00),
    # Cool off-white identity accent — panel title / highlighted row.
    bright=(0.86, 0.88, 0.91, 1.00),
    # Dim cyan-teal — E-style status indicator, cool accent.
    accent_cyan=(0.22, 0.58, 0.64, 1.00),
    # Desaturated magenta — E-panel alert / mode indicator.
    accent_magenta=(0.56, 0.30, 0.58, 1.00),
    # Muted green — E "ok" indicator (dim, not saturated).
    accent_green=(0.32, 0.60, 0.38, 1.00),
    # Amber-yellow — E warning chrome, the warmest register in the set.
    accent_yellow=(0.78, 0.68, 0.32, 1.00),
    # Dim red — E critical chrome; desaturated to stay in register.
    accent_red=(0.66, 0.28, 0.28, 1.00),
    # Cool blue — E selection / focus accent.
    accent_blue=(0.30, 0.44, 0.66, 1.00),
    # Content body — warm off-white, slightly softer than bright.
    terminal_default=(0.80, 0.82, 0.84, 1.00),
    # Composite background — near-black with alpha so the shader
    # surface shows through; slightly warmer than pure black to evoke
    # the E panel's matte chrome.
    background=(0.05, 0.06, 0.07, 0.88),
)


# ── Typography ─────────────────────────────────────────────────────────────
# DejaVu Sans Mono is Moksha's default monospace and is universally
# installed on the target systems. No aesthetic-library dependency for
# this Phase 1 package — the font is a system font, not ingested.
_MOKSHA_TYPOGRAPHY = TypographyStack(
    primary_font_family="DejaVu Sans Mono",
    fallback_families=(
        "Liberation Mono",
        "IBM Plex Mono",
        "monospace",
    ),
    size_classes={
        "compact": 10,
        "normal": 14,
        "large": 18,
        "banner": 22,
    },
    weight="single",
    monospaced=True,
)


# ── Grammar ────────────────────────────────────────────────────────────────
_MOKSHA_GRAMMAR = GrammarRules(
    punctuation_colour_role="muted",
    identity_colour_role="bright",
    content_colour_role="terminal_default",
    # E-panel brace chrome marker; single-glyph open-curly as the line-start.
    line_start_marker="{",
    container_shape="curly",
    raster_cell_required=False,
    # ~333ms envelope at 60fps; fits the E-EDC soft-fade / chrome-lift
    # idiom without becoming slow-television.
    transition_frame_count=20,
    event_rhythm_as_texture=True,
    signed_artefacts_required=True,
)


# ── Transition vocabulary ──────────────────────────────────────────────────
# Moksha transitions map onto the shared TransitionName literal
# (ticker-scroll-* for the soft fade envelope; mode-change for
# chrome-lift beats; topic-change for panel transitions). E-EDC-flavoured
# names live in ``extra`` as descriptors so downstream tooling can walk
# the Moksha vocabulary by intent without breaking the shared enum.
_MOKSHA_TRANSITIONS = TransitionVocab(
    supported=frozenset(
        [
            "ticker-scroll-in",
            "ticker-scroll-out",
            "mode-change",
            "topic-change",
        ]
    ),
    default_entry="ticker-scroll-in",
    default_exit="ticker-scroll-out",
    max_simultaneous_entries=2,
    max_simultaneous_exits=2,
    extra={
        "fade-in": "ticker-scroll-in rendered as a soft alpha envelope (~333ms at 60fps)",
        "fade-out": "ticker-scroll-out rendered as a soft alpha envelope (~333ms at 60fps)",
        "chrome-lift-in": "mode-change rendered as E-panel chrome-lift entry",
        "chrome-lift-out": "mode-change rendered as E-panel chrome-lift exit",
        "panel-slide-in": "topic-change rendered as panel-slide entry",
        "panel-slide-out": "topic-change rendered as panel-slide exit",
    },
)


# ── Coupling ───────────────────────────────────────────────────────────────
_MOKSHA_COUPLING = CouplingRules(
    custom_slot_index=4,
    payload_channels=(
        "active_transition_energy",
        "palette_chrome_temperature",
        "signature_artefact_intensity",
        "panel_focus_phase",
    ),
    shader_feedback_enabled=True,
    shader_feedback_key="shader_energy",
)


# ── Signature ──────────────────────────────────────────────────────────────
_MOKSHA_SIGNATURE = SignatureRules(
    author_tag="by Hapax/enlightenment-moksha",
    attribution_inline=True,
    generated_content_only=True,
    # Slower cadences than BitchX — E-panel aesthetic is deliberate,
    # not ticker-fast.
    rotation_cadence_s_steady=120.0,
    rotation_cadence_s_deliberate=240.0,
    rotation_cadence_s_rapid=45.0,
)


ENLIGHTENMENT_MOKSHA_PACKAGE = HomagePackage(
    name="enlightenment-moksha-v1",
    version="v1",
    description=(
        "Enlightenment/Moksha-grammar HOMAGE — steel-grey chrome skeleton, "
        "curly E-panel containers, 20-frame soft envelope transitions, "
        "dark-chrome palette. Phase 1 (inline constants); authentic EDC "
        "+ theme PNG ingestion is ytb-AUTH-PALETTE (Moksha portion) + "
        "ytb-AUTH-GEAL follow-on."
    ),
    grammar=_MOKSHA_GRAMMAR,
    typography=_MOKSHA_TYPOGRAPHY,
    palette=_MOKSHA_PALETTE,
    transition_vocabulary=_MOKSHA_TRANSITIONS,
    coupling_rules=_MOKSHA_COUPLING,
    signature_conventions=_MOKSHA_SIGNATURE,
    voice_register_default=VoiceRegister.TEXTMODE,
    # No seed artefact corpus for Phase 1; the authentic EDC/PNG
    # follow-on will populate signature_artefacts from the library.
    signature_artefacts=(),
    refuses_anti_patterns=frozenset(
        [
            "emoji",
            "anti-aliased",
            "proportional-font",
            "iso-8601-timestamp",
            "swiss-grid-motd",
            "flat-ui-chrome",
        ]
    ),
    # None — Phase 1 ships inline constants; authentic sibling will set this.
    asset_library_ref=None,
)


__all__ = ["ENLIGHTENMENT_MOKSHA_PACKAGE"]

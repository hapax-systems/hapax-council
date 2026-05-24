"""Quake HomagePackage — third aesthetic member.

Tower of Babel interior rendered by DarkPlaces Quake engine. The visual
grammar draws from Quake I (1996): brown-olive-grey palette, angular
geometry, hard-cut transitions, console message typography.

The Quake homage is fundamentally spatial — the 3D scroom IS the visual
surface — whereas BitchX and Enlightenment-Moksha are typographic. Ward
identity/drift should live in DarkPlaces geometry/materials first; Cairo/Pango
surfaces are legacy bridge surfaces until a given ward has an engine-native
dynamic strategy.

Spec: ``docs/superpowers/specs/2026-05-23-screwm-quake-hybrid-isap.md``.
"""

from __future__ import annotations

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

_QUAKE_PALETTE = HomagePalette(
    muted=(0.35, 0.30, 0.25, 1.00),
    bright=(0.75, 0.70, 0.60, 1.00),
    accent_cyan=(0.30, 0.55, 0.55, 1.00),
    accent_magenta=(0.60, 0.20, 0.20, 1.00),
    accent_green=(0.42, 0.56, 0.14, 1.00),
    accent_yellow=(0.70, 0.55, 0.25, 1.00),
    accent_red=(0.55, 0.00, 0.00, 1.00),
    accent_blue=(0.20, 0.30, 0.45, 1.00),
    terminal_default=(0.65, 0.60, 0.50, 1.00),
    background=(0.10, 0.08, 0.06, 0.85),
)


_QUAKE_TYPOGRAPHY = TypographyStack(
    primary_font_family="Px437 IBM VGA 8x16",
    fallback_families=(
        "Terminus",
        "Unscii",
        "DejaVu Sans Mono",
    ),
    size_classes={
        "compact": 10,
        "normal": 14,
        "large": 18,
        "banner": 24,
    },
    weight="single",
    monospaced=True,
)


_QUAKE_GRAMMAR = GrammarRules(
    punctuation_colour_role="accent_yellow",
    identity_colour_role="accent_green",
    content_colour_role="terminal_default",
    line_start_marker="▌",
    container_shape="angle-bracket",
    raster_cell_required=True,
    transition_frame_count=6,
    event_rhythm_as_texture=True,
    signed_artefacts_required=True,
)


_QUAKE_TRANSITIONS = TransitionVocab(
    supported=frozenset(
        [
            "zero-cut-in",
            "zero-cut-out",
            "join-message",
            "part-message",
            "topic-change",
            "netsplit-burst",
            "mode-change",
            "ticker-scroll-in",
            "ticker-scroll-out",
        ]
    ),
    default_entry="zero-cut-in",
    default_exit="zero-cut-out",
    max_simultaneous_entries=3,
    max_simultaneous_exits=2,
    netsplit_burst_min_interval_s=90.0,
)


_QUAKE_COUPLING = CouplingRules(
    custom_slot_index=4,
    payload_channels=(
        "active_transition_energy",
        "palette_accent_hue_deg",
        "signature_artefact_intensity",
        "rotation_phase",
    ),
    shader_feedback_enabled=True,
    shader_feedback_key="shader_energy",
)


_QUAKE_SIGNATURE = SignatureRules(
    author_tag="by Hapax/quake",
    attribution_inline=True,
    generated_content_only=True,
    rotation_cadence_s_steady=60.0,
    rotation_cadence_s_deliberate=120.0,
    rotation_cadence_s_rapid=20.0,
    netsplit_burst_cadence_s=90.0,
)


_TAG = "by Hapax/quake"

_QUAKE_ARTEFACTS = (
    SignatureArtefact(
        form="join-banner",
        author_tag=_TAG,
        content="═══ Entering The Screwm ═══\n  Tower of Babel interior\n  Research instrument online",
    ),
    SignatureArtefact(
        form="quit-quip",
        author_tag=_TAG,
        content="Hapax: slipgate closed — grounding persists",
    ),
    SignatureArtefact(
        form="quit-quip",
        author_tag=_TAG,
        content="Connection reset by Sierpinski",
    ),
    SignatureArtefact(
        form="quit-quip",
        author_tag=_TAG,
        content="Hapax: the tower remembers your frequency",
    ),
    SignatureArtefact(
        form="motd-block",
        author_tag=_TAG,
        content="╔══════════════════════════════════╗\n║  THE SCREWM — level 1/5         ║\n║  perception → grounding          ║\n║  Hapax research instrument       ║\n╚══════════════════════════════════╝",
    ),
    SignatureArtefact(
        form="kick-reason",
        author_tag=_TAG,
        content="[SLIPGATE DRIFT] teleported outside the tower",
    ),
    SignatureArtefact(
        form="kick-reason",
        author_tag=_TAG,
        content="[GROUNDING LOST] fell through the central void",
    ),
    SignatureArtefact(
        form="kick-reason",
        author_tag=_TAG,
        content="[QUAD EXPIRED] expression window collapsed",
    ),
    SignatureArtefact(
        form="kick-reason",
        author_tag=_TAG,
        content="[PERCEPTION OVERLOAD] too many sensors active",
    ),
)


QUAKE_PACKAGE = HomagePackage(
    name="quake",
    version="1.0.0",
    description=(
        "Quake-grammar homage: Tower of Babel interior, brown-olive-grey "
        "palette, angular containers, hard 6-frame transitions, teleport-flash "
        "entry, console-message artefacts. DarkPlaces renders the 3D spatial "
        "environment; ward identity and drift live in the scroom geometry, with "
        "Cairo kept only as a legacy dynamic bridge where still required."
    ),
    palette=_QUAKE_PALETTE,
    typography=_QUAKE_TYPOGRAPHY,
    grammar=_QUAKE_GRAMMAR,
    transition_vocabulary=_QUAKE_TRANSITIONS,
    coupling_rules=_QUAKE_COUPLING,
    signature_conventions=_QUAKE_SIGNATURE,
    signature_artefacts=_QUAKE_ARTEFACTS,
    voice_register_default=VoiceRegister.TEXTMODE,
    refuses_anti_patterns=frozenset(
        [
            "emoji",
            "rounded-corners",
            "proportional-font",
            "anti-aliased",
        ]
    ),
)

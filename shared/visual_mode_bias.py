"""shared/visual_mode_bias.py — Per-mode visual aesthetic bias (cc-task u8 Phase 0).

Audit underutilization U8: today the visual surface looks ~identical between
RESEARCH and RND working modes. The mode-switch should produce a visibly
different aesthetic regime per the design language: muted-Solarized in
RESEARCH (low motion, contemplative), saturated-Gruvbox in RND (high motion,
generative).

This module is the **single source of truth for the per-mode aesthetic
bias map**. Compositor / imagination / reverie consumers read it via
``get_visual_mode_bias()`` and apply the bias at their own scale (preset
weight multipliers, motion-factor knobs, colorgrade param overrides).

Phase 0 (this PR): the bias map + accessor + regression test that the
research and RND palettes do not share their first 3 colors. No consumer
wiring yet — Phase 1 cc-tasks land per-consumer (compositor preset
weights, imagination color hint, reverie satellite-recruitment threshold).

Phase 1 (separate cc-tasks):
  * `u8-compositor-preset-bias-consumer` — wire the preset selector
    to multiply candidate scores by ``preset_family_weights[mode]``
  * `u8-imagination-mode-tint` — read ``palette_hint[mode]`` into
    the imagination colorgrade target
  * `u8-reverie-mode-motion-factor` — apply ``motion_factor[mode]``
    multiplicatively to satellite recruitment thresholds
  * `u8-screenshot-grid` — operator-side 60s capture in each mode
    proving the visible delta (not a CI test; uses live compositor)

Refs:
  * `docs/logos-design-language.md` §3 (Gruvbox + Solarized palettes)
  * `shared/working_mode.py` (single mode source of truth)
  * `agents/studio_compositor/preset_family_selector.py` (consumer site
    candidate for Phase 1)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from shared.working_mode import WorkingMode, get_working_mode

# ── Palette hints (RGB tuples in the 0-255 range, top-3 saturation order) ──
#
# Per `docs/logos-design-language.md` §3 — RND uses Gruvbox Hard Dark
# (warm, high-saturation, foreground-pop), RESEARCH uses Solarized Dark
# (cool, low-saturation, contemplative). Top-3 entries are the dominant
# hues each consumer should bias preset selection toward.
#
# FORTRESS reuses RND's palette intentionally (livestream-gating mode
# is operationally R&D + extra checks; aesthetic register stays RND).

PALETTE_HINT: dict[WorkingMode, tuple[tuple[int, int, int], ...]] = {
    WorkingMode.RND: (
        (251, 73, 52),  # Gruvbox bright-red
        (250, 189, 47),  # Gruvbox bright-yellow
        (211, 134, 155),  # Gruvbox bright-purple
    ),
    WorkingMode.RESEARCH: (
        (38, 139, 210),  # Solarized blue
        (42, 161, 152),  # Solarized cyan
        (133, 153, 0),  # Solarized green
    ),
    WorkingMode.FORTRESS: (
        (251, 73, 52),
        (250, 189, 47),
        (211, 134, 155),
    ),
}

# ── Motion factor (multiplier on temporal-distortion + recruitment thresholds) ──
#
# RND amplifies motion (more recruits, faster cycling). RESEARCH dampens
# (slower, longer-dwell). FORTRESS sits between — livestream-gated
# attention means more reach for recruitment but less reach for
# disruptive motion.

MOTION_FACTOR: dict[WorkingMode, float] = {
    WorkingMode.RND: 1.4,
    WorkingMode.RESEARCH: 0.6,
    WorkingMode.FORTRESS: 1.0,
}

# ── Preset-family recruitment weights ──
#
# Multipliers applied to candidate scores in the AffordancePipeline's
# `fx.family.*` retrieve step. Per-mode lean: RND keeps a mild residual
# preference for high-energy families (audio-reactive, glitch-dense);
# RESEARCH keeps a mild residual preference for calm families
# (calm-textural, warm-minimal). Default 1.0 elsewhere.
#
# Rebalance (researcher visual-monoculture audit, 2026-05-03): the
# previous weights (RND audio-reactive=1.5, glitch-dense=1.4 vs
# warm-minimal=0.7, calm-textural=0.6) produced winner-take-all
# selection — over the last 2h of recruitment, 100% of selections came
# from 2 of 5 families, while warm-minimal, calm-textural, and
# neutral-ambient (no weight at all) became dark matter: preset corpus
# present, never selected. New weights compress the per-family spread
# to keep all families above 0.85 so similarity scoring (the dominant
# signal) actually decides selection within each mode's mild
# aesthetic lean. Pairs with `preset_mutator.DEFAULT_VARIANCE = 0.30`
# for stronger in-family per-instance jitter.

PRESET_FAMILY_WEIGHTS: dict[WorkingMode, dict[str, float]] = {
    WorkingMode.RND: {
        "fx.family.audio-reactive": 1.2,
        "fx.family.glitch-dense": 1.2,
        "fx.family.warm-minimal": 1.0,
        "fx.family.calm-textural": 1.0,
        "fx.family.neutral-ambient": 1.0,
    },
    WorkingMode.RESEARCH: {
        "fx.family.calm-textural": 1.2,
        "fx.family.warm-minimal": 1.2,
        "fx.family.neutral-ambient": 1.0,
        "fx.family.audio-reactive": 0.9,
        "fx.family.glitch-dense": 0.85,
    },
    WorkingMode.FORTRESS: {
        # Neutral — fortress mode prioritizes consent + livestream gating
        # over aesthetic regime; weights default to 1.0 across the board.
    },
}


@dataclass(frozen=True)
class VisualModeBias:
    """The full per-mode bias snapshot consumers can apply at their own scale."""

    mode: WorkingMode
    palette_hint: tuple[tuple[int, int, int], ...]
    motion_factor: float
    preset_family_weights: dict[str, float] = field(default_factory=dict)

    def family_weight(self, capability_name: str, default: float = 1.0) -> float:
        """Look up the multiplier for an `fx.family.*` capability_name."""
        return self.preset_family_weights.get(capability_name, default)


def visual_mode_bias_for(mode: WorkingMode) -> VisualModeBias:
    """Snapshot the bias for an explicit mode (deterministic; tests use this)."""
    return VisualModeBias(
        mode=mode,
        palette_hint=PALETTE_HINT[mode],
        motion_factor=MOTION_FACTOR[mode],
        preset_family_weights=dict(PRESET_FAMILY_WEIGHTS.get(mode, {})),
    )


def get_visual_mode_bias() -> VisualModeBias:
    """Read the live working mode and return the bias snapshot.

    Single accessor for compositor / imagination / reverie consumers.
    Cached at-call cost is one file read; consumers should call once per
    tick (not per-pixel) and capture the snapshot for the tick.
    """
    return visual_mode_bias_for(get_working_mode())

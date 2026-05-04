"""Tests for cc-task u8-stream-mode-delta-amplification (Phase 0).

Pin the per-mode bias map's non-triviality and the per-consumer
contracts. The substrate (this module) ships before any consumer wires
in, so the regression-prevention here is mainly:

  L0: every WorkingMode has palette + motion + family-weight entries
  L1: research and rnd palettes do NOT share their first 3 colors
      (the U8 acceptance criterion from the cc-task body)
  L2: motion_factor[rnd] > motion_factor[research] (regime delta is
      meaningful, not tied)
  L3: preset_family_weights[rnd][audio-reactive] > research
      (per-family weight matches the regime semantics)
  L4: VisualModeBias.family_weight() returns 1.0 default for unknown
      capability_names (consumers must work for every fx.family.*
      whether explicitly weighted or not)
"""

from __future__ import annotations

from shared.visual_mode_bias import (
    MOTION_FACTOR,
    PALETTE_HINT,
    PRESET_FAMILY_WEIGHTS,
    VisualModeBias,
    visual_mode_bias_for,
)
from shared.working_mode import WorkingMode


class TestEveryModeHasBiasEntry:
    """Catch a future WorkingMode addition that forgot the bias map update."""

    def test_palette_covers_every_mode(self) -> None:
        for mode in WorkingMode:
            assert mode in PALETTE_HINT, f"palette missing for {mode!r}"
            assert len(PALETTE_HINT[mode]) >= 3, (
                f"palette for {mode!r} must have ≥3 dominant hues for the bias to be applicable"
            )

    def test_motion_factor_covers_every_mode(self) -> None:
        for mode in WorkingMode:
            assert mode in MOTION_FACTOR, f"motion factor missing for {mode!r}"
            assert 0.0 < MOTION_FACTOR[mode] < 5.0, (
                f"motion factor for {mode!r} = {MOTION_FACTOR[mode]} out of [0, 5] sanity range"
            )

    def test_preset_family_weights_covers_every_mode(self) -> None:
        for mode in WorkingMode:
            assert mode in PRESET_FAMILY_WEIGHTS, f"preset family weights missing for {mode!r}"


class TestRegimeDeltaIsNonTrivial:
    """The U8 acceptance criterion — modes must be aesthetically distinct."""

    def test_research_and_rnd_palettes_do_not_share_first_3(self) -> None:
        """Direct quote from the cc-task acceptance criteria."""
        rnd_top3 = set(PALETTE_HINT[WorkingMode.RND][:3])
        research_top3 = set(PALETTE_HINT[WorkingMode.RESEARCH][:3])
        overlap = rnd_top3 & research_top3
        assert not overlap, (
            f"research and rnd palettes share {overlap} in their top-3 — "
            f"the regime delta is not visually distinguishable. The U8 "
            f"acceptance criterion explicitly forbids palette overlap."
        )

    def test_rnd_motion_factor_strictly_greater_than_research(self) -> None:
        """Not equal — the regime semantics require directional difference."""
        assert MOTION_FACTOR[WorkingMode.RND] > MOTION_FACTOR[WorkingMode.RESEARCH], (
            f"motion_factor[rnd]={MOTION_FACTOR[WorkingMode.RND]} must be > "
            f"motion_factor[research]={MOTION_FACTOR[WorkingMode.RESEARCH]}; "
            f"RND is the high-energy regime per design language §3"
        )

    def test_rnd_favors_audio_reactive_research_favors_calm(self) -> None:
        """Per-family bias matches the regime semantics."""
        rnd = PRESET_FAMILY_WEIGHTS[WorkingMode.RND]
        research = PRESET_FAMILY_WEIGHTS[WorkingMode.RESEARCH]
        assert rnd.get("fx.family.audio-reactive", 1.0) > research.get(
            "fx.family.audio-reactive", 1.0
        ), "RND must favor audio-reactive presets over RESEARCH"
        assert research.get("fx.family.calm-textural", 1.0) > rnd.get(
            "fx.family.calm-textural", 1.0
        ), "RESEARCH must favor calm-textural presets over RND"


class TestVisualModeBiasSnapshot:
    def test_visual_mode_bias_for_returns_dataclass_snapshot(self) -> None:
        bias = visual_mode_bias_for(WorkingMode.RND)
        assert isinstance(bias, VisualModeBias)
        assert bias.mode == WorkingMode.RND
        assert bias.palette_hint == PALETTE_HINT[WorkingMode.RND]
        assert bias.motion_factor == MOTION_FACTOR[WorkingMode.RND]

    def test_family_weight_returns_default_for_unknown_capability(self) -> None:
        """Consumers must work for every fx.family.* whether explicitly
        weighted or not — neutral 1.0 default."""
        bias = visual_mode_bias_for(WorkingMode.RND)
        assert bias.family_weight("fx.family.unknown-future-family") == 1.0
        # Custom default also propagated:
        assert bias.family_weight("fx.family.unknown", default=0.5) == 0.5

    def test_family_weight_returns_configured_value(self) -> None:
        bias = visual_mode_bias_for(WorkingMode.RND)
        # PRESET_FAMILY_WEIGHTS[RND] sets audio-reactive to 1.2 after
        # the 2026-05-03 visual-monoculture rebalance (was 1.5).
        assert bias.family_weight("fx.family.audio-reactive") == 1.2

    def test_snapshot_is_independent_per_mode(self) -> None:
        """Mutating one snapshot's preset_family_weights must not leak
        into the module-level registry (defensive copy)."""
        a = visual_mode_bias_for(WorkingMode.RND)
        a.preset_family_weights["fx.family.test-leak"] = 99.0
        b = visual_mode_bias_for(WorkingMode.RND)
        assert "fx.family.test-leak" not in b.preset_family_weights, (
            "preset_family_weights snapshot leaked into the next call — defensive-copy contract broken"
        )


class TestLiveModeReader:
    """get_visual_mode_bias() reads the live mode file."""

    def test_get_visual_mode_bias_returns_a_valid_snapshot(self, monkeypatch) -> None:
        """Without monkeypatching the file, just confirm the call returns
        a valid snapshot — exact mode varies by what the operator has set
        on this workstation."""
        from shared.visual_mode_bias import get_visual_mode_bias

        bias = get_visual_mode_bias()
        assert isinstance(bias, VisualModeBias)
        assert bias.mode in WorkingMode
        assert isinstance(bias.motion_factor, float)

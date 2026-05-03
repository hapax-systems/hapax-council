"""Tests for U8 reverie motion-factor mode bias (cc-task u8-reverie-mode-motion-factor).

Pin:
- _effective_recruitment_threshold math (RND lower threshold, RESEARCH higher)
- SatelliteManager.recruit() honors the per-mode threshold
- Mode flip → recruitment delta within 1 tick (single recruit() call)
- Fail-open on bias provider failure (broken mode file → use base threshold)
"""

from __future__ import annotations

import pytest

from agents.reverie._satellites import (
    DISMISSAL_THRESHOLD,
    RECRUITMENT_THRESHOLD,
    SatelliteManager,
    _effective_recruitment_threshold,
)
from shared.visual_mode_bias import VisualModeBias, WorkingMode


def _bias(mode: WorkingMode, motion_factor: float) -> VisualModeBias:
    """Build a bias snapshot inline for tests (avoids reading mode file)."""
    return VisualModeBias(
        mode=mode,
        palette_hint=((0, 0, 0),),
        motion_factor=motion_factor,
        preset_family_weights={},
    )


class TestEffectiveRecruitmentThreshold:
    def test_rnd_mode_lowers_threshold(self) -> None:
        """RND motion_factor=1.4 → 0.3/1.4 ≈ 0.214 (LOWER → easier)."""
        result = _effective_recruitment_threshold(0.3, lambda: _bias(WorkingMode.RND, 1.4))
        assert result == pytest.approx(0.3 / 1.4)
        assert result < 0.3

    def test_research_mode_raises_threshold(self) -> None:
        """RESEARCH motion_factor=0.6 → 0.3/0.6 = 0.5 (HIGHER → harder)."""
        result = _effective_recruitment_threshold(0.3, lambda: _bias(WorkingMode.RESEARCH, 0.6))
        assert result == pytest.approx(0.5)
        assert result > 0.3

    def test_fortress_mode_neutral(self) -> None:
        """FORTRESS motion_factor=1.0 → unchanged."""
        result = _effective_recruitment_threshold(0.3, lambda: _bias(WorkingMode.FORTRESS, 1.0))
        assert result == pytest.approx(0.3)

    def test_zero_motion_factor_falls_back_to_base(self) -> None:
        """Pathological motion_factor=0 must NOT divide-by-zero; fall back."""
        result = _effective_recruitment_threshold(0.3, lambda: _bias(WorkingMode.RND, 0.0))
        assert result == 0.3

    def test_negative_motion_factor_falls_back_to_base(self) -> None:
        result = _effective_recruitment_threshold(0.3, lambda: _bias(WorkingMode.RND, -1.0))
        assert result == 0.3

    def test_provider_raises_falls_back_to_base(self) -> None:
        """Mode-file missing / parse error → use base threshold (fail-open)."""

        def boom() -> VisualModeBias:
            raise RuntimeError("working-mode file missing")

        result = _effective_recruitment_threshold(0.3, boom)
        assert result == 0.3


class TestSatelliteManagerHonoursMotionFactor:
    """Mode-flip → recruitment delta within 1 tick."""

    def _new_manager(self, mode: WorkingMode, motion_factor: float) -> SatelliteManager:
        return SatelliteManager(
            core_vocab={"core": {}},
            mode_bias_provider=lambda: _bias(mode, motion_factor),
        )

    def test_rnd_mode_recruits_at_strength_below_base_threshold(self) -> None:
        """RND lowers threshold to 0.214; strength=0.25 should recruit."""
        manager = self._new_manager(WorkingMode.RND, 1.4)
        manager.begin_tick()
        manager.recruit("noise_amp", 0.25)
        assert "noise_amp" in manager.recruited

    def test_research_mode_blocks_recruit_below_higher_threshold(self) -> None:
        """RESEARCH raises threshold to 0.5; strength=0.4 should NOT recruit."""
        manager = self._new_manager(WorkingMode.RESEARCH, 0.6)
        manager.begin_tick()
        manager.recruit("noise_amp", 0.4)
        assert "noise_amp" not in manager.recruited

    def test_research_mode_recruits_at_strength_above_higher_threshold(self) -> None:
        manager = self._new_manager(WorkingMode.RESEARCH, 0.6)
        manager.begin_tick()
        manager.recruit("noise_amp", 0.6)
        assert "noise_amp" in manager.recruited

    def test_strength_above_base_threshold_recruits_in_all_modes(self) -> None:
        """Strength=0.7 is well above any effective threshold; should
        always recruit."""
        for mode, mf in [
            (WorkingMode.RND, 1.4),
            (WorkingMode.RESEARCH, 0.6),
            (WorkingMode.FORTRESS, 1.0),
        ]:
            manager = self._new_manager(mode, mf)
            manager.begin_tick()
            manager.recruit("noise_amp", 0.7)
            assert "noise_amp" in manager.recruited, (
                f"strength=0.7 must recruit in {mode}; effective threshold = "
                f"{_effective_recruitment_threshold(0.3, lambda: _bias(mode, mf))}"
            )

    def test_strength_well_below_all_thresholds_blocks_in_all_modes(self) -> None:
        """Strength=0.1 is below all effective thresholds; should NEVER recruit."""
        for mode, mf in [
            (WorkingMode.RND, 1.4),
            (WorkingMode.RESEARCH, 0.6),
            (WorkingMode.FORTRESS, 1.0),
        ]:
            manager = self._new_manager(mode, mf)
            manager.begin_tick()
            manager.recruit("noise_amp", 0.1)
            assert "noise_amp" not in manager.recruited


class TestModeFlipDeltaWithinOneTick:
    """Mode-flip causes recruitment outcome change at the very next call.

    Pinned because the U8 substrate's ``get_visual_mode_bias`` is a per-call
    file read (no internal cache), so the next ``recruit()`` after a mode
    flip MUST see the new bias.
    """

    def test_flip_research_to_rnd_unblocks_marginal_recruit(self) -> None:
        # Mutable holder for the test-controlled bias.
        bias_holder = {"current": _bias(WorkingMode.RESEARCH, 0.6)}

        manager = SatelliteManager(
            core_vocab={"core": {}},
            mode_bias_provider=lambda: bias_holder["current"],
        )
        # Strength=0.4 in RESEARCH mode (threshold 0.5) → blocked.
        manager.begin_tick()
        manager.recruit("noise_amp", 0.4)
        assert "noise_amp" not in manager.recruited

        # Operator flips to RND (threshold 0.214); the same strength now
        # recruits on the next call.
        bias_holder["current"] = _bias(WorkingMode.RND, 1.4)
        manager.begin_tick()
        manager.recruit("noise_amp", 0.4)
        assert "noise_amp" in manager.recruited

    def test_flip_rnd_to_research_blocks_marginal_recruit(self) -> None:
        bias_holder = {"current": _bias(WorkingMode.RND, 1.4)}
        manager = SatelliteManager(
            core_vocab={"core": {}},
            mode_bias_provider=lambda: bias_holder["current"],
        )
        # Strength=0.25 in RND (threshold 0.214) → recruits.
        manager.begin_tick()
        manager.recruit("noise_amp", 0.25)
        assert "noise_amp" in manager.recruited

        # Strength would NOT recruit in RESEARCH (threshold 0.5). To keep
        # the test on the threshold edge, dismiss the satellite first by
        # decay, then flip mode and try a new recruit.
        # Force decay below dismissal:
        manager._recruited["noise_amp"] = DISMISSAL_THRESHOLD - 0.01
        manager.decay(dt=0.001)
        assert "noise_amp" not in manager.recruited

        # Flip to RESEARCH; strength=0.25 must now be blocked.
        bias_holder["current"] = _bias(WorkingMode.RESEARCH, 0.6)
        manager.begin_tick()
        manager.recruit("noise_amp", 0.25)
        assert "noise_amp" not in manager.recruited


class TestBackwardCompatibility:
    """SatelliteManager without explicit mode_bias_provider must still work
    (defaults to live get_visual_mode_bias)."""

    def test_default_mode_bias_provider_is_callable(self) -> None:
        manager = SatelliteManager(core_vocab={"core": {}})
        # Should not crash on construction.
        assert manager._mode_bias_provider is not None
        # Calling it returns a VisualModeBias instance (whatever the live
        # working mode is — research / rnd / fortress all valid).
        bias = manager._mode_bias_provider()
        assert isinstance(bias, VisualModeBias)

    def test_recruitment_threshold_constant_unchanged(self) -> None:
        """Pin the base value — Phase 1 must not silently mutate the
        substrate constant."""
        assert RECRUITMENT_THRESHOLD == 0.3

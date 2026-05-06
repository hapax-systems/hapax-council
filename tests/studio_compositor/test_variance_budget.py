"""Property pin for the ward modulator's variance budget constants.

Gap #8 (PR #2750) codified the env-knock the operator landed during
variance recovery (MAX_ALPHA_STEP 0.16→0.5, MAX_Z_INDEX_STEP 0.18→0.4).
This test pins those values so they can't silently regress.

The budget governs how much each stimmung tick can move ward alpha
and z-index. Too tight → the modulator barely moves wards, variance
stalls. Too loose → wards jump visually on every tick.
"""

from __future__ import annotations

from agents.studio_compositor.ward_stimmung_modulator import (
    MAX_ALPHA_STEP,
    MAX_Z_INDEX_STEP,
)


class TestVarianceBudget:
    def test_alpha_step_matches_env_knock(self) -> None:
        assert MAX_ALPHA_STEP == 0.5, (
            f"MAX_ALPHA_STEP regressed to {MAX_ALPHA_STEP}. Gap #8 codified "
            f"the operator's env-knock at 0.5 (was 0.16). The tighter value "
            f"starves variance recovery."
        )

    def test_z_index_step_matches_env_knock(self) -> None:
        assert MAX_Z_INDEX_STEP == 0.4, (
            f"MAX_Z_INDEX_STEP regressed to {MAX_Z_INDEX_STEP}. Gap #8 codified "
            f"the operator's env-knock at 0.4 (was 0.18). The tighter value "
            f"starves spatial variance."
        )

    def test_alpha_step_is_positive(self) -> None:
        assert MAX_ALPHA_STEP > 0.0

    def test_z_index_step_is_positive(self) -> None:
        assert MAX_Z_INDEX_STEP > 0.0

    def test_steps_are_bounded(self) -> None:
        assert MAX_ALPHA_STEP <= 1.0, "Alpha step > 1.0 would produce invalid alpha values"
        assert MAX_Z_INDEX_STEP <= 1.0, "Z-index step > 1.0 would produce extreme jumps"

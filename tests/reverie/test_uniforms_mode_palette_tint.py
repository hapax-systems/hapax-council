"""u8-imagination-mode-tint — colorgrade hue_rotate driven by PALETTE_HINT.

cc-task `u8-imagination-mode-tint`. The reverie mixer's `write_uniforms`
must read `PALETTE_HINT[mode]` from `shared/visual_mode_bias.py` and
write `color.hue_rotate` so research vs rnd modes are visibly distinct
on stream. Active homage packages (BitchX) override the mode tint —
homage is per-package and authoritative.

Test surface:
  * `_rgb_to_hsv_hue` correctness on canonical colors
  * `_palette_hint_to_hue_rotate` wrap into ±180 range
  * `_apply_mode_palette_tint` writes color.hue_rotate from bias
  * `_apply_mode_palette_tint` swallow on bias-read failure
  * `_apply_mode_palette_tint` honors per-mode palette via fake
  * `_apply_mode_palette_tint` followed by homage damping → homage wins
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agents.reverie import _uniforms
from shared.visual_mode_bias import PALETTE_HINT, VisualModeBias
from shared.working_mode import WorkingMode

# ── _rgb_to_hsv_hue ──────────────────────────────────────────────────


class TestRgbToHsvHue:
    def test_pure_red(self) -> None:
        assert _uniforms._rgb_to_hsv_hue(255, 0, 0) == pytest.approx(0.0)

    def test_pure_green(self) -> None:
        assert _uniforms._rgb_to_hsv_hue(0, 255, 0) == pytest.approx(120.0)

    def test_pure_blue(self) -> None:
        assert _uniforms._rgb_to_hsv_hue(0, 0, 255) == pytest.approx(240.0)

    def test_grey_returns_zero(self) -> None:
        assert _uniforms._rgb_to_hsv_hue(128, 128, 128) == pytest.approx(0.0)

    def test_black_returns_zero(self) -> None:
        assert _uniforms._rgb_to_hsv_hue(0, 0, 0) == pytest.approx(0.0)

    def test_white_returns_zero(self) -> None:
        assert _uniforms._rgb_to_hsv_hue(255, 255, 255) == pytest.approx(0.0)

    def test_gruvbox_bright_red_warm(self) -> None:
        """RND palette[0] = (251, 73, 52) — warm, hue ≈ 6°."""
        h = _uniforms._rgb_to_hsv_hue(251, 73, 52)
        assert 0.0 <= h <= 15.0  # warm-red bin

    def test_solarized_blue_cool(self) -> None:
        """RESEARCH palette[0] = (38, 139, 210) — cool, hue ≈ 205°."""
        h = _uniforms._rgb_to_hsv_hue(38, 139, 210)
        assert 195.0 <= h <= 215.0  # blue bin


# ── _palette_hint_to_hue_rotate ─────────────────────────────────────


class TestPaletteHintToHueRotate:
    def test_empty_palette_returns_zero(self) -> None:
        assert _uniforms._palette_hint_to_hue_rotate(()) == pytest.approx(0.0)

    def test_warm_palette_stays_positive(self) -> None:
        """RND Gruvbox red → small positive offset (warm)."""
        rotate = _uniforms._palette_hint_to_hue_rotate(PALETTE_HINT[WorkingMode.RND])
        assert 0.0 <= rotate <= 30.0

    def test_cool_palette_wraps_to_negative(self) -> None:
        """RESEARCH Solarized blue (≈205°) wraps to -155° (in range)."""
        rotate = _uniforms._palette_hint_to_hue_rotate(PALETTE_HINT[WorkingMode.RESEARCH])
        assert -180.0 < rotate < 0.0
        assert rotate == pytest.approx(_uniforms._rgb_to_hsv_hue(38, 139, 210) - 360.0)

    def test_research_and_rnd_produce_different_signs(self) -> None:
        """Distinctness pin: research and rnd land in opposite halves of
        the hue_rotate range. Mode flip → visible delta."""
        research = _uniforms._palette_hint_to_hue_rotate(PALETTE_HINT[WorkingMode.RESEARCH])
        rnd = _uniforms._palette_hint_to_hue_rotate(PALETTE_HINT[WorkingMode.RND])
        assert (research < 0) != (rnd < 0)  # opposite signs

    def test_output_within_colorgrade_range(self) -> None:
        """Pin the output bound — colorgrade.wgsl's u_hue_rotate is signed
        ±180, so the helper must never escape that range."""
        for mode in (WorkingMode.RND, WorkingMode.RESEARCH, WorkingMode.FORTRESS):
            rotate = _uniforms._palette_hint_to_hue_rotate(PALETTE_HINT[mode])
            assert -180.0 <= rotate <= 180.0

    def test_fortress_reuses_rnd_palette_rotate(self) -> None:
        """FORTRESS is livestream-gated RND aesthetically, not a third tint."""
        fortress = _uniforms._palette_hint_to_hue_rotate(PALETTE_HINT[WorkingMode.FORTRESS])
        rnd = _uniforms._palette_hint_to_hue_rotate(PALETTE_HINT[WorkingMode.RND])
        assert fortress == pytest.approx(rnd)


# ── _apply_mode_palette_tint ────────────────────────────────────────


def _bias_for(mode: WorkingMode) -> VisualModeBias:
    """Build a deterministic VisualModeBias snapshot for the given mode."""
    from shared.visual_mode_bias import MOTION_FACTOR, PRESET_FAMILY_WEIGHTS

    return VisualModeBias(
        mode=mode,
        palette_hint=PALETTE_HINT[mode],
        motion_factor=MOTION_FACTOR[mode],
        preset_family_weights=dict(PRESET_FAMILY_WEIGHTS.get(mode, {})),
    )


class TestApplyModePaletteTint:
    def test_writes_color_hue_rotate_for_rnd_mode(self) -> None:
        uniforms: dict[str, float] = {}
        _uniforms._apply_mode_palette_tint(
            uniforms, bias_provider=lambda: _bias_for(WorkingMode.RND)
        )
        assert "color.hue_rotate" in uniforms
        assert 0.0 <= uniforms["color.hue_rotate"] <= 30.0

    def test_writes_color_hue_rotate_for_research_mode(self) -> None:
        uniforms: dict[str, float] = {}
        _uniforms._apply_mode_palette_tint(
            uniforms, bias_provider=lambda: _bias_for(WorkingMode.RESEARCH)
        )
        assert "color.hue_rotate" in uniforms
        assert -180.0 < uniforms["color.hue_rotate"] < 0.0

    def test_mode_flip_changes_uniform_within_one_call(self) -> None:
        """AC#3: mode flip → colorgrade uniform delta within 1 tick."""
        uniforms: dict[str, float] = {}
        _uniforms._apply_mode_palette_tint(
            uniforms, bias_provider=lambda: _bias_for(WorkingMode.RESEARCH)
        )
        research_value = uniforms["color.hue_rotate"]

        _uniforms._apply_mode_palette_tint(
            uniforms, bias_provider=lambda: _bias_for(WorkingMode.RND)
        )
        rnd_value = uniforms["color.hue_rotate"]

        assert research_value != rnd_value
        # Difference must be substantial (> 100°), not a 1° drift.
        assert abs(research_value - rnd_value) > 100.0

    def test_bias_provider_failure_does_not_crash(self) -> None:
        """If `get_visual_mode_bias()` fails (e.g. missing working-mode
        file), the uniforms dict is left untouched — the colorgrade pass
        falls back to plan-default `color.hue_rotate=0.0`."""

        def raising_provider() -> VisualModeBias:
            raise RuntimeError("synthetic working-mode read failure")

        uniforms: dict[str, float] = {"existing": 1.0}
        # Should not raise.
        _uniforms._apply_mode_palette_tint(uniforms, bias_provider=raising_provider)
        # Did not write color.hue_rotate.
        assert "color.hue_rotate" not in uniforms
        # Did not corrupt other keys.
        assert uniforms["existing"] == 1.0

    def test_invalid_working_mode_file_falls_back_to_rnd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Invalid live mode content should route through get_working_mode's
        RND fallback rather than skipping the tint or raising."""
        from shared import working_mode

        mode_file = tmp_path / "working-mode"
        mode_file.write_text("not-a-mode\n")
        monkeypatch.setattr(working_mode, "WORKING_MODE_FILE", mode_file)

        uniforms: dict[str, float] = {}
        _uniforms._apply_mode_palette_tint(uniforms)

        expected = _uniforms._palette_hint_to_hue_rotate(PALETTE_HINT[WorkingMode.RND])
        assert uniforms["color.hue_rotate"] == pytest.approx(expected)

    def test_homage_damping_called_after_overrides_mode_tint(self) -> None:
        """Composition pin: when mode tint runs first and homage damping
        runs second (matching the production order in `write_uniforms`),
        homage's hue_rotate is the final value. This is the explicit
        precedence the cc-task requires — homage is authoritative.
        """
        uniforms: dict[str, float] = {}
        _uniforms._apply_mode_palette_tint(
            uniforms, bias_provider=lambda: _bias_for(WorkingMode.RESEARCH)
        )
        # Mode tint wrote a research value.
        assert uniforms["color.hue_rotate"] < 0
        # Now homage applies — BitchX overrides.
        _uniforms._apply_homage_package_damping(
            uniforms,
            {"package": "bitchx", "palette_accent_hue_deg": 180.0},
        )
        # Homage value wins.
        assert uniforms["color.hue_rotate"] == pytest.approx(180.0)


# ── module-export pin ───────────────────────────────────────────────


def test_module_exports() -> None:
    """Future refactors must keep these helpers importable."""
    from agents.reverie._uniforms import (  # noqa: F401
        _apply_mode_palette_tint,
        _palette_hint_to_hue_rotate,
        _rgb_to_hsv_hue,
    )

    assert callable(_apply_mode_palette_tint)
    assert callable(_palette_hint_to_hue_rotate)
    assert callable(_rgb_to_hsv_hue)


# pytest-fixture-warning suppressor (mirrors test_layout_switcher_periodic_driver)
@pytest.fixture
def _placeholder() -> Any:
    return None

"""Tests for the palette family primitives (video-container Phase 2)."""

from __future__ import annotations

import pytest

from shared.palette_family import (
    PaletteChain,
    PaletteChainStep,
    PaletteResponseCurve,
    ScrimPalette,
)


class TestPaletteResponseCurve:
    def test_default_is_identity(self):
        curve = PaletteResponseCurve()
        assert curve.mode == "identity"
        assert curve.params == {}
        assert curve.preserve_luminance is False
        assert curve.clip_s_curve is None

    def test_lab_shift_params_accepted(self):
        curve = PaletteResponseCurve(
            mode="lab_shift",
            params={"delta_l": 5.0, "delta_a": -3.0, "delta_b": 2.0},
        )
        assert curve.mode == "lab_shift"
        assert curve.params["delta_l"] == 5.0

    def test_frozen_rejects_mutation(self):
        curve = PaletteResponseCurve()
        with pytest.raises((AttributeError, ValueError, TypeError)):
            curve.mode = "lab_shift"  # type: ignore[misc]

    def test_rejects_unknown_mode(self):
        with pytest.raises(Exception, match="mode"):
            PaletteResponseCurve(mode="unknown")  # type: ignore[arg-type]


class TestScrimPalette:
    def _minimal(self, palette_id: str = "sage-morning") -> ScrimPalette:
        return ScrimPalette(
            id=palette_id,
            display_name="Sage Morning",
            semantic_tags=("warm", "dawn", "sage"),
            warmth_axis=0.3,
            saturation_axis=0.4,
            lightness_axis=0.2,
            dominant_lab=(68.0, -8.0, 14.0),
            accent_lab=(55.0, 6.0, 18.0),
        )

    def test_minimal_instance(self):
        p = self._minimal()
        assert p.id == "sage-morning"
        assert p.temporal_profile == "steady"
        assert p.working_mode_affinity == ("any",)

    def test_equality_by_id(self):
        a = self._minimal("x")
        b = ScrimPalette(
            id="x",
            display_name="Different Name",
            semantic_tags=("cool",),  # different tags, same id
        )
        assert a == b
        assert hash(a) == hash(b)

    def test_axes_clamp_enforced(self):
        with pytest.raises(Exception, match="warmth_axis|less than|greater than"):
            ScrimPalette(id="x", display_name="X", warmth_axis=2.0)

    def test_affinity_default_any(self):
        p = self._minimal()
        assert "any" in p.working_mode_affinity

    def test_frozen(self):
        p = self._minimal()
        with pytest.raises((AttributeError, ValueError, TypeError)):
            p.display_name = "Mutated"  # type: ignore[misc]


class TestPaletteChain:
    def test_single_step_chain(self):
        chain = PaletteChain(
            id="solo",
            display_name="Solo",
            steps=(PaletteChainStep(palette_id="sage-morning", dwell_s=30.0),),
        )
        assert len(chain.steps) == 1
        assert chain.loop is True  # default

    def test_multi_step_chain(self):
        steps = (
            PaletteChainStep(palette_id="dawn", dwell_s=60.0, transition_s=3.0),
            PaletteChainStep(palette_id="midday", dwell_s=120.0, transition_s=2.0),
            PaletteChainStep(palette_id="dusk", dwell_s=60.0, transition_s=5.0),
        )
        chain = PaletteChain(id="day-arc", display_name="Day Arc", steps=steps, loop=False)
        assert len(chain.steps) == 3
        assert chain.loop is False

    def test_empty_steps_rejected(self):
        with pytest.raises(Exception, match="steps"):
            PaletteChain(id="empty", display_name="Empty", steps=())

    def test_swap_with_nonzero_transition_rejected(self):
        with pytest.raises(Exception, match="swap"):
            PaletteChainStep(palette_id="x", dwell_s=1.0, transition_mode="swap", transition_s=0.5)

    def test_swap_with_zero_transition_ok(self):
        step = PaletteChainStep(
            palette_id="x", dwell_s=1.0, transition_mode="swap", transition_s=0.0
        )
        assert step.transition_mode == "swap"

    def test_chain_frozen(self):
        chain = PaletteChain(
            id="x",
            display_name="X",
            steps=(PaletteChainStep(palette_id="a", dwell_s=1.0),),
        )
        with pytest.raises((AttributeError, ValueError, TypeError)):
            chain.id = "mutated"  # type: ignore[misc]

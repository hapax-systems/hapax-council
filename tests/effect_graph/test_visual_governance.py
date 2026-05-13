"""Tests for perception-visual governance."""

from __future__ import annotations


class TestPresetFamily:
    def test_first_available_returns_match(self):
        from agents.effect_graph.types import PresetFamily

        family = PresetFamily(presets=("trails", "ghost", "clean"))
        assert family.first_available({"ghost", "clean"}) == "ghost"

    def test_first_available_returns_first(self):
        from agents.effect_graph.types import PresetFamily

        family = PresetFamily(presets=("trails", "ghost"))
        assert family.first_available({"trails", "ghost"}) == "trails"

    def test_first_available_none_when_empty(self):
        from agents.effect_graph.types import PresetFamily

        family = PresetFamily(presets=("trails",))
        assert family.first_available({"clean"}) is None


class TestAtmosphericSelector:
    def test_nominal_low_energy(self):
        from agents.effect_graph.visual_governance import AtmosphericSelector

        sel = AtmosphericSelector()
        family = sel.select_family(stance="nominal", energy_level="low")
        assert family is not None
        assert len(family.presets) > 0

    def test_critical_always_silhouette(self):
        from agents.effect_graph.visual_governance import AtmosphericSelector

        sel = AtmosphericSelector()
        for level in ("low", "medium", "high"):
            family = sel.select_family(stance="critical", energy_level=level)
            assert "silhouette" in family.presets

    def test_dwell_time_prevents_rapid_change(self):
        from agents.effect_graph.visual_governance import AtmosphericSelector

        sel = AtmosphericSelector()
        first = sel.evaluate(
            stance="nominal",
            energy_level="low",
            available_presets={"clean", "ambient"},
        )
        # Immediately change inputs — should return same preset (dwell)
        second = sel.evaluate(
            stance="nominal",
            energy_level="high",
            available_presets={"feedback_preset", "kaleidodream"},
        )
        assert second == first  # dwell prevents change

    def test_configured_dwell_floor_controls_topology_rotation(self):
        from agents.effect_graph.visual_governance import AtmosphericSelector

        sel = AtmosphericSelector(dwell_min_s=120.0)
        available = {"ghost", "ambient"}
        first = sel.evaluate(
            stance="nominal",
            energy_level="low",
            available_presets=available,
        )

        sel._last_transition -= 31.0
        still_held = sel.evaluate(
            stance="nominal",
            energy_level="low",
            available_presets=available,
        )
        assert still_held == first

        sel._last_transition -= 121.0
        rotated = sel.evaluate(
            stance="nominal",
            energy_level="low",
            available_presets=available,
        )
        assert rotated != first

    def test_stable_context_rotation_can_be_held_without_disabling_response(self):
        from agents.effect_graph.visual_governance import AtmosphericSelector

        sel = AtmosphericSelector(dwell_min_s=0.0, rotate_on_stable=False)
        first = sel.evaluate(
            stance="nominal",
            energy_level="low",
            available_presets={"ghost", "ambient"},
        )

        stable = sel.evaluate(
            stance="nominal",
            energy_level="low",
            available_presets={"ghost", "ambient"},
        )
        assert stable == first

        changed_context = sel.evaluate(
            stance="nominal",
            energy_level="medium",
            available_presets={"kaleidodream", "nightvision"},
        )
        assert changed_context in {"kaleidodream", "nightvision"}
        assert changed_context != first

    def test_stance_change_bypasses_dwell(self):
        from agents.effect_graph.visual_governance import AtmosphericSelector

        sel = AtmosphericSelector()
        sel.evaluate(
            stance="nominal",
            energy_level="low",
            available_presets={"clean", "ambient"},
        )
        second = sel.evaluate(
            stance="critical",
            energy_level="low",
            available_presets={"silhouette"},
        )
        assert second == "silhouette"  # stance change bypasses dwell

    def test_load_failure_clears_optimistic_dwell_hold(self):
        from agents.effect_graph.visual_governance import AtmosphericSelector

        sel = AtmosphericSelector(dwell_min_s=120.0)
        first = sel.evaluate(
            stance="nominal",
            energy_level="low",
            available_presets={"ghost"},
        )
        assert first == "ghost"

        sel.mark_load_failed("ghost")
        second = sel.evaluate(
            stance="nominal",
            energy_level="low",
            available_presets={"ambient"},
        )
        assert second == "ambient"

    def test_energy_level_from_desk_activity(self):
        from agents.effect_graph.visual_governance import energy_level_from_activity

        assert energy_level_from_activity("idle") == "low"
        assert energy_level_from_activity("typing") == "low"
        assert energy_level_from_activity("tapping") == "medium"
        assert energy_level_from_activity("drumming") == "high"
        assert energy_level_from_activity("scratching") == "high"

    def test_nominal_low_yields_diversity_under_repeated_invocation(self):
        """Regression: identical inputs MUST produce >=3 distinct outputs.

        Halftone-monoculture root-cause fix (2026-05-04). The pre-fix
        behaviour was deterministic ``first_available`` — every governance
        tick with ``stance="nominal"``, ``energy_level="low"`` returned the
        same preset (``halftone_preset``). The selector now anti-recency-
        rotates within the loaded family, so 10 consecutive invocations
        against the full ``("nominal", "low")`` family must surface at
        least 3 distinct presets.
        """
        import random as _random

        from agents.effect_graph.visual_governance import (
            _DWELL_MIN_S,
            AtmosphericSelector,
        )

        # Seeded RNG so the test is deterministic; the seed is arbitrary.
        sel = AtmosphericSelector(rng=_random.Random(0xC0FFEE))
        # Full available set so the family-resolution exercises every entry.
        available = {
            "vhs_preset",
            "ghost",
            "ambient",
            "dither_retro",
            "trails",
            "kaleidodream",
            "halftone_preset",
        }
        seen: set[str] = set()
        for _ in range(10):
            target = sel.evaluate(
                stance="nominal",
                energy_level="low",
                available_presets=available,
            )
            if target is not None:
                seen.add(target)
            # Defeat the dwell timer between calls — every invocation must
            # be free to return a new preset, otherwise the test would
            # only measure the first call.
            sel._last_transition -= _DWELL_MIN_S + 1.0
        assert len(seen) >= 3, (
            f"expected >=3 distinct presets across 10 invocations, saw {sorted(seen)!r}"
        )

    def test_default_fallback_is_not_halftone_only(self):
        """Unknown matrix keys must NOT return a halftone-only family."""
        from agents.effect_graph.visual_governance import AtmosphericSelector

        sel = AtmosphericSelector()
        family = sel.select_family(stance="unknown_stance", energy_level="low")
        assert "halftone_preset" not in family.presets or len(family.presets) > 1, (
            f"default fallback must offer alternatives, got {family.presets!r}"
        )

    def test_nominal_low_does_not_lead_with_halftone(self):
        """Halftone must not be the FIRST entry of the dominant family."""
        from agents.effect_graph.visual_governance import AtmosphericSelector

        sel = AtmosphericSelector()
        family = sel.select_family(stance="nominal", energy_level="low")
        assert family.presets[0] != "halftone_preset", (
            f"nominal/low first entry must not be halftone, got {family.presets[0]!r}"
        )

    def test_seeking_rows_present_and_diverse(self):
        """SEEKING stance has explicit rows so fx_tick fold-back is optional."""
        from agents.effect_graph.visual_governance import AtmosphericSelector

        sel = AtmosphericSelector()
        for level in ("low", "medium", "high"):
            family = sel.select_family(stance="seeking", energy_level=level)
            assert len(family.presets) >= 3, (
                f"seeking/{level} should be diverse, got {family.presets!r}"
            )
            assert family.presets[0] != "halftone_preset"


class TestGesturalOffsets:
    def test_scratching_boosts_trail_opacity(self):
        from agents.effect_graph.visual_governance import compute_gestural_offsets

        offsets = compute_gestural_offsets(
            desk_activity="scratching",
            gaze_direction="hardware",
            person_count=1,
        )
        assert ("trail", "opacity") in offsets
        assert offsets[("trail", "opacity")] > 0

    def test_idle_returns_empty(self):
        from agents.effect_graph.visual_governance import compute_gestural_offsets

        offsets = compute_gestural_offsets(
            desk_activity="idle",
            gaze_direction="screen",
            person_count=1,
        )
        assert all(v <= 0 for v in offsets.values()) or len(offsets) == 0

    def test_guest_reduces_intensity(self):
        from agents.effect_graph.visual_governance import compute_gestural_offsets

        alone = compute_gestural_offsets("drumming", "hardware", person_count=1)
        guest = compute_gestural_offsets("drumming", "hardware", person_count=2)
        for key in alone:
            if key in guest:
                assert guest[key] <= alone[key]


class TestBreathingSubstrate:
    def test_perlin_drift_within_range(self):
        from agents.effect_graph.visual_governance import compute_perlin_drift

        for t in [0.0, 1.0, 10.0, 100.0]:
            drift = compute_perlin_drift(t, desk_energy=0.0)
            assert -0.1 < drift < 0.1

    def test_drift_suppressed_by_energy(self):
        from agents.effect_graph.visual_governance import compute_perlin_drift

        quiet = abs(compute_perlin_drift(5.0, desk_energy=0.0))
        loud = abs(compute_perlin_drift(5.0, desk_energy=0.8))
        assert loud < quiet

    def test_idle_escalation(self):
        from agents.effect_graph.visual_governance import compute_idle_escalation

        short = compute_idle_escalation(idle_duration_s=10.0)
        long = compute_idle_escalation(idle_duration_s=300.0)
        assert long > short
        assert short >= 1.0
        assert long <= 3.0

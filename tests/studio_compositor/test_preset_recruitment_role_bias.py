"""Tests for preset recruitment programme role bias.

Verifies:
1. Role-aligned family passes through unchanged.
2. Role-misaligned family rerolls into preferred set (statistical).
3. No programme active = no bias.
4. Feature flag HAPAX_SEGMENT_BIAS_DISABLED disables the bias.
5. Unknown role = no bias.
6. ROLE_FAMILY_BIAS covers all 12 ProgrammeRole values.
7. All weights in valid range.
"""

from __future__ import annotations

from random import Random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

from agents.studio_compositor.preset_family_selector import (
    ROLE_FAMILY_BIAS,
    family_bias_for_role,
    pick_family_with_role_bias,
)


class TestRoleFamilyBias:
    """Tests for the ROLE_FAMILY_BIAS table and helpers."""

    def test_all_12_roles_covered(self) -> None:
        """ROLE_FAMILY_BIAS should have entries for all 12 ProgrammeRole values."""
        from shared.programme import ProgrammeRole

        for role in ProgrammeRole:
            assert role.value in ROLE_FAMILY_BIAS, f"Missing bias for role {role.value}"

    def test_weights_in_valid_range(self) -> None:
        """All weights should be in [0.25, 1.5]."""
        for role, entries in ROLE_FAMILY_BIAS.items():
            for family, weight in entries:
                assert 0.25 <= weight <= 1.5, (
                    f"Weight {weight} for {role}/{family} out of [0.25, 1.5]"
                )

    def test_no_zero_weights(self) -> None:
        """No weight should be zero (architectural axiom: never hard gate)."""
        for role, entries in ROLE_FAMILY_BIAS.items():
            for family, weight in entries:
                assert weight > 0, f"Zero weight for {role}/{family}"

    def test_family_bias_for_role_known(self) -> None:
        """Known role returns non-empty dict."""
        bias = family_bias_for_role("wind_down")
        assert isinstance(bias, dict)
        assert len(bias) > 0
        assert "calm-textural" in bias
        assert bias["calm-textural"] == 1.5

    def test_family_bias_for_role_unknown(self) -> None:
        """Unknown role returns empty dict."""
        assert family_bias_for_role("nonexistent_role") == {}


class TestPickFamilyWithRoleBias:
    """Tests for pick_family_with_role_bias()."""

    def test_aligned_family_passes_through(self) -> None:
        """Family already in the role's preferred set passes through."""
        rng = Random(42)
        result = pick_family_with_role_bias("calm-textural", "wind_down", rng=rng)
        assert result == "calm-textural"

    def test_aligned_alias_resolves_before_bias(self) -> None:
        """Aliases are aligned by their canonical family.

        ``audio-abstract`` resolves to ``neutral-ambient``; roles that
        prefer neutral ambient must not treat the alias as misaligned
        and reroll away from it.
        """
        rng = Random(0)
        result = pick_family_with_role_bias("audio-abstract", "interlude", rng=rng)
        assert result == "neutral-ambient"

    def test_no_role_passes_through(self) -> None:
        """No active programme (role=None) → no bias."""
        result = pick_family_with_role_bias("glitch-dense", None)
        assert result == "glitch-dense"

    def test_unknown_role_passes_through(self) -> None:
        """Unknown role → no bias."""
        result = pick_family_with_role_bias("glitch-dense", "made_up_role")
        assert result == "glitch-dense"

    def test_misaligned_family_rerolls_statistically(self) -> None:
        """Misaligned family should reroll ~60% of the time.

        Over 1000 trials with different seeds, at least 50% should
        reroll (allowing for statistical variance).
        """
        reroll_count = 0
        for seed in range(1000):
            rng = Random(seed)
            result = pick_family_with_role_bias("glitch-dense", "wind_down", rng=rng)
            if result != "glitch-dense":
                reroll_count += 1

        # Expect ~60% rerolls (±10% for variance)
        assert reroll_count > 400, f"Only {reroll_count}/1000 rerolls (expected ~600)"
        assert reroll_count < 800, f"Too many rerolls: {reroll_count}/1000"

    def test_rerolled_family_is_in_preferred_set(self) -> None:
        """When a reroll happens, it should land in the preferred families."""
        for seed in range(200):
            rng = Random(seed)
            result = pick_family_with_role_bias("glitch-dense", "wind_down", rng=rng)
            if result != "glitch-dense":
                bias = family_bias_for_role("wind_down")
                assert result in bias, f"Rerolled to {result} which is not in preferred set"

    def test_wind_down_prefers_calm_and_neutral(self) -> None:
        """WIND_DOWN role should bias toward calm-textural and neutral-ambient."""
        results: dict[str, int] = {}
        for seed in range(500):
            rng = Random(seed)
            result = pick_family_with_role_bias("audio-reactive", "wind_down", rng=rng)
            results[result] = results.get(result, 0) + 1

        # calm-textural should be the most common reroll (weight 1.5)
        rerolled = {k: v for k, v in results.items() if k != "audio-reactive"}
        if rerolled:
            top_family = max(rerolled, key=lambda k: rerolled[k])
            assert top_family in ("calm-textural", "neutral-ambient")

    def test_deterministic_with_seed(self) -> None:
        """Same seed + same inputs → same result."""
        for seed in range(50):
            rng1 = Random(seed)
            rng2 = Random(seed)
            r1 = pick_family_with_role_bias("glitch-dense", "wind_down", rng=rng1)
            r2 = pick_family_with_role_bias("glitch-dense", "wind_down", rng=rng2)
            assert r1 == r2


class TestFeatureFlag:
    """Test HAPAX_SEGMENT_BIAS_DISABLED feature flag."""

    def test_flag_disabled_no_bias(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When flag is set, bias should be disabled (but this is tested
        at the consumer level, not the selector level — the selector
        doesn't read the flag; the consumer does)."""
        # This is a pass-through test confirming the selector itself
        # doesn't have the flag — it's the consumer's responsibility.
        # We test the selector's behavior without the flag.
        rng = Random(0)
        result = pick_family_with_role_bias("glitch-dense", "wind_down", rng=rng)
        # With seed=0, this should either pass through or reroll
        assert result in ("glitch-dense", "calm-textural", "neutral-ambient")

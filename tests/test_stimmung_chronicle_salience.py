"""Tests for chronicle salience tagging on stimmung emit paths.

The chronicle-ticker ward's ``_is_lore_worthy`` helper accepts events
whose payload carries ``salience >= 0.7``. Until this layer landed,
no in-tree emitter was setting that field — every stimmung event
relied on the source-allowlist path. These tests pin the new
salience contract so downstream consumers that rank or filter by
salience get a stable signal.
"""

from __future__ import annotations

import pytest

from shared.stimmung import (
    _STANCE_TRANSITION_SALIENCE,
    dimension_spike_salience,
    stance_transition_salience,
)


class TestDimensionSpikeSalience:
    """``dimension_spike_salience`` maps spike value to [0.7, 1.0]."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            # High-side spike threshold: value=0.7 → 0.5 + 0.2 = 0.7
            (0.7, 0.7),
            # Low-side spike threshold: value=0.3 → 0.5 + 0.2 = 0.7
            (0.3, 0.7),
            # Far high: value=1.0 → 0.5 + 0.5 = 1.0
            (1.0, 1.0),
            # Far low: value=0.0 → 0.5 + 0.5 = 1.0
            (0.0, 1.0),
            # Mid-spike high: value=0.85 → 0.5 + 0.35 = 0.85
            (0.85, 0.85),
            # Mid-spike low: value=0.15 → 0.5 + 0.35 = 0.85
            (0.15, 0.85),
        ],
    )
    def test_value_to_salience(self, value: float, expected: float) -> None:
        assert dimension_spike_salience(value) == expected

    def test_clamped_above_one(self) -> None:
        """Out-of-range upper values clamp to 1.0 (defensive)."""
        assert dimension_spike_salience(1.5) == 1.0

    def test_clamped_above_one_low(self) -> None:
        """Out-of-range lower values still clamp via ``min(1.0, ...)``."""
        assert dimension_spike_salience(-0.5) == 1.0

    def test_meets_chronicle_ticker_floor(self) -> None:
        """Every value in the spike range produces salience >= 0.7."""
        # The chronicle-ticker ward (``_is_lore_worthy``) requires
        # salience >= 0.7 to surface an event without source-allowlist
        # gating. Spikes only fire for value in [0, 0.3] ∪ [0.7, 1.0],
        # so confirm the floor across that range.
        for value in (0.0, 0.05, 0.15, 0.3, 0.7, 0.85, 0.95, 1.0):
            assert dimension_spike_salience(value) >= 0.7


class TestStanceTransitionSalience:
    """``stance_transition_salience`` returns severity-aware floors."""

    def test_critical_top(self) -> None:
        assert stance_transition_salience("critical") == 1.0

    def test_degraded_high(self) -> None:
        assert stance_transition_salience("degraded") == 0.9

    def test_cautious_mid(self) -> None:
        assert stance_transition_salience("cautious") == 0.8

    def test_nominal_floor(self) -> None:
        # Recoveries to nominal still surface, just with lower priority.
        assert stance_transition_salience("nominal") == 0.75

    def test_unknown_stance_uses_default(self) -> None:
        # Any unmapped stance name falls back to 0.85 — still above the
        # 0.7 chronicle-ticker floor.
        assert stance_transition_salience("imaginary-stance") == 0.85

    def test_all_known_stances_meet_floor(self) -> None:
        # Every entry in the canonical stance table must keep the
        # ticker floor; the table is the contract.
        for value in _STANCE_TRANSITION_SALIENCE.values():
            assert value >= 0.7

"""Tests for shared.sheaf_stalks linearisers.

51-LOC stateless linearisers turning /dev/shm JSON traces into
numeric vectors for sheaf computation. Untested before this commit.
"""

from __future__ import annotations

from shared.sheaf_stalks import (
    STANCE_MAP,
    TREND_MAP,
    linearize_imagination,
    linearize_perception,
    linearize_stimmung,
)

# ── Constants pinning ──────────────────────────────────────────────


class TestConstants:
    def test_stance_map_pinned(self) -> None:
        """Pin the canonical stance → numeric mapping."""
        assert STANCE_MAP == {
            "nominal": 0.0,
            "seeking": 0.1,
            "cautious": 0.25,
            "degraded": 0.5,
            "critical": 1.0,
        }

    def test_trend_map_pinned(self) -> None:
        assert TREND_MAP == {"stable": 0.0, "rising": 0.5, "falling": -0.5}


# ── linearize_stimmung ─────────────────────────────────────────────


class TestLinearizeStimmung:
    def test_empty_state_returns_31_zero_vector(self) -> None:
        """10 dims × 3 floats + 1 stance = 31-element vector, all zero
        for an empty state."""
        result = linearize_stimmung({})
        assert len(result) == 31
        assert all(x == 0.0 for x in result)

    def test_dim_value_trend_freshness_serialised(self) -> None:
        result = linearize_stimmung(
            {
                "health": {"value": 0.7, "trend": "rising", "freshness_s": 5.0},
            }
        )
        # First dim (health) is at indices 0,1,2
        assert result[0] == 0.7
        assert result[1] == 0.5  # rising → 0.5
        assert result[2] == 5.0

    def test_unknown_trend_falls_back_to_stable(self) -> None:
        result = linearize_stimmung(
            {"health": {"value": 0.5, "trend": "spiking", "freshness_s": 0.0}}
        )
        assert result[1] == 0.0  # unknown → 0.0 (stable)

    def test_non_dict_dim_treated_as_zero_triple(self) -> None:
        """A non-dict value at a dim slot (e.g. None) zeroes the triple."""
        result = linearize_stimmung({"health": None, "resource_pressure": "weird"})
        assert result[0:3] == [0.0, 0.0, 0.0]
        assert result[3:6] == [0.0, 0.0, 0.0]

    def test_overall_stance_at_last_index(self) -> None:
        result = linearize_stimmung({"overall_stance": "critical"})
        assert result[-1] == 1.0

    def test_unknown_overall_stance_falls_back_to_nominal(self) -> None:
        result = linearize_stimmung({"overall_stance": "transcendent"})
        assert result[-1] == 0.0  # nominal

    def test_string_value_converts_via_float(self) -> None:
        """The impl uses float(...) — numeric strings parse, others raise."""
        result = linearize_stimmung(
            {"health": {"value": "0.42", "trend": "stable", "freshness_s": "3"}}
        )
        assert result[0] == 0.42
        assert result[2] == 3.0


# ── linearize_perception ───────────────────────────────────────────


class TestLinearizePerception:
    def test_full_state(self) -> None:
        result = linearize_perception(
            {
                "presence_probability": 0.85,
                "flow_score": 0.6,
                "audio_energy": 0.3,
                "vad_confidence": 0.95,
                "heart_rate_bpm": 72.0,
            }
        )
        assert result == [0.85, 0.6, 0.3, 0.95, 72.0]

    def test_empty_state_zeroes(self) -> None:
        assert linearize_perception({}) == [0.0, 0.0, 0.0, 0.0, 0.0]

    def test_partial_state(self) -> None:
        result = linearize_perception({"flow_score": 0.5, "heart_rate_bpm": 60})
        assert result == [0.0, 0.5, 0.0, 0.0, 60.0]


# ── linearize_imagination ──────────────────────────────────────────


class TestLinearizeImagination:
    def test_full_state(self) -> None:
        result = linearize_imagination(
            {
                "salience": 0.7,
                "dimensions": {"red": 0.1, "blue": 0.2, "green": 0.3},
                "continuation": True,
            }
        )
        assert result == [0.7, 0.1, 0.2, 0.3, 1.0]

    def test_empty_state(self) -> None:
        """No salience, no dims, no continuation → 5-zero vector."""
        assert linearize_imagination({}) == [0.0, 0.0, 0.0, 0.0, 0.0]

    def test_continuation_false_serialises_zero(self) -> None:
        result = linearize_imagination({"continuation": False})
        assert result[-1] == 0.0

    def test_missing_dims_keys_zeroed(self) -> None:
        """Missing red/blue/green keys default to 0.0 each."""
        result = linearize_imagination(
            {"salience": 0.5, "dimensions": {"red": 1.0}, "continuation": False}
        )
        assert result == [0.5, 1.0, 0.0, 0.0, 0.0]

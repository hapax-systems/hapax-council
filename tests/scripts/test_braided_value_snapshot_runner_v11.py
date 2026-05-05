"""Tests for v1.1 braid-schema dispatch in the braided-value snapshot runner.

Pins the v1.1 formula and the schema-discriminator dispatch from
``cc-readme.md`` braid-overlay section. Backward-compatibility invariant:
any task with ``braid_schema: 1`` (or missing) computes IDENTICALLY to
its pre-v1.1 score.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pytest

RUNNER_PATH = Path(__file__).resolve().parents[2] / "scripts" / "braided_value_snapshot_runner.py"


def _runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("braided_value_snapshot_runner", RUNNER_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ── Schema discriminator ────────────────────────────────────────────────


class TestSchemaDiscriminator:
    def test_missing_schema_routes_to_v1(self) -> None:
        mod = _runner()
        vector = mod.braid_vector_from_frontmatter(
            {
                "braid_engagement": 5,
                "braid_monetary": 5,
                "braid_research": 5,
                "braid_tree_effect": 5,
                "braid_evidence_confidence": 8,
                "braid_risk_penalty": 0.1,
            }
        )
        assert vector.schema == "1"
        assert vector.is_v11 is False

    def test_schema_one_routes_to_v1(self) -> None:
        mod = _runner()
        vector = mod.braid_vector_from_frontmatter({"braid_schema": 1})
        assert vector.schema == "1"
        assert vector.is_v11 is False

    def test_schema_one_dot_one_routes_to_v11(self) -> None:
        mod = _runner()
        vector = mod.braid_vector_from_frontmatter({"braid_schema": 1.1})
        assert vector.schema == "1.1"
        assert vector.is_v11 is True

    def test_schema_string_one_dot_one_routes_to_v11(self) -> None:
        mod = _runner()
        vector = mod.braid_vector_from_frontmatter({"braid_schema": "1.1"})
        assert vector.is_v11 is True

    def test_unknown_schema_falls_back_to_v1(self) -> None:
        mod = _runner()
        vector = mod.braid_vector_from_frontmatter({"braid_schema": "9.99"})
        assert vector.is_v11 is False


# ── v1 formula unchanged (backward-compat) ──────────────────────────────


class TestV1FormulaUnchanged:
    def test_v1_score_identity_after_extension(self) -> None:
        """Pin: v1 formula matches the literal cc-readme.md formula.

        0.35*min(E,M,R) + 0.30*avg(E,M,R) + 0.25*T + 0.10*C - P.
        """

        mod = _runner()
        vector = mod.braid_vector_from_frontmatter(
            {
                "braid_engagement": 7,
                "braid_monetary": 6,
                "braid_research": 9,
                "braid_tree_effect": 8,
                "braid_evidence_confidence": 6,
                "braid_risk_penalty": 1.0,
                "braid_schema": 1,
            }
        )
        # 0.35*6 + 0.30*7.333 + 0.25*8 + 0.10*6 - 1.0
        # = 2.10 + 2.20 + 2.00 + 0.60 - 1.0 = 5.90 (but actually 5.9 round)
        # Recompute exactly: avg = (7+6+9)/3 = 22/3 ≈ 7.3333
        expected = 0.35 * 6 + 0.30 * (22 / 3) + 0.25 * 8 + 0.10 * 6 - 1.0
        result = mod.recompute_braid_score(vector)
        assert result == round(expected, 2)


# ── forcing_function_urgency table ──────────────────────────────────────


class TestForcingFunctionUrgency:
    NOW = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)

    def test_none_returns_zero(self) -> None:
        assert _runner().compute_forcing_function_urgency("none", now=self.NOW) == 0.0

    def test_empty_string_returns_zero(self) -> None:
        assert _runner().compute_forcing_function_urgency("", now=self.NOW) == 0.0

    def test_null_returns_zero(self) -> None:
        assert _runner().compute_forcing_function_urgency(None, now=self.NOW) == 0.0

    def test_far_future_returns_two(self) -> None:
        # > 365 days
        assert (
            _runner().compute_forcing_function_urgency("regulatory:2028-01-01", now=self.NOW) == 2.0
        )

    def test_medium_horizon_returns_five(self) -> None:
        # 90 - 365 days
        assert (
            _runner().compute_forcing_function_urgency("deadline:2026-09-01", now=self.NOW) == 5.0
        )

    def test_near_horizon_returns_eight(self) -> None:
        # 30 - 90 days
        assert (
            _runner().compute_forcing_function_urgency("amplifier_window:2026-06-15", now=self.NOW)
            == 8.0
        )

    def test_imminent_returns_ten(self) -> None:
        # < 30 days
        assert (
            _runner().compute_forcing_function_urgency("regulatory:2026-05-15", now=self.NOW)
            == 10.0
        )

    def test_closed_window_returns_zero(self) -> None:
        # Past date — closed window per spec
        assert (
            _runner().compute_forcing_function_urgency("regulatory:2026-04-01", now=self.NOW) == 0.0
        )

    def test_malformed_window_returns_zero(self) -> None:
        assert _runner().compute_forcing_function_urgency("bogus", now=self.NOW) == 0.0

    def test_invalid_date_returns_zero(self) -> None:
        assert (
            _runner().compute_forcing_function_urgency("regulatory:2026-99-99", now=self.NOW) == 0.0
        )


# ── polysemic_channels validation ──────────────────────────────────────


class TestPolysemicChannels:
    def test_valid_channels_pass_through(self) -> None:
        mod = _runner()
        vector = mod.braid_vector_from_frontmatter({"braid_polysemic_channels": [1, 3, 5, 7]})
        assert vector.polysemic_channels == (1, 3, 5, 7)

    def test_out_of_range_channels_skipped(self) -> None:
        mod = _runner()
        vector = mod.braid_vector_from_frontmatter({"braid_polysemic_channels": [0, 1, 8, 99]})
        # Only 1 is in {1..7}.
        assert vector.polysemic_channels == (1,)

    def test_duplicates_collapsed(self) -> None:
        mod = _runner()
        vector = mod.braid_vector_from_frontmatter({"braid_polysemic_channels": [1, 1, 2, 2, 3]})
        assert vector.polysemic_channels == (1, 2, 3)

    def test_non_integer_entries_skipped(self) -> None:
        mod = _runner()
        vector = mod.braid_vector_from_frontmatter(
            {"braid_polysemic_channels": [1, "two", 3.5, None, 4]}
        )
        assert vector.polysemic_channels == (1, 4)

    def test_all_invalid_returns_none(self) -> None:
        mod = _runner()
        vector = mod.braid_vector_from_frontmatter({"braid_polysemic_channels": [0, 99, "x"]})
        assert vector.polysemic_channels is None

    def test_missing_returns_none(self) -> None:
        mod = _runner()
        vector = mod.braid_vector_from_frontmatter({})
        assert vector.polysemic_channels is None

    def test_non_list_returns_none(self) -> None:
        mod = _runner()
        vector = mod.braid_vector_from_frontmatter({"braid_polysemic_channels": "not-a-list"})
        assert vector.polysemic_channels is None


# ── forcing_function_window validation ─────────────────────────────────


class TestForcingFunctionWindowValidation:
    def test_none_token_passes(self) -> None:
        mod = _runner()
        vector = mod.braid_vector_from_frontmatter({"braid_forcing_function_window": "none"})
        assert vector.forcing_function_window == "none"

    def test_regulatory_passes(self) -> None:
        mod = _runner()
        vector = mod.braid_vector_from_frontmatter(
            {"braid_forcing_function_window": "regulatory:2026-08-02"}
        )
        assert vector.forcing_function_window == "regulatory:2026-08-02"

    def test_malformed_skipped(self) -> None:
        mod = _runner()
        vector = mod.braid_vector_from_frontmatter(
            {"braid_forcing_function_window": "regulatory-2026-08-02"}
        )
        assert vector.forcing_function_window is None


# ── enum field validation ───────────────────────────────────────────────


class TestEnumFields:
    def test_valid_funnel_role_passes(self) -> None:
        mod = _runner()
        vector = mod.braid_vector_from_frontmatter({"braid_funnel_role": "amplifier"})
        assert vector.funnel_role == "amplifier"

    def test_invalid_funnel_role_skipped(self) -> None:
        mod = _runner()
        vector = mod.braid_vector_from_frontmatter({"braid_funnel_role": "made_up"})
        assert vector.funnel_role is None

    def test_valid_compounding_curve_passes(self) -> None:
        mod = _runner()
        vector = mod.braid_vector_from_frontmatter(
            {"braid_compounding_curve": "preferential_attachment"}
        )
        assert vector.compounding_curve == "preferential_attachment"

    def test_invalid_compounding_curve_skipped(self) -> None:
        mod = _runner()
        vector = mod.braid_vector_from_frontmatter({"braid_compounding_curve": "exponential"})
        assert vector.compounding_curve is None


# ── v1.1 formula computation ────────────────────────────────────────────


class TestV11Formula:
    NOW = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)

    def test_v11_with_zero_extras_matches_rebalanced_base(self) -> None:
        """v1.1 task with no v1.1 fields populated: only base weights differ.

        Formula (with extras = 0):
          0.30*min + 0.25*avg + 0.20*T + 0.10*0 + 0.10*0 + 0.05*0 + 0.10*C - P - 0
        """

        mod = _runner()
        vector = mod.braid_vector_from_frontmatter(
            {
                "braid_engagement": 7,
                "braid_monetary": 6,
                "braid_research": 9,
                "braid_tree_effect": 8,
                "braid_evidence_confidence": 6,
                "braid_risk_penalty": 1.0,
                "braid_schema": 1.1,
            }
        )
        expected = 0.30 * 6 + 0.25 * (22 / 3) + 0.20 * 8 + 0.10 * 6 - 1.0
        result = mod.recompute_braid_score(vector, now=self.NOW)
        assert result == round(expected, 2)

    def test_v11_picks_up_unblock_breadth(self) -> None:
        mod = _runner()
        vector = mod.braid_vector_from_frontmatter(
            {
                "braid_engagement": 5,
                "braid_monetary": 5,
                "braid_research": 5,
                "braid_tree_effect": 5,
                "braid_evidence_confidence": 5,
                "braid_risk_penalty": 0.0,
                "braid_unblock_breadth": 9.0,
                "braid_schema": 1.1,
            }
        )
        # 0.30*5 + 0.25*5 + 0.20*5 + 0.10*(9/1.5) + 0.10*5 = 1.5 + 1.25 + 1.0 + 0.6 + 0.5 = 4.85
        expected = 0.30 * 5 + 0.25 * 5 + 0.20 * 5 + 0.10 * (9 / 1.5) + 0.10 * 5
        result = mod.recompute_braid_score(vector, now=self.NOW)
        assert result == round(expected, 2)

    def test_v11_picks_up_polysemic_channel_count(self) -> None:
        mod = _runner()
        vector = mod.braid_vector_from_frontmatter(
            {
                "braid_engagement": 5,
                "braid_monetary": 5,
                "braid_research": 5,
                "braid_tree_effect": 5,
                "braid_evidence_confidence": 5,
                "braid_risk_penalty": 0.0,
                "braid_polysemic_channels": [1, 2, 3, 4, 5, 6, 7],
                "braid_schema": 1.1,
            }
        )
        # +0.10 * 7 = +0.70 for full-channel artifact
        expected = 0.30 * 5 + 0.25 * 5 + 0.20 * 5 + 0.10 * 7 + 0.10 * 5
        result = mod.recompute_braid_score(vector, now=self.NOW)
        assert result == round(expected, 2)

    def test_v11_picks_up_axiomatic_strain_subtractive(self) -> None:
        mod = _runner()
        vector = mod.braid_vector_from_frontmatter(
            {
                "braid_engagement": 5,
                "braid_monetary": 5,
                "braid_research": 5,
                "braid_tree_effect": 5,
                "braid_evidence_confidence": 5,
                "braid_risk_penalty": 0.0,
                "braid_axiomatic_strain": 1.5,
                "braid_schema": 1.1,
            }
        )
        expected = 0.30 * 5 + 0.25 * 5 + 0.20 * 5 + 0.10 * 5 - 1.5
        result = mod.recompute_braid_score(vector, now=self.NOW)
        assert result == round(expected, 2)

    def test_v11_picks_up_forcing_function_urgency(self) -> None:
        mod = _runner()
        vector = mod.braid_vector_from_frontmatter(
            {
                "braid_engagement": 5,
                "braid_monetary": 5,
                "braid_research": 5,
                "braid_tree_effect": 5,
                "braid_evidence_confidence": 5,
                "braid_risk_penalty": 0.0,
                "braid_forcing_function_window": "regulatory:2026-05-15",
                "braid_schema": 1.1,
            }
        )
        # Within 30 days → urgency 10 → +0.05*10 = +0.50
        expected = 0.30 * 5 + 0.25 * 5 + 0.20 * 5 + 0.05 * 10 + 0.10 * 5
        result = mod.recompute_braid_score(vector, now=self.NOW)
        assert result == round(expected, 2)


# ── Incomplete-vector returns None ──────────────────────────────────────


class TestIncompleteVector:
    def test_v1_incomplete_returns_none(self) -> None:
        mod = _runner()
        vector = mod.braid_vector_from_frontmatter({"braid_engagement": 5, "braid_schema": 1})
        assert mod.recompute_braid_score(vector) is None

    def test_v11_incomplete_returns_none(self) -> None:
        mod = _runner()
        vector = mod.braid_vector_from_frontmatter({"braid_engagement": 5, "braid_schema": 1.1})
        assert mod.recompute_braid_score(vector) is None


# ── as_dict round-trip ────────────────────────────────────────────────


class TestAsDictRoundTrip:
    def test_v11_fields_appear_in_dict(self) -> None:
        mod = _runner()
        vector = mod.braid_vector_from_frontmatter(
            {
                "braid_engagement": 5,
                "braid_monetary": 5,
                "braid_research": 5,
                "braid_tree_effect": 5,
                "braid_evidence_confidence": 5,
                "braid_risk_penalty": 0.5,
                "braid_schema": 1.1,
                "braid_forcing_function_window": "deadline:2026-12-01",
                "braid_unblock_breadth": 4.5,
                "braid_polysemic_channels": [2, 4, 6],
                "braid_funnel_role": "inbound",
                "braid_compounding_curve": "log_saturating",
                "braid_axiomatic_strain": 0.3,
            }
        )
        result = vector.as_dict()
        assert result["schema"] == "1.1"
        assert result["forcing_function_window"] == "deadline:2026-12-01"
        assert result["unblock_breadth"] == 4.5
        assert result["polysemic_channels"] == [2, 4, 6]
        assert result["funnel_role"] == "inbound"
        assert result["compounding_curve"] == "log_saturating"
        assert result["axiomatic_strain"] == pytest.approx(0.3)

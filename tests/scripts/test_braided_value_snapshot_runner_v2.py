"""Tests for v2.0 braid-schema dispatch in the braided-value snapshot runner.

Pins the v2.0 5-layer composition formula and the schema-discriminator
dispatch from
``docs/superpowers/specs/2026-05-04-braid-v2-and-wsjf-expansion-design.md``.

Backward-compatibility invariant: any task with ``braid_schema: 1`` (or
missing) computes IDENTICALLY to its pre-v1.1 score; ``braid_schema:
1.1`` computes IDENTICALLY to its v1.1 score; only ``braid_schema: 2``
(or ``2.0``) selects the new pipeline.
"""

from __future__ import annotations

import importlib.util
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

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


class TestSchemaDispatchV2:
    def test_schema_two_int_routes_to_v2(self) -> None:
        mod = _runner()
        vector = mod.braid_vector_from_frontmatter({"braid_schema": 2})
        assert vector.schema == "2"
        assert vector.is_v2 is True
        assert vector.is_v11 is False

    def test_schema_two_float_routes_to_v2(self) -> None:
        mod = _runner()
        vector = mod.braid_vector_from_frontmatter({"braid_schema": 2.0})
        assert vector.is_v2 is True

    def test_schema_string_two_routes_to_v2(self) -> None:
        mod = _runner()
        vector = mod.braid_vector_from_frontmatter({"braid_schema": "2"})
        assert vector.is_v2 is True

    def test_schema_string_two_dot_zero_routes_to_v2(self) -> None:
        mod = _runner()
        vector = mod.braid_vector_from_frontmatter({"braid_schema": "2.0"})
        assert vector.is_v2 is True

    def test_unknown_schema_falls_back_to_v1(self) -> None:
        mod = _runner()
        vector = mod.braid_vector_from_frontmatter({"braid_schema": "9.99"})
        assert vector.is_v2 is False
        assert vector.is_v11 is False


# ── Backward-compat — v1 + v1.1 unchanged ───────────────────────────────


class TestBackwardCompatibility:
    NOW = datetime(2026, 5, 4, 12, 0, tzinfo=UTC)

    def _v1_dimensions(self) -> dict[str, object]:
        return {
            "braid_engagement": 7,
            "braid_monetary": 6,
            "braid_research": 9,
            "braid_tree_effect": 8,
            "braid_evidence_confidence": 6,
            "braid_risk_penalty": 1.0,
            "braid_schema": 1,
        }

    def test_v1_unchanged_after_v2_added(self) -> None:
        mod = _runner()
        vector = mod.braid_vector_from_frontmatter(self._v1_dimensions())
        result = mod.recompute_braid_score(vector, now=self.NOW)
        # v1 formula: 0.35*min + 0.30*avg + 0.25*T + 0.10*C - P
        expected = 0.35 * 6 + 0.30 * (22 / 3) + 0.25 * 8 + 0.10 * 6 - 1.0
        assert result == round(expected, 2)

    def test_v11_unchanged_after_v2_added(self) -> None:
        mod = _runner()
        dims = self._v1_dimensions()
        dims["braid_schema"] = 1.1
        vector = mod.braid_vector_from_frontmatter(dims)
        result = mod.recompute_braid_score(vector, now=self.NOW)
        # v1.1 with no v1.1 fields populated: 0.30*min + 0.25*avg + 0.20*T + 0.10*C - P
        expected = 0.30 * 6 + 0.25 * (22 / 3) + 0.20 * 8 + 0.10 * 6 - 1.0
        assert result == round(expected, 2)


# ── CES aggregator ──────────────────────────────────────────────────────


class TestCesAggregate:
    def test_ces_at_rho_one_is_weighted_average(self) -> None:
        mod = _runner()
        result = mod._ces_aggregate([5.0, 10.0, 4.0], [0.40, 0.30, 0.30], rho=1.0)
        expected = 0.40 * 5 + 0.30 * 10 + 0.30 * 4
        assert math.isclose(result, expected, rel_tol=1e-9)

    def test_ces_at_rho_negative_infinity_is_min(self) -> None:
        mod = _runner()
        result = mod._ces_aggregate([5.0, 10.0, 4.0], [0.40, 0.30, 0.30], rho=float("-inf"))
        assert result == 4.0

    def test_ces_at_rho_zero_is_cobb_douglas(self) -> None:
        mod = _runner()
        result = mod._ces_aggregate([5.0, 10.0, 4.0], [0.40, 0.30, 0.30], rho=0.0)
        expected = math.exp(0.40 * math.log(5) + 0.30 * math.log(10) + 0.30 * math.log(4))
        assert math.isclose(result, expected, rel_tol=1e-9)

    def test_ces_negative_rho_zero_input_returns_zero(self) -> None:
        mod = _runner()
        result = mod._ces_aggregate([0.0, 10.0, 4.0], [0.40, 0.30, 0.30], rho=-2.0)
        assert result == 0.0

    def test_ces_default_rho_minus_two_matches_harmonic_form(self) -> None:
        mod = _runner()
        result = mod._ces_aggregate([8.0, 7.0, 9.0], [0.40, 0.30, 0.30], rho=-2.0)
        inner = 0.40 / 64 + 0.30 / 49 + 0.30 / 81
        expected = inner ** (-0.5)
        assert math.isclose(result, expected, rel_tol=1e-9)

    def test_ces_mismatched_lengths_raises(self) -> None:
        mod = _runner()
        with __import__("pytest").raises(ValueError, match="matched values/weights"):
            mod._ces_aggregate([1.0, 2.0], [0.5], rho=-2.0)


# ── Layer 1 gates ───────────────────────────────────────────────────────


class TestLayer1Gates:
    NOW = datetime(2026, 5, 4, 12, 0, tzinfo=UTC)

    def _populated(self, **overrides: object) -> dict[str, object]:
        base: dict[str, object] = {
            "braid_engagement": 7,
            "braid_monetary": 6,
            "braid_research": 9,
            "braid_tree_effect": 8,
            "braid_evidence_confidence": 6,
            "braid_risk_penalty": 0.0,
            "braid_schema": 2,
        }
        base.update(overrides)
        return base

    def test_deny_wins_returns_none(self) -> None:
        mod = _runner()
        vector = mod.braid_vector_from_frontmatter(self._populated(braid_deny_wins=True))
        assert mod.recompute_braid_score(vector, now=self.NOW) is None

    def test_strain_three_returns_none(self) -> None:
        mod = _runner()
        vector = mod.braid_vector_from_frontmatter(self._populated(braid_axiomatic_strain=3.0))
        assert mod.recompute_braid_score(vector, now=self.NOW) is None

    def test_strain_two_does_not_gate(self) -> None:
        mod = _runner()
        vector = mod.braid_vector_from_frontmatter(self._populated(braid_axiomatic_strain=2.0))
        assert mod.recompute_braid_score(vector, now=self.NOW) is not None

    def test_forcing_zero_deadline_returns_none(self) -> None:
        # Deadline within 30 days of NOW = urgency 10 → gate fires.
        mod = _runner()
        vector = mod.braid_vector_from_frontmatter(
            self._populated(braid_forcing_function_window="regulatory:2026-05-15")
        )
        assert mod.recompute_braid_score(vector, now=self.NOW) is None

    def test_mode_ceiling_public_with_strain_one_gates(self) -> None:
        mod = _runner()
        vector = mod.braid_vector_from_frontmatter(
            self._populated(
                braid_mode_ceiling="public_archive",
                braid_axiomatic_strain=1.0,
            )
        )
        assert mod.recompute_braid_score(vector, now=self.NOW) is None

    def test_mode_ceiling_public_with_strain_zero_does_not_gate(self) -> None:
        mod = _runner()
        vector = mod.braid_vector_from_frontmatter(
            self._populated(
                braid_mode_ceiling="public_archive",
                braid_axiomatic_strain=0.0,
            )
        )
        assert mod.recompute_braid_score(vector, now=self.NOW) is not None

    def test_max_public_claim_below_target_gates(self) -> None:
        mod = _runner()
        vector = mod.braid_vector_from_frontmatter(
            self._populated(
                braid_max_public_claim="research-only",
                braid_target_deposit_tier="public-live",
            )
        )
        assert mod.recompute_braid_score(vector, now=self.NOW) is None

    def test_max_public_claim_dominates_target_does_not_gate(self) -> None:
        mod = _runner()
        vector = mod.braid_vector_from_frontmatter(
            self._populated(
                braid_max_public_claim="public-live",
                braid_target_deposit_tier="public-archive",
            )
        )
        assert mod.recompute_braid_score(vector, now=self.NOW) is not None


# ── Layers 2-5 composition ──────────────────────────────────────────────


class TestV2FullPipeline:
    NOW = datetime(2026, 5, 4, 12, 0, tzinfo=UTC)

    def test_full_pipeline_matches_design_formula(self) -> None:
        """Sample task end-to-end: refusal-brief-style frontmatter."""

        mod = _runner()
        vector = mod.braid_vector_from_frontmatter(
            {
                "braid_engagement": 8,
                "braid_monetary": 7,
                "braid_research": 9,
                "braid_tree_effect": 9,
                "braid_evidence_confidence": 8,
                "braid_risk_penalty": 0.5,
                "braid_unblock_breadth": 3.0,
                "braid_polysemic_channels": [1, 2, 3, 4, 5, 6, 7],
                "braid_forcing_function_window": "amplifier_window:2026-06-15",
                "braid_axiomatic_strain": 0.0,
                "braid_schema": 2,
            }
        )

        inner = 0.40 / 64 + 0.30 / 49 + 0.30 / 81
        core = inner ** (-0.5)

        urgency = mod.compute_forcing_function_urgency("amplifier_window:2026-06-15", now=self.NOW)
        bonuses = 0.20 * 9 + 0.10 * (3.0 / 1.5) + 0.10 * (7**1.3) + 0.05 * urgency
        penalties = 0.5 + 0.0
        raw = core + bonuses - penalties
        expected = raw * (8.0 / 10.0) * 1.0

        result = mod.recompute_braid_score(vector, now=self.NOW)
        assert result == round(expected, 2)

    def test_witness_freshness_zero_zeros_score(self) -> None:
        mod = _runner()
        vector = mod.braid_vector_from_frontmatter(
            {
                "braid_engagement": 8,
                "braid_monetary": 7,
                "braid_research": 9,
                "braid_tree_effect": 9,
                "braid_evidence_confidence": 8,
                "braid_risk_penalty": 0.0,
                "braid_witness_freshness": 0.0,
                "braid_schema": 2,
            }
        )
        result = mod.recompute_braid_score(vector, now=self.NOW)
        assert result == 0.0

    def test_zero_engagement_zeros_core_under_negative_rho(self) -> None:
        mod = _runner()
        vector = mod.braid_vector_from_frontmatter(
            {
                "braid_engagement": 0,
                "braid_monetary": 10,
                "braid_research": 10,
                "braid_tree_effect": 5,
                "braid_evidence_confidence": 5,
                "braid_risk_penalty": 0.0,
                "braid_schema": 2,
            }
        )
        result = mod.recompute_braid_score(vector, now=self.NOW)
        # core=0; bonuses=0.20*5=1.0; penalties=0; raw=1.0; × 0.5 (C/10) = 0.5
        assert result == 0.5

    def test_no_polysemic_channels_zeros_polysemic_term(self) -> None:
        mod = _runner()
        vector = mod.braid_vector_from_frontmatter(
            {
                "braid_engagement": 5,
                "braid_monetary": 5,
                "braid_research": 5,
                "braid_tree_effect": 0,
                "braid_evidence_confidence": 10,
                "braid_risk_penalty": 0.0,
                "braid_schema": 2,
            }
        )
        result = mod.recompute_braid_score(vector, now=self.NOW)
        # CES with E=M=R=5 yields exactly 5 regardless of ρ; no bonuses; 5 × 1.0 = 5.0
        assert result == 5.0

    def test_strain_two_subtracts_full_value(self) -> None:
        mod = _runner()
        vector = mod.braid_vector_from_frontmatter(
            {
                "braid_engagement": 10,
                "braid_monetary": 10,
                "braid_research": 10,
                "braid_tree_effect": 0,
                "braid_evidence_confidence": 10,
                "braid_risk_penalty": 0.0,
                "braid_axiomatic_strain": 2.0,
                "braid_schema": 2,
            }
        )
        result = mod.recompute_braid_score(vector, now=self.NOW)
        # core=10; bonuses=0; penalties=0+2=2; raw=8; × 1.0 = 8.0
        assert result == 8.0


# ── SPEC_AUTO_GTM_PREDICTIONS_V2 sanity ─────────────────────────────────


class TestSpecAutoGtmPredictionsV2Sanity:
    """Confirm the hardcoded prediction table reproduces under the formula."""

    NOW = datetime(2026, 5, 1, 15, 10, tzinfo=UTC)

    # Per-task frontmatter dimensions matching the spec §3.6 worked-examples table.
    _FIXTURES: dict[str, dict[str, object]] = {
        "wyoming-llc-dba-legal-entity-bootstrap": {
            "E": 5,
            "M": 10,
            "R": 4,
            "T": 10,
            "C": 9,
            "U": 12,
            "channels": [1],
            "window": "none",
            "P": 0.3,
            "strain": 0,
        },
        "citable-nexus-front-door-static-site": {
            "E": 8,
            "M": 7,
            "R": 8,
            "T": 9,
            "C": 8,
            "U": 4,
            "channels": [1, 2, 3],
            "window": "none",
            "P": 0.3,
            "strain": 0,
        },
        "publication-bus-monetization-rails-surfaces": {
            "E": 6,
            "M": 9,
            "R": 5,
            "T": 8,
            "C": 8,
            "U": 5,
            "channels": [1, 2],
            "window": "none",
            "P": 0.4,
            "strain": 0,
        },
        "immediate-q2-2026-grant-submission-batch": {
            "E": 6,
            "M": 8,
            "R": 9,
            "T": 6,
            "C": 7,
            "U": 2,
            "channels": [1],
            "window": "deadline:2026-06-01",
            "P": 0.5,
            "strain": 0,
        },
        "refusal-brief-article-50-case-study": {
            "E": 8,
            "M": 7,
            "R": 9,
            "T": 9,
            "C": 8,
            "U": 3,
            "channels": [1, 2, 3, 4, 5, 6, 7],
            "window": "amplifier_window:2026-06-15",
            "P": 0.5,
            "strain": 0,
        },
        "eu-ai-act-art-50-c2pa-watermark-fingerprint-mvp": {
            "E": 6,
            "M": 10,
            "R": 7,
            "T": 8,
            "C": 7,
            "U": 3,
            "channels": [1, 2],
            "window": "regulatory:2026-08-02",
            "P": 0.7,
            "strain": 0,
        },
        "auto-clip-shorts-livestream-pipeline": {
            "E": 9,
            "M": 7,
            "R": 4,
            "T": 6,
            "C": 7,
            "U": 1,
            "channels": [1, 2, 3, 4, 5, 6],
            "window": "none",
            "P": 0.4,
            "strain": 0,
        },
    }

    def test_predictions_table_reproduces_under_formula(self) -> None:
        mod = _runner()
        for task_id, predicted in mod.SPEC_AUTO_GTM_PREDICTIONS_V2.items():
            fixture = self._FIXTURES[task_id]
            vector = mod.braid_vector_from_frontmatter(
                {
                    "braid_engagement": fixture["E"],
                    "braid_monetary": fixture["M"],
                    "braid_research": fixture["R"],
                    "braid_tree_effect": fixture["T"],
                    "braid_evidence_confidence": fixture["C"],
                    "braid_unblock_breadth": fixture["U"],
                    "braid_polysemic_channels": fixture["channels"],
                    "braid_forcing_function_window": fixture["window"],
                    "braid_risk_penalty": fixture["P"],
                    "braid_axiomatic_strain": fixture["strain"],
                    "braid_schema": 2,
                }
            )
            computed = mod.recompute_braid_score(vector, now=self.NOW)
            assert computed is not None, f"{task_id} unexpectedly gated"
            assert abs(computed - predicted) <= 0.01, (
                f"{task_id}: computed={computed} predicted={predicted}"
            )

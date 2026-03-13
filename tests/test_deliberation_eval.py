"""Tests for deliberation metric extraction, storage, and sufficiency probes."""

from __future__ import annotations

from pathlib import Path

import pytest

from shared.deliberation_metrics import (
    DeliberationMetrics,
    HoopTestResults,
    append_metrics,
    compute_concession_asymmetry,
    extract_activation_rate,
    extract_concession_counts,
    extract_metrics,
    extract_position_movement,
    extract_responsive_reference_rate,
    read_recent_metrics,
    run_hoop_tests,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────


def _make_early_convergence_record() -> dict:
    """1 round, no conditions checked — early convergence."""
    return {
        "id": "deliberation-early-001",
        "rounds": [
            {"round": 1, "agent": "publius", "position": "They agree."},
            {"round": 1, "agent": "brutus", "position": "I also agree."},
        ],
        "publius_final": {
            "concessions_made": [],
            "final_position_movement": "converged in round 1",
        },
        "brutus_final": {
            "concessions_made": [],
            "final_position_movement": "converged in round 1",
        },
        "process_metadata": {
            "total_rounds": 1,
            "total_concessions": 0,
            "termination": "early_convergence",
        },
    }


def _make_full_deliberation_record(
    *,
    publius_conditions_met: list[bool] | None = None,
    brutus_conditions_met: list[bool] | None = None,
    publius_concessions: list[str] | None = None,
    brutus_concessions: list[str] | None = None,
    publius_movement: str = "Refined position on X",
    brutus_movement: str = "Partial convergence on Y",
    publius_claims_attacked: list[dict] | None = None,
    brutus_claims_attacked: list[dict] | None = None,
) -> dict:
    """Configurable 4-round record."""
    if publius_conditions_met is None:
        publius_conditions_met = [True, False, False]
    if brutus_conditions_met is None:
        brutus_conditions_met = [False, False, False]
    if publius_concessions is None:
        publius_concessions = ["Conceded point A"]
    if brutus_concessions is None:
        brutus_concessions = ["Conceded point B"]
    if publius_claims_attacked is None:
        publius_claims_attacked = [
            {"claim": "X is wrong", "attack": "X is right because...", "attack_type": "rebutting"}
        ]
    if brutus_claims_attacked is None:
        brutus_claims_attacked = [
            {"claim": "Y is wrong", "attack": "Y is right because...", "attack_type": "undercutting"}
        ]

    def _make_conditions(met_list: list[bool]) -> list[dict]:
        return [
            {"condition": f"If opponent argues point {i}", "met": m, "reasoning": f"Because {i}"}
            for i, m in enumerate(met_list)
        ]

    return {
        "id": "deliberation-full-001",
        "rounds": [
            {"round": 1, "agent": "publius", "position": "Initial pub position"},
            {"round": 1, "agent": "brutus", "position": "Initial bru position"},
            {
                "round": 2,
                "agent": "brutus",
                "responds_to": "round 1",
                "claims_attacked": brutus_claims_attacked,
                "update_conditions_checked": _make_conditions(brutus_conditions_met),
                "concessions": [],
                "position_movement": "no movement",
            },
            {
                "round": 3,
                "agent": "publius",
                "responds_to": "round 2",
                "claims_attacked": publius_claims_attacked,
                "update_conditions_checked": _make_conditions(publius_conditions_met),
                "concessions": publius_concessions,
                "position_movement": publius_movement,
            },
            {
                "round": 4,
                "agent": "brutus",
                "responds_to": "round 3",
                "claims_attacked": brutus_claims_attacked,
                "update_conditions_checked": _make_conditions(brutus_conditions_met),
                "concessions": brutus_concessions,
                "position_movement": brutus_movement,
            },
        ],
        "publius_final": {
            "concessions_made": publius_concessions,
            "final_position_movement": publius_movement,
        },
        "brutus_final": {
            "concessions_made": brutus_concessions,
            "final_position_movement": brutus_movement,
        },
        "process_metadata": {
            "total_rounds": 4,
            "total_concessions": len(publius_concessions) + len(brutus_concessions),
            "termination": "round_limit",
        },
    }


# ── TestActivationRate ───────────────────────────────────────────────────────


class TestActivationRate:
    def test_early_convergence_zero(self):
        record = _make_early_convergence_record()
        overall, pub, bru = extract_activation_rate(record)
        assert overall == 0.0
        assert pub == 0.0
        assert bru == 0.0

    def test_mixed_conditions(self):
        record = _make_full_deliberation_record(
            publius_conditions_met=[True, False, False],
            brutus_conditions_met=[False, False, False],
        )
        overall, pub, bru = extract_activation_rate(record)
        assert pub == pytest.approx(1 / 3)
        assert bru == 0.0
        assert overall == pytest.approx(1 / 9)

    def test_all_met(self):
        record = _make_full_deliberation_record(
            publius_conditions_met=[True, True, True],
            brutus_conditions_met=[True, True, True],
        )
        overall, pub, bru = extract_activation_rate(record)
        assert overall == 1.0
        assert pub == 1.0
        assert bru == 1.0

    def test_per_agent_decomposition(self):
        record = _make_full_deliberation_record(
            publius_conditions_met=[True, True, False],
            brutus_conditions_met=[False, False, True],
        )
        overall, pub, bru = extract_activation_rate(record)
        assert pub == pytest.approx(2 / 3)
        assert bru == pytest.approx(2 / 6)


# ── TestConcessionCounts ─────────────────────────────────────────────────────


class TestConcessionCounts:
    def test_zero_concessions(self):
        record = _make_early_convergence_record()
        total, pub, bru = extract_concession_counts(record)
        assert total == 0
        assert pub == 0
        assert bru == 0

    def test_asymmetric(self):
        record = _make_full_deliberation_record(
            publius_concessions=["A", "B", "C"],
            brutus_concessions=["D"],
        )
        total, pub, bru = extract_concession_counts(record)
        assert total == 4
        assert pub == 3
        assert bru == 1

    def test_symmetric(self):
        record = _make_full_deliberation_record(
            publius_concessions=["A", "B"],
            brutus_concessions=["C", "D"],
        )
        total, pub, bru = extract_concession_counts(record)
        assert total == 4
        assert pub == 2
        assert bru == 2


# ── TestConcessionAsymmetry ──────────────────────────────────────────────────


class TestConcessionAsymmetry:
    def test_both_zero(self):
        assert compute_concession_asymmetry(0, 0) == 1.0

    def test_one_zero(self):
        assert compute_concession_asymmetry(3, 0) == 99.0
        assert compute_concession_asymmetry(0, 5) == 99.0

    def test_equal(self):
        assert compute_concession_asymmetry(4, 4) == 1.0

    def test_skewed(self):
        assert compute_concession_asymmetry(6, 2) == 3.0
        assert compute_concession_asymmetry(1, 3) == 3.0


# ── TestResponsiveReference ──────────────────────────────────────────────────


class TestResponsiveReference:
    def test_early_convergence_zero(self):
        record = _make_early_convergence_record()
        assert extract_responsive_reference_rate(record) == 0.0

    def test_all_responsive(self):
        record = _make_full_deliberation_record()
        rate = extract_responsive_reference_rate(record)
        assert rate == 1.0

    def test_partial(self):
        record = _make_full_deliberation_record()
        record["rounds"][2]["claims_attacked"] = []
        rate = extract_responsive_reference_rate(record)
        assert rate == pytest.approx(2 / 3)


# ── TestPositionMovement ─────────────────────────────────────────────────────


class TestPositionMovement:
    def test_converged(self):
        record = _make_early_convergence_record()
        pub, bru = extract_position_movement(record)
        assert pub is False
        assert bru is False

    def test_both_moved(self):
        record = _make_full_deliberation_record(
            publius_movement="Refined position",
            brutus_movement="Partial convergence",
        )
        pub, bru = extract_position_movement(record)
        assert pub is True
        assert bru is True

    def test_no_movement_string(self):
        record = _make_full_deliberation_record(
            publius_movement="no movement",
            brutus_movement="Adjusted stance on X",
        )
        pub, bru = extract_position_movement(record)
        assert pub is False
        assert bru is True


# ── TestHoopTests ────────────────────────────────────────────────────────────


class TestHoopTests:
    def test_early_convergence_fails_all(self):
        record = _make_early_convergence_record()
        ht = run_hoop_tests(record)
        assert ht.position_shift is False
        assert ht.argument_tracing is False
        assert ht.counterfactual_divergence is False

    def test_full_deliberation_with_movement_passes(self):
        record = _make_full_deliberation_record(
            publius_conditions_met=[True, False, False],
        )
        ht = run_hoop_tests(record)
        assert ht.position_shift is True
        assert ht.argument_tracing is True
        assert ht.counterfactual_divergence is True

    def test_no_conditions_met_fails_counterfactual(self):
        record = _make_full_deliberation_record(
            publius_conditions_met=[False, False, False],
            brutus_conditions_met=[False, False, False],
        )
        ht = run_hoop_tests(record)
        assert ht.position_shift is True
        assert ht.argument_tracing is True
        assert ht.counterfactual_divergence is False


# ── TestExtractMetrics (integration) ─────────────────────────────────────────


class TestExtractMetrics:
    def test_early_convergence_not_pseudo(self):
        record = _make_early_convergence_record()
        m = extract_metrics(record)
        assert m.is_pseudo_deliberation is False
        assert m.termination_type == "early_convergence"

    def test_healthy_full_deliberation(self):
        record = _make_full_deliberation_record(
            publius_conditions_met=[True, False, False],
        )
        m = extract_metrics(record)
        assert m.activation_rate > 0
        assert m.hoop_tests is not None
        assert m.is_pseudo_deliberation is False

    def test_pseudo_deliberation_detected(self):
        record = _make_full_deliberation_record(
            publius_conditions_met=[False, False, False],
            brutus_conditions_met=[False, False, False],
            publius_movement="no movement",
            brutus_movement="no movement",
            publius_claims_attacked=[],
            brutus_claims_attacked=[],
        )
        m = extract_metrics(record)
        assert m.is_pseudo_deliberation is True


# ── TestJSONLStorage ─────────────────────────────────────────────────────────


class TestJSONLStorage:
    def test_append_and_read(self, tmp_path: Path):
        jsonl = tmp_path / "test-eval.jsonl"
        m1 = extract_metrics(_make_early_convergence_record())
        m2 = extract_metrics(_make_full_deliberation_record())

        append_metrics(m1, jsonl)
        append_metrics(m2, jsonl)

        results = read_recent_metrics(jsonl, n=10)
        assert len(results) == 2
        assert results[0].deliberation_id == "deliberation-early-001"
        assert results[1].deliberation_id == "deliberation-full-001"

    def test_empty_file(self, tmp_path: Path):
        jsonl = tmp_path / "empty.jsonl"
        jsonl.write_text("")
        assert read_recent_metrics(jsonl) == []

    def test_missing_file(self, tmp_path: Path):
        jsonl = tmp_path / "nonexistent.jsonl"
        assert read_recent_metrics(jsonl) == []

    def test_tail_read(self, tmp_path: Path):
        jsonl = tmp_path / "test-eval.jsonl"
        for i in range(10):
            record = _make_early_convergence_record()
            record["id"] = f"deliberation-{i:03d}"
            append_metrics(extract_metrics(record), jsonl)

        results = read_recent_metrics(jsonl, n=3)
        assert len(results) == 3
        assert results[0].deliberation_id == "deliberation-007"
        assert results[2].deliberation_id == "deliberation-009"

    def test_roundtrip_preserves_hoop_tests(self, tmp_path: Path):
        jsonl = tmp_path / "hoop.jsonl"
        record = _make_full_deliberation_record(publius_conditions_met=[True, False, False])
        m = extract_metrics(record)
        append_metrics(m, jsonl)

        results = read_recent_metrics(jsonl)
        assert len(results) == 1
        assert results[0].hoop_tests is not None
        assert results[0].hoop_tests.position_shift is True
        assert results[0].hoop_tests.counterfactual_divergence is True


# ── TestSufficiencyProbes ────────────────────────────────────────────────────


class TestSufficiencyProbes:
    """Test that probes produce correct results given known JSONL state."""

    def test_hoop_test_probe_passes_with_good_data(self, tmp_path: Path, monkeypatch):
        jsonl = tmp_path / "eval.jsonl"
        # 3 good multi-round deliberations
        for i in range(3):
            record = _make_full_deliberation_record(publius_conditions_met=[True, False, False])
            record["id"] = f"delib-{i}"
            append_metrics(extract_metrics(record), jsonl)

        monkeypatch.setattr("shared.deliberation_metrics.EVAL_FILE", jsonl)

        from shared.sufficiency_probes import _check_deliberation_hoop_tests

        met, evidence = _check_deliberation_hoop_tests()
        assert met is True

    def test_hoop_test_probe_fails_with_pseudo(self, tmp_path: Path, monkeypatch):
        jsonl = tmp_path / "eval.jsonl"
        # 3 pseudo-deliberations
        for i in range(3):
            record = _make_full_deliberation_record(
                publius_conditions_met=[False, False, False],
                brutus_conditions_met=[False, False, False],
                publius_movement="no movement",
                brutus_movement="no movement",
                publius_claims_attacked=[],
                brutus_claims_attacked=[],
            )
            record["id"] = f"delib-pseudo-{i}"
            append_metrics(extract_metrics(record), jsonl)

        monkeypatch.setattr("shared.deliberation_metrics.EVAL_FILE", jsonl)

        from shared.sufficiency_probes import _check_deliberation_hoop_tests

        met, evidence = _check_deliberation_hoop_tests()
        assert met is False

    def test_activation_trend_probe_excludes_early_convergence(self, tmp_path: Path, monkeypatch):
        jsonl = tmp_path / "eval.jsonl"
        # Mix of early convergence and full — trend should only consider full
        for i in range(4):
            record = _make_early_convergence_record()
            record["id"] = f"delib-early-{i}"
            append_metrics(extract_metrics(record), jsonl)
        # Not enough multi-round for trend
        monkeypatch.setattr("shared.deliberation_metrics.EVAL_FILE", jsonl)

        from shared.sufficiency_probes import _check_deliberation_activation_trend

        met, evidence = _check_deliberation_activation_trend()
        assert met is True  # Insufficient data = pass
        assert "insufficient" in evidence.lower()

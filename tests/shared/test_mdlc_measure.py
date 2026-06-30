"""Tests for the standalone MonDLC measurement scorer."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

import shared.mdlc_measure as mdlc_measure
from shared.capdlc_lifecycle import GateStatus
from shared.mdlc_measure import (
    MonDLCGateName,
    MonDLCLadder,
    MonDLCScoreResult,
    MonDLCVerdict,
    score,
)

NOW = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)
HASH = "ruler-hash-fixture"


def _ladder(**overrides: object) -> MonDLCLadder:
    data = {
        "ruler_hash": HASH,
        "min_corroboration_count": 2,
        "freshness_ttl_seconds": 3600,
        "as_of": NOW,
        "positive_threshold": 0.0,
        "negative_threshold": -50.0,
    }
    data.update(overrides)
    return MonDLCLadder(**data)


def _measurement(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "measurement": 12.5,
        "provenance": "realized",
        "observed_at": NOW - timedelta(minutes=5),
        "evidence_refs": ("rail:event:1", "ledger:receipt:1"),
    }
    data.update(overrides)
    return data


def _by_gate(result: MonDLCScoreResult, name: MonDLCGateName):
    for gate in result.gates:
        if gate.name is name:
            return gate
    raise AssertionError(f"missing gate {name}")


def test_score_returns_lit_corrob_result_when_all_four_gates_pass() -> None:
    result = score(_measurement(), _ladder(), ruler_hash_commit=HASH)

    assert result.status is GateStatus.LIT
    assert result.verdict is MonDLCVerdict.CORROBORATED
    assert result.ok is True
    assert result.gate_result.status is GateStatus.LIT
    assert result.gate_result.verdict is True
    assert result.reason == "corroborated_realized_return"
    assert [gate.name for gate in result.gates] == [
        MonDLCGateName.RULER_HASH,
        MonDLCGateName.OBSERVED_EVIDENCE,
        MonDLCGateName.FRESHNESS,
        MonDLCGateName.CORROBORATION,
    ]
    assert all(gate.status is GateStatus.LIT for gate in result.gates)
    assert result.corroboration_count == 2
    assert result.min_corroboration_count == 2


@pytest.mark.parametrize(
    ("measurement", "reason"),
    (
        (None, "measurement_missing"),
        (_measurement(measurement=None), "measurement_missing"),
    ),
)
def test_missing_measurement_is_dark_not_success(
    measurement: dict[str, object] | None, reason: str
) -> None:
    result = score(measurement, _ladder(), ruler_hash_commit=HASH)

    assert result.status is GateStatus.DARK
    assert result.verdict is MonDLCVerdict.DARK
    assert result.ok is False
    assert result.gate_result.verdict is None
    assert result.refusal_reason == reason


def test_projected_measurement_is_dark() -> None:
    result = score(_measurement(provenance="projected"), _ladder(), ruler_hash_commit=HASH)

    assert result.status is GateStatus.DARK
    assert result.verdict is MonDLCVerdict.DARK
    assert result.refusal_reason == "projected_measurement"
    gate = _by_gate(result, MonDLCGateName.OBSERVED_EVIDENCE)
    assert gate.status is GateStatus.DARK


def test_stale_measurement_is_dark() -> None:
    result = score(
        _measurement(observed_at=NOW - timedelta(hours=3)),
        _ladder(freshness_ttl_seconds=3600),
        ruler_hash_commit=HASH,
    )

    assert result.status is GateStatus.DARK
    assert result.verdict is MonDLCVerdict.DARK
    assert result.refusal_reason == "measurement_stale"
    gate = _by_gate(result, MonDLCGateName.FRESHNESS)
    assert gate.status is GateStatus.DARK


def test_uncorroborated_measurement_is_undetermined_not_success() -> None:
    result = score(
        _measurement(evidence_refs=("rail:event:1",)),
        _ladder(min_corroboration_count=2),
        ruler_hash_commit=HASH,
    )

    assert result.status is GateStatus.PARTIAL
    assert result.verdict is MonDLCVerdict.UNDETERMINED
    assert result.ok is False
    assert result.gate_result.verdict is None
    assert result.reason == "insufficient_corroboration"
    gate = _by_gate(result, MonDLCGateName.CORROBORATION)
    assert gate.status is GateStatus.PARTIAL


@pytest.mark.parametrize(
    ("commit", "reason"),
    (
        ("", "ruler_hash_missing"),
        ("different-hash", "ruler_hash_mismatch"),
    ),
)
def test_ruler_hash_missing_or_mismatch_refuses(commit: str, reason: str) -> None:
    result = score(_measurement(), _ladder(), ruler_hash_commit=commit)

    assert result.status is GateStatus.DARK
    assert result.verdict is MonDLCVerdict.DARK
    assert result.refusal_reason == reason
    gate = _by_gate(result, MonDLCGateName.RULER_HASH)
    assert gate.status is GateStatus.DARK
    assert gate.reason == reason


def test_ruler_hash_commit_is_required_keyword_argument() -> None:
    with pytest.raises(TypeError):
        score(_measurement(), _ladder())  # type: ignore[call-arg]


def test_single_overwhelming_loss_is_lit_negative_under_ladder() -> None:
    result = score(
        _measurement(measurement=-75.0),
        _ladder(negative_threshold=-50.0),
        ruler_hash_commit=HASH,
    )

    assert result.status is GateStatus.LIT
    assert result.verdict is MonDLCVerdict.NEGATIVE
    assert result.ok is False
    assert result.gate_result.status is GateStatus.LIT
    assert result.gate_result.verdict is False
    assert result.reason == "negative_realized_return"


def test_ladder_mapping_and_measurement_mapping_are_supported() -> None:
    result = score(
        {
            "realized_return": 3,
            "provenance": "inbound_rail",
            "timestamp": (NOW - timedelta(seconds=10)).isoformat(),
            "evidence_refs": ["rail:event:1"],
            "corroborated_by": ["ledger:receipt:1"],
        },
        {
            "ruler_hash": HASH,
            "min_N": 2,
            "freshness_ttl_s": 60,
            "as_of": NOW.isoformat(),
        },
        ruler_hash_commit=HASH,
    )

    assert result.status is GateStatus.LIT
    assert result.verdict is MonDLCVerdict.CORROBORATED
    assert result.corroboration_count == 2


def test_result_truthiness_is_forbidden() -> None:
    result = score(_measurement(), _ladder(), ruler_hash_commit=HASH)

    with pytest.raises(TypeError, match="truthiness is undefined"):
        bool(result)


def test_to_dict_exposes_gate_contract_without_python_identities() -> None:
    result = score(_measurement(), _ladder(), ruler_hash_commit=HASH)

    payload = result.to_dict()

    assert payload["status"] == "lit"
    assert payload["verdict"] == "corroborated"
    assert payload["ok"] is True
    assert payload["gates"] == [
        {"name": "ruler_hash", "status": "lit", "reason": "ruler_hash_matched"},
        {
            "name": "observed_evidence",
            "status": "lit",
            "reason": "observed_realized_measurement",
        },
        {"name": "freshness", "status": "lit", "reason": "measurement_fresh"},
        {
            "name": "corroboration",
            "status": "lit",
            "reason": "corroboration_threshold_met",
        },
    ]


def test_public_exports_are_stable() -> None:
    expected = {
        "MDLC_MEASURE_SCORER_NAME",
        "MDLC_MEASURE_SCORER_VERSION",
        "MonDLCGate",
        "MonDLCGateName",
        "MonDLCLadder",
        "MonDLCMeasurement",
        "MonDLCScoreResult",
        "MonDLCVerdict",
        "score",
    }

    assert set(mdlc_measure.__all__) == expected
    for name in expected:
        assert getattr(mdlc_measure, name) is mdlc_measure.__dict__[name]

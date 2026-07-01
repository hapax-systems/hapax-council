"""Tests for the MonDLC M-instrument binding boundary."""

from __future__ import annotations

import importlib
import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from shared.capdlc_lifecycle import GateResult, GateStatus

NOW = datetime(2026, 7, 1, 9, 0, tzinfo=UTC)
HASH = "ruler-hash-fixture"


def _binding_module():
    return importlib.import_module("shared.mdlc_m_binding")


def _measure_module():
    return importlib.import_module("shared.mdlc_measure")


def _ladder(**overrides: object):
    mdlc_measure = _measure_module()
    data = {
        "ruler_hash": HASH,
        "min_corroboration_count": 2,
        "freshness_ttl_seconds": 3600,
        "as_of": NOW,
        "positive_threshold": 0.0,
        "negative_threshold": -50.0,
    }
    data.update(overrides)
    return mdlc_measure.MonDLCLadder(**data)


def _measurement(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "measurement": 12.5,
        "provenance": "realized",
        "observed_at": NOW - timedelta(minutes=5),
        "evidence_refs": ("rail:event:1", "ledger:receipt:1"),
    }
    data.update(overrides)
    return data


def _score_result(**measurement_overrides: object):
    mdlc_measure = _measure_module()
    return mdlc_measure.score(
        _measurement(**measurement_overrides), _ladder(), ruler_hash_commit=HASH
    )


def _rail_result(
    *,
    status: str = "accepted",
    value: float | None = 12.5,
    evidence_refs: tuple[str, ...] = ("rail:event:1",),
    refusal_reason: str | None = None,
):
    measurement = None
    if value is not None:
        measurement = SimpleNamespace(
            value=value,
            provenance="inbound_rail",
            observed_at=NOW - timedelta(minutes=5),
            evidence_refs=evidence_refs,
            corroborated_by=(),
        )
    return SimpleNamespace(
        status=SimpleNamespace(value=status),
        measurement=measurement,
        refusal_reason=None if refusal_reason is None else SimpleNamespace(value=refusal_reason),
        evidence_refs=evidence_refs,
    )


def test_import_is_lazy_for_measure_and_rail_modules() -> None:
    sys.modules.pop("shared.mdlc_m_binding", None)
    sys.modules.pop("shared.mdlc_measure", None)
    sys.modules.pop("shared.mdlc_realized_return", None)

    importlib.import_module("shared.mdlc_m_binding")

    assert "shared.mdlc_measure" not in sys.modules
    assert "shared.mdlc_realized_return" not in sys.modules


def test_native_score_result_lifts_without_recomputing_or_mutating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    m_binding = _binding_module()
    native = _score_result()
    before = native.to_dict()
    monkeypatch.setattr(
        m_binding,
        "_load_measure_module",
        lambda: (_ for _ in ()).throw(AssertionError("scorer should not load")),
    )

    result = m_binding.bind_m_result(native)

    assert result.status is native.status
    assert result.native_verdict is native.verdict
    assert result.score_result is native
    assert result.gate_result is native.gate_result
    assert result.verdict == "corroborated"
    assert native.to_dict() == before


def test_measurement_binding_delegates_to_scorer(monkeypatch: pytest.MonkeyPatch) -> None:
    m_binding = _binding_module()
    calls: list[tuple[Any, Any, str]] = []
    fake_score_result = SimpleNamespace(
        scorer="mdlc_measure",
        scorer_version=77,
        status=GateStatus.LIT,
        verdict=SimpleNamespace(value="corroborated"),
        gate_result=GateResult(
            status=GateStatus.LIT,
            verdict=True,
            reason="stubbed_scorer",
            evidence_refs=("rail:event:stub",),
        ),
        reason="stubbed_scorer",
        evidence_refs=("rail:event:stub",),
        refusal_reason=None,
    )

    def fake_score(measurement: Any, ladder: Any, *, ruler_hash_commit: str):
        calls.append((measurement, ladder, ruler_hash_commit))
        return fake_score_result

    monkeypatch.setattr(
        m_binding, "_load_measure_module", lambda: SimpleNamespace(score=fake_score)
    )

    result = m_binding.bind_m_result(_measurement(), _ladder(), ruler_hash_commit=HASH)

    assert calls == [(_measurement(), _ladder(), HASH)]
    assert result.score_result is fake_score_result
    assert result.ok is True


def test_missing_scorer_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    m_binding = _binding_module()
    monkeypatch.setattr(
        m_binding,
        "_load_measure_module",
        lambda: (_ for _ in ()).throw(ModuleNotFoundError("mdlc_measure")),
    )

    result = m_binding.bind_m_result(_measurement(), _ladder(), ruler_hash_commit=HASH)

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is m_binding.MonDLCBindingRefusalReason.MISSING_SCORER
    assert result.gate_result.verdict is None
    assert result.next_action
    assert "next action:" in result.reason
    assert result.to_dict()["next_action"] == result.next_action


def test_accepted_rail_result_without_evidence_fails_closed() -> None:
    m_binding = _binding_module()

    result = m_binding.bind_m_result(
        _rail_result(evidence_refs=()),
        _ladder(),
        ruler_hash_commit=HASH,
    )

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is m_binding.MonDLCBindingRefusalReason.MISSING_RAIL_EVIDENCE
    assert result.score_result is None
    assert result.next_action


def test_measurement_without_ladder_fails_closed() -> None:
    m_binding = _binding_module()

    result = m_binding.bind_m_result(_measurement(), None, ruler_hash_commit=HASH)

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is m_binding.MonDLCBindingRefusalReason.MISSING_LADDER
    assert result.next_action


def test_rail_result_without_ladder_fails_closed() -> None:
    m_binding = _binding_module()

    result = m_binding.bind_m_result(_rail_result(), None, ruler_hash_commit=HASH)

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is m_binding.MonDLCBindingRefusalReason.MISSING_LADDER
    assert result.next_action


def test_refused_rail_result_fails_closed_with_native_reason() -> None:
    m_binding = _binding_module()

    result = m_binding.bind_m_result(
        _rail_result(status="refused", value=None, refusal_reason="refund_or_reversal_event"),
        _ladder(),
        ruler_hash_commit=HASH,
    )

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is m_binding.MonDLCBindingRefusalReason.RAIL_REFUSED
    assert result.native_refusal_reason == "refund_or_reversal_event"
    assert result.next_action


def test_rail_result_sequence_scores_through_binding() -> None:
    m_binding = _binding_module()

    result = m_binding.bind_m_result(
        (
            _rail_result(value=12.5, evidence_refs=("rail:event:1",)),
            _rail_result(value=7.5, evidence_refs=("rail:event:2",)),
        ),
        _ladder(min_corroboration_count=2),
        ruler_hash_commit=HASH,
    )

    assert result.status is GateStatus.LIT
    assert result.verdict == "corroborated"
    assert result.score_result.measurement_value == 20.0
    assert result.evidence_refs == ("rail:event:1", "rail:event:2")
    assert len(result.rail_results) == 2


def test_empty_rail_result_sequence_fails_closed_as_missing_evidence() -> None:
    m_binding = _binding_module()

    result = m_binding.bind_m_result([], _ladder(), ruler_hash_commit=HASH)

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is m_binding.MonDLCBindingRefusalReason.MISSING_RAIL_EVIDENCE
    assert result.rail_results == ()
    assert result.next_action


def test_bind_durable_payment_events_scores_lazy_reader_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    m_binding = _binding_module()
    rail_results = (
        _rail_result(value=12.5, evidence_refs=("rail:event:1",)),
        _rail_result(value=7.5, evidence_refs=("rail:event:2",)),
    )
    calls: list[Path | str] = []

    def fake_reader(path: Path | str):
        calls.append(path)
        return rail_results

    monkeypatch.setattr(
        m_binding,
        "_load_rail_module",
        lambda: SimpleNamespace(realized_returns_from_durable_payment_events=fake_reader),
    )

    result = m_binding.bind_durable_payment_events(
        "/tmp/payment-events.jsonl",
        _ladder(min_corroboration_count=2),
        ruler_hash_commit=HASH,
    )

    assert calls == ["/tmp/payment-events.jsonl"]
    assert result.status is GateStatus.LIT
    assert result.verdict == "corroborated"
    assert result.source_kind == "durable_payment_events"
    assert result.rail_results == rail_results
    assert result.score_result.measurement_value == 20.0
    assert result.evidence_refs == ("rail:event:1", "rail:event:2")


def test_bind_durable_payment_events_missing_reader_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    m_binding = _binding_module()
    monkeypatch.setattr(
        m_binding,
        "_load_rail_module",
        lambda: (_ for _ in ()).throw(ModuleNotFoundError("shared.mdlc_realized_return")),
    )

    result = m_binding.bind_durable_payment_events(
        "/tmp/payment-events.jsonl",
        _ladder(),
        ruler_hash_commit=HASH,
    )

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is m_binding.MonDLCBindingRefusalReason.MISSING_RAIL_READER
    assert result.source_kind == "durable_payment_events"
    assert result.next_action
    assert "next action:" in result.gate_result.reason


def test_unsupported_shape_fails_closed() -> None:
    m_binding = _binding_module()

    result = m_binding.bind_m_result(object(), _ladder(), ruler_hash_commit=HASH)

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is m_binding.MonDLCBindingRefusalReason.UNSUPPORTED_SHAPE
    assert "unsupported_shape" in result.reason
    assert result.next_action


def test_result_truthiness_is_forbidden() -> None:
    m_binding = _binding_module()
    result = m_binding.bind_m_result(_score_result())

    with pytest.raises(TypeError, match="truthiness is undefined"):
        bool(result)


def test_public_exports_are_stable() -> None:
    m_binding = _binding_module()
    expected = {
        "MONDLC_M_BINDING_NAME",
        "MONDLC_M_BINDING_VERSION",
        "MonDLCBindingRefusalReason",
        "MonDLCBindingResult",
        "bind_durable_payment_events",
        "bind_m_result",
    }

    assert set(m_binding.__all__) == expected
    for name in expected:
        assert getattr(m_binding, name) is m_binding.__dict__[name]

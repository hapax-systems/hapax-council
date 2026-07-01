"""Acceptance tests for the first MonDLC measurement firing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import shared.durable_jsonl_sink as sink_mod
from shared.capdlc_lifecycle import GateStatus
from shared.mdlc_m_binding import bind_durable_payment_events, bind_m_result
from shared.mdlc_measure import MonDLCLadder

NOW = datetime(2026, 7, 1, 11, 30, tzinfo=UTC)
HASH = "e16bfb8c6c5f80f69dd53edd7f5a9c303c7bff047153d6a337bf5c23db76fbb7"
RAW_SHA = "4cad08e003531ce772360aca72435081607ebd1174d4ab8dddba685ad89726d2"


def _trusted_sink(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> sink_mod.DurableJsonlSink:
    root = tmp_path / "durable"
    root.mkdir()
    monkeypatch.setattr(sink_mod, "_mount_fstype_for_path", lambda _path: "btrfs")
    return sink_mod.DurableJsonlSink(root)


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


def _append_payment_event(
    sink: sink_mod.DurableJsonlSink,
    *,
    event_id: str,
    amount_cents: int,
) -> None:
    sink.append(
        stream_id="payment-event",
        data_class="financial_receipt",
        source_receipt_ref=f"receipt://payment/phase5/{event_id}",
        timestamp=NOW.isoformat().replace("+00:00", "Z"),
        payload={
            "event_kind": "payment_intent_succeeded",
            "event_id": event_id,
            "amount_currency_cents": amount_cents,
            "currency": "USD",
            "occurred_at": (NOW - timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
            "raw_payload_sha256": RAW_SHA,
            "source_amount_sign": "positive",
        },
    )


def test_first_firing_payment_events_corrob_lit_without_minting_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = _trusted_sink(tmp_path, monkeypatch)
    _append_payment_event(sink, event_id="one", amount_cents=1200)
    _append_payment_event(sink, event_id="two", amount_cents=1300)
    stream_path = sink.path_for_stream("payment-event")
    stream_before = stream_path.read_text(encoding="utf-8")

    result = bind_durable_payment_events(
        stream_path,
        _ladder(min_corroboration_count=2),
        ruler_hash_commit=HASH,
    )

    assert result.status is GateStatus.LIT
    assert result.verdict == "corroborated"
    assert result.ok is True
    assert result.source_kind == "durable_payment_events"
    assert result.score_result.measurement_value == 2500.0
    assert result.score_result.corroboration_count >= result.score_result.min_corroboration_count
    assert len(result.rail_results) == 2
    assert stream_path.read_text(encoding="utf-8") == stream_before


def test_first_firing_payment_events_below_corroboration_floor_is_undetermined(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = _trusted_sink(tmp_path, monkeypatch)
    _append_payment_event(sink, event_id="solo", amount_cents=1200)

    result = bind_durable_payment_events(
        sink.path_for_stream("payment-event"),
        _ladder(min_corroboration_count=99),
        ruler_hash_commit=HASH,
    )

    assert result.status is GateStatus.PARTIAL
    assert result.verdict == "undetermined"
    assert result.ok is False
    assert result.reason == "insufficient_corroboration"
    assert result.score_result.corroboration_count < result.score_result.min_corroboration_count


def test_first_firing_overwhelming_loss_is_lit_negative_under_frozen_ruler() -> None:
    result = bind_m_result(
        {
            "measurement": -75.0,
            "provenance": "realized",
            "observed_at": NOW - timedelta(minutes=1),
            "evidence_refs": ("loss-ledger:phase5", "review:phase5"),
        },
        _ladder(negative_threshold=-50.0),
        ruler_hash_commit=HASH,
    )

    assert result.status is GateStatus.LIT
    assert result.verdict == "negative"
    assert result.ok is False
    assert result.gate_result.verdict is False
    assert result.reason == "negative_realized_return"


@pytest.mark.parametrize(
    ("measurement", "native_reason"),
    (
        (None, "measurement_missing"),
        (
            {
                "measurement": 12.5,
                "provenance": "projected",
                "observed_at": NOW - timedelta(minutes=1),
                "evidence_refs": ("projection:phase5", "review:phase5"),
            },
            "projected_measurement",
        ),
    ),
)
def test_first_firing_absent_or_projected_measurement_is_dark(
    measurement: object,
    native_reason: str,
) -> None:
    result = bind_m_result(measurement, _ladder(), ruler_hash_commit=HASH)

    assert result.status is GateStatus.DARK
    assert result.verdict == "dark"
    assert result.ok is False
    assert result.gate_result.verdict is None
    assert result.native_refusal_reason == native_reason

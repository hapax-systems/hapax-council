"""Tests for governed money-rail resource receipts."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agents.payment_processors.resource_receipts import (
    MoneyRailReceiptOperation,
    append_resource_receipt,
    build_resource_receipt,
    receipt_reference,
    require_resource_receipt,
    resource_receipt_exists,
    tail_resource_receipts,
)


def _receipt():
    return build_resource_receipt(
        rail="github-sponsors",
        operation=MoneyRailReceiptOperation.INGRESS,
        route_path="/api/payment-rails/github-sponsors",
        external_id="delivery-1",
        event_kind="created",
        raw_payload_sha256="a" * 64,
        downstream_action="publication_bus.publish_event",
        created_at=datetime(2026, 6, 30, 4, 0, tzinfo=UTC),
    )


def test_receipt_never_grants_spend_or_public_projection() -> None:
    receipt = _receipt()

    assert receipt.receive_only is True
    assert receipt.spend_authority_granted is False
    assert receipt.provider_spend_authorized is False
    assert receipt.public_projection_allowed is False
    assert receipt.no_perk_or_relationship_granted is True


def test_append_is_idempotent_by_receipt_id(tmp_path) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    receipt = _receipt()

    assert append_resource_receipt(receipt, log_path=log_path)
    assert append_resource_receipt(receipt, log_path=log_path)

    rows = tail_resource_receipts(log_path=log_path)
    assert len(rows) == 1
    assert rows[0].receipt_id == receipt.receipt_id


def test_require_resource_receipt_fails_closed_when_missing(tmp_path) -> None:
    receipt = _receipt()
    ref = receipt_reference(receipt)

    assert resource_receipt_exists(ref, log_path=tmp_path / "missing.jsonl") is False
    with pytest.raises(Exception, match="missing money-rail resource receipt"):
        require_resource_receipt(ref, log_path=tmp_path / "missing.jsonl")


def test_resource_receipt_exists_scans_beyond_tail_window(tmp_path) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    first = build_resource_receipt(
        rail="github-sponsors",
        operation=MoneyRailReceiptOperation.INGRESS,
        route_path="/api/payment-rails/github-sponsors",
        external_id="delivery-0",
        event_kind="created",
        raw_payload_sha256="0" * 64,
        downstream_action="publication_bus.publish_event",
        created_at=datetime(2026, 6, 30, 4, 0, tzinfo=UTC),
    )

    for idx in range(250):
        receipt = build_resource_receipt(
            rail="github-sponsors",
            operation=MoneyRailReceiptOperation.INGRESS,
            route_path="/api/payment-rails/github-sponsors",
            external_id=f"delivery-{idx}",
            event_kind="created",
            raw_payload_sha256=f"{idx:064x}"[-64:],
            downstream_action="publication_bus.publish_event",
            created_at=datetime(2026, 6, 30, 4, 0, tzinfo=UTC),
        )
        assert append_resource_receipt(receipt, log_path=log_path)

    assert resource_receipt_exists(receipt_reference(first), log_path=log_path)

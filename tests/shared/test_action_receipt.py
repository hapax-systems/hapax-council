"""Tests for typed action receipts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.action_receipt import ActionReceipt, ActionReceiptStatus
from shared.capability_outcome import AuthorityCeiling


def _receipt(**overrides: object) -> ActionReceipt:
    payload: dict[str, object] = {
        "receipt_id": "ar:test:requested",
        "created_at": "2026-05-15T22:30:00Z",
        "request_id": "request:test:1",
        "capability_name": "studio.toggle_livestream",
        "requested_action": "toggle livestream on",
        "status": ActionReceiptStatus.REQUESTED,
        "authority_ceiling": AuthorityCeiling.NO_CLAIM,
        "operator_visible_summary": "request recorded",
    }
    payload.update(overrides)
    return ActionReceipt.model_validate(payload)


def test_action_receipt_schema_exposes_required_contract_fields() -> None:
    schema = ActionReceipt.model_json_schema()
    fields = schema["properties"]

    for field in (
        "request_id",
        "status",
        "target_aperture",
        "wcs_refs",
        "evidence_refs",
        "command_ref",
        "confirmation_refs",
        "applied_refs",
        "readback_refs",
        "blocked_reasons",
        "error_refs",
        "authority_ceiling",
        "learning_update_allowed",
        "structural_reflex",
        "readback_required",
    ):
        assert field in fields

    assert set(ActionReceiptStatus) == {
        ActionReceiptStatus.REQUESTED,
        ActionReceiptStatus.STAGED,
        ActionReceiptStatus.CONFIRMED,
        ActionReceiptStatus.APPLIED,
        ActionReceiptStatus.READBACK,
        ActionReceiptStatus.BLOCKED,
        ActionReceiptStatus.ERROR,
    }


def test_requested_and_staged_receipts_do_not_support_learning() -> None:
    requested = _receipt(status=ActionReceiptStatus.REQUESTED)
    staged = _receipt(
        receipt_id="ar:test:staged",
        status=ActionReceiptStatus.STAGED,
        command_ref="shm:control-file",
    )

    assert requested.can_support_affordance_success() is False
    assert staged.can_support_affordance_success() is False
    assert staged.learning_update_allowed is False


def test_confirmed_requires_command_and_confirmation_refs() -> None:
    with pytest.raises(ValidationError, match="confirmed receipts require"):
        _receipt(status=ActionReceiptStatus.CONFIRMED, command_ref="cmd:a")

    confirmed = _receipt(
        status=ActionReceiptStatus.CONFIRMED,
        command_ref="cmd:a",
        confirmation_refs=["controller:accepted"],
    )
    assert confirmed.can_support_affordance_success() is False


def test_applied_receipt_requires_target_aperture_and_wcs_refs() -> None:
    with pytest.raises(ValidationError, match="applied/readback receipts require target_aperture"):
        _receipt(status=ActionReceiptStatus.APPLIED, applied_refs=["apply:a"])

    applied = _receipt(
        status=ActionReceiptStatus.APPLIED,
        applied_refs=["apply:a"],
        target_aperture="aperture:livestream",
        wcs_refs=["wcs:livestream-egress"],
    )
    assert applied.can_support_affordance_success() is False


def test_readback_receipt_can_support_affordance_success() -> None:
    readback = _receipt(
        status=ActionReceiptStatus.READBACK,
        target_aperture="aperture:livestream",
        wcs_refs=["wcs:livestream-egress"],
        evidence_refs=["evidence:obs-live-state"],
        applied_refs=["apply:livestream-control"],
        readback_refs=["readback:obs-live-state"],
        upstream_outcome_refs=["ToolProviderOutcome:source-route"],
        authority_ceiling=AuthorityCeiling.EVIDENCE_BOUND,
        learning_update_allowed=True,
    )

    assert readback.can_support_affordance_success() is True


def test_learning_update_requires_evidence_bound_authority() -> None:
    with pytest.raises(ValidationError, match="evidence-bound authority"):
        _receipt(
            status=ActionReceiptStatus.READBACK,
            target_aperture="aperture:livestream",
            wcs_refs=["wcs:livestream-egress"],
            evidence_refs=["evidence:obs-live-state"],
            applied_refs=["apply:livestream-control"],
            readback_refs=["readback:obs-live-state"],
            authority_ceiling=AuthorityCeiling.NO_CLAIM,
            learning_update_allowed=True,
        )


def test_structural_reflex_applied_receipt_requires_readback_before_learning() -> None:
    receipt = _receipt(
        receipt_id="ar:test:structural-reflex",
        capability_name="structural.intent",
        requested_action="structural intent reflex",
        status=ActionReceiptStatus.APPLIED,
        target_aperture="aperture:compositor:structural-intent",
        wcs_refs=["wcs:compositor:structural-intent"],
        applied_refs=["shm:hapax-compositor/narrative-structural-intent.json"],
        structural_reflex=True,
        readback_required=True,
    )

    assert receipt.structural_reflex is True
    assert receipt.readback_required is True
    assert receipt.learning_update_allowed is False
    assert receipt.can_support_affordance_success() is False


def test_structural_reflex_must_require_readback() -> None:
    with pytest.raises(ValidationError, match="structural reflex receipts require readback"):
        _receipt(
            receipt_id="ar:test:structural-no-readback",
            capability_name="structural.intent",
            requested_action="structural intent reflex",
            status=ActionReceiptStatus.APPLIED,
            target_aperture="aperture:compositor:structural-intent",
            wcs_refs=["wcs:compositor:structural-intent"],
            applied_refs=["shm:hapax-compositor/narrative-structural-intent.json"],
            structural_reflex=True,
            readback_required=False,
        )


def test_structural_reflex_readback_cannot_support_learning() -> None:
    with pytest.raises(ValidationError, match="structural reflex receipts cannot update learning"):
        _receipt(
            receipt_id="ar:test:structural-learning",
            capability_name="structural.intent",
            requested_action="structural intent reflex",
            status=ActionReceiptStatus.READBACK,
            target_aperture="aperture:compositor:structural-intent",
            wcs_refs=["wcs:compositor:structural-intent"],
            evidence_refs=["evidence:structural-readback"],
            applied_refs=["shm:hapax-compositor/narrative-structural-intent.json"],
            readback_refs=["readback:structural-intent-file"],
            structural_reflex=True,
            readback_required=True,
            learning_update_allowed=True,
        )

    receipt = _receipt(
        receipt_id="ar:test:structural-readback",
        capability_name="structural.intent",
        requested_action="structural intent reflex",
        status=ActionReceiptStatus.READBACK,
        target_aperture="aperture:compositor:structural-intent",
        wcs_refs=["wcs:compositor:structural-intent"],
        evidence_refs=["evidence:structural-readback"],
        applied_refs=["shm:hapax-compositor/narrative-structural-intent.json"],
        readback_refs=["readback:structural-intent-file"],
        structural_reflex=True,
        readback_required=True,
        learning_update_allowed=False,
    )
    assert receipt.can_support_affordance_success() is False


def test_learning_update_fails_closed_without_readback_evidence() -> None:
    with pytest.raises(ValidationError, match="learning updates require applied readback"):
        _receipt(
            status=ActionReceiptStatus.APPLIED,
            target_aperture="aperture:livestream",
            wcs_refs=["wcs:livestream-egress"],
            applied_refs=["apply:livestream-control"],
            learning_update_allowed=True,
        )


def test_blocked_and_error_receipts_require_reasons() -> None:
    with pytest.raises(ValidationError, match="blocked receipts require"):
        _receipt(status=ActionReceiptStatus.BLOCKED)
    with pytest.raises(ValidationError, match="error receipts require"):
        _receipt(status=ActionReceiptStatus.ERROR)

    blocked = _receipt(
        status=ActionReceiptStatus.BLOCKED,
        blocked_reasons=["policy:public-egress-disabled"],
    )
    error = _receipt(status=ActionReceiptStatus.ERROR, error_refs=["subprocess:returncode:1"])
    assert blocked.can_support_affordance_success() is False
    assert error.can_support_affordance_success() is False

"""Publication bindings for the existing route/resource/authority receipt gate.

This consumer does not select routes, issue receipts or authorize provider spend.
Bindings belong to the executing service, not to authored publication content.
"""

from __future__ import annotations

import os
from dataclasses import asdict
from datetime import UTC, datetime

from shared.mcp_connector_policy import (
    ConnectorReceiptGateResult,
    _connector_receipt_match,
    _latest_route_decision,
    _ledger_path,
    _load_route_receipts,
    _receipt_root,
    _route_decision_refusal,
    _sequence,
)


class PublicationAdmissionError(RuntimeError):
    """A route hold, never an editorial verdict or a model response."""

    def __init__(self, result: ConnectorReceiptGateResult) -> None:
        self.result = result
        super().__init__(result.message)


def admission_report(result: ConnectorReceiptGateResult) -> dict[str, object]:
    return asdict(result)


def publication_hold(reason: str, *, route_id: str | None = None) -> ConnectorReceiptGateResult:
    return ConnectorReceiptGateResult(
        allowed=False,
        reason_code=reason,
        route_id=route_id,
        message=(
            f"publication route/resource hold: {reason}. Next action: the publication "
            "owner must qualify the exact route, execution binding and current task-bound "
            "quota/resource/authority evidence before retrying."
        ),
    )


def evaluate_publication_admission(
    surface: str, *, review_model: str | None = None, now: datetime | None = None
) -> ConnectorReceiptGateResult:
    """Read current receipts at the effect boundary; missing bindings hold.

    Use the existing route decision ledger and connector_mutation receipts.
    A receipt must include the specific ``publication:<surface>`` scope as well
    as the effect class. Artifact metadata cannot choose a different task,
    lane, route or receipt directory. Publication review execution still needs
    a qualified executor; these receipts alone do not establish served identity.
    """
    task_id = os.environ.get("HAPAX_PUBLICATION_TASK_ID", "").strip()
    role = os.environ.get("HAPAX_PUBLICATION_ROLE", "").strip()
    route_key = (
        "HAPAX_PUBLICATION_REVIEW_ROUTE_ID"
        if review_model is not None
        else "HAPAX_PUBLICATION_ROUTE_ID"
    )
    route_id = os.environ.get(route_key, "").strip()
    if not task_id or not role or not route_id:
        return publication_hold("publication_route_binding_absent")
    checked_at = now or datetime.now(UTC)
    try:
        row = _latest_route_decision(task_id=task_id, role=role, ledger_path=_ledger_path(None))
        refusal = _route_decision_refusal(row, now=checked_at)
        if refusal:
            return publication_hold(refusal, route_id=route_id)
        assert row is not None
        if row.get("lane") != role or row.get("route_id") != route_id:
            return publication_hold("publication_route_identity_mismatch", route_id=route_id)
        if row.get("registry_freshness_green") is not True:
            return publication_hold("registry_freshness_not_green", route_id=route_id)
        if row.get("quality_floor_satisfied") is not True:
            return publication_hold("quality_floor_not_satisfied", route_id=route_id)
        required = ("connector", "external", "public", f"publication:{surface}")
        if review_model is not None:
            from shared.capability_execution import resolve_execution_descriptor

            selected_leaf = row.get("selected_descriptor_leaf")
            if selected_leaf is not None and not selected_leaf.startswith(f"{route_id}#"):
                return publication_hold("review_descriptor_route_mismatch", route_id=route_id)
            descriptor = resolve_execution_descriptor(selected_leaf or route_id)
            if descriptor.model_id != review_model:
                return publication_hold("review_model_identity_mismatch", route_id=route_id)
            if row.get("prompt_allowed") is not True:
                return publication_hold("review_prompt_not_allowed", route_id=route_id)
            required = ("connector", "provider_spend", "publication:review")
        root = _receipt_root(None)
        if root is None:
            return publication_hold("receipt_dir_disabled", route_id=route_id)
        refusal, receipt_ref = _connector_receipt_match(
            route_id=route_id,
            task_id=task_id,
            required_surfaces=required,
            receipt_root=root,
            now=checked_at,
        )
        if refusal:
            return publication_hold(refusal, route_id=route_id)
        from shared.dispatcher_policy import route_authority_receipt_reference

        matched = [
            receipt
            for receipt in _load_route_receipts(root)
            if route_authority_receipt_reference(receipt) == receipt_ref
        ]
        if len(matched) != 1 or matched[0].issued_at > checked_at:
            return publication_hold("publication_authority_not_current", route_id=route_id)
        return ConnectorReceiptGateResult(
            allowed=True,
            reason_code="publication_receipts_ok",
            message="publication route, quota, resource and scoped authority receipts are current",
            route_id=route_id,
            receipt_ref=receipt_ref,
            evidence_refs=(
                *_sequence(row.get("quota_evidence_refs")),
                *_sequence(row.get("resource_state_refs")),
            ),
        )
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return publication_hold("publication_route_evidence_invalid", route_id=route_id)


def require_publication_admission(
    surface: str, *, review_model: str | None = None
) -> ConnectorReceiptGateResult:
    result = evaluate_publication_admission(surface, review_model=review_model)
    if not result.allowed:
        raise PublicationAdmissionError(result)
    return result

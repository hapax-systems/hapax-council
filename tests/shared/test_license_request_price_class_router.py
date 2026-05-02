"""Tests for the license request price class router.

cc-task: license-request-price-class-router.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from shared.license_request_price_class_router import (
    IntendedUse,
    LicenseRequest,
    PriceClass,
    Quote,
    ReceiveOnlyRail,
    RefusalReason,
    RequestStatus,
    RouteVerdict,
    evaluate_request,
    ledger_entry,
)


def _request(**overrides) -> LicenseRequest:
    payload = {
        "request_id": "req-001",
        "received_at": datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
        "intended_use": IntendedUse.PERSONAL_LEARNING,
        "target_artifact_id": "methodology-dossier-v1",
    }
    payload.update(overrides)
    return LicenseRequest(**payload)


def test_personal_learning_routes_to_personal_research_use():
    verdict = evaluate_request(_request(intended_use=IntendedUse.PERSONAL_LEARNING))
    assert verdict.price_class is PriceClass.PERSONAL_OR_RESEARCH_USE
    assert verdict.quote is not None
    assert verdict.quote.pay_what_you_want is True
    assert verdict.quote.rail is ReceiveOnlyRail.GITHUB_SPONSORS


def test_academic_research_routes_to_personal_research_use():
    verdict = evaluate_request(_request(intended_use=IntendedUse.ACADEMIC_RESEARCH))
    assert verdict.price_class is PriceClass.PERSONAL_OR_RESEARCH_USE


def test_commercial_trial_routes_to_commercial_evaluation():
    verdict = evaluate_request(_request(intended_use=IntendedUse.COMMERCIAL_TRIAL))
    assert verdict.price_class is PriceClass.COMMERCIAL_EVALUATION
    assert verdict.quote is not None
    assert verdict.quote.fixed_price_usd is not None
    assert verdict.quote.rail is ReceiveOnlyRail.STRIPE_PAYMENT_LINK


def test_internal_deployment_routes_to_commercial_internal_use():
    verdict = evaluate_request(_request(intended_use=IntendedUse.INTERNAL_DEPLOYMENT))
    assert verdict.price_class is PriceClass.COMMERCIAL_INTERNAL_USE


def test_public_publication_routes_to_publication_or_reuse():
    verdict = evaluate_request(_request(intended_use=IntendedUse.PUBLIC_PUBLICATION))
    assert verdict.price_class is PriceClass.PUBLICATION_OR_REUSE


def test_dataset_redistribution_routes_to_dataset_or_artifact_access():
    verdict = evaluate_request(_request(intended_use=IntendedUse.DATASET_REDISTRIBUTION))
    assert verdict.price_class is PriceClass.DATASET_OR_ARTIFACT_ACCESS
    assert verdict.quote is not None
    assert verdict.quote.rail is ReceiveOnlyRail.OMG_LOL_PAY_AS_PUBLISHER


def test_outbound_payment_request_refused():
    verdict = evaluate_request(_request(requires_outbound_payment=True))
    assert verdict.price_class is PriceClass.REFUSAL_OR_NO_SALE
    assert verdict.refusal is not None
    assert RefusalReason.REQUIRES_OUTBOUND_PAYMENT in verdict.refusal.reasons


def test_discovery_call_request_refused():
    verdict = evaluate_request(_request(requires_discovery_call=True))
    assert verdict.price_class is PriceClass.REFUSAL_OR_NO_SALE
    assert RefusalReason.REQUIRES_DISCOVERY_CALL in verdict.refusal.reasons


def test_retainer_request_refused():
    verdict = evaluate_request(_request(requires_retainer=True))
    assert verdict.price_class is PriceClass.REFUSAL_OR_NO_SALE
    assert RefusalReason.REQUIRES_RETAINER in verdict.refusal.reasons


def test_customer_success_request_refused():
    verdict = evaluate_request(_request(requires_customer_success=True))
    assert verdict.price_class is PriceClass.REFUSAL_OR_NO_SALE
    assert RefusalReason.REQUIRES_CUSTOMER_SUCCESS in verdict.refusal.reasons


def test_account_portal_request_refused():
    verdict = evaluate_request(_request(requires_account_portal=True))
    assert verdict.price_class is PriceClass.REFUSAL_OR_NO_SALE
    assert RefusalReason.REQUIRES_ACCOUNT_PORTAL in verdict.refusal.reasons


def test_multi_user_features_request_refused():
    verdict = evaluate_request(_request(requires_multi_user_features=True))
    assert verdict.price_class is PriceClass.REFUSAL_OR_NO_SALE
    assert RefusalReason.REQUIRES_MULTI_USER_FEATURES in verdict.refusal.reasons


def test_custom_service_request_refused():
    verdict = evaluate_request(_request(requires_custom_service=True))
    assert verdict.price_class is PriceClass.REFUSAL_OR_NO_SALE
    assert RefusalReason.REQUIRES_CUSTOM_SERVICE in verdict.refusal.reasons


def test_multiple_forbidden_flows_aggregate_refusal_reasons():
    verdict = evaluate_request(
        _request(requires_outbound_payment=True, requires_retainer=True),
    )
    assert verdict.refusal is not None
    assert RefusalReason.REQUIRES_OUTBOUND_PAYMENT in verdict.refusal.reasons
    assert RefusalReason.REQUIRES_RETAINER in verdict.refusal.reasons


def test_refusal_class_cannot_carry_quote():
    with pytest.raises(ValueError, match="REFUSAL_OR_NO_SALE class produces a refusal"):
        Quote(
            request_id="req-bad",
            price_class=PriceClass.REFUSAL_OR_NO_SALE,
            rail=ReceiveOnlyRail.NO_RAIL,
            quote_text="Should not be allowed",
        )


def test_quote_cannot_be_fixed_and_pwyw_at_once():
    with pytest.raises(ValueError, match="cannot be both fixed_price"):
        Quote(
            request_id="req-bad",
            price_class=PriceClass.COMMERCIAL_EVALUATION,
            rail=ReceiveOnlyRail.STRIPE_PAYMENT_LINK,
            fixed_price_usd=99.0,
            pay_what_you_want=True,
            quote_text="Conflicting price terms",
        )


def test_commercial_class_requires_price():
    with pytest.raises(ValueError, match="requires a fixed_price_usd or pay_what_you_want"):
        Quote(
            request_id="req-bad",
            price_class=PriceClass.COMMERCIAL_EVALUATION,
            rail=ReceiveOnlyRail.STRIPE_PAYMENT_LINK,
            quote_text="Missing price",
        )


def test_route_verdict_requires_exactly_one_branch():
    with pytest.raises(ValueError, match="requires either a quote or a refusal"):
        RouteVerdict(request_id="req-x", price_class=PriceClass.PERSONAL_OR_RESEARCH_USE)


def test_route_verdict_rejects_quote_for_refusal_class():
    quote = Quote(
        request_id="req-x",
        price_class=PriceClass.PERSONAL_OR_RESEARCH_USE,
        rail=ReceiveOnlyRail.GITHUB_SPONSORS,
        pay_what_you_want=True,
        quote_text="ok",
    )
    with pytest.raises(ValueError, match="REFUSAL_OR_NO_SALE class requires a refusal"):
        RouteVerdict(
            request_id="req-x",
            price_class=PriceClass.REFUSAL_OR_NO_SALE,
            quote=quote,
        )


def test_quote_text_includes_no_call_no_retainer_language():
    verdict = evaluate_request(_request(intended_use=IntendedUse.COMMERCIAL_TRIAL))
    assert verdict.quote is not None
    assert "discovery call" in verdict.quote.quote_text
    assert "retainer" in verdict.quote.quote_text
    assert "customer-success" in verdict.quote.quote_text


def test_personal_quote_text_explicitly_pay_what_you_want():
    verdict = evaluate_request(_request(intended_use=IntendedUse.PERSONAL_LEARNING))
    assert "pay-what-you-want" in verdict.quote.quote_text.lower()
    assert "no calls" in verdict.quote.quote_text.lower()


def test_ledger_entry_tracks_request_lifecycle():
    request = _request(intended_use=IntendedUse.COMMERCIAL_TRIAL)
    verdict = evaluate_request(request)
    entry = ledger_entry(verdict, request, RequestStatus.PAID)
    assert entry.quote_sent is True
    assert entry.accepted is True
    assert entry.paid is True
    assert entry.refused is False
    assert entry.price_class is PriceClass.COMMERCIAL_EVALUATION
    assert entry.rail is ReceiveOnlyRail.STRIPE_PAYMENT_LINK


def test_ledger_entry_tracks_refusal():
    request = _request(requires_outbound_payment=True)
    verdict = evaluate_request(request)
    entry = ledger_entry(verdict, request, RequestStatus.REFUSED)
    assert entry.refused is True
    assert entry.paid is False
    assert entry.accepted is False
    assert entry.quote_sent is False
    assert entry.price_class is PriceClass.REFUSAL_OR_NO_SALE
    assert entry.rail is ReceiveOnlyRail.NO_RAIL


def test_ledger_entry_tracks_legal_attestation_need():
    request = _request(operator_legal_attestation_required=True)
    verdict = evaluate_request(request)
    entry = ledger_entry(verdict, request, RequestStatus.QUOTED)
    assert entry.operator_legal_attestation_required is True


def test_ledger_entry_status_open_marks_no_send_no_acceptance():
    request = _request()
    verdict = evaluate_request(request)
    entry = ledger_entry(verdict, request, RequestStatus.OPEN)
    assert entry.quote_sent is False
    assert entry.accepted is False
    assert entry.paid is False
    assert entry.refused is False

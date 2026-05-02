"""License request price class router.

Routes commercial-interest and license-request events into predefined
price classes, receive-only payment rails, or refusal artifacts —
*without* calls, CRM, bespoke negotiations, or multi-user product
shape.

The router is fail-closed on forbidden outflow shapes:
outbound payments, account portals, custom-service commitments,
discovery calls, retainers, and customer-success flows are rejected
at construction. The single operator's surface stays receive-only.

cc-task: ``license-request-price-class-router``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PriceClass(StrEnum):
    """Six routable price classes per acceptance §1."""

    PERSONAL_OR_RESEARCH_USE = "personal_or_research_use"
    COMMERCIAL_EVALUATION = "commercial_evaluation"
    COMMERCIAL_INTERNAL_USE = "commercial_internal_use"
    PUBLICATION_OR_REUSE = "publication_or_reuse"
    DATASET_OR_ARTIFACT_ACCESS = "dataset_or_artifact_access"
    REFUSAL_OR_NO_SALE = "refusal_or_no_sale"


class IntendedUse(StrEnum):
    """Requester-declared intended use."""

    PERSONAL_LEARNING = "personal_learning"
    ACADEMIC_RESEARCH = "academic_research"
    COMMERCIAL_TRIAL = "commercial_trial"
    INTERNAL_DEPLOYMENT = "internal_deployment"
    PUBLIC_PUBLICATION = "public_publication"
    DATASET_REDISTRIBUTION = "dataset_redistribution"
    PLATFORM_INTEGRATION = "platform_integration"
    UNKNOWN = "unknown"


class ReceiveOnlyRail(StrEnum):
    """Approved receive-only payment rails — *no* outbound flows."""

    GITHUB_SPONSORS = "github_sponsors"
    OPEN_COLLECTIVE = "open_collective"
    LIBERAPAY = "liberapay"
    STRIPE_PAYMENT_LINK = "stripe_payment_link"
    OMG_LOL_PAY_AS_PUBLISHER = "omg_lol_pay_as_publisher"
    NO_RAIL = "no_rail"


class RefusalReason(StrEnum):
    EXPORT_GATE_BLOCKED = "export_gate_blocked"
    REQUIRES_CUSTOM_SERVICE = "requires_custom_service"
    REQUIRES_OUTBOUND_PAYMENT = "requires_outbound_payment"
    REQUIRES_DISCOVERY_CALL = "requires_discovery_call"
    REQUIRES_RETAINER = "requires_retainer"
    REQUIRES_CUSTOMER_SUCCESS = "requires_customer_success"
    REQUIRES_ACCOUNT_PORTAL = "requires_account_portal"
    REQUIRES_MULTI_USER_FEATURES = "requires_multi_user_features"
    UNKNOWN_TARGET_ARTIFACT = "unknown_target_artifact"
    OPERATOR_LEGAL_ATTESTATION_REQUIRED = "operator_legal_attestation_required"


class RequestStatus(StrEnum):
    OPEN = "open"
    QUOTED = "quoted"
    ACCEPTED = "accepted"
    PAID = "paid"
    REFUSED = "refused"


class _RouterModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class LicenseRequest(_RouterModel):
    """Inbound license-interest event."""

    request_id: str = Field(min_length=1)
    received_at: datetime
    intended_use: IntendedUse
    target_artifact_id: str | None = Field(default=None, min_length=1)
    requester_self_described: str = Field(default="", max_length=2000)
    requires_custom_service: bool = False
    requires_outbound_payment: bool = False
    requires_discovery_call: bool = False
    requires_retainer: bool = False
    requires_customer_success: bool = False
    requires_account_portal: bool = False
    requires_multi_user_features: bool = False
    operator_legal_attestation_required: bool = False


class Quote(_RouterModel):
    """Operator-receivable quote draft."""

    request_id: str
    price_class: PriceClass
    rail: ReceiveOnlyRail
    fixed_price_usd: float | None = Field(default=None, ge=0)
    pay_what_you_want: bool = False
    quote_text: str = Field(min_length=1)
    operator_legal_attestation_required: bool = False

    @model_validator(mode="after")
    def _validate_price_invariants(self) -> Self:
        if self.price_class is PriceClass.REFUSAL_OR_NO_SALE:
            raise ValueError("REFUSAL_OR_NO_SALE class produces a refusal, not a quote")
        if self.fixed_price_usd is None and not self.pay_what_you_want:
            if self.price_class is not PriceClass.PERSONAL_OR_RESEARCH_USE:
                raise ValueError(
                    f"price_class {self.price_class.value!r} requires a fixed_price_usd or pay_what_you_want"
                )
        if self.fixed_price_usd is not None and self.pay_what_you_want:
            raise ValueError("a quote cannot be both fixed_price and pay_what_you_want")
        return self


class RefusalResponse(_RouterModel):
    """Refusal-as-data record for inbound requests we will not transact."""

    request_id: str
    reasons: tuple[RefusalReason, ...] = Field(min_length=1)
    refusal_text: str = Field(min_length=1)


class RouteVerdict(_RouterModel):
    """The router's decision: a quote OR a refusal, never both."""

    request_id: str
    price_class: PriceClass
    quote: Quote | None = None
    refusal: RefusalResponse | None = None

    @model_validator(mode="after")
    def _exactly_one_branch(self) -> Self:
        if self.quote is None and self.refusal is None:
            raise ValueError("verdict requires either a quote or a refusal")
        if self.quote is not None and self.refusal is not None:
            raise ValueError("verdict cannot carry both a quote and a refusal")
        if self.price_class is PriceClass.REFUSAL_OR_NO_SALE and self.refusal is None:
            raise ValueError("REFUSAL_OR_NO_SALE class requires a refusal")
        if self.price_class is not PriceClass.REFUSAL_OR_NO_SALE and self.quote is None:
            raise ValueError(
                f"price_class {self.price_class.value!r} requires a quote, not a refusal"
            )
        return self


class LedgerEntry(_RouterModel):
    """One row in the request tracking ledger."""

    request_id: str
    received_at: datetime
    intended_use: IntendedUse
    price_class: PriceClass
    status: RequestStatus
    quote_sent: bool
    accepted: bool
    paid: bool
    refused: bool
    operator_legal_attestation_required: bool
    rail: ReceiveOnlyRail


_FORBIDDEN_OUTFLOW_FIELDS: tuple[tuple[str, RefusalReason], ...] = (
    ("requires_outbound_payment", RefusalReason.REQUIRES_OUTBOUND_PAYMENT),
    ("requires_discovery_call", RefusalReason.REQUIRES_DISCOVERY_CALL),
    ("requires_retainer", RefusalReason.REQUIRES_RETAINER),
    ("requires_customer_success", RefusalReason.REQUIRES_CUSTOMER_SUCCESS),
    ("requires_account_portal", RefusalReason.REQUIRES_ACCOUNT_PORTAL),
    ("requires_multi_user_features", RefusalReason.REQUIRES_MULTI_USER_FEATURES),
    ("requires_custom_service", RefusalReason.REQUIRES_CUSTOM_SERVICE),
)


def _classify_intended_use(use: IntendedUse) -> PriceClass:
    """Map an intended use to its default price class (overridable by gate)."""
    match use:
        case IntendedUse.PERSONAL_LEARNING | IntendedUse.ACADEMIC_RESEARCH:
            return PriceClass.PERSONAL_OR_RESEARCH_USE
        case IntendedUse.COMMERCIAL_TRIAL:
            return PriceClass.COMMERCIAL_EVALUATION
        case IntendedUse.INTERNAL_DEPLOYMENT | IntendedUse.PLATFORM_INTEGRATION:
            return PriceClass.COMMERCIAL_INTERNAL_USE
        case IntendedUse.PUBLIC_PUBLICATION:
            return PriceClass.PUBLICATION_OR_REUSE
        case IntendedUse.DATASET_REDISTRIBUTION:
            return PriceClass.DATASET_OR_ARTIFACT_ACCESS
        case IntendedUse.UNKNOWN:
            return PriceClass.PERSONAL_OR_RESEARCH_USE


_DEFAULT_RAIL_PER_CLASS: dict[PriceClass, ReceiveOnlyRail] = {
    PriceClass.PERSONAL_OR_RESEARCH_USE: ReceiveOnlyRail.GITHUB_SPONSORS,
    PriceClass.COMMERCIAL_EVALUATION: ReceiveOnlyRail.STRIPE_PAYMENT_LINK,
    PriceClass.COMMERCIAL_INTERNAL_USE: ReceiveOnlyRail.STRIPE_PAYMENT_LINK,
    PriceClass.PUBLICATION_OR_REUSE: ReceiveOnlyRail.STRIPE_PAYMENT_LINK,
    PriceClass.DATASET_OR_ARTIFACT_ACCESS: ReceiveOnlyRail.OMG_LOL_PAY_AS_PUBLISHER,
    PriceClass.REFUSAL_OR_NO_SALE: ReceiveOnlyRail.NO_RAIL,
}

_DEFAULT_PRICE_USD: dict[PriceClass, float | None] = {
    PriceClass.PERSONAL_OR_RESEARCH_USE: None,  # pay-what-you-want
    PriceClass.COMMERCIAL_EVALUATION: 99.0,
    PriceClass.COMMERCIAL_INTERNAL_USE: 499.0,
    PriceClass.PUBLICATION_OR_REUSE: 199.0,
    PriceClass.DATASET_OR_ARTIFACT_ACCESS: 49.0,
    PriceClass.REFUSAL_OR_NO_SALE: None,
}


def _quote_text(price_class: PriceClass, request: LicenseRequest, rail: ReceiveOnlyRail) -> str:
    if price_class is PriceClass.PERSONAL_OR_RESEARCH_USE:
        return (
            f"Personal/research use: pay-what-you-want via {rail.value}. "
            f"No invoicing, no support contract, no calls. "
            f"Re-use covered by the artifact's published license."
        )
    artifact = request.target_artifact_id or "(unspecified artifact)"
    price = _DEFAULT_PRICE_USD.get(price_class)
    price_line = f" ${price:.2f} USD." if price is not None else ""
    return (
        f"License class: {price_class.value}. Artifact: {artifact}.{price_line} "
        f"Receive-only rail: {rail.value}. "
        f"No discovery call, retainer, or customer-success flow is part of this offer."
    )


def _refusal_text(reasons: tuple[RefusalReason, ...]) -> str:
    if RefusalReason.REQUIRES_OUTBOUND_PAYMENT in reasons:
        prefix = "This system does not initiate outbound payments. "
    elif RefusalReason.REQUIRES_DISCOVERY_CALL in reasons:
        prefix = "This system does not take discovery calls. "
    elif RefusalReason.REQUIRES_RETAINER in reasons:
        prefix = "This system does not enter retainer agreements. "
    elif RefusalReason.REQUIRES_CUSTOMER_SUCCESS in reasons:
        prefix = "This system does not provide customer-success engagement. "
    elif RefusalReason.REQUIRES_ACCOUNT_PORTAL in reasons:
        prefix = "This system does not operate account portals. "
    elif RefusalReason.REQUIRES_CUSTOM_SERVICE in reasons:
        prefix = "This system does not deliver custom service. "
    elif RefusalReason.REQUIRES_MULTI_USER_FEATURES in reasons:
        prefix = "This system is single-operator and does not ship multi-user features. "
    else:
        prefix = "This request cannot be transacted under current policy. "
    reason_list = ", ".join(r.value for r in reasons)
    return prefix + f"Refusal reasons: {reason_list}."


def evaluate_request(request: LicenseRequest) -> RouteVerdict:
    """Apply the price-class router to a request — fail-closed on forbidden flows."""
    refusal_reasons: list[RefusalReason] = []
    for field_name, reason in _FORBIDDEN_OUTFLOW_FIELDS:
        if getattr(request, field_name):
            refusal_reasons.append(reason)

    if refusal_reasons:
        return RouteVerdict(
            request_id=request.request_id,
            price_class=PriceClass.REFUSAL_OR_NO_SALE,
            refusal=RefusalResponse(
                request_id=request.request_id,
                reasons=tuple(refusal_reasons),
                refusal_text=_refusal_text(tuple(refusal_reasons)),
            ),
        )

    price_class = _classify_intended_use(request.intended_use)
    rail = _DEFAULT_RAIL_PER_CLASS[price_class]
    fixed_price = _DEFAULT_PRICE_USD[price_class]
    pay_what_you_want = fixed_price is None and price_class is not PriceClass.REFUSAL_OR_NO_SALE

    quote = Quote(
        request_id=request.request_id,
        price_class=price_class,
        rail=rail,
        fixed_price_usd=fixed_price,
        pay_what_you_want=pay_what_you_want,
        quote_text=_quote_text(price_class, request, rail),
        operator_legal_attestation_required=request.operator_legal_attestation_required,
    )
    return RouteVerdict(request_id=request.request_id, price_class=price_class, quote=quote)


def ledger_entry(
    verdict: RouteVerdict, request: LicenseRequest, status: RequestStatus
) -> LedgerEntry:
    """Build a tracked ledger entry from a verdict + request + outcome status."""
    rail = verdict.quote.rail if verdict.quote is not None else ReceiveOnlyRail.NO_RAIL
    legal_attestation = (
        verdict.quote.operator_legal_attestation_required
        if verdict.quote is not None
        else request.operator_legal_attestation_required
    )
    return LedgerEntry(
        request_id=request.request_id,
        received_at=request.received_at,
        intended_use=request.intended_use,
        price_class=verdict.price_class,
        status=status,
        quote_sent=verdict.quote is not None
        and status in {RequestStatus.QUOTED, RequestStatus.ACCEPTED, RequestStatus.PAID},
        accepted=status in {RequestStatus.ACCEPTED, RequestStatus.PAID},
        paid=status is RequestStatus.PAID,
        refused=status is RequestStatus.REFUSED,
        operator_legal_attestation_required=legal_attestation,
        rail=rail,
    )


def now_utc() -> datetime:
    return datetime.now(tz=UTC)


__all__ = [
    "IntendedUse",
    "LedgerEntry",
    "LicenseRequest",
    "PriceClass",
    "Quote",
    "ReceiveOnlyRail",
    "RefusalReason",
    "RefusalResponse",
    "RequestStatus",
    "RouteVerdict",
    "evaluate_request",
    "ledger_entry",
    "now_utc",
]

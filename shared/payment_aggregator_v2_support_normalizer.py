"""Payment aggregator v2 — support-receipt normalizer.

Extends receive-only support aggregation so Liberapay,
Lightning / Nostr, guarded Ko-fi, and YouTube fan funding can be
recorded as aggregate, no-perk support signals — *without* exposing
payer identity or creating a relationship surface.

Constitutional invariants enforced at construction:

1. Public-emit shape carries no name, email, handle, message /
   comment, payer id, or per-payer history.
2. Adapters exist only for rails approved by
   ``support-surface-registry``.
3. Public emission is gated on
   ``MonetizationReadiness.safe_to_monetize``.
4. Rails are receive-only — there is no method that initiates send,
   payout, transfer, or refund.

cc-task: ``payment-aggregator-v2-support-normalizer``.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Rail(StrEnum):
    """Approved receive-only support rails."""

    LIGHTNING = "lightning"
    NOSTR_ZAP = "nostr_zap"
    LIBERAPAY = "liberapay"
    KOFI_GUARDED = "kofi_guarded"
    YOUTUBE_FAN_FUNDING = "youtube_fan_funding"


class CurrencyUnit(StrEnum):
    """Unit the rail reports in. Each rail has one canonical unit."""

    SATS = "sats"
    USD = "usd"
    EUR = "eur"


class EventType(StrEnum):
    """Aggregate event categories — no per-payer narrative kinds."""

    SUPPORT_RECEIVED = "support_received"
    RECURRING_RENEWAL = "recurring_renewal"
    ONE_TIME_TIP = "one_time_tip"
    FAN_FUNDING_SUPER_THANKS = "fan_funding_super_thanks"


class Visibility(StrEnum):
    """Public-vs-private flag for the normalized receipt."""

    PRIVATE_ONLY = "private_only"
    AGGREGATE_PUBLIC = "aggregate_public"


_RAIL_DEFAULT_CURRENCY: dict[Rail, CurrencyUnit] = {
    Rail.LIGHTNING: CurrencyUnit.SATS,
    Rail.NOSTR_ZAP: CurrencyUnit.SATS,
    Rail.LIBERAPAY: CurrencyUnit.EUR,
    Rail.KOFI_GUARDED: CurrencyUnit.USD,
    Rail.YOUTUBE_FAN_FUNDING: CurrencyUnit.USD,
}


class _NormalizerModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class NormalizedSupportReceipt(_NormalizerModel):
    """Aggregate, payer-anonymous support receipt.

    *No PII fields exist on this type.* The constructor refuses to
    accept ``name``, ``email``, ``handle``, ``payer_id``,
    ``message``, or ``comment`` via the ``extra="forbid"`` config —
    construction simply fails if any caller tries to inject them.
    """

    receipt_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    rail: Rail
    amount: float = Field(gt=0)
    currency_unit: CurrencyUnit
    timestamp: datetime
    event_type: EventType
    visibility: Visibility

    @model_validator(mode="after")
    def _validate_rail_currency_match(self) -> Self:
        expected = _RAIL_DEFAULT_CURRENCY[self.rail]
        if self.currency_unit is not expected:
            raise ValueError(
                f"rail {self.rail.value!r} requires currency_unit={expected.value!r}; "
                f"got {self.currency_unit.value!r}"
            )
        return self


class MonetizationReadinessGate(_NormalizerModel):
    """Minimal projection of MonetizationReadiness used by the normalizer.

    The full ledger lives in ``shared.monetization_readiness_ledger``;
    the normalizer only needs the boolean ``safe_to_monetize`` plus
    the captured-at timestamp for traceability.
    """

    safe_to_monetize: bool
    captured_at: datetime
    snapshot_source: str = Field(min_length=1)


class SupportSurfaceApproval(_NormalizerModel):
    """Approval projection from ``support-surface-registry`` — one rail."""

    rail: Rail
    approved: bool
    decision_ref: str = Field(min_length=1)


class PublicAggregateEmission(_NormalizerModel):
    """Public-safe aggregate emission produced from approved receipts.

    Carries only counts and totals — never per-receipt detail, never
    payer identity. The renderer in this module is the only allowed
    public-emit path; ``NormalizedSupportReceipt`` itself is private
    by default.
    """

    rail: Rail
    receipt_count: int = Field(ge=0)
    total_amount: float = Field(ge=0)
    currency_unit: CurrencyUnit
    window_start: datetime
    window_end: datetime
    captured_at: datetime

    @model_validator(mode="after")
    def _validate_window(self) -> Self:
        if self.window_end < self.window_start:
            raise ValueError("window_end must be >= window_start")
        return self


class NormalizerVerdict(StrEnum):
    EMITTED = "emitted"
    REFUSED_NOT_APPROVED = "refused_not_approved"
    REFUSED_NOT_SAFE_TO_MONETIZE = "refused_not_safe_to_monetize"
    REFUSED_PRIVATE_ONLY = "refused_private_only"
    REFUSED_NO_RECEIPTS = "refused_no_receipts"


class PublicEmitDecision(_NormalizerModel):
    rail: Rail
    verdict: NormalizerVerdict
    emission: PublicAggregateEmission | None = None
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def _exactly_emit_or_refuse(self) -> Self:
        if self.verdict is NormalizerVerdict.EMITTED and self.emission is None:
            raise ValueError("EMITTED verdict requires an emission")
        if self.verdict is not NormalizerVerdict.EMITTED and self.emission is not None:
            raise ValueError(f"verdict {self.verdict.value!r} cannot carry an emission")
        return self


def evaluate_public_emit(
    rail: Rail,
    receipts: tuple[NormalizedSupportReceipt, ...],
    *,
    surface_approval: SupportSurfaceApproval,
    readiness: MonetizationReadinessGate,
    window_start: datetime,
    window_end: datetime,
    captured_at: datetime,
) -> PublicEmitDecision:
    """Apply the public-emit gate to a receipt window — fail-closed.

    The gate refuses unless the surface is approved AND
    ``safe_to_monetize`` AND at least one receipt is marked
    ``aggregate_public``. The emission carries only counts and totals.
    """

    if surface_approval.rail is not rail:
        raise ValueError(
            f"surface_approval rail {surface_approval.rail.value!r} does not match {rail.value!r}"
        )

    if not surface_approval.approved:
        return PublicEmitDecision(
            rail=rail,
            verdict=NormalizerVerdict.REFUSED_NOT_APPROVED,
            reason=f"rail {rail.value!r} not approved by support-surface-registry",
        )

    if not readiness.safe_to_monetize:
        return PublicEmitDecision(
            rail=rail,
            verdict=NormalizerVerdict.REFUSED_NOT_SAFE_TO_MONETIZE,
            reason=(
                f"MonetizationReadiness.safe_to_monetize is False at "
                f"{readiness.captured_at.isoformat()!r}"
            ),
        )

    public_receipts = tuple(
        r for r in receipts if r.rail is rail and r.visibility is Visibility.AGGREGATE_PUBLIC
    )
    if not public_receipts:
        if not any(r.rail is rail for r in receipts):
            return PublicEmitDecision(
                rail=rail,
                verdict=NormalizerVerdict.REFUSED_NO_RECEIPTS,
                reason=f"no receipts for rail {rail.value!r}",
            )
        return PublicEmitDecision(
            rail=rail,
            verdict=NormalizerVerdict.REFUSED_PRIVATE_ONLY,
            reason=(
                f"all receipts for rail {rail.value!r} are marked private_only; "
                f"public aggregate emission refused"
            ),
        )

    expected_currency = _RAIL_DEFAULT_CURRENCY[rail]
    total = sum(r.amount for r in public_receipts)
    emission = PublicAggregateEmission(
        rail=rail,
        receipt_count=len(public_receipts),
        total_amount=total,
        currency_unit=expected_currency,
        window_start=window_start,
        window_end=window_end,
        captured_at=captured_at,
    )
    return PublicEmitDecision(
        rail=rail,
        verdict=NormalizerVerdict.EMITTED,
        emission=emission,
        reason=(
            f"emitted aggregate for rail {rail.value!r}: "
            f"{len(public_receipts)} receipts totaling {total} {expected_currency.value}"
        ),
    )


def render_public_aggregate_text(emission: PublicAggregateEmission) -> str:
    """Render a payer-anonymous aggregate emission string.

    The output contains only the fields on ``PublicAggregateEmission``
    — count, total, currency, rail, and the window. There are no
    fields for name, message, handle, or per-payer history because
    those fields do not exist on the input.
    """
    return (
        f"Support window {emission.window_start.isoformat()} → "
        f"{emission.window_end.isoformat()}: "
        f"{emission.receipt_count} aggregate receipts via "
        f"{emission.rail.value} totaling "
        f"{emission.total_amount} {emission.currency_unit.value}."
    )


__all__ = [
    "CurrencyUnit",
    "EventType",
    "MonetizationReadinessGate",
    "NormalizedSupportReceipt",
    "NormalizerVerdict",
    "PublicAggregateEmission",
    "PublicEmitDecision",
    "Rail",
    "SupportSurfaceApproval",
    "Visibility",
    "evaluate_public_emit",
    "render_public_aggregate_text",
]

"""Stripe Payment Link V5 publisher — fourth wired monetization rail.

Per cc-task ``stripe-payment-link-end-to-end-wiring``. Pattern-matches
the Sponsors / Liberapay / Open Collective publishers; the
distinguishing shape is Stripe's **timestamped HMAC** (the rail
handles this internally; the publisher just receives a normalized
:class:`PaymentEvent`).

V5 publication-bus invariants the publisher enforces:

1. **AllowlistGate** — only the four canonical
   :class:`PaymentEventKind` values dispatch.
2. **Legal-name-leak guard** — manifest body never carries the
   operator's legal name.
3. **Prometheus Counter** — per-surface per-result outcome.

Manifest output: ``{output_dir}/event-{kind}-{sha16}.md``. Body
carries the four normalized fields + currency — *no* receipt URLs,
*no* customer emails, *no* billing addresses.

**Subscription-deletion auto-link.** When
:class:`PaymentEventKind.CUSTOMER_SUBSCRIPTION_DELETED` fires, the
publisher additionally appends a :class:`agents.refusal_brief.RefusalEvent`
to the canonical refusal log under axiom ``full_auto_or_nothing``
and surface ``publication_bus:stripe-payment-link-receiver:customer_subscription_deleted``.
The existing ``refusal_annex_renderer`` aggregates these into the
``declined-stripe-subscription-deletion`` annex slug.

cc-task: ``stripe-payment-link-end-to-end-wiring``. Fourth Tier-1
rail to ship a wired publisher.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

from agents.publication_bus.publisher_kit import (
    Publisher,
    PublisherPayload,
    PublisherResult,
)
from agents.publication_bus.publisher_kit.allowlist import (
    AllowlistGate,
    load_allowlist,
)
from shared.stripe_payment_link_receive_only_rail import (
    PaymentEvent,
    PaymentEventKind,
)

log = logging.getLogger(__name__)

STRIPE_PAYMENT_LINK_PUBLISHER_SURFACE: str = "stripe-payment-link-receiver"


def _default_output_dir() -> Path:
    home_env = os.environ.get("HAPAX_HOME")
    base = Path(home_env) if home_env else Path.home()
    return base / "hapax-state" / "publications" / "stripe-payment-link"


DEFAULT_STRIPE_PAYMENT_LINK_ALLOWLIST: AllowlistGate = load_allowlist(
    STRIPE_PAYMENT_LINK_PUBLISHER_SURFACE,
    [k.value for k in PaymentEventKind],
)

CANCELLATION_REFUSAL_AXIOM: str = "full_auto_or_nothing"
CANCELLATION_REFUSAL_SURFACE: str = (
    "publication_bus:stripe-payment-link-receiver:customer_subscription_deleted"
)


class StripePaymentLinkPublisher(Publisher):
    """V5 publisher for normalized Stripe Payment Link events."""

    surface_name: ClassVar[str] = STRIPE_PAYMENT_LINK_PUBLISHER_SURFACE
    allowlist: ClassVar[AllowlistGate] = DEFAULT_STRIPE_PAYMENT_LINK_ALLOWLIST
    requires_legal_name: ClassVar[bool] = False

    def __init__(self, *, output_dir: Path | None = None) -> None:
        self.output_dir = output_dir if output_dir is not None else _default_output_dir()

    def publish_event(self, event: PaymentEvent) -> PublisherResult:
        body = self._render_manifest_body(event)
        payload = PublisherPayload(
            target=event.event_kind.value,
            text=body,
            metadata={
                "customer_handle": event.customer_handle,
                "amount_currency_cents": event.amount_currency_cents,
                "currency": event.currency,
                "raw_payload_sha256": event.raw_payload_sha256,
                "occurred_at_iso": event.occurred_at.isoformat(),
            },
        )
        return self.publish(payload)

    @staticmethod
    def _render_manifest_body(event: PaymentEvent) -> str:
        lines = [
            f"# Stripe Payment Link event — {event.event_kind.value}",
            "",
            f"- **Event kind:** {event.event_kind.value}",
            f"- **Customer:** {event.customer_handle}",
            f"- **Amount ({event.currency} minor units):** {event.amount_currency_cents}",
            f"- **Occurred at:** {event.occurred_at.isoformat()}",
            f"- **Payload SHA-256:** `{event.raw_payload_sha256}`",
            "",
        ]
        return "\n".join(lines)

    def _emit(self, payload: PublisherPayload) -> PublisherResult:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        sha = str(payload.metadata.get("raw_payload_sha256", ""))[:16] or "unknown"
        path = self.output_dir / f"event-{payload.target}-{sha}.md"
        try:
            path.write_text(payload.text, encoding="utf-8")
        except OSError as exc:
            log.warning("stripe_payment_link manifest write failed: %s", exc)
            return PublisherResult(error=True, detail=f"write failed: {exc}")

        if payload.target == PaymentEventKind.CUSTOMER_SUBSCRIPTION_DELETED.value:
            self._auto_link_cancellation_to_refusal_log(payload)

        return PublisherResult(ok=True, detail=str(path))

    @staticmethod
    def _auto_link_cancellation_to_refusal_log(payload: PublisherPayload) -> None:
        try:
            from pathlib import Path as _Path

            from agents.refusal_brief import RefusalEvent, append

            sha = str(payload.metadata.get("raw_payload_sha256", ""))[:16] or "unknown"
            currency = payload.metadata.get("currency", "")
            cents = payload.metadata.get("amount_currency_cents", 0)
            reason = f"stripe subscription deletion: {currency}_cents={cents} sha16={sha}"
            override_path = os.environ.get("HAPAX_REFUSALS_LOG_PATH")
            event = RefusalEvent(
                timestamp=datetime.now(UTC),
                axiom=CANCELLATION_REFUSAL_AXIOM,
                surface=CANCELLATION_REFUSAL_SURFACE,
                reason=reason[:160],
            )
            if override_path:
                append(event, log_path=_Path(override_path))
            else:
                append(event)
        except Exception:
            log.debug("refusal_brief auto-link failed", exc_info=True)


def manifest_path_for_event(
    event: PaymentEvent,
    *,
    output_dir: Path | None = None,
) -> Path:
    base = output_dir if output_dir is not None else _default_output_dir()
    sha = event.raw_payload_sha256[:16]
    return base / f"event-{event.event_kind.value}-{sha}.md"


def event_to_manifest_record(event: PaymentEvent) -> dict[str, object]:
    return {
        "event_kind": event.event_kind.value,
        "customer_handle": event.customer_handle,
        "amount_currency_cents": int(event.amount_currency_cents),
        "currency": event.currency,
        "occurred_at_iso": event.occurred_at.isoformat(),
        "raw_payload_sha256": event.raw_payload_sha256,
    }


__all__ = [
    "CANCELLATION_REFUSAL_AXIOM",
    "CANCELLATION_REFUSAL_SURFACE",
    "DEFAULT_STRIPE_PAYMENT_LINK_ALLOWLIST",
    "STRIPE_PAYMENT_LINK_PUBLISHER_SURFACE",
    "StripePaymentLinkPublisher",
    "event_to_manifest_record",
    "manifest_path_for_event",
]

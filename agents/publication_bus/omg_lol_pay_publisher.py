"""omg.lol Pay V5 publisher — fifth wired monetization rail.

Closes cc-task ``publication-bus-monetization-rails-surfaces``
(4 of 5 rails — github-sponsors, stripe-payment-link, open-collective,
liberapay — shipped previously on main; this module + the sibling
:mod:`shared.omg_lol_pay_receive_only_rail` complete the keystone).

Pattern-matches
:class:`agents.publication_bus.liberapay_publisher.LiberapayPublisher`
exactly; the only differences are the typed event class
(``PaymentEvent`` vs ``DonationEvent``), the cancellation-equivalent
event kinds (``payment_refunded`` + ``subscription_cancelled`` vs
``tip_cancelled``), and the USD-cents amount field
(``amount_usd_cents`` vs ``amount_eur_cents``).

V5 publication-bus invariants the publisher enforces (inherited
from the :class:`Publisher` ABC):

1. AllowlistGate — only the four canonical
   :class:`PaymentEventKind` values dispatch through the publisher.
2. Legal-name-leak guard — the manifest body must never carry the
   operator's legal name (payment manifests are aggregate-only and
   use the operator-referent picker).
3. Prometheus Counter — per-surface per-result outcome on the
   canonical ``hapax_publication_bus_publishes_total`` metric.

The publisher writes one aggregate manifest row per dispatch to
``{output_dir}/event-{kind}-{sha16}.md``. Body carries only the
aggregate fields surfaced on the normalized event (``event_kind``,
``donor_handle``, ``amount_usd_cents``, ``occurred_at``) — *no*
payment notes, *no* donor email, *no* omg.lol-internal IDs.

Refund / subscription-cancellation auto-link. When
:class:`PaymentEventKind.PAYMENT_REFUNDED` or
:class:`PaymentEventKind.SUBSCRIPTION_CANCELLED` fires, the publisher
appends a refusal-log entry so the existing
:func:`agents.marketing.refusal_annex_renderer` aggregator picks it
up under the ``declined-omg-lol-pay-refund`` /
``declined-omg-lol-pay-subscription-cancellation`` annex slugs. This
is the auto-link path the canonical refusal pattern names: a
cancellation/refund is refusal-as-data and routes through the
canonical log.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import ClassVar

from agents.publication_bus._rail_publisher_helpers import (
    CANCELLATION_REFUSAL_AXIOM,
    auto_link_cancellation_to_refusal_log,
    default_output_dir,
    safe_filename_for_event,
    write_manifest_entry,
)
from agents.publication_bus.publisher_kit import (
    Publisher,
    PublisherPayload,
    PublisherResult,
)
from agents.publication_bus.publisher_kit.allowlist import (
    AllowlistGate,
    load_allowlist,
)
from shared.omg_lol_pay_receive_only_rail import (
    PaymentEvent,
    PaymentEventKind,
)

log = logging.getLogger(__name__)

OMG_LOL_PAY_PUBLISHER_SURFACE: str = "omg-lol-pay-receiver"
"""Stable surface identifier for the V5 publisher."""

DEFAULT_OMG_LOL_PAY_ALLOWLIST: AllowlistGate = load_allowlist(
    OMG_LOL_PAY_PUBLISHER_SURFACE,
    [k.value for k in PaymentEventKind],
)

PAYMENT_REFUNDED_REFUSAL_SURFACE: str = "publication_bus:omg-lol-pay-receiver:payment_refunded"
SUBSCRIPTION_CANCELLED_REFUSAL_SURFACE: str = (
    "publication_bus:omg-lol-pay-receiver:subscription_cancelled"
)


class OmgLolPayPublisher(Publisher):
    """V5 publisher for normalized omg.lol Pay events.

    Construction is cheap and side-effect-free. Each
    :meth:`publish_event` call writes one aggregate manifest row
    plus (on refund or subscription cancellation) one refusal-log
    entry. The Publisher ABC's three invariants enforce that:

    - The event_kind (``payload.target``) is explicitly registered.
    - The body (``payload.text``) contains no legal-name leak.
    - Outcomes counter-record on the canonical metric.
    """

    surface_name: ClassVar[str] = OMG_LOL_PAY_PUBLISHER_SURFACE
    allowlist: ClassVar[AllowlistGate] = DEFAULT_OMG_LOL_PAY_ALLOWLIST
    requires_legal_name: ClassVar[bool] = False

    def __init__(self, *, output_dir: Path | None = None) -> None:
        self.output_dir = (
            output_dir if output_dir is not None else default_output_dir("omg_lol_pay")
        )

    def publish_event(self, event: PaymentEvent) -> PublisherResult:
        """Convenience wrapper: build payload from normalized event and publish."""

        body = self._render_manifest_body(event)
        payload = PublisherPayload(
            target=event.event_kind.value,
            text=body,
            metadata={
                "donor_handle": event.donor_handle,
                "amount_usd_cents": event.amount_usd_cents,
                "raw_payload_sha256": event.raw_payload_sha256,
                "occurred_at_iso": event.occurred_at.isoformat(),
            },
        )
        return self.publish(payload)

    @staticmethod
    def _render_manifest_body(event: PaymentEvent) -> str:
        """Render the aggregate manifest markdown body.

        Aggregate-only — carries the four normalized fields on the
        :class:`PaymentEvent`, no omg.lol-internal IDs and no
        free-text from the original payload. Renders deterministically.
        """

        lines = [
            f"# omg.lol Pay event — {event.event_kind.value}",
            "",
            f"- **Event kind:** {event.event_kind.value}",
            f"- **Donor:** {event.donor_handle}",
            f"- **Amount (USD cents):** {event.amount_usd_cents}",
            f"- **Occurred at:** {event.occurred_at.isoformat()}",
            f"- **Payload SHA-256:** `{event.raw_payload_sha256}`",
            "",
        ]
        return "\n".join(lines)

    def _emit(self, payload: PublisherPayload) -> PublisherResult:
        """Write the aggregate manifest entry; auto-link on refund / cancel."""

        result = write_manifest_entry(self.output_dir, payload, log=log)
        if not result.ok:
            return result

        target = payload.target
        sha = str(payload.metadata.get("raw_payload_sha256", ""))[:16] or "unknown"
        cents = payload.metadata.get("amount_usd_cents", 0)

        if target == PaymentEventKind.PAYMENT_REFUNDED.value:
            auto_link_cancellation_to_refusal_log(
                payload,
                axiom=CANCELLATION_REFUSAL_AXIOM,
                surface=PAYMENT_REFUNDED_REFUSAL_SURFACE,
                reason=f"omg.lol Pay refund: amount_usd_cents={cents} sha16={sha}",
                log=log,
            )
        elif target == PaymentEventKind.SUBSCRIPTION_CANCELLED.value:
            auto_link_cancellation_to_refusal_log(
                payload,
                axiom=CANCELLATION_REFUSAL_AXIOM,
                surface=SUBSCRIPTION_CANCELLED_REFUSAL_SURFACE,
                reason=(
                    f"omg.lol Pay subscription cancellation: amount_usd_cents={cents} sha16={sha}"
                ),
                log=log,
            )
        return result


def manifest_path_for_event(
    event: PaymentEvent,
    *,
    output_dir: Path | None = None,
) -> Path:
    """Pure helper: compute the manifest path for a given event."""

    base = output_dir if output_dir is not None else default_output_dir("omg_lol_pay")
    return base / safe_filename_for_event(event.event_kind.value, event.raw_payload_sha256)


def event_to_manifest_record(event: PaymentEvent) -> dict[str, object]:
    """Pure helper: project the normalized event onto its aggregate fields."""

    return {
        "event_kind": event.event_kind.value,
        "donor_handle": event.donor_handle,
        "amount_usd_cents": int(event.amount_usd_cents),
        "occurred_at_iso": event.occurred_at.isoformat(),
        "raw_payload_sha256": event.raw_payload_sha256,
    }


__all__ = [
    "CANCELLATION_REFUSAL_AXIOM",
    "DEFAULT_OMG_LOL_PAY_ALLOWLIST",
    "OMG_LOL_PAY_PUBLISHER_SURFACE",
    "OmgLolPayPublisher",
    "PAYMENT_REFUNDED_REFUSAL_SURFACE",
    "SUBSCRIPTION_CANCELLED_REFUSAL_SURFACE",
    "event_to_manifest_record",
    "manifest_path_for_event",
]

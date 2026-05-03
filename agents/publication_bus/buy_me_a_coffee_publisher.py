"""Buy Me a Coffee V5 publisher — seventh wired monetization rail.

Per cc-task ``buy-me-a-coffee-end-to-end-wiring``. Pattern-matches
the prior six wired rails. BMaC uses HMAC SHA-256 over raw body in
``X-Signature-Sha256`` header (already shipped with ``raw_body=``
kwarg from day 1; no rail patch needed).

V5 publication-bus invariants:

1. **AllowlistGate** — only the four canonical
   :class:`CoffeeEventKind` values dispatch.
2. **Legal-name-leak guard** — manifest body never carries the
   operator's legal name.
3. **Prometheus Counter** — per-surface per-result outcome.

Manifest output: ``{output_dir}/event-{kind}-{sha16}.md``. Body
carries the four normalized fields + currency — *no* free-text
messages, *no* emails, *no* shipping addresses, *no* BMaC IDs.

**Membership-cancellation auto-link.** When
:class:`CoffeeEventKind.MEMBERSHIP_CANCELLED` fires, the publisher
appends a :class:`agents.refusal_brief.RefusalEvent` to the
canonical refusal log under axiom ``full_auto_or_nothing`` and
surface ``publication_bus:buy-me-a-coffee-receiver:membership_cancelled``.

cc-task: ``buy-me-a-coffee-end-to-end-wiring``. Seventh Tier-1 rail.
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
from shared.buy_me_a_coffee_receive_only_rail import (
    CoffeeEvent,
    CoffeeEventKind,
)

log = logging.getLogger(__name__)

BUY_ME_A_COFFEE_PUBLISHER_SURFACE: str = "buy-me-a-coffee-receiver"


DEFAULT_BUY_ME_A_COFFEE_ALLOWLIST: AllowlistGate = load_allowlist(
    BUY_ME_A_COFFEE_PUBLISHER_SURFACE,
    [k.value for k in CoffeeEventKind],
)

CANCELLATION_REFUSAL_SURFACE: str = "publication_bus:buy-me-a-coffee-receiver:membership_cancelled"


class BuyMeACoffeePublisher(Publisher):
    """V5 publisher for normalized BMaC events."""

    surface_name: ClassVar[str] = BUY_ME_A_COFFEE_PUBLISHER_SURFACE
    allowlist: ClassVar[AllowlistGate] = DEFAULT_BUY_ME_A_COFFEE_ALLOWLIST
    requires_legal_name: ClassVar[bool] = False

    def __init__(self, *, output_dir: Path | None = None) -> None:
        self.output_dir = (
            output_dir if output_dir is not None else default_output_dir("buy-me-a-coffee")
        )

    def publish_event(self, event: CoffeeEvent) -> PublisherResult:
        body = self._render_manifest_body(event)
        payload = PublisherPayload(
            target=event.event_kind.value,
            text=body,
            metadata={
                "supporter_handle": event.supporter_handle,
                "amount_currency_cents": event.amount_currency_cents,
                "currency": event.currency,
                "raw_payload_sha256": event.raw_payload_sha256,
                "occurred_at_iso": event.occurred_at.isoformat(),
            },
        )
        return self.publish(payload)

    @staticmethod
    def _render_manifest_body(event: CoffeeEvent) -> str:
        lines = [
            f"# Buy Me a Coffee event — {event.event_kind.value}",
            "",
            f"- **Event kind:** {event.event_kind.value}",
            f"- **Supporter:** {event.supporter_handle}",
            f"- **Amount ({event.currency} minor units):** {event.amount_currency_cents}",
            f"- **Occurred at:** {event.occurred_at.isoformat()}",
            f"- **Payload SHA-256:** `{event.raw_payload_sha256}`",
            "",
        ]
        return "\n".join(lines)

    def _emit(self, payload: PublisherPayload) -> PublisherResult:
        result = write_manifest_entry(self.output_dir, payload, log=log)
        if result.ok and payload.target == CoffeeEventKind.MEMBERSHIP_CANCELLED.value:
            sha = str(payload.metadata.get("raw_payload_sha256", ""))[:16] or "unknown"
            currency = payload.metadata.get("currency", "")
            cents = payload.metadata.get("amount_currency_cents", 0)
            auto_link_cancellation_to_refusal_log(
                payload,
                axiom=CANCELLATION_REFUSAL_AXIOM,
                surface=CANCELLATION_REFUSAL_SURFACE,
                reason=f"bmac membership cancellation: {currency}_cents={cents} sha16={sha}",
                log=log,
            )
        return result


def manifest_path_for_event(
    event: CoffeeEvent,
    *,
    output_dir: Path | None = None,
) -> Path:
    base = output_dir if output_dir is not None else default_output_dir("buy-me-a-coffee")
    return base / safe_filename_for_event(event.event_kind.value, event.raw_payload_sha256)


def event_to_manifest_record(event: CoffeeEvent) -> dict[str, object]:
    return {
        "event_kind": event.event_kind.value,
        "supporter_handle": event.supporter_handle,
        "amount_currency_cents": int(event.amount_currency_cents),
        "currency": event.currency,
        "occurred_at_iso": event.occurred_at.isoformat(),
        "raw_payload_sha256": event.raw_payload_sha256,
    }


__all__ = [
    "BUY_ME_A_COFFEE_PUBLISHER_SURFACE",
    "BuyMeACoffeePublisher",
    "CANCELLATION_REFUSAL_AXIOM",
    "CANCELLATION_REFUSAL_SURFACE",
    "DEFAULT_BUY_ME_A_COFFEE_ALLOWLIST",
    "event_to_manifest_record",
    "manifest_path_for_event",
]

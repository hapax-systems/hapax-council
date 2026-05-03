"""Treasury Prime V5 publisher — tenth wired monetization rail (FINAL rail).

Per cc-task ``treasury-prime-end-to-end-wiring``. Last rail in the
Tier 1 e2e wiring epic. Phase 0 accepts only
``incoming_ach.create``; Phase 1 extension to ``transaction.create``
(core direct accounts) is a separate downstream cc-task.

V5 publication-bus invariants:

1. **AllowlistGate** — only :class:`IncomingAchEventKind.INCOMING_ACH_CREATED`
   dispatches.
2. **Legal-name-leak guard** — manifest body never carries the
   operator's legal name.
3. **Prometheus Counter** — per-surface per-result outcome.

Manifest output: ``{output_dir}/event-{kind}-{sha16}.md``.

**No cancellation auto-link.** Treasury Prime's Phase 0 event is
``incoming_ach.create`` only — a creation event, not a cancellation.

cc-task: ``treasury-prime-end-to-end-wiring``. Tenth and FINAL
Tier-1 rail to ship a wired publisher.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import ClassVar

from agents.publication_bus._rail_publisher_helpers import (
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
from shared.treasury_prime_receive_only_rail import (
    IncomingAchEvent,
    IncomingAchEventKind,
)

log = logging.getLogger(__name__)

TREASURY_PRIME_PUBLISHER_SURFACE: str = "treasury-prime-receiver"


DEFAULT_TREASURY_PRIME_ALLOWLIST: AllowlistGate = load_allowlist(
    TREASURY_PRIME_PUBLISHER_SURFACE,
    [k.value for k in IncomingAchEventKind],
)


class TreasuryPrimePublisher(Publisher):
    """V5 publisher for normalized Treasury Prime incoming-ACH events."""

    surface_name: ClassVar[str] = TREASURY_PRIME_PUBLISHER_SURFACE
    allowlist: ClassVar[AllowlistGate] = DEFAULT_TREASURY_PRIME_ALLOWLIST
    requires_legal_name: ClassVar[bool] = False

    def __init__(self, *, output_dir: Path | None = None) -> None:
        self.output_dir = (
            output_dir if output_dir is not None else default_output_dir("treasury-prime")
        )

    def publish_event(self, event: IncomingAchEvent) -> PublisherResult:
        body = self._render_manifest_body(event)
        payload = PublisherPayload(
            target=event.event_kind.value,
            text=body,
            metadata={
                "originating_party_handle": event.originating_party_handle,
                "amount_currency_cents": event.amount_currency_cents,
                "currency": event.currency,
                "raw_payload_sha256": event.raw_payload_sha256,
                "occurred_at_iso": event.occurred_at.isoformat(),
            },
        )
        return self.publish(payload)

    @staticmethod
    def _render_manifest_body(event: IncomingAchEvent) -> str:
        lines = [
            f"# Treasury Prime event — {event.event_kind.value}",
            "",
            f"- **Event kind:** {event.event_kind.value}",
            f"- **Originating party:** {event.originating_party_handle}",
            f"- **Amount ({event.currency} minor units):** {event.amount_currency_cents}",
            f"- **Occurred at:** {event.occurred_at.isoformat()}",
            f"- **Payload SHA-256:** `{event.raw_payload_sha256}`",
            "",
        ]
        return "\n".join(lines)

    def _emit(self, payload: PublisherPayload) -> PublisherResult:
        return write_manifest_entry(self.output_dir, payload, log=log)


def manifest_path_for_event(
    event: IncomingAchEvent,
    *,
    output_dir: Path | None = None,
) -> Path:
    base = output_dir if output_dir is not None else default_output_dir("treasury-prime")
    return base / safe_filename_for_event(event.event_kind.value, event.raw_payload_sha256)


def event_to_manifest_record(event: IncomingAchEvent) -> dict[str, object]:
    return {
        "event_kind": event.event_kind.value,
        "originating_party_handle": event.originating_party_handle,
        "amount_currency_cents": int(event.amount_currency_cents),
        "currency": event.currency,
        "occurred_at_iso": event.occurred_at.isoformat(),
        "raw_payload_sha256": event.raw_payload_sha256,
    }


__all__ = [
    "DEFAULT_TREASURY_PRIME_ALLOWLIST",
    "TREASURY_PRIME_PUBLISHER_SURFACE",
    "TreasuryPrimePublisher",
    "event_to_manifest_record",
    "manifest_path_for_event",
]

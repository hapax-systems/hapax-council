"""Open Collective V5 publisher — third wired monetization rail.

Per cc-task ``open-collective-end-to-end-wiring`` (sister of #2280
github-sponsors-end-to-end-wiring and #2287 liberapay-end-to-end-wiring).
Pattern-matches the Sponsors / Liberapay publishers; adds multi-
currency normalization at the manifest level (Open Collective is
multi-currency-native vs Liberapay's EUR-only and Sponsors' USD-only
shapes).

V5 publication-bus invariants the publisher enforces (inherited
from the :class:`Publisher` ABC):

1. **AllowlistGate** — only the four canonical
   :class:`CollectiveEventKind` values dispatch.
2. **Legal-name-leak guard** — the manifest body must never carry
   the operator's legal name.
3. **Prometheus Counter** — per-surface per-result outcome on the
   canonical ``hapax_publication_bus_publishes_total`` metric.

The publisher writes one **aggregate manifest row** per dispatch
to ``{output_dir}/event-{kind}-{sha16}.md``. Body carries only the
aggregate fields surfaced on the normalized event (``event_kind``,
``member_handle``, ``amount_currency_cents``, ``currency``,
``occurred_at``) — *no* expense notes, *no* member email, *no*
Open Collective-internal IDs.

**No cancellation auto-link.** Unlike Sponsors / Liberapay, Open
Collective's canonical event kinds (``collective_transaction_created``,
``order_processed``, ``member_created``, ``expense_paid``) do not
include a cancellation-equivalent. The publisher therefore only
writes manifest entries; no refusal-log auto-link path fires. If
Open Collective adds cancellation events in the future, this
publisher should grow the auto-link path to mirror Sponsors /
Liberapay.

cc-task: ``open-collective-end-to-end-wiring``. Third Tier-1 rail
to ship a wired publisher.
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
from shared.open_collective_receive_only_rail import (
    CollectiveEvent,
    CollectiveEventKind,
)

log = logging.getLogger(__name__)

OPEN_COLLECTIVE_PUBLISHER_SURFACE: str = "open-collective-receiver"
"""Stable surface identifier for the V5 publisher."""


DEFAULT_OPEN_COLLECTIVE_ALLOWLIST: AllowlistGate = load_allowlist(
    OPEN_COLLECTIVE_PUBLISHER_SURFACE,
    [k.value for k in CollectiveEventKind],
)


class OpenCollectivePublisher(Publisher):
    """V5 publisher for normalized Open Collective events.

    Construction is cheap and side-effect-free. Each
    :meth:`publish_event` call writes one aggregate manifest row.
    The Publisher ABC's three invariants enforce that:

    - The event_kind (``payload.target``) is explicitly registered.
    - The body (``payload.text``) contains no legal-name leak.
    - Outcomes counter-record on the canonical metric.
    """

    surface_name: ClassVar[str] = OPEN_COLLECTIVE_PUBLISHER_SURFACE
    allowlist: ClassVar[AllowlistGate] = DEFAULT_OPEN_COLLECTIVE_ALLOWLIST
    requires_legal_name: ClassVar[bool] = False

    def __init__(self, *, output_dir: Path | None = None) -> None:
        self.output_dir = (
            output_dir if output_dir is not None else default_output_dir("open-collective")
        )

    def publish_event(self, event: CollectiveEvent) -> PublisherResult:
        """Convenience wrapper: build payload from normalized event and publish."""
        body = self._render_manifest_body(event)
        payload = PublisherPayload(
            target=event.event_kind.value,
            text=body,
            metadata={
                "member_handle": event.member_handle,
                "amount_currency_cents": event.amount_currency_cents,
                "currency": event.currency,
                "raw_payload_sha256": event.raw_payload_sha256,
                "occurred_at_iso": event.occurred_at.isoformat(),
            },
        )
        return self.publish(payload)

    @staticmethod
    def _render_manifest_body(event: CollectiveEvent) -> str:
        """Render the aggregate manifest markdown body."""
        lines = [
            f"# Open Collective event — {event.event_kind.value}",
            "",
            f"- **Event kind:** {event.event_kind.value}",
            f"- **Member:** {event.member_handle}",
            f"- **Amount ({event.currency} minor units):** {event.amount_currency_cents}",
            f"- **Occurred at:** {event.occurred_at.isoformat()}",
            f"- **Payload SHA-256:** `{event.raw_payload_sha256}`",
            "",
        ]
        return "\n".join(lines)

    def _emit(self, payload: PublisherPayload) -> PublisherResult:
        """Write the aggregate manifest entry."""
        return write_manifest_entry(self.output_dir, payload, log=log)


def manifest_path_for_event(
    event: CollectiveEvent,
    *,
    output_dir: Path | None = None,
) -> Path:
    """Pure helper: compute the manifest path for a given event."""
    base = output_dir if output_dir is not None else default_output_dir("open-collective")
    return base / safe_filename_for_event(event.event_kind.value, event.raw_payload_sha256)


def event_to_manifest_record(event: CollectiveEvent) -> dict[str, object]:
    """Pure helper: project the normalized event onto its aggregate fields."""
    return {
        "event_kind": event.event_kind.value,
        "member_handle": event.member_handle,
        "amount_currency_cents": int(event.amount_currency_cents),
        "currency": event.currency,
        "occurred_at_iso": event.occurred_at.isoformat(),
        "raw_payload_sha256": event.raw_payload_sha256,
    }


__all__ = [
    "DEFAULT_OPEN_COLLECTIVE_ALLOWLIST",
    "OPEN_COLLECTIVE_PUBLISHER_SURFACE",
    "OpenCollectivePublisher",
    "event_to_manifest_record",
    "manifest_path_for_event",
]

"""Ko-fi V5 publisher — fifth wired monetization rail.

Per cc-task ``ko-fi-end-to-end-wiring``. Pattern-matches the prior
four wired rails; the distinguishing shape is Ko-fi's
**token-in-payload verification** (NOT HMAC over a header). The
rail's ``_verify_token`` reads ``payload['verification_token']``
inline and compares against the env-var secret; the publisher just
receives a normalized :class:`KoFiEvent`.

V5 publication-bus invariants the publisher enforces:

1. **AllowlistGate** — only the four canonical
   :class:`KoFiEventKind` values dispatch.
2. **Legal-name-leak guard** — manifest body never carries the
   operator's legal name.
3. **Prometheus Counter** — per-surface per-result outcome.

Manifest output: ``{output_dir}/event-{kind}-{sha16}.md``. Body
carries the four normalized fields + currency — *no* free-text
supporter messages, *no* shipping addresses, *no* Ko-fi internal
IDs, *no* email even when the supporter ticked the marketing
opt-in checkbox.

**No cancellation auto-link.** Ko-fi's canonical 4 event kinds
(donation / subscription / commission / shop_order) do not include
a cancellation-equivalent. Publisher writes manifest entries only;
no refusal-log auto-link path. Subscription cancellations (if Ko-fi
adds them) would warrant a follow-up to introduce the auto-link
path, mirroring Sponsors / Liberapay / Stripe.

cc-task: ``ko-fi-end-to-end-wiring``. Fifth Tier-1 rail to ship a
wired publisher.
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
from shared.ko_fi_receive_only_rail import (
    KoFiEvent,
    KoFiEventKind,
)

log = logging.getLogger(__name__)

KO_FI_PUBLISHER_SURFACE: str = "ko-fi-receiver"


DEFAULT_KO_FI_ALLOWLIST: AllowlistGate = load_allowlist(
    KO_FI_PUBLISHER_SURFACE,
    [k.value for k in KoFiEventKind],
)


class KoFiPublisher(Publisher):
    """V5 publisher for normalized Ko-fi events."""

    surface_name: ClassVar[str] = KO_FI_PUBLISHER_SURFACE
    allowlist: ClassVar[AllowlistGate] = DEFAULT_KO_FI_ALLOWLIST
    requires_legal_name: ClassVar[bool] = False

    def __init__(self, *, output_dir: Path | None = None) -> None:
        self.output_dir = output_dir if output_dir is not None else default_output_dir("ko-fi")

    def publish_event(self, event: KoFiEvent) -> PublisherResult:
        body = self._render_manifest_body(event)
        payload = PublisherPayload(
            target=event.event_kind.value,
            text=body,
            metadata={
                "sender_handle": event.sender_handle,
                "amount_currency_cents": event.amount_currency_cents,
                "currency": event.currency,
                "raw_payload_sha256": event.raw_payload_sha256,
                "occurred_at_iso": event.occurred_at.isoformat(),
            },
        )
        return self.publish(payload)

    @staticmethod
    def _render_manifest_body(event: KoFiEvent) -> str:
        lines = [
            f"# Ko-fi event — {event.event_kind.value}",
            "",
            f"- **Event kind:** {event.event_kind.value}",
            f"- **Sender:** {event.sender_handle}",
            f"- **Amount ({event.currency} minor units):** {event.amount_currency_cents}",
            f"- **Occurred at:** {event.occurred_at.isoformat()}",
            f"- **Payload SHA-256:** `{event.raw_payload_sha256}`",
            "",
        ]
        return "\n".join(lines)

    def _emit(self, payload: PublisherPayload) -> PublisherResult:
        return write_manifest_entry(self.output_dir, payload, log=log)


def manifest_path_for_event(
    event: KoFiEvent,
    *,
    output_dir: Path | None = None,
) -> Path:
    base = output_dir if output_dir is not None else default_output_dir("ko-fi")
    return base / safe_filename_for_event(event.event_kind.value, event.raw_payload_sha256)


def event_to_manifest_record(event: KoFiEvent) -> dict[str, object]:
    return {
        "event_kind": event.event_kind.value,
        "sender_handle": event.sender_handle,
        "amount_currency_cents": int(event.amount_currency_cents),
        "currency": event.currency,
        "occurred_at_iso": event.occurred_at.isoformat(),
        "raw_payload_sha256": event.raw_payload_sha256,
    }


__all__ = [
    "DEFAULT_KO_FI_ALLOWLIST",
    "KO_FI_PUBLISHER_SURFACE",
    "KoFiPublisher",
    "event_to_manifest_record",
    "manifest_path_for_event",
]

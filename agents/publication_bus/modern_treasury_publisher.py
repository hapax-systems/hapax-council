"""Modern Treasury V5 publisher — ninth wired monetization rail (2nd bank rail).

Per cc-task ``modern-treasury-end-to-end-wiring``. Second bank rail
e2e wiring; cleaner direction-filter shape than Mercury (event-name-
level rather than data-level — accept set IS the filter).

V5 publication-bus invariants:

1. **AllowlistGate** — only the two
   :class:`IncomingPaymentEventKind` values dispatch
   (``incoming_payment_detail.created``, ``incoming_payment_detail.completed``).
2. **Legal-name-leak guard** — manifest body never carries the
   operator's legal name.
3. **Prometheus Counter** — per-surface per-result outcome.

Manifest output: ``{output_dir}/event-{kind}-{sha16}.md``. Body
carries normalized fields + currency + payment_method — *no*
account numbers, *no* memo, *no* vendor IDs.

**No cancellation auto-link.** Modern Treasury's 2 event kinds are
incoming lifecycle states (created / completed), not cancellations.

cc-task: ``modern-treasury-end-to-end-wiring``. Ninth Tier-1 rail.
"""

from __future__ import annotations

import logging
import os
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
from shared.modern_treasury_receive_only_rail import (
    IncomingPaymentEvent,
    IncomingPaymentEventKind,
)

log = logging.getLogger(__name__)

MODERN_TREASURY_PUBLISHER_SURFACE: str = "modern-treasury-receiver"


def _default_output_dir() -> Path:
    home_env = os.environ.get("HAPAX_HOME")
    base = Path(home_env) if home_env else Path.home()
    return base / "hapax-state" / "publications" / "modern-treasury"


DEFAULT_MODERN_TREASURY_ALLOWLIST: AllowlistGate = load_allowlist(
    MODERN_TREASURY_PUBLISHER_SURFACE,
    [k.value for k in IncomingPaymentEventKind],
)


class ModernTreasuryPublisher(Publisher):
    """V5 publisher for normalized Modern Treasury incoming-payment events."""

    surface_name: ClassVar[str] = MODERN_TREASURY_PUBLISHER_SURFACE
    allowlist: ClassVar[AllowlistGate] = DEFAULT_MODERN_TREASURY_ALLOWLIST
    requires_legal_name: ClassVar[bool] = False

    def __init__(self, *, output_dir: Path | None = None) -> None:
        self.output_dir = output_dir if output_dir is not None else _default_output_dir()

    def publish_event(self, event: IncomingPaymentEvent) -> PublisherResult:
        body = self._render_manifest_body(event)
        payload = PublisherPayload(
            target=event.event_kind.value,
            text=body,
            metadata={
                "originating_party_handle": event.originating_party_handle,
                "amount_currency_cents": event.amount_currency_cents,
                "currency": event.currency,
                "payment_method": event.payment_method.value,
                "raw_payload_sha256": event.raw_payload_sha256,
                "occurred_at_iso": event.occurred_at.isoformat(),
            },
        )
        return self.publish(payload)

    @staticmethod
    def _render_manifest_body(event: IncomingPaymentEvent) -> str:
        lines = [
            f"# Modern Treasury event — {event.event_kind.value}",
            "",
            f"- **Event kind:** {event.event_kind.value}",
            f"- **Payment method:** {event.payment_method.value}",
            f"- **Originating party:** {event.originating_party_handle}",
            f"- **Amount ({event.currency} minor units):** {event.amount_currency_cents}",
            f"- **Occurred at:** {event.occurred_at.isoformat()}",
            f"- **Payload SHA-256:** `{event.raw_payload_sha256}`",
            "",
        ]
        return "\n".join(lines)

    def _emit(self, payload: PublisherPayload) -> PublisherResult:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        sha = str(payload.metadata.get("raw_payload_sha256", ""))[:16] or "unknown"
        # incoming_payment_detail.created is dotted; sanitize for filename.
        safe_target = payload.target.replace(".", "_")
        path = self.output_dir / f"event-{safe_target}-{sha}.md"
        try:
            path.write_text(payload.text, encoding="utf-8")
        except OSError as exc:
            log.warning("modern_treasury manifest write failed: %s", exc)
            return PublisherResult(error=True, detail=f"write failed: {exc}")
        return PublisherResult(ok=True, detail=str(path))


def manifest_path_for_event(
    event: IncomingPaymentEvent,
    *,
    output_dir: Path | None = None,
) -> Path:
    base = output_dir if output_dir is not None else _default_output_dir()
    sha = event.raw_payload_sha256[:16]
    safe_kind = event.event_kind.value.replace(".", "_")
    return base / f"event-{safe_kind}-{sha}.md"


def event_to_manifest_record(event: IncomingPaymentEvent) -> dict[str, object]:
    return {
        "event_kind": event.event_kind.value,
        "payment_method": event.payment_method.value,
        "originating_party_handle": event.originating_party_handle,
        "amount_currency_cents": int(event.amount_currency_cents),
        "currency": event.currency,
        "occurred_at_iso": event.occurred_at.isoformat(),
        "raw_payload_sha256": event.raw_payload_sha256,
    }


__all__ = [
    "DEFAULT_MODERN_TREASURY_ALLOWLIST",
    "MODERN_TREASURY_PUBLISHER_SURFACE",
    "ModernTreasuryPublisher",
    "event_to_manifest_record",
    "manifest_path_for_event",
]

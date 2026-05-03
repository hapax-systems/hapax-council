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
from shared.buy_me_a_coffee_receive_only_rail import (
    CoffeeEvent,
    CoffeeEventKind,
)

log = logging.getLogger(__name__)

BUY_ME_A_COFFEE_PUBLISHER_SURFACE: str = "buy-me-a-coffee-receiver"


def _default_output_dir() -> Path:
    home_env = os.environ.get("HAPAX_HOME")
    base = Path(home_env) if home_env else Path.home()
    return base / "hapax-state" / "publications" / "buy-me-a-coffee"


DEFAULT_BUY_ME_A_COFFEE_ALLOWLIST: AllowlistGate = load_allowlist(
    BUY_ME_A_COFFEE_PUBLISHER_SURFACE,
    [k.value for k in CoffeeEventKind],
)

CANCELLATION_REFUSAL_AXIOM: str = "full_auto_or_nothing"
CANCELLATION_REFUSAL_SURFACE: str = "publication_bus:buy-me-a-coffee-receiver:membership_cancelled"


class BuyMeACoffeePublisher(Publisher):
    """V5 publisher for normalized BMaC events."""

    surface_name: ClassVar[str] = BUY_ME_A_COFFEE_PUBLISHER_SURFACE
    allowlist: ClassVar[AllowlistGate] = DEFAULT_BUY_ME_A_COFFEE_ALLOWLIST
    requires_legal_name: ClassVar[bool] = False

    def __init__(self, *, output_dir: Path | None = None) -> None:
        self.output_dir = output_dir if output_dir is not None else _default_output_dir()

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
        self.output_dir.mkdir(parents=True, exist_ok=True)
        sha = str(payload.metadata.get("raw_payload_sha256", ""))[:16] or "unknown"
        # Sanitize event_kind for use in filename (replace dots with underscores)
        safe_target = payload.target.replace(".", "_")
        path = self.output_dir / f"event-{safe_target}-{sha}.md"
        try:
            path.write_text(payload.text, encoding="utf-8")
        except OSError as exc:
            log.warning("buy_me_a_coffee manifest write failed: %s", exc)
            return PublisherResult(error=True, detail=f"write failed: {exc}")

        if payload.target == CoffeeEventKind.MEMBERSHIP_CANCELLED.value:
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
            reason = f"bmac membership cancellation: {currency}_cents={cents} sha16={sha}"
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
    event: CoffeeEvent,
    *,
    output_dir: Path | None = None,
) -> Path:
    base = output_dir if output_dir is not None else _default_output_dir()
    sha = event.raw_payload_sha256[:16]
    safe_kind = event.event_kind.value.replace(".", "_")
    return base / f"event-{safe_kind}-{sha}.md"


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

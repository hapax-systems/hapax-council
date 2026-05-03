"""Mercury V5 publisher — eighth wired monetization rail (1st bank rail).

Per cc-task ``mercury-end-to-end-wiring``. First bank-rail e2e wiring.
Pattern-matches the prior seven creator-platform rails. Mercury adds
**direction filter at data level** (the rail's
``MercuryTransactionDirection`` filter rejects outgoing transaction
kinds before the publisher ever sees the event); receiver already
shipped with ``raw_body=`` kwarg from day 1.

V5 publication-bus invariants:

1. **AllowlistGate** — only the two canonical
   :class:`MercuryEventKind` values dispatch
   (``transaction.created``, ``transaction.updated``).
2. **Legal-name-leak guard** — manifest body never carries the
   operator's legal name.
3. **Prometheus Counter** — per-surface per-result outcome.

Manifest output: ``{output_dir}/event-{kind}-{sha16}.md``. Body
carries the four normalized fields + currency + direction — *no*
account/routing numbers, *no* counterparty email, *no* address,
*no* memo, *no* status.

**No cancellation auto-link.** Mercury's canonical 2 event kinds
are lifecycle states (created / updated), not cancellations. The
receive-only direction filter handles the only refusal-as-data
concern (rejecting outgoing kinds), and that already happens at the
rail boundary, not the publisher boundary. Publisher writes manifest
entries only.

cc-task: ``mercury-end-to-end-wiring``. Eighth Tier-1 rail.
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
from shared.mercury_receive_only_rail import (
    MercuryEventKind,
    MercuryTransactionEvent,
)

log = logging.getLogger(__name__)

MERCURY_PUBLISHER_SURFACE: str = "mercury-receiver"


def _default_output_dir() -> Path:
    home_env = os.environ.get("HAPAX_HOME")
    base = Path(home_env) if home_env else Path.home()
    return base / "hapax-state" / "publications" / "mercury"


DEFAULT_MERCURY_ALLOWLIST: AllowlistGate = load_allowlist(
    MERCURY_PUBLISHER_SURFACE,
    [k.value for k in MercuryEventKind],
)


class MercuryPublisher(Publisher):
    """V5 publisher for normalized Mercury transaction events."""

    surface_name: ClassVar[str] = MERCURY_PUBLISHER_SURFACE
    allowlist: ClassVar[AllowlistGate] = DEFAULT_MERCURY_ALLOWLIST
    requires_legal_name: ClassVar[bool] = False

    def __init__(self, *, output_dir: Path | None = None) -> None:
        self.output_dir = output_dir if output_dir is not None else _default_output_dir()

    def publish_event(self, event: MercuryTransactionEvent) -> PublisherResult:
        body = self._render_manifest_body(event)
        payload = PublisherPayload(
            target=event.event_kind.value,
            text=body,
            metadata={
                "counterparty_handle": event.counterparty_handle,
                "amount_currency_cents": event.amount_currency_cents,
                "currency": event.currency,
                "direction": event.direction.value,
                "raw_payload_sha256": event.raw_payload_sha256,
                "occurred_at_iso": event.occurred_at.isoformat(),
            },
        )
        return self.publish(payload)

    @staticmethod
    def _render_manifest_body(event: MercuryTransactionEvent) -> str:
        lines = [
            f"# Mercury event — {event.event_kind.value}",
            "",
            f"- **Event kind:** {event.event_kind.value}",
            f"- **Direction:** {event.direction.value}",
            f"- **Counterparty:** {event.counterparty_handle}",
            f"- **Amount ({event.currency} minor units):** {event.amount_currency_cents}",
            f"- **Occurred at:** {event.occurred_at.isoformat()}",
            f"- **Payload SHA-256:** `{event.raw_payload_sha256}`",
            "",
        ]
        return "\n".join(lines)

    def _emit(self, payload: PublisherPayload) -> PublisherResult:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        sha = str(payload.metadata.get("raw_payload_sha256", ""))[:16] or "unknown"
        # Mercury event kinds are dotted (transaction.created); sanitize for filename.
        safe_target = payload.target.replace(".", "_")
        path = self.output_dir / f"event-{safe_target}-{sha}.md"
        try:
            path.write_text(payload.text, encoding="utf-8")
        except OSError as exc:
            log.warning("mercury manifest write failed: %s", exc)
            return PublisherResult(error=True, detail=f"write failed: {exc}")
        return PublisherResult(ok=True, detail=str(path))


def manifest_path_for_event(
    event: MercuryTransactionEvent,
    *,
    output_dir: Path | None = None,
) -> Path:
    base = output_dir if output_dir is not None else _default_output_dir()
    sha = event.raw_payload_sha256[:16]
    safe_kind = event.event_kind.value.replace(".", "_")
    return base / f"event-{safe_kind}-{sha}.md"


def event_to_manifest_record(event: MercuryTransactionEvent) -> dict[str, object]:
    return {
        "event_kind": event.event_kind.value,
        "direction": event.direction.value,
        "counterparty_handle": event.counterparty_handle,
        "amount_currency_cents": int(event.amount_currency_cents),
        "currency": event.currency,
        "occurred_at_iso": event.occurred_at.isoformat(),
        "raw_payload_sha256": event.raw_payload_sha256,
    }


__all__ = [
    "DEFAULT_MERCURY_ALLOWLIST",
    "MERCURY_PUBLISHER_SURFACE",
    "MercuryPublisher",
    "event_to_manifest_record",
    "manifest_path_for_event",
]

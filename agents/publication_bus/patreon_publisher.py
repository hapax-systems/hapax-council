"""Patreon V5 publisher — sixth wired monetization rail.

Per cc-task ``patreon-end-to-end-wiring``. Pattern-matches the prior
five wired rails. Patreon-specific shape: **HMAC MD5** (not SHA-256
— Patreon's documented wire format) + event-kind in
``X-Patreon-Event`` header (separate from the
``X-Patreon-Signature`` header).

V5 publication-bus invariants:

1. **AllowlistGate** — only the four canonical
   :class:`PledgeEventKind` values dispatch.
2. **Legal-name-leak guard** — manifest body never carries the
   operator's legal name.
3. **Prometheus Counter** — per-surface per-result outcome.

Manifest output: ``{output_dir}/event-{kind}-{sha16}.md``. Body
carries the four normalized fields + currency — *no* email, *no*
full_name, *no* billing addresses, *no* notes, *no* per-cycle
charge history.

**Pledge-delete auto-link.** When
:class:`PledgeEventKind.MEMBERS_PLEDGE_DELETE` fires, the publisher
appends a :class:`agents.refusal_brief.RefusalEvent` to the
canonical refusal log under axiom ``full_auto_or_nothing`` and
surface ``publication_bus:patreon-receiver:members_pledge_delete``.
The refusal_annex_renderer aggregates these into the
``declined-patreon-pledge-deletion`` annex slug.

cc-task: ``patreon-end-to-end-wiring``. Sixth Tier-1 rail.
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
from shared.patreon_receive_only_rail import (
    PledgeEvent,
    PledgeEventKind,
)

log = logging.getLogger(__name__)

PATREON_PUBLISHER_SURFACE: str = "patreon-receiver"


def _default_output_dir() -> Path:
    home_env = os.environ.get("HAPAX_HOME")
    base = Path(home_env) if home_env else Path.home()
    return base / "hapax-state" / "publications" / "patreon"


DEFAULT_PATREON_ALLOWLIST: AllowlistGate = load_allowlist(
    PATREON_PUBLISHER_SURFACE,
    [k.value for k in PledgeEventKind],
)

CANCELLATION_REFUSAL_AXIOM: str = "full_auto_or_nothing"
CANCELLATION_REFUSAL_SURFACE: str = "publication_bus:patreon-receiver:members_pledge_delete"


class PatreonPublisher(Publisher):
    """V5 publisher for normalized Patreon events."""

    surface_name: ClassVar[str] = PATREON_PUBLISHER_SURFACE
    allowlist: ClassVar[AllowlistGate] = DEFAULT_PATREON_ALLOWLIST
    requires_legal_name: ClassVar[bool] = False

    def __init__(self, *, output_dir: Path | None = None) -> None:
        self.output_dir = output_dir if output_dir is not None else _default_output_dir()

    def publish_event(self, event: PledgeEvent) -> PublisherResult:
        body = self._render_manifest_body(event)
        payload = PublisherPayload(
            target=event.event_kind.value,
            text=body,
            metadata={
                "patron_handle": event.patron_handle,
                "amount_currency_cents": event.amount_currency_cents,
                "currency": event.currency,
                "raw_payload_sha256": event.raw_payload_sha256,
                "occurred_at_iso": event.occurred_at.isoformat(),
            },
        )
        return self.publish(payload)

    @staticmethod
    def _render_manifest_body(event: PledgeEvent) -> str:
        lines = [
            f"# Patreon event — {event.event_kind.value}",
            "",
            f"- **Event kind:** {event.event_kind.value}",
            f"- **Patron:** {event.patron_handle}",
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
            log.warning("patreon manifest write failed: %s", exc)
            return PublisherResult(error=True, detail=f"write failed: {exc}")

        if payload.target == PledgeEventKind.MEMBERS_PLEDGE_DELETE.value:
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
            reason = f"patreon pledge delete: {currency}_cents={cents} sha16={sha}"
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
    event: PledgeEvent,
    *,
    output_dir: Path | None = None,
) -> Path:
    base = output_dir if output_dir is not None else _default_output_dir()
    sha = event.raw_payload_sha256[:16]
    return base / f"event-{event.event_kind.value}-{sha}.md"


def event_to_manifest_record(event: PledgeEvent) -> dict[str, object]:
    return {
        "event_kind": event.event_kind.value,
        "patron_handle": event.patron_handle,
        "amount_currency_cents": int(event.amount_currency_cents),
        "currency": event.currency,
        "occurred_at_iso": event.occurred_at.isoformat(),
        "raw_payload_sha256": event.raw_payload_sha256,
    }


__all__ = [
    "CANCELLATION_REFUSAL_AXIOM",
    "CANCELLATION_REFUSAL_SURFACE",
    "DEFAULT_PATREON_ALLOWLIST",
    "PATREON_PUBLISHER_SURFACE",
    "PatreonPublisher",
    "event_to_manifest_record",
    "manifest_path_for_event",
]

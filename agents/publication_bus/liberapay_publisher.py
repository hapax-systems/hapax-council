"""Liberapay V5 publisher — second wired monetization rail.

Per cc-task ``liberapay-end-to-end-wiring`` (sister of #2280
github-sponsors-end-to-end-wiring). Pattern-matches
:class:`agents.publication_bus.github_sponsors_publisher.GitHubSponsorsPublisher`
exactly; the only differences are the typed event class
(``DonationEvent`` vs ``SponsorshipEvent``), the cancellation-
equivalent event kind (``tip_cancelled`` vs ``cancelled``), and the
EUR-cents amount field (``amount_eur_cents`` vs ``tier_amount_usd``).

V5 publication-bus invariants the publisher enforces (inherited
from the :class:`Publisher` ABC):

1. **AllowlistGate** — only the four canonical
   :class:`DonationEventKind` values dispatch through the publisher.
2. **Legal-name-leak guard** — the manifest body must never carry
   the operator's legal name (donation manifests are aggregate-only
   and use the operator-referent picker).
3. **Prometheus Counter** — per-surface per-result outcome on the
   canonical ``hapax_publication_bus_publishes_total`` metric.

The publisher writes one **aggregate manifest row** per dispatch to
``{output_dir}/event-{kind}-{sha16}.md``. Body carries only the
aggregate fields surfaced on the normalized event (``event_kind``,
``donor_handle``, ``amount_eur_cents``, ``occurred_at``) — *no* tip
message, *no* donor email, *no* Liberapay-internal IDs.

**Tip-cancellation auto-link.** When
:class:`DonationEventKind.TIP_CANCELLED` fires, the publisher
additionally appends a :class:`agents.refusal_brief.RefusalEvent`
to the canonical refusal log so the existing
:func:`agents.marketing.refusal_annex_renderer` aggregator picks it
up under the ``declined-liberapay-tip-cancellation`` annex slug.
This is the auto-link path the cc-task names: a tip cancellation is
a refusal-as-data event, and refusal-as-data events route through
the canonical log.

cc-task: ``liberapay-end-to-end-wiring``. Second Tier-1 rail to
ship a wired publisher; first replication of the github-sponsors
pattern.
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
from shared.liberapay_receive_only_rail import (
    DonationEvent,
    DonationEventKind,
)

log = logging.getLogger(__name__)

LIBERAPAY_PUBLISHER_SURFACE: str = "liberapay-receiver"
"""Stable surface identifier for the V5 publisher."""


DEFAULT_LIBERAPAY_ALLOWLIST: AllowlistGate = load_allowlist(
    LIBERAPAY_PUBLISHER_SURFACE,
    [k.value for k in DonationEventKind],
)

CANCELLATION_REFUSAL_SURFACE: str = "publication_bus:liberapay-receiver:tip_cancelled"


class LiberapayPublisher(Publisher):
    """V5 publisher for normalized Liberapay donation events.

    Construction is cheap and side-effect-free. Each
    :meth:`publish_event` call writes one aggregate manifest row
    plus (on tip cancellation) one refusal-log entry. The Publisher
    ABC's three invariants enforce that:

    - The event_kind (``payload.target``) is explicitly registered.
    - The body (``payload.text``) contains no legal-name leak.
    - Outcomes counter-record on the canonical metric.
    """

    surface_name: ClassVar[str] = LIBERAPAY_PUBLISHER_SURFACE
    allowlist: ClassVar[AllowlistGate] = DEFAULT_LIBERAPAY_ALLOWLIST
    requires_legal_name: ClassVar[bool] = False

    def __init__(self, *, output_dir: Path | None = None) -> None:
        self.output_dir = output_dir if output_dir is not None else default_output_dir("liberapay")

    def publish_event(self, event: DonationEvent) -> PublisherResult:
        """Convenience wrapper: build payload from normalized event and publish."""
        body = self._render_manifest_body(event)
        payload = PublisherPayload(
            target=event.event_kind.value,
            text=body,
            metadata={
                "donor_handle": event.donor_handle,
                "amount_eur_cents": event.amount_eur_cents,
                "raw_payload_sha256": event.raw_payload_sha256,
                "occurred_at_iso": event.occurred_at.isoformat(),
            },
        )
        return self.publish(payload)

    @staticmethod
    def _render_manifest_body(event: DonationEvent) -> str:
        """Render the aggregate manifest markdown body.

        Aggregate-only — carries the four normalized fields on the
        :class:`DonationEvent`, no Liberapay-internal IDs and no
        free-text from the original payload. Renders deterministically.
        """
        lines = [
            f"# Liberapay donation event — {event.event_kind.value}",
            "",
            f"- **Event kind:** {event.event_kind.value}",
            f"- **Donor:** {event.donor_handle}",
            f"- **Amount (EUR cents):** {event.amount_eur_cents}",
            f"- **Occurred at:** {event.occurred_at.isoformat()}",
            f"- **Payload SHA-256:** `{event.raw_payload_sha256}`",
            "",
        ]
        return "\n".join(lines)

    def _emit(self, payload: PublisherPayload) -> PublisherResult:
        """Write the aggregate manifest entry; auto-link on tip cancellation."""
        result = write_manifest_entry(self.output_dir, payload, log=log)
        if result.ok and payload.target == DonationEventKind.TIP_CANCELLED.value:
            sha = str(payload.metadata.get("raw_payload_sha256", ""))[:16] or "unknown"
            cents = payload.metadata.get("amount_eur_cents", 0)
            auto_link_cancellation_to_refusal_log(
                payload,
                axiom=CANCELLATION_REFUSAL_AXIOM,
                surface=CANCELLATION_REFUSAL_SURFACE,
                reason=f"liberapay tip cancellation: amount_eur_cents={cents} sha16={sha}",
                log=log,
            )
        return result


def manifest_path_for_event(
    event: DonationEvent,
    *,
    output_dir: Path | None = None,
) -> Path:
    """Pure helper: compute the manifest path for a given event."""
    base = output_dir if output_dir is not None else default_output_dir("liberapay")
    return base / safe_filename_for_event(event.event_kind.value, event.raw_payload_sha256)


def event_to_manifest_record(event: DonationEvent) -> dict[str, object]:
    """Pure helper: project the normalized event onto its aggregate fields."""
    return {
        "event_kind": event.event_kind.value,
        "donor_handle": event.donor_handle,
        "amount_eur_cents": int(event.amount_eur_cents),
        "occurred_at_iso": event.occurred_at.isoformat(),
        "raw_payload_sha256": event.raw_payload_sha256,
    }


__all__ = [
    "CANCELLATION_REFUSAL_AXIOM",
    "CANCELLATION_REFUSAL_SURFACE",
    "DEFAULT_LIBERAPAY_ALLOWLIST",
    "LIBERAPAY_PUBLISHER_SURFACE",
    "LiberapayPublisher",
    "event_to_manifest_record",
    "manifest_path_for_event",
]

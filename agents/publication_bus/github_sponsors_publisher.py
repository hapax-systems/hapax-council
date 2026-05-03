"""GitHub Sponsors V5 publisher — first end-to-end wired monetization rail.

Per cc-task ``github-sponsors-end-to-end-wiring``. Wraps the
:class:`shared.github_sponsors_receive_only_rail.SponsorshipEvent`
record with the V5 publication-bus invariants:

1. **AllowlistGate** — only the four canonical
   :class:`SponsorshipEventKind` values dispatch through the publisher.
2. **Legal-name-leak guard** — the manifest body must never carry the
   operator's legal name (sponsor manifests are aggregate-only and
   use the operator-referent picker).
3. **Prometheus Counter** — per-surface per-result outcome on the
   canonical ``hapax_publication_bus_publishes_total`` metric.

The publisher writes one **aggregate manifest row** per dispatch to
``{output_dir}/event-{sha}.md`` where ``sha`` is the first 16 chars
of ``SponsorshipEvent.raw_payload_sha256``. The body carries only the
aggregate fields surfaced on the normalized event (``event_kind``,
``tier_amount_usd``, ``occurred_at``, ``sponsor_login``) — *no* tier
name, *no* sponsor email, *no* free-text supporter messages, and *no*
GitHub-internal IDs are persisted.

**Cancellation auto-link.** When :class:`SponsorshipEventKind.CANCELLED`
fires, the publisher additionally appends a
:class:`agents.refusal_brief.RefusalEvent` to the canonical refusal
log so the existing :func:`agents.marketing.refusal_annex_renderer`
aggregator picks it up under the ``declined-github-sponsorship-cancellation``
annex slug. This is the "auto-link" path the cc-task names: a
cancellation is itself a refusal-as-data event, and refusal-as-data
events route through the canonical log.

cc-task: ``github-sponsors-end-to-end-wiring``. First Tier-1 rail to
ship a wired publisher; pattern for the other 9 rails to copy.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import ClassVar

from agents.publication_bus._rail_publisher_helpers import (
    CANCELLATION_REFUSAL_AXIOM,
    auto_link_cancellation_to_refusal_log,
    default_output_dir,
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
from shared.github_sponsors_receive_only_rail import (
    SponsorshipEvent,
    SponsorshipEventKind,
)

log = logging.getLogger(__name__)

GITHUB_SPONSORS_PUBLISHER_SURFACE: str = "github-sponsors-receiver"
"""Stable surface identifier for the V5 publisher; mirrored in the
canonical Prometheus counter label and AllowlistGate key."""


DEFAULT_GITHUB_SPONSORS_ALLOWLIST: AllowlistGate = load_allowlist(
    GITHUB_SPONSORS_PUBLISHER_SURFACE,
    [k.value for k in SponsorshipEventKind],
)
"""Default allowlist permits the four canonical event kinds. Adding a
fifth requires editing :class:`SponsorshipEventKind` AND this allowlist
(compile-time gate)."""

CANCELLATION_REFUSAL_SURFACE: str = "publication_bus:github-sponsors-receiver:cancelled"


class GitHubSponsorsPublisher(Publisher):
    """V5 publisher for normalized GitHub Sponsors events.

    Construction is cheap and side-effect-free. Each
    :meth:`publish_event` call writes one aggregate manifest row plus
    (on cancellation) one refusal-log entry. The Publisher ABC's three
    invariants enforce that:

    - The event_kind (``payload.target``) is explicitly registered.
    - The body (``payload.text``) contains no legal-name leak.
    - Outcomes counter-record on the canonical metric.
    """

    surface_name: ClassVar[str] = GITHUB_SPONSORS_PUBLISHER_SURFACE
    allowlist: ClassVar[AllowlistGate] = DEFAULT_GITHUB_SPONSORS_ALLOWLIST
    requires_legal_name: ClassVar[bool] = False

    def __init__(self, *, output_dir: Path | None = None) -> None:
        self.output_dir = (
            output_dir if output_dir is not None else default_output_dir("github-sponsors")
        )

    def publish_event(self, event: SponsorshipEvent) -> PublisherResult:
        """Convenience wrapper: build payload from a normalized event and publish.

        The :meth:`publish` superclass method enforces the three V5
        invariants; this wrapper just adapts the typed event into the
        :class:`PublisherPayload` the superclass expects.
        """
        body = self._render_manifest_body(event)
        payload = PublisherPayload(
            target=event.event_kind.value,
            text=body,
            metadata={
                "sponsor_login": event.sponsor_login,
                "tier_amount_usd": event.tier_amount_usd,
                "raw_payload_sha256": event.raw_payload_sha256,
                "occurred_at_iso": event.occurred_at.isoformat(),
            },
        )
        return self.publish(payload)

    @staticmethod
    def _render_manifest_body(event: SponsorshipEvent) -> str:
        """Render the aggregate manifest markdown body.

        Aggregate-only — carries the four normalized fields on the
        :class:`SponsorshipEvent`, no GitHub-internal IDs and no
        free-text from the original webhook payload. Renders
        deterministically: same event input produces byte-identical
        output.
        """
        lines = [
            f"# GitHub Sponsors event — {event.event_kind.value}",
            "",
            f"- **Event kind:** {event.event_kind.value}",
            f"- **Sponsor:** {event.sponsor_login}",
            f"- **Tier (USD):** {event.tier_amount_usd:.2f}",
            f"- **Occurred at:** {event.occurred_at.isoformat()}",
            f"- **Payload SHA-256:** `{event.raw_payload_sha256}`",
            "",
        ]
        return "\n".join(lines)

    def _emit(self, payload: PublisherPayload) -> PublisherResult:
        """Write the aggregate manifest entry; auto-link on cancellation."""
        result = write_manifest_entry(self.output_dir, payload, log=log)
        if result.ok and payload.target == SponsorshipEventKind.CANCELLED.value:
            sha = str(payload.metadata.get("raw_payload_sha256", ""))[:16] or "unknown"
            tier_amount = payload.metadata.get("tier_amount_usd", 0.0)
            auto_link_cancellation_to_refusal_log(
                payload,
                axiom=CANCELLATION_REFUSAL_AXIOM,
                surface=CANCELLATION_REFUSAL_SURFACE,
                reason=f"github-sponsors cancellation: tier_amount_usd={tier_amount} sha16={sha}",
                log=log,
            )
        return result


def manifest_path_for_event(
    event: SponsorshipEvent,
    *,
    output_dir: Path | None = None,
) -> Path:
    """Pure helper: compute the manifest path for a given event.

    Useful for tests that need to assert the file appears at the
    expected location without instantiating a publisher.
    """
    from agents.publication_bus._rail_publisher_helpers import safe_filename_for_event

    base = output_dir if output_dir is not None else default_output_dir("github-sponsors")
    return base / safe_filename_for_event(event.event_kind.value, event.raw_payload_sha256)


def event_to_manifest_record(event: SponsorshipEvent) -> dict[str, object]:
    """Pure helper: project the normalized event onto its aggregate fields.

    Useful for callers that want a JSON-friendly dict instead of the
    rendered markdown body. Returns a fresh dict on every call.
    """
    return {
        "event_kind": event.event_kind.value,
        "sponsor_login": event.sponsor_login,
        "tier_amount_usd": float(event.tier_amount_usd),
        "occurred_at_iso": event.occurred_at.isoformat(),
        "raw_payload_sha256": event.raw_payload_sha256,
    }


__all__ = [
    "CANCELLATION_REFUSAL_AXIOM",
    "CANCELLATION_REFUSAL_SURFACE",
    "DEFAULT_GITHUB_SPONSORS_ALLOWLIST",
    "GITHUB_SPONSORS_PUBLISHER_SURFACE",
    "GitHubSponsorsPublisher",
    "event_to_manifest_record",
    "manifest_path_for_event",
]

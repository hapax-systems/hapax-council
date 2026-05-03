"""Refused-publisher subclass for V5 publication-bus.

Per V5 weave §2.1 PUB-P0-B keystone acceptance criterion #6: each
REFUSED-class publisher gets a corresponding ``RefusedPublisher``
subclass that registers refusal at module load. The subclass exists
to record refusal as a first-class graph citizen, never to attempt
publication.

A ``RefusedPublisher.publish()`` always returns
``PublisherResult(refused=True)`` with the operator-ratified refusal
rationale in ``detail``. The Prometheus counter still increments
(label ``result="refused"``) so dashboards show the refusal-event
count alongside successful and errored publish-events.

The four currently-registered refusal surfaces are:

- ``bandcamp-upload`` — no documented public upload API
- ``discogs-submission`` — ToS forbids automated submission
- ``rym-submission`` — Rate Your Music has no public API
- ``crossref-event-data`` — service was sunset; superseded by
  DataCite Commons GraphQL

Each ships under the constitutional posture
``feedback_full_automation_or_no_engagement``: surfaces that cannot
be daemonised constitutionally are refused, and the refusal is
recorded as data per the Refusal Brief discipline.
"""

from __future__ import annotations

from typing import ClassVar

from agents.publication_bus.publisher_kit.allowlist import AllowlistGate
from agents.publication_bus.publisher_kit.base import (
    Publisher,
    PublisherPayload,
    PublisherResult,
)


class RefusedPublisher(Publisher):
    """Refused-publisher subclass; ``publish()`` always returns refused.

    Subclass shape (~10 LOC per refused surface):

        class BandcampRefusedPublisher(RefusedPublisher):
            surface_name = "bandcamp-upload"
            refusal_reason = "Bandcamp has no documented public upload API."

    The ``allowlist`` ClassVar is set to an empty AllowlistGate at
    class-creation time so any publish() call short-circuits at the
    allowlist gate. The ``_emit()`` override never runs in practice
    (the empty allowlist refuses every target) — but is implemented
    defensively to return refused with the rationale in case a
    subclass overrides allowlist.
    """

    refusal_reason: ClassVar[str]
    """Operator-ratified refusal rationale; rendered in PublisherResult.detail."""

    @classmethod
    def __init_subclass__(cls, **kwargs: object) -> None:
        """Auto-construct the empty AllowlistGate per RefusedPublisher subclass.

        Subclasses don't need to declare ``allowlist`` explicitly; the
        empty gate at class-creation guarantees publish() refuses every
        target before reaching ``_emit()``.
        """
        super().__init_subclass__(**kwargs)
        if not hasattr(cls, "allowlist"):
            cls.allowlist = AllowlistGate(
                surface_name=cls.surface_name,
                permitted=frozenset(),
            )

    def _emit(self, payload: PublisherPayload) -> PublisherResult:
        """Defensive _emit returning refused; reached only if subclass
        overrode the empty allowlist."""
        return PublisherResult(
            refused=True,
            detail=f"refused surface ({self.refusal_reason})",
        )


# ── Registered refused surfaces (per V5 weave drop 5 SURFACE_REGISTRY) ─


class BandcampRefusedPublisher(RefusedPublisher):
    """Bandcamp upload — no documented public upload API."""

    surface_name = "bandcamp-upload"
    refusal_reason = (
        "Bandcamp has no documented public upload API; the web-form upload "
        "flow requires authenticated browser session + multi-step file "
        "upload that cannot be daemonised constitutionally."
    )


class DiscogsRefusedPublisher(RefusedPublisher):
    """Discogs submission — ToS forbids automated submission."""

    surface_name = "discogs-submission"
    refusal_reason = (
        "Discogs Terms of Service explicitly forbid automated submission "
        "of releases. The community submission process is human-mediated "
        "by design; daemonising would violate ToS."
    )


class RymRefusedPublisher(RefusedPublisher):
    """Rate Your Music — no public API."""

    surface_name = "rym-submission"
    refusal_reason = (
        "Rate Your Music provides no public API for submission. The site's "
        "submission flow is human-mediated; daemon-side automation is not "
        "constitutionally available."
    )


class CrossrefEventDataRefusedPublisher(RefusedPublisher):
    """Crossref Event Data — service sunset."""

    surface_name = "crossref-event-data"
    refusal_reason = (
        "Crossref Event Data was sunset. The DataCite Commons GraphQL "
        "surface (already operational) supersedes its event-stream role. "
        "No alternative within Crossref's surface area is daemon-tractable."
    )


class DiscordWebhookRefusedPublisher(RefusedPublisher):
    """Discord webhook — multi-user platform, single-operator axiom precludes.

    Per cc-task ``discord-public-event-activation-or-retire`` (2026-05-01
    retirement): Discord webhook bots violate both the single-operator
    axiom (multi-user platform; community moderation is per-user / per-
    message) and ``feedback_full_automation_or_no_engagement`` (the
    moment a webhook bot lands in a server, @-mentions become a
    bidirectional engagement surface). The cross-surface webhook agent
    at ``agents/cross_surface/discord_webhook.py`` was retained as
    legacy reference but the surface is REFUSED tier; runtime dispatch
    is quarantined via ``is_engageable()``. The systemd unit was
    decommissioned in the same PR.
    """

    surface_name = "discord-webhook"
    refusal_reason = (
        "Discord is a multi-user platform — single-operator axiom precludes "
        "operator-mediated community moderation, and webhook bots become "
        "bidirectional engagement surfaces the moment users @-mention them, "
        "violating the full-automation-or-no-engagement constitutional posture."
    )


class AlphaXivCommentsRefusedPublisher(RefusedPublisher):
    """alphaXiv comments — community guidelines prohibit LLM-generated comments.

    Per cc-task ``cold-contact-alphaxiv-comments``: alphaXiv community
    guidelines prohibit LLM-generated comments per drop 2 §3 mechanic
    #3. Even AI-authorship disclosure does not lift the prohibition;
    operator-approval-gating during a "trial period" is itself the
    pattern that ``feedback_full_automation_or_no_engagement`` rejects.
    PR #1444's allowlist contract is governance-shape only and does
    not make the surface daemon-tractable.
    """

    surface_name = "alphaxiv-comments"
    refusal_reason = (
        "alphaXiv community guidelines prohibit LLM-generated comments; "
        "AI-authorship disclosure does not lift the prohibition. "
        "Operator-approval gating during a 'trial period' violates the "
        "full-automation-or-no-engagement constitutional posture."
    )


class WiseDirectDebitRefusedPublisher(RefusedPublisher):
    """Wise Direct Debit (active reception) — receive-only invariant precludes.

    Per the Wise design spike (`docs/research/2026-05-03-wise-ach-receive-
    only-rail-design.md` § Open questions #5): Wise's 2026 Direct Debit
    API allows platforms to PULL funds from external bank accounts. The
    receive-only rail invariant forbids initiating outbound monetary
    movement, even when the movement collects funds toward the operator
    rather than dispersing them.

    The distinction matters: receive-only means we never INITIATE money
    movement on third-party accounts. A pull-payment is operator-
    initiated debit against a payer's account; consent-wise it is the
    inverse direction of a passive deposit. Treating "we collect, so
    it's incoming" as receive-only would erode the invariant for every
    rail (every push payment also "collects"). The bright line is who
    initiates the debit instruction, not where the money lands.

    The passive Wise reception path (virtual USD account details +
    `account-details-payment#state-change` webhook) remains acceptable
    and is the design spike's recommended Phase-0 implementation. Only
    the active Direct Debit path is REFUSED.
    """

    surface_name = "wise-direct-debit-active-reception"
    refusal_reason = (
        "Wise Direct Debit pulls funds from payer bank accounts via "
        "operator-initiated debit instructions. Even though funds land on "
        "the operator side, initiating the movement violates the receive-"
        "only rail invariant. The passive virtual-USD-account path "
        "(account-details-payment#state-change webhook) is the "
        "constitutional alternative."
    )


# Registry of refused-publisher classes for module-load auditing.
REFUSED_PUBLISHER_CLASSES: list[type[RefusedPublisher]] = [
    BandcampRefusedPublisher,
    DiscogsRefusedPublisher,
    DiscordWebhookRefusedPublisher,
    RymRefusedPublisher,
    CrossrefEventDataRefusedPublisher,
    AlphaXivCommentsRefusedPublisher,
    WiseDirectDebitRefusedPublisher,
]


__all__ = [
    "REFUSED_PUBLISHER_CLASSES",
    "AlphaXivCommentsRefusedPublisher",
    "BandcampRefusedPublisher",
    "CrossrefEventDataRefusedPublisher",
    "DiscogsRefusedPublisher",
    "DiscordWebhookRefusedPublisher",
    "RefusedPublisher",
    "RymRefusedPublisher",
    "WiseDirectDebitRefusedPublisher",
]

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


class TwitterRefusedPublisher(RefusedPublisher):
    """Twitter/X — operator-mediated social media; engagement violates axiom.

    Per cc-task ``leverage-REFUSED-twitter-linkedin-substack-accounts``
    (PR #1560, 2026-04-26): mainstream social-media surfaces are
    operator-mediated by design. Twitter/X requires reply-thread
    management, @-mention reply expectations, and quote-tweet
    relationship dynamics that constitute bidirectional engagement
    surfaces — incompatible with
    ``feedback_full_automation_or_no_engagement``.

    A daemon-side post-only mode would still surface @-mentions and
    DMs back to the operator with implicit response expectations.
    The ratchet from "post" to "engage" cannot be daemonised
    constitutionally.
    """

    surface_name = "twitter-x-account"
    refusal_reason = (
        "Twitter/X is an operator-mediated social-media platform — daemon-side "
        "posting still surfaces @-mentions, replies, quote-tweets, and DMs that "
        "create bidirectional engagement expectations, violating the full-"
        "automation-or-no-engagement constitutional posture."
    )


class LinkedInRefusedPublisher(RefusedPublisher):
    """LinkedIn — connection-graph mediation precludes daemon engagement.

    Per cc-task ``leverage-REFUSED-twitter-linkedin-substack-accounts``
    (PR #1560, 2026-04-26): LinkedIn requires connection-graph
    mediation. Posts surface to a curated-connection feed, comments
    arrive from connections expecting reciprocal engagement, and the
    platform's identity model is structurally bidirectional. No
    daemon-tractable post-only mode exists.
    """

    surface_name = "linkedin-account"
    refusal_reason = (
        "LinkedIn requires connection-graph mediation; post-and-walk-away mode "
        "is structurally unavailable. Comments and reactions arrive from named "
        "connections with implicit reciprocal-engagement expectations. The "
        "single-operator + full-automation-or-no-engagement constitutional "
        "posture forbids the surface."
    )


class SubstackRefusedPublisher(RefusedPublisher):
    """Substack — subscriber-relationship management precludes daemon engagement.

    Per cc-task ``leverage-REFUSED-twitter-linkedin-substack-accounts``
    (PR #1560, 2026-04-26): Substack monetizes via subscriber
    relationships. Newsletter cadence, comment threads on posts, and
    direct subscriber emails all expect operator-mediated engagement.
    A daemon-side publishing mode without subscriber-relationship
    management would degrade the surface for subscribers and
    structurally violate the platform's product model.
    """

    surface_name = "substack-account"
    refusal_reason = (
        "Substack monetizes via subscriber-relationship management — newsletter "
        "cadence, post-comment threads, and direct subscriber correspondence "
        "all require operator-mediated engagement. Daemon-only publishing "
        "would degrade the platform-promised subscriber experience and violates "
        "the full-automation-or-no-engagement constitutional posture."
    )


class RedditRefusedPublisher(RefusedPublisher):
    """Reddit — multi-user community-mediated platform, daemon engagement precluded.

    Reddit is a community-moderation platform: posts surface to
    subreddit feeds whose moderators apply per-community rules,
    comments arrive from named accounts, and the platform's
    karma/account-age signals encode reciprocal engagement. Daemon-
    side posting violates both ``single_user`` (subreddits are
    multi-moderator communities) and
    ``feedback_full_automation_or_no_engagement`` (replies and
    cross-post discussions surface back to the operator with
    implicit response expectations).

    Even broadcast-only modes would face platform-side rate limits +
    shadowban risks for accounts that post but never engage —
    Reddit's algorithm explicitly penalizes this pattern. Most
    subreddits also have community rules forbidding bot-authored
    content unless explicitly marked, and many ban LLM-generated
    posts entirely.
    """

    surface_name = "reddit-account"
    refusal_reason = (
        "Reddit is a multi-moderator community platform — subreddits enforce "
        "per-community rules including bot-content prohibitions; comments "
        "arrive from named accounts with engagement-reciprocity expectations; "
        "the platform algorithmically penalizes accounts that post without "
        "engaging. Violates both single_user (community-moderator structure) "
        "and full-automation-or-no-engagement constitutional postures."
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
    LinkedInRefusedPublisher,
    RedditRefusedPublisher,
    RymRefusedPublisher,
    CrossrefEventDataRefusedPublisher,
    AlphaXivCommentsRefusedPublisher,
    SubstackRefusedPublisher,
    TwitterRefusedPublisher,
    WiseDirectDebitRefusedPublisher,
]


__all__ = [
    "REFUSED_PUBLISHER_CLASSES",
    "AlphaXivCommentsRefusedPublisher",
    "BandcampRefusedPublisher",
    "CrossrefEventDataRefusedPublisher",
    "DiscogsRefusedPublisher",
    "DiscordWebhookRefusedPublisher",
    "LinkedInRefusedPublisher",
    "RedditRefusedPublisher",
    "RefusedPublisher",
    "RymRefusedPublisher",
    "SubstackRefusedPublisher",
    "TwitterRefusedPublisher",
    "WiseDirectDebitRefusedPublisher",
]

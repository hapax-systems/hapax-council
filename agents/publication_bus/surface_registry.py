"""Canonical V5 publication-bus surface registry.

Per V5 weave §2.1 PUB-P0-B follow-on
(``pub-bus-zenodo-related-identifier-graph`` task). Single source of
truth for which surfaces the publication-bus engages, refuses, or
treats as conditional.

Three automation tiers:

- ``FULL_AUTO`` — daemon-side end-to-end; no operator action per
  publish-event after one-time credential bootstrap
- ``CONDITIONAL_ENGAGE`` — bootstrap-on-first-use (one-time human
  action per surface, e.g., logging into Playwright session daemon)
- ``REFUSED`` — surface declined per Refusal Brief; subclass exists
  to record refusal, never to attempt publication

The registry is operator-curated and committed; runtime mutation is
forbidden per the single_user axiom. Each entry references the
appropriate Refusal Brief docs/refusal-briefs/ entry when
``automation_status == REFUSED``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final


class AutomationStatus(Enum):
    """Automation tier for a publication-bus surface."""

    FULL_AUTO = "FULL_AUTO"
    CONDITIONAL_ENGAGE = "CONDITIONAL_ENGAGE"
    REFUSED = "REFUSED"


@dataclass(frozen=True)
class SurfaceSpec:
    """One publication-bus surface specification.

    Carries the surface's automation status, API style, and (when
    refused) a link to the Refusal Brief docs entry documenting
    why. ``api`` is informational; the actual transport is owned by
    the surface's Publisher subclass.
    """

    automation_status: AutomationStatus
    api: str | None = None
    dispatch_entry: str | None = None
    activation_path: str | None = None
    refusal_link: str | None = None
    scope_note: str | None = None


# Canonical registry. Sorted by automation status, then alphabetically
# within each tier for predictable diff review.
SURFACE_REGISTRY: Final[dict[str, SurfaceSpec]] = {
    # ── FULL_AUTO ──────────────────────────────────────────────────
    "bluesky-atproto-multi-identity": SurfaceSpec(
        automation_status=AutomationStatus.FULL_AUTO,
        api="ATProto",
        dispatch_entry="agents.bluesky_atproto_adapter:publish_artifact",
    ),
    "oudepode-bluesky-atproto": SurfaceSpec(
        automation_status=AutomationStatus.FULL_AUTO,
        api="ATProto",
        dispatch_entry="agents.bluesky_atproto_adapter:publish_artifact_oudepode",
        scope_note="music-side bluesky identity (oudepode), per operator-referent-policy",
    ),
    "bluesky-post": SurfaceSpec(
        automation_status=AutomationStatus.FULL_AUTO,
        api="ATProto",
        dispatch_entry="agents.cross_surface.bluesky_post:publish_artifact",
        activation_path=(
            "agents.publication_bus.bluesky_publisher.BlueskyPostPublisher "
            "+ systemd/units/hapax-bluesky-post.service"
        ),
        scope_note="public-event Bluesky fanout routed through publication bus",
    ),
    "bridgy-webmention-publish": SurfaceSpec(
        automation_status=AutomationStatus.FULL_AUTO,
        api="webmention",
        dispatch_entry="agents.bridgy_adapter:publish_artifact",
        scope_note=(
            "generic weblog webmention fanout; refusal-annex artifacts are held "
            "until an omg-weblog source URL witness/sequencing path is committed"
        ),
    ),
    "datacite-graphql-mirror": SurfaceSpec(
        automation_status=AutomationStatus.FULL_AUTO,
        api="GraphQL",
        activation_path=(
            "systemd/units/hapax-datacite-mirror.timer + "
            "agents.publication_bus.self_citation_graph_doi --commit"
        ),
    ),
    "internet-archive-ias3": SurfaceSpec(
        automation_status=AutomationStatus.FULL_AUTO,
        api="S3",
        dispatch_entry="agents.internet_archive_ias3_adapter:publish_artifact",
    ),
    "marketing-refusal-annex": SurfaceSpec(
        automation_status=AutomationStatus.FULL_AUTO,
        api="local-file",
        activation_path="agents.marketing.refusal_annex_publisher.RefusalAnnexPublisher",
        scope_note="renders refusal annex markdown to ~/hapax-state/publications/",
    ),
    "github-sponsors-receiver": SurfaceSpec(
        automation_status=AutomationStatus.FULL_AUTO,
        api="webhook",
        dispatch_entry="logos.api.routes.payment_rails:receive_github_sponsors_webhook",
        activation_path="agents.publication_bus.github_sponsors_publisher.GitHubSponsorsPublisher",
        scope_note=(
            "First wired monetization rail. POST /api/payment-rails/github-sponsors "
            "on logos :8051; HMAC SHA-256 over raw body via X-Hub-Signature-256 + "
            "GITHUB_SPONSORS_WEBHOOK_SECRET env var. Cancellation events auto-link "
            "to the canonical refusal log under axiom full_auto_or_nothing."
        ),
    ),
    "treasury-prime-receiver": SurfaceSpec(
        automation_status=AutomationStatus.FULL_AUTO,
        api="webhook",
        dispatch_entry="logos.api.routes.payment_rails:receive_treasury_prime_webhook",
        activation_path="agents.publication_bus.treasury_prime_publisher.TreasuryPrimePublisher",
        scope_note=(
            "Tenth (final) wired monetization rail. POST "
            "/api/payment-rails/treasury-prime on logos :8051; HMAC SHA-256 "
            "over raw body via X-Signature + TREASURY_PRIME_WEBHOOK_SECRET "
            "env var. Phase 0: incoming_ach.create only. No cancellation "
            "auto-link."
        ),
    ),
    "modern-treasury-receiver": SurfaceSpec(
        automation_status=AutomationStatus.FULL_AUTO,
        api="webhook",
        dispatch_entry="logos.api.routes.payment_rails:receive_modern_treasury_webhook",
        activation_path="agents.publication_bus.modern_treasury_publisher.ModernTreasuryPublisher",
        scope_note=(
            "Ninth wired monetization rail (2nd bank rail). POST "
            "/api/payment-rails/modern-treasury on logos :8051; HMAC SHA-256 over "
            "raw body via X-Signature + MODERN_TREASURY_WEBHOOK_SECRET env var. "
            "Event-name-level direction filter; no cancellation auto-link."
        ),
    ),
    "mercury-receiver": SurfaceSpec(
        automation_status=AutomationStatus.FULL_AUTO,
        api="webhook",
        dispatch_entry="logos.api.routes.payment_rails:receive_mercury_webhook",
        activation_path="agents.publication_bus.mercury_publisher.MercuryPublisher",
        scope_note=(
            "Eighth wired monetization rail (1st bank rail). POST "
            "/api/payment-rails/mercury on logos :8051; HMAC SHA-256 over raw "
            "body via X-Mercury-Signature (canonical) + X-Hook-Signature "
            "(legacy fallback) + MERCURY_WEBHOOK_SECRET env var. Direction "
            "filter at receiver boundary; no cancellation auto-link."
        ),
    ),
    "buy-me-a-coffee-receiver": SurfaceSpec(
        automation_status=AutomationStatus.FULL_AUTO,
        api="webhook",
        dispatch_entry="logos.api.routes.payment_rails:receive_buy_me_a_coffee_webhook",
        activation_path="agents.publication_bus.buy_me_a_coffee_publisher.BuyMeACoffeePublisher",
        scope_note=(
            "Seventh wired monetization rail. POST /api/payment-rails/buy-me-a-coffee "
            "on logos :8051; HMAC SHA-256 over raw body via X-Signature-Sha256 + "
            "BUY_ME_A_COFFEE_WEBHOOK_SECRET env var. Membership-cancellation "
            "events auto-link to the canonical refusal log."
        ),
    ),
    "patreon-receiver": SurfaceSpec(
        automation_status=AutomationStatus.FULL_AUTO,
        api="webhook",
        dispatch_entry="logos.api.routes.payment_rails:receive_patreon_webhook",
        activation_path="agents.publication_bus.patreon_publisher.PatreonPublisher",
        scope_note=(
            "Sixth wired monetization rail. POST /api/payment-rails/patreon on "
            "logos :8051; HMAC MD5 (not SHA-256, per Patreon's documented wire "
            "format) via X-Patreon-Signature + PATREON_WEBHOOK_SECRET env var. "
            "Event-kind in X-Patreon-Event header. Pledge-deletion events "
            "auto-link to the canonical refusal log."
        ),
    ),
    "ko-fi-receiver": SurfaceSpec(
        automation_status=AutomationStatus.FULL_AUTO,
        api="webhook",
        dispatch_entry="logos.api.routes.payment_rails:receive_ko_fi_webhook",
        activation_path="agents.publication_bus.ko_fi_publisher.KoFiPublisher",
        scope_note=(
            "Fifth wired monetization rail. POST /api/payment-rails/ko-fi on "
            "logos :8051; token-in-payload verification (NOT HMAC) via "
            "KO_FI_WEBHOOK_VERIFICATION_TOKEN env var. No cancellation auto-link."
        ),
    ),
    "stripe-payment-link-receiver": SurfaceSpec(
        automation_status=AutomationStatus.FULL_AUTO,
        api="webhook",
        dispatch_entry="logos.api.routes.payment_rails:receive_stripe_payment_link_webhook",
        activation_path="agents.publication_bus.stripe_payment_link_publisher.StripePaymentLinkPublisher",
        scope_note=(
            "Fourth wired monetization rail. POST /api/payment-rails/stripe-payment-link "
            "on logos :8051; timestamped HMAC SHA-256 via Stripe-Signature + "
            "STRIPE_PAYMENT_LINK_WEBHOOK_SECRET env var. Subscription-deletion "
            "events auto-link to the canonical refusal log."
        ),
    ),
    "open-collective-receiver": SurfaceSpec(
        automation_status=AutomationStatus.FULL_AUTO,
        api="webhook",
        dispatch_entry="logos.api.routes.payment_rails:receive_open_collective_webhook",
        activation_path="agents.publication_bus.open_collective_publisher.OpenCollectivePublisher",
        scope_note=(
            "Third wired monetization rail. POST /api/payment-rails/open-collective "
            "on logos :8051; HMAC SHA-256 over raw body via X-Open-Collective-Signature "
            "+ OPEN_COLLECTIVE_WEBHOOK_SECRET env var. Multi-currency-native; no "
            "cancellation auto-link (no cancellation event in the canonical 4)."
        ),
    ),
    "liberapay-receiver": SurfaceSpec(
        automation_status=AutomationStatus.CONDITIONAL_ENGAGE,
        api="webhook-via-bridge",
        dispatch_entry="logos.api.routes.payment_rails:receive_liberapay_webhook",
        activation_path="agents.publication_bus.liberapay_publisher.LiberapayPublisher",
        scope_note=(
            "Second wired monetization rail. POST /api/payment-rails/liberapay on "
            "logos :8051. Liberapay does not natively ship webhooks — bridge "
            "(cloudmailin/mailgun/n8n) forwards parsed deliveries with optional "
            "HMAC SHA-256 via X-Liberapay-Signature + LIBERAPAY_WEBHOOK_SECRET env. "
            "IP allowlist gate via LIBERAPAY_REQUIRE_IP_ALLOWLIST=1. CONDITIONAL_ENGAGE "
            "until the bridge is bootstrapped (operator-action: configure email "
            "forwarder + n8n parser flow). Tip-cancellation events auto-link to "
            "the canonical refusal log."
        ),
    ),
    "arena-post": SurfaceSpec(
        automation_status=AutomationStatus.FULL_AUTO,
        api="REST",
        dispatch_entry="agents.cross_surface.arena_post:publish_artifact",
        activation_path=(
            "agents.publication_bus.arena_publisher.ArenaPublisher "
            "+ systemd/units/hapax-arena-post.service"
        ),
        scope_note="public-event Are.na fanout routed through publication bus",
    ),
    "mastodon-post": SurfaceSpec(
        automation_status=AutomationStatus.FULL_AUTO,
        api="REST",
        dispatch_entry="agents.cross_surface.mastodon_post:publish_artifact",
        activation_path=(
            "agents.publication_bus.mastodon_publisher.MastodonPublisher "
            "+ systemd/units/hapax-mastodon-post.service"
        ),
        scope_note="public-event Mastodon fanout routed through publication bus",
    ),
    "omg-weblog": SurfaceSpec(
        automation_status=AutomationStatus.FULL_AUTO,
        api="REST",
        dispatch_entry="agents.omg_weblog_publisher:publish_artifact",
        scope_note="operator-owned hapax omg.lol weblog identity",
    ),
    "omg-lol-weblog-bearer-fanout": SurfaceSpec(
        automation_status=AutomationStatus.FULL_AUTO,
        api="REST",
        activation_path="agents.publication_bus.omg_weblog_publisher.OmgLolWeblogPublisher",
        scope_note="weblog entry bearer-token publication helper",
    ),
    "omg-lol-statuslog": SurfaceSpec(
        automation_status=AutomationStatus.FULL_AUTO,
        api="REST",
        activation_path=(
            "agents.publication_bus.omg_statuslog_publisher.OmgLolStatuslogPublisher "
            "+ systemd/units/hapax-omg-lol-fanout.timer"
        ),
        scope_note="live awareness statuslog fanout routed through publication bus",
    ),
    "omg-lol-web": SurfaceSpec(
        automation_status=AutomationStatus.FULL_AUTO,
        api="REST",
        activation_path=(
            "agents.publication_bus.omg_web_publisher.OmgLolWebPublisher "
            "+ agents.omg_web_builder.publisher"
        ),
        scope_note="operator-owned hapax.omg.lol landing page routed through publication bus",
    ),
    "omg-lol-now": SurfaceSpec(
        automation_status=AutomationStatus.FULL_AUTO,
        api="REST",
        activation_path=(
            "agents.publication_bus.omg_now_publisher.OmgLolNowPublisher + agents.omg_now_sync"
        ),
        scope_note="operator-owned omg.lol /now page routed through publication bus",
    ),
    "omg-lol-pastebin": SurfaceSpec(
        automation_status=AutomationStatus.FULL_AUTO,
        api="REST",
        activation_path=(
            "agents.publication_bus.omg_pastebin_publisher.OmgLolPastebinPublisher "
            "+ agents.omg_pastebin_publisher/agents.omg_credits_publisher"
        ),
        scope_note="operator-owned omg.lol pastebin artifacts routed through publication bus",
    ),
    "omg-lol-purl": SurfaceSpec(
        automation_status=AutomationStatus.FULL_AUTO,
        api="REST",
        activation_path=(
            "agents.publication_bus.omg_purl_publisher.OmgLolPurlPublisher "
            "+ agents.omg_purl_registrar"
        ),
        scope_note="operator-owned omg.lol PURL registrations routed through publication bus",
    ),
    "omg-lol-email-forward": SurfaceSpec(
        automation_status=AutomationStatus.FULL_AUTO,
        api="REST",
        activation_path=(
            "agents.publication_bus.omg_email_publisher.OmgLolEmailPublisher "
            "+ agents.omg_email_setup"
        ),
        scope_note="operator-owned omg.lol email forwarding configuration routed through publication bus",
    ),
    "omg-lol-weblog-delete": SurfaceSpec(
        automation_status=AutomationStatus.FULL_AUTO,
        api="REST",
        activation_path=(
            "agents.publication_bus.omg_weblog_delete_publisher.OmgLolWeblogDeletePublisher "
            "+ scripts/verify-weblog-producer-deploy.py --cleanup-live"
        ),
        scope_note="tightly allowlisted weblog cleanup egress routed through publication bus",
    ),
    "orcid-auto-update": SurfaceSpec(
        automation_status=AutomationStatus.FULL_AUTO,
        api="OAuth+REST",
        activation_path="systemd/units/hapax-orcid-verifier.timer",
        scope_note="concept-DOI granularity only",
    ),
    "osf-prereg": SurfaceSpec(
        automation_status=AutomationStatus.FULL_AUTO,
        api="REST",
        dispatch_entry="agents.osf_prereg_adapter:publish_artifact",
        scope_note="OSF preregistrations with named-related-work cross-references",
    ),
    "osf-preprint": SurfaceSpec(
        automation_status=AutomationStatus.FULL_AUTO,
        api="REST",
        dispatch_entry="agents.osf_preprint_publisher:publish_artifact",
    ),
    "oudepode-omg-weblog": SurfaceSpec(
        automation_status=AutomationStatus.FULL_AUTO,
        api="REST",
        dispatch_entry="agents.omg_weblog_publisher:publish_artifact_oudepode",
        scope_note="music-side omg.lol weblog identity",
    ),
    "zenodo-deposit": SurfaceSpec(
        automation_status=AutomationStatus.FULL_AUTO,
        api="REST",
        activation_path="canonical Zenodo surface; runtime dispatch uses zenodo-doi",
    ),
    "zenodo-doi": SurfaceSpec(
        automation_status=AutomationStatus.FULL_AUTO,
        api="REST",
        dispatch_entry="agents.zenodo_publisher:publish_artifact",
        scope_note="legacy preprint DOI minter surface slug",
    ),
    "zenodo-refusal-deposit": SurfaceSpec(
        automation_status=AutomationStatus.FULL_AUTO,
        api="REST",
        dispatch_entry="agents.refusal_brief_zenodo_adapter:publish_artifact",
        scope_note="Refusal Brief deposits with refusal-shaped RelatedIdentifier edges",
    ),
    "zenodo-related-identifier-graph": SurfaceSpec(
        automation_status=AutomationStatus.FULL_AUTO,
        api="REST",
        activation_path="agents.publication_bus.related_identifier via agents.zenodo_publisher",
    ),
    "crossref-doi-deposit": SurfaceSpec(
        automation_status=AutomationStatus.CONDITIONAL_ENGAGE,
        api="REST/XML",
        activation_path="agents.attribution.crossref_depositor after credential bootstrap",
        scope_note="credential-blocked until Crossref membership depositor credentials exist",
    ),
    # ── CONDITIONAL_ENGAGE ─────────────────────────────────────────
    "philarchive-deposit": SurfaceSpec(
        automation_status=AutomationStatus.CONDITIONAL_ENGAGE,
        api="Playwright",
        dispatch_entry="agents.philarchive_adapter:publish_artifact",
        scope_note="bootstrap login via Playwright session daemon (one-time)",
    ),
    "alphaxiv-deposit": SurfaceSpec(
        automation_status=AutomationStatus.CONDITIONAL_ENGAGE,
        api="Playwright",
        scope_note="bootstrap login via Playwright session daemon (one-time)",
    ),
    "art-50-credential-issue": SurfaceSpec(
        automation_status=AutomationStatus.FULL_AUTO,
        api="local+webhook",
        dispatch_entry="agents.art_50_provenance:issue_image_credential",
        activation_path="agents.art_50_provenance after one-time signer/credential bootstrap",
        scope_note=(
            "image-only Article 50 credential issue path; fully daemon-side after "
            "operator bootstraps C2PA claim signer, Zenodo/IA credentials, and "
            "customer webhook secret. Missing bootstrap returns machine-readable "
            "blocked/pending_substrate state, not a trusted claim."
        ),
    ),
    "art-50-credential-verify": SurfaceSpec(
        automation_status=AutomationStatus.FULL_AUTO,
        api="REST",
        dispatch_entry="logos.api.routes.art_50_credentials:verify_credential_v1",
        activation_path="logos :8051 /v1/credential/verify/{credential_id}",
        scope_note="read-only local certificate packet verification; no external callout",
    ),
    "youtube-live-chat-message": SurfaceSpec(
        automation_status=AutomationStatus.CONDITIONAL_ENGAGE,
        api="YouTube Data API v3",
        dispatch_entry="agents.hapax_daimonion.cpal.response_dispatch:dispatch_response",
        scope_note=(
            "bootstrap requires (1) operator-minted Google OAuth token with "
            "youtube.force-ssl scope via shared.google_auth and (2) populating "
            "config/publication-bus/youtube-live-chat.yaml with the active "
            "broadcast's liveChatId; pairs with epsilon's youtube_chat_reader "
            "(cc-task youtube-chat-ingestion-impingement) for the reverse channel"
        ),
    ),
    # ── REFUSED ────────────────────────────────────────────────────
    "alphaxiv-comments": SurfaceSpec(
        automation_status=AutomationStatus.REFUSED,
        refusal_link="docs/refusal-briefs/cold-contact-alphaxiv-comments.md",
        scope_note="alphaXiv community guidelines prohibit LLM-generated comments",
    ),
    "bandcamp-upload": SurfaceSpec(
        automation_status=AutomationStatus.REFUSED,
        refusal_link="docs/refusal-briefs/bandcamp-no-upload-api.md",
    ),
    "discogs-submission": SurfaceSpec(
        automation_status=AutomationStatus.REFUSED,
        refusal_link="docs/refusal-briefs/discogs-tos-forbids.md",
    ),
    "discord-webhook": SurfaceSpec(
        automation_status=AutomationStatus.REFUSED,
        refusal_link="docs/refusal-briefs/leverage-discord-community.md",
        scope_note=(
            "Discord is a multi-user platform; the single-operator axiom "
            "and feedback_full_automation_or_no_engagement constitutional "
            "directive both refuse webhook bots. The cross-surface webhook "
            "agent at agents/cross_surface/discord_webhook.py is retained "
            "as legacy reference; runtime dispatch is gated off via the "
            "REFUSED tier (is_engageable returns False) so the publish "
            "orchestrator never reaches it."
        ),
    ),
    "rym-submission": SurfaceSpec(
        automation_status=AutomationStatus.REFUSED,
        refusal_link="docs/refusal-briefs/rym-no-api.md",
    ),
    "crossref-event-data": SurfaceSpec(
        automation_status=AutomationStatus.REFUSED,
        refusal_link="docs/refusal-briefs/crossref-event-data-sunset.md",
        scope_note="superseded by DataCite Commons GraphQL surface",
    ),
    "wise-direct-debit-active-reception": SurfaceSpec(
        automation_status=AutomationStatus.REFUSED,
        refusal_link="docs/refusal-briefs/wise-direct-debit-active-reception.md",
        scope_note=(
            "Wise Direct Debit pulls funds from payer bank accounts via "
            "operator-initiated debit instructions. Even though funds land "
            "on the operator side, initiating the movement violates the "
            "receive-only rail invariant. Passive virtual-USD-account "
            "reception remains acceptable (separate Phase-0 implementation)."
        ),
    ),
    "twitter-x-account": SurfaceSpec(
        automation_status=AutomationStatus.REFUSED,
        refusal_link="docs/refusal-briefs/twitter-x-account.md",
        scope_note=(
            "Twitter/X is operator-mediated; @-mentions, replies, quote-"
            "tweets, and DMs make daemon-only posting impossible without "
            "creating bidirectional engagement expectations."
        ),
    ),
    "linkedin-account": SurfaceSpec(
        automation_status=AutomationStatus.REFUSED,
        refusal_link="docs/refusal-briefs/linkedin-account.md",
        scope_note=(
            "LinkedIn requires connection-graph mediation; comments and "
            "reactions arrive from named connections expecting reciprocal "
            "engagement."
        ),
    ),
    "substack-account": SurfaceSpec(
        automation_status=AutomationStatus.REFUSED,
        refusal_link="docs/refusal-briefs/substack-account.md",
        scope_note=(
            "Substack monetizes via subscriber-relationship management "
            "(newsletter cadence, post-comment threads, direct subscriber "
            "correspondence). Daemon-only publishing degrades the platform-"
            "promised subscriber experience."
        ),
    ),
    "reddit-account": SurfaceSpec(
        automation_status=AutomationStatus.REFUSED,
        refusal_link="docs/refusal-briefs/reddit-account.md",
        scope_note=(
            "Reddit is a multi-moderator community platform. Subreddits enforce "
            "per-community rules including bot-content prohibitions; comments "
            "arrive from named accounts with engagement-reciprocity expectations; "
            "the platform algorithmically penalizes accounts that post without "
            "engaging."
        ),
    ),
    "github-discussions": SurfaceSpec(
        automation_status=AutomationStatus.REFUSED,
        refusal_link="docs/refusal-briefs/github-discussions.md",
        scope_note=(
            "GitHub Discussions creates a Q&A surface expecting operator-mediated "
            "answers + accepted-answer marking + community moderation. Daemon "
            "enable would advertise an operator-attention affordance the daemon "
            "cannot honor."
        ),
    ),
    "wikipedia-auto-edit": SurfaceSpec(
        automation_status=AutomationStatus.REFUSED,
        refusal_link="docs/refusal-briefs/wikipedia-auto-edit.md",
        scope_note=(
            "Wikipedia ToS forbids unflagged automated editing; the Bot Approvals "
            "Group requires per-bot community approval. Multi-editor platform also "
            "violates single_user. Double constitutional barrier."
        ),
    ),
}


def is_engageable(surface_name: str) -> bool:
    """Return True iff ``surface_name`` has automation_status FULL_AUTO
    or CONDITIONAL_ENGAGE.

    Useful for runtime gates that should not attempt to publish to a
    REFUSED surface even when called erroneously. The Publisher ABC
    does not consult this registry directly (the AllowlistGate is the
    runtime mechanism); this is a higher-level dispatch helper.
    """
    spec = SURFACE_REGISTRY.get(surface_name)
    if spec is None:
        return False
    return spec.automation_status in (
        AutomationStatus.FULL_AUTO,
        AutomationStatus.CONDITIONAL_ENGAGE,
    )


def refused_surfaces() -> list[str]:
    """Return the sorted list of REFUSED surface names.

    Consumed by the Refusal Brief renderer + the operator dashboard's
    "what we don't engage with" panel.
    """
    return sorted(
        name
        for name, spec in SURFACE_REGISTRY.items()
        if spec.automation_status == AutomationStatus.REFUSED
    )


def auto_surfaces() -> list[str]:
    """Return the sorted list of FULL_AUTO surface names."""
    return sorted(
        name
        for name, spec in SURFACE_REGISTRY.items()
        if spec.automation_status == AutomationStatus.FULL_AUTO
    )


def dispatch_registry() -> dict[str, str]:
    """Return runtime-dispatchable surfaces from the canonical registry."""
    return {
        name: spec.dispatch_entry
        for name, spec in SURFACE_REGISTRY.items()
        if spec.dispatch_entry and is_engageable(name)
    }


__all__ = [
    "SURFACE_REGISTRY",
    "AutomationStatus",
    "SurfaceSpec",
    "auto_surfaces",
    "dispatch_registry",
    "is_engageable",
    "refused_surfaces",
]

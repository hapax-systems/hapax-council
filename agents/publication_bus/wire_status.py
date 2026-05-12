"""V5 publication-bus wire-or-delete registry — tracks per-publisher reachability.

Each V5 ``Publisher`` subclass under ``agents/publication_bus/`` is one of:

- **WIRED** — instantiated by a daemon (publish_orchestrator, weblog
  composer, sc-attestation runner, etc.) on the prod path. Confirmed via
  ``grep`` for prod callers excluding tests.
- **CRED_BLOCKED** — substrate complete and tested; awaiting operator
  credential bootstrap (e.g., ``pass insert <slug>``). When creds arrive,
  the wire decision flips to WIRED via a follow-up adapter PR.
- **DELETE** — substrate cannot be reached because the upstream surface
  was retired or replaced. Slated for removal in a follow-up cleanup PR.

The registry replaces the absence-bug R-5 ``wire-or-delete-decision``
ambiguity: each publisher now has an explicit decision recorded alongside
its module. Audit tooling can verify that any new publisher under
``agents/publication_bus/*_publisher.py`` is catalogued here.

R-5 source: ``~/.cache/hapax/relay/research/2026-04-26-absence-bugs-synthesis-for-beta.md``
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from datetime import date
from typing import Literal

WireStatus = Literal["WIRED", "CRED_BLOCKED", "DELETE"]


@dataclass(frozen=True)
class WireEntry:
    """One per-publisher reachability entry."""

    module: str
    surface_slug: str
    status: WireStatus
    pass_key_required: str | None = None
    rationale: str = ""


PUBLISHER_WIRE_REGISTRY: dict[str, WireEntry] = {
    "agents.publication_bus.bluesky_publisher": WireEntry(
        module="agents.publication_bus.bluesky_publisher",
        surface_slug="bluesky-atproto-multi-identity",
        status="WIRED",
        pass_key_required=None,
        rationale=(
            "Wired via agents/bluesky_atproto_adapter into "
            "publish_orchestrator.SURFACE_REGISTRY entry "
            "`bluesky-atproto-multi-identity`. Identifier from env "
            "HAPAX_BLUESKY_HANDLE (preferred) or HAPAX_BLUESKY_DID; "
            "app-password from HAPAX_BLUESKY_APP_PASSWORD. The same module "
            "also exposes BlueskyPostPublisher for the `bluesky-post` "
            "public-event daemon path."
        ),
    ),
    "agents.publication_bus.mastodon_publisher": WireEntry(
        module="agents.publication_bus.mastodon_publisher",
        surface_slug="mastodon-post",
        status="WIRED",
        pass_key_required=None,
        rationale=(
            "Wired via agents.cross_surface.mastodon_post for both the "
            "hapax-mastodon-post public-event systemd path and the "
            "publish_orchestrator.SURFACE_REGISTRY compatibility entry "
            "`mastodon-post`. Instance URL from HAPAX_MASTODON_INSTANCE_URL; "
            "access token from HAPAX_MASTODON_ACCESS_TOKEN."
        ),
    ),
    "agents.publication_bus.bridgy_publisher": WireEntry(
        module="agents.publication_bus.bridgy_publisher",
        surface_slug="bridgy-webmention-publish",
        status="WIRED",
        pass_key_required=None,
        rationale=(
            "Wired via agents/bridgy_adapter into "
            "publish_orchestrator.SURFACE_REGISTRY entry "
            "`bridgy-webmention-publish`. No publish-time credentials — "
            "Bridgy was OAuth'd to the operator's downstream silos at "
            "bootstrap and reads source URL microformats at crawl time. "
            "Source URL constructed as https://hapax.omg.lol/weblog/{slug}. "
            "Refusal-annex artifacts remain blocked at the adapter until "
            "omg-weblog source URL witness/sequencing is committed."
        ),
    ),
    "agents.publication_bus.internet_archive_publisher": WireEntry(
        module="agents.publication_bus.internet_archive_publisher",
        surface_slug="internet-archive-ias3",
        status="WIRED",
        pass_key_required=None,
        rationale=(
            "Wired via agents/internet_archive_ias3_adapter into "
            "publish_orchestrator.SURFACE_REGISTRY entry "
            "`internet-archive-ias3`. Access + secret keys from env "
            "HAPAX_IA_ACCESS_KEY + HAPAX_IA_SECRET_KEY (hapax-secrets.service "
            "from pass `ia/access-key` + `ia/secret-key`)."
        ),
    ),
    "agents.publication_bus.omg_weblog_publisher": WireEntry(
        module="agents.publication_bus.omg_weblog_publisher",
        surface_slug="omg-lol-weblog-bearer-fanout",
        status="WIRED",
        pass_key_required="omg-lol/api-key",
        rationale=(
            "Wired via agents/omg_weblog_publisher (legacy adapter) into "
            "publish_orchestrator._DISPATCH_MAP entries `omg-weblog` and "
            "`oudepode-omg-weblog`. Also referenced by sc_attestation_publisher "
            "and omg_rss_fanout helper."
        ),
    ),
    "agents.publication_bus.omg_statuslog_publisher": WireEntry(
        module="agents.publication_bus.omg_statuslog_publisher",
        surface_slug="omg-lol-statuslog",
        status="WIRED",
        pass_key_required="omg-lol/api-key",
        rationale=(
            "Wired via agents.operator_awareness.omg_lol_fanout, invoked by "
            "systemd/units/hapax-omg-lol-fanout.service. The daemon renders a "
            "public-filtered awareness summary, dedupes by hash, then publishes "
            "through OmgLolStatuslogPublisher so the live statuslog egress path "
            "uses the publication-bus allowlist/legal-name/counter/witness "
            "invariants."
        ),
    ),
    "agents.publication_bus.osf_prereg_publisher": WireEntry(
        module="agents.publication_bus.osf_prereg_publisher",
        surface_slug="osf-prereg",
        status="WIRED",
        pass_key_required=None,
        rationale=(
            "Wired via agents/osf_prereg_adapter into "
            "publish_orchestrator.SURFACE_REGISTRY entry `osf-prereg`. "
            "Token from env HAPAX_OSF_TOKEN. Distinct from the legacy "
            "agents/osf_preprint_publisher (preprints `/v2/preprints/`); "
            "preregistration is `/v2/registrations/`."
        ),
    ),
    "agents.publication_bus.philarchive_publisher": WireEntry(
        module="agents.publication_bus.philarchive_publisher",
        surface_slug="philarchive-deposit",
        status="WIRED",
        pass_key_required=None,
        rationale=(
            "Wired via agents/philarchive_adapter into "
            "publish_orchestrator.SURFACE_REGISTRY entry "
            "`philarchive-deposit`. Session cookie + author ID from env "
            "HAPAX_PHILARCHIVE_SESSION_COOKIE + HAPAX_PHILARCHIVE_AUTHOR_ID. "
            "requires_legal_name=True per ORCID linkage."
        ),
    ),
    "agents.publication_bus.refusal_brief_publisher": WireEntry(
        module="agents.publication_bus.refusal_brief_publisher",
        surface_slug="zenodo-refusal-deposit",
        status="WIRED",
        pass_key_required=None,
        rationale=(
            "Wired via agents/refusal_brief_zenodo_adapter into "
            "publish_orchestrator._DISPATCH_MAP entry "
            "`zenodo-refusal-deposit`. Token from env HAPAX_ZENODO_TOKEN "
            "(hapax-secrets.service from pass `zenodo/api-token`). "
            "RelatedIdentifier graph composition (IsRequiredBy + "
            "IsObsoletedBy) ships with the publisher."
        ),
    ),
    "agents.publication_bus.treasury_prime_publisher": WireEntry(
        module="agents.publication_bus.treasury_prime_publisher",
        surface_slug="treasury-prime-receiver",
        status="WIRED",
        pass_key_required="treasury-prime/webhook-secret",
        rationale=(
            "Tenth (and final) wired monetization rail (cc-task "
            "treasury-prime-end-to-end-wiring). Third bank rail wired e2e. "
            "Wired via logos/api/routes/payment_rails.py POST "
            "/api/payment-rails/treasury-prime. HMAC SHA-256 over raw body via "
            "X-Signature + TREASURY_PRIME_WEBHOOK_SECRET env var (same header "
            "name as Modern Treasury — disambiguated by URL path). Phase 0 "
            "accepts only incoming_ach.create; Phase 1 transaction.create for "
            "core direct accounts is a separate downstream cc-task. No "
            "cancellation auto-link."
        ),
    ),
    "agents.publication_bus.modern_treasury_publisher": WireEntry(
        module="agents.publication_bus.modern_treasury_publisher",
        surface_slug="modern-treasury-receiver",
        status="WIRED",
        pass_key_required="modern-treasury/webhook-secret",
        rationale=(
            "Ninth wired monetization rail (cc-task modern-treasury-end-to-end-wiring). "
            "Second bank rail wired e2e. Wired via logos/api/routes/payment_rails.py "
            "POST /api/payment-rails/modern-treasury. HMAC SHA-256 over raw body via "
            "X-Signature + MODERN_TREASURY_WEBHOOK_SECRET env var. Direction filter "
            "is event-name-level (only incoming_payment_detail.* accepted; "
            "payment_order.* rejected). No cancellation auto-link."
        ),
    ),
    "agents.publication_bus.mercury_publisher": WireEntry(
        module="agents.publication_bus.mercury_publisher",
        surface_slug="mercury-receiver",
        status="WIRED",
        pass_key_required="mercury/webhook-secret",
        rationale=(
            "Eighth wired monetization rail (cc-task mercury-end-to-end-wiring). "
            "First bank rail wired e2e. Wired via logos/api/routes/payment_rails.py "
            "POST /api/payment-rails/mercury. HMAC SHA-256 over raw body via "
            "X-Mercury-Signature (canonical) with X-Hook-Signature (legacy) "
            "fallback + MERCURY_WEBHOOK_SECRET env var. Rail's "
            "MercuryTransactionDirection filter rejects outgoing kinds (ach_outgoing, "
            "wire_outgoing, etc.) at the receiver boundary; publisher writes "
            "manifest entries only (no cancellation auto-link — Mercury's 2 "
            "event kinds are lifecycle states)."
        ),
    ),
    "agents.publication_bus.buy_me_a_coffee_publisher": WireEntry(
        module="agents.publication_bus.buy_me_a_coffee_publisher",
        surface_slug="buy-me-a-coffee-receiver",
        status="WIRED",
        pass_key_required="buy-me-a-coffee/webhook-secret",
        rationale=(
            "Seventh wired monetization rail (cc-task buy-me-a-coffee-end-to-end-wiring). "
            "Wired via logos/api/routes/payment_rails.py POST "
            "/api/payment-rails/buy-me-a-coffee. HMAC SHA-256 over raw body via "
            "X-Signature-Sha256 + BUY_ME_A_COFFEE_WEBHOOK_SECRET env var "
            "(hapax-secrets.service from pass `buy-me-a-coffee/webhook-secret`). "
            "Membership-cancellation events emit a RefusalEvent under axiom "
            "full_auto_or_nothing for the refusal_annex_renderer to aggregate."
        ),
    ),
    "agents.publication_bus.patreon_publisher": WireEntry(
        module="agents.publication_bus.patreon_publisher",
        surface_slug="patreon-receiver",
        status="WIRED",
        pass_key_required="patreon/webhook-secret",
        rationale=(
            "Sixth wired monetization rail (cc-task patreon-end-to-end-wiring). "
            "Wired via logos/api/routes/payment_rails.py POST "
            "/api/payment-rails/patreon. HMAC MD5 (not SHA-256, per Patreon's "
            "documented wire format) via X-Patreon-Signature + "
            "PATREON_WEBHOOK_SECRET env var. Event-kind in X-Patreon-Event "
            "header (colon-delimited form). Pledge-deletion events emit a "
            "RefusalEvent under axiom full_auto_or_nothing for the "
            "refusal_annex_renderer to aggregate."
        ),
    ),
    "agents.publication_bus.ko_fi_publisher": WireEntry(
        module="agents.publication_bus.ko_fi_publisher",
        surface_slug="ko-fi-receiver",
        status="WIRED",
        pass_key_required="ko-fi/webhook-verification-token",
        rationale=(
            "Fifth wired monetization rail (cc-task ko-fi-end-to-end-wiring). "
            "Wired via logos/api/routes/payment_rails.py POST "
            "/api/payment-rails/ko-fi. Token-in-payload verification (NOT HMAC) "
            "via KO_FI_WEBHOOK_VERIFICATION_TOKEN env var (hapax-secrets.service "
            "from pass `ko-fi/webhook-verification-token`). No cancellation event "
            "in the canonical 4 (donation / subscription / commission / shop_order), "
            "so no auto-link path."
        ),
    ),
    "agents.publication_bus.stripe_payment_link_publisher": WireEntry(
        module="agents.publication_bus.stripe_payment_link_publisher",
        surface_slug="stripe-payment-link-receiver",
        status="WIRED",
        pass_key_required="stripe-payment-link/webhook-secret",
        rationale=(
            "Fourth wired monetization rail (cc-task stripe-payment-link-end-to-end-wiring). "
            "Wired via logos/api/routes/payment_rails.py POST "
            "/api/payment-rails/stripe-payment-link. Stripe-Signature header carries "
            "timestamped HMAC SHA-256 (t=<unix>,v1=<hex>) with replay-tolerance "
            "verified internally by the rail. Subscription-deletion events emit a "
            "RefusalEvent under axiom full_auto_or_nothing to the canonical refusal "
            "log for the refusal_annex_renderer to aggregate."
        ),
    ),
    "agents.publication_bus.open_collective_publisher": WireEntry(
        module="agents.publication_bus.open_collective_publisher",
        surface_slug="open-collective-receiver",
        status="WIRED",
        pass_key_required="open-collective/webhook-secret",
        rationale=(
            "Third wired monetization rail (cc-task open-collective-end-to-end-wiring). "
            "Wired via logos/api/routes/payment_rails.py POST "
            "/api/payment-rails/open-collective. HMAC SHA-256 over raw body via "
            "X-Open-Collective-Signature + OPEN_COLLECTIVE_WEBHOOK_SECRET env var "
            "(hapax-secrets.service from pass `open-collective/webhook-secret`). "
            "Multi-currency-native; no cancellation event in the canonical 4 "
            "(collective_transaction_created / order_processed / member_created / "
            "expense_paid), so no auto-link path. Operator-action gated on the "
            "Wyoming-LLC bootstrap (Open Source Collective fiscal-sponsor "
            "application requires a payout entity)."
        ),
    ),
    "agents.publication_bus.liberapay_publisher": WireEntry(
        module="agents.publication_bus.liberapay_publisher",
        surface_slug="liberapay-receiver",
        status="WIRED",
        pass_key_required="liberapay/webhook-secret",
        rationale=(
            "Second wired monetization rail (cc-task liberapay-end-to-end-wiring). "
            "Wired via logos/api/routes/payment_rails.py POST "
            "/api/payment-rails/liberapay which captures the raw body + "
            "X-Liberapay-Signature header and dispatches accepted events through "
            "LiberapayPublisher.publish_event(). Liberapay does not natively ship "
            "webhooks (per liberapay/liberapay.com#688); upstream bridge "
            "(cloudmailin / mailgun / n8n) parses Liberapay outbound emails or "
            "CSV exports and POSTs to this endpoint. Webhook secret from "
            "LIBERAPAY_WEBHOOK_SECRET env var (hapax-secrets.service from pass "
            "`liberapay/webhook-secret`); IP allowlist gate via "
            "LIBERAPAY_REQUIRE_IP_ALLOWLIST=1. Tip-cancellation events emit a "
            "RefusalEvent to the canonical refusal log under axiom "
            "full_auto_or_nothing for the refusal_annex_renderer to aggregate."
        ),
    ),
    "agents.publication_bus.github_sponsors_publisher": WireEntry(
        module="agents.publication_bus.github_sponsors_publisher",
        surface_slug="github-sponsors-receiver",
        status="WIRED",
        pass_key_required="github-sponsors/webhook-secret",
        rationale=(
            "First wired monetization rail (cc-task github-sponsors-end-to-end-wiring). "
            "Wired via logos/api/routes/payment_rails.py POST "
            "/api/payment-rails/github-sponsors which captures the raw body + "
            "X-Hub-Signature-256 header and dispatches accepted events through "
            "GitHubSponsorsPublisher.publish_event(). Webhook secret from "
            "GITHUB_SPONSORS_WEBHOOK_SECRET env var (hapax-secrets.service from "
            "pass `github-sponsors/webhook-secret`). Cancellation events emit a "
            "RefusalEvent to the canonical refusal log under axiom "
            "full_auto_or_nothing for the existing refusal_annex_renderer to "
            "aggregate. Tier setup on github.com is operator-action gated by "
            "the legal-entity bootstrap (Wyoming LLC + EIN); the wire itself "
            "is live regardless."
        ),
    ),
    "agents.attribution.crossref_depositor": WireEntry(
        module="agents.attribution.crossref_depositor",
        surface_slug="crossref-doi-deposit",
        status="CRED_BLOCKED",
        pass_key_required="crossref/depositor-credentials",
        rationale=(
            "Crossref DOI depositor (sibling to Zenodo). Substrate complete + "
            "tested (agents/attribution/crossref_depositor.py, 223 LOC). "
            "Operator-action: `pass insert crossref/depositor-credentials` — "
            "requires Crossref membership (institutional affiliation OR paid). "
            "Disposition: review-by 2026-08-01 — if creds not bootstrapped by "
            "that date, re-evaluate retire vs continued hold. DataCite mirror "
            "via agents.publication_bus.graph_publisher already provides "
            "load-bearing citation-graph coverage; Crossref is additive."
        ),
    ),
    "agents.publication_bus.graph_publisher": WireEntry(
        module="agents.publication_bus.graph_publisher",
        surface_slug="datacite-graphql-mirror",
        status="WIRED",
        pass_key_required=None,
        rationale=(
            "Wired via agents.publication_bus.self_citation_graph_doi commit path "
            "using GraphPublisher. Mirrors SURFACE_REGISTRY entry "
            "`datacite-graphql-mirror`."
        ),
    ),
    "agents.publication_bus.youtube_live_chat_publisher": WireEntry(
        module="agents.publication_bus.youtube_live_chat_publisher",
        surface_slug="youtube-live-chat-message",
        status="CRED_BLOCKED",
        pass_key_required="google/youtube-force-ssl-token",
        rationale=(
            "Wired via agents.hapax_daimonion.cpal.response_dispatch.dispatch_response "
            "for cc-task chat-response-verbal-and-text (operator outcome 5/5). "
            "Operator-action: (1) mint a Google OAuth token with youtube.force-ssl "
            "scope through shared.google_auth and (2) populate "
            "config/publication-bus/youtube-live-chat.yaml (or set "
            "HAPAX_YOUTUBE_LIVE_CHAT_ALLOWLIST) with the active broadcast's "
            "liveChatId. Disposition: review-by 2026-08-01. Once epsilon's "
            "youtube_chat_reader (cc-task youtube-chat-ingestion-impingement) "
            "registers a concrete reader and the operator-action above lands, "
            "the chat-post path activates automatically."
        ),
    ),
}


def status_summary() -> dict[WireStatus, int]:
    """Tally publishers by status."""
    counts: dict[WireStatus, int] = {"WIRED": 0, "CRED_BLOCKED": 0, "DELETE": 0}
    for entry in PUBLISHER_WIRE_REGISTRY.values():
        counts[entry.status] += 1
    return counts


def cred_blocked_pass_keys() -> list[str]:
    """Return the operator-action queue: pass keys needed to unblock wiring."""
    keys: list[str] = []
    for entry in PUBLISHER_WIRE_REGISTRY.values():
        if entry.status == "CRED_BLOCKED" and entry.pass_key_required:
            for k in entry.pass_key_required.split(","):
                keys.append(k.strip())
    return sorted(set(keys))


def credential_readiness() -> dict[str, bool]:
    """Probe ``pass`` for each CRED_BLOCKED entry's key without reading values.

    Returns a dict of ``{pass_key: exists}`` where ``exists`` is True when
    ``pass show <key>`` exits 0 (credential is present in the store).
    """
    result: dict[str, bool] = {}
    for key in cred_blocked_pass_keys():
        try:
            proc = subprocess.run(
                ["pass", "show", key],
                capture_output=True,
                timeout=5,
            )
            result[key] = proc.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            result[key] = False
    return result


_ISO_DATE_RE = re.compile(r"\breview-by\s+(\d{4}-\d{2}-\d{2})\b")


def overdue_reviews(*, today: date | None = None) -> list[tuple[str, str, date]]:
    """Return CRED_BLOCKED entries whose review-by date has passed.

    Each tuple is ``(module, pass_key, review_date)``.
    """
    today = today or date.today()
    overdue: list[tuple[str, str, date]] = []
    for module, entry in PUBLISHER_WIRE_REGISTRY.items():
        if entry.status != "CRED_BLOCKED":
            continue
        m = _ISO_DATE_RE.search(entry.rationale)
        if not m:
            continue
        review_date = date.fromisoformat(m.group(1))
        if review_date < today:
            overdue.append((module, entry.pass_key_required or "", review_date))
    return overdue


__all__ = [
    "PUBLISHER_WIRE_REGISTRY",
    "WireEntry",
    "WireStatus",
    "cred_blocked_pass_keys",
    "credential_readiness",
    "overdue_reviews",
    "status_summary",
]

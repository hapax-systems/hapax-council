# Support Surface Registry Design

**Date:** 2026-04-29
**Status:** implementation-contract
**Task:** `support-surface-registry`
**Branch:** `codex/cx-blue-support-surface-registry`
**Canonical config:** `config/support-surface-registry.json`
**Schema:** `schemas/support-surface-registry.schema.json`
**Runtime helpers:** `shared/support_surface_registry.py`

## Purpose

The support surface registry is the train-readable boundary for support,
patronage, fan-funding, sponsor, and support-copy surfaces. It prevents payment
normalizers and public offer generators from rediscovering platform policy by
making every surface one of:

- `allowed`: receive-only support rails that fit the no-perk doctrine.
- `guarded`: platform or copy surfaces that may be used only when readiness
  gates are true.
- `refusal_conversion`: generic money paths that must be refused and converted
  into a daemon-tractable artifact or no-perk support rail.

## Source Authority

This packet consumes the 2026-04-29 autonomous grounding value-stream map, the
HSEA Phase 9 revenue-preparation draft, and the later refusal briefs for
Patreon, GitHub Sponsors, Stripe, Discord community surfaces, and consulting.
Where HSEA Phase 9 suggested GitHub Sponsors copy, patron-style tiers, Discord
roles, Stripe payment links, or consulting offers, this registry supersedes that
copy with the refusal briefs.

## Surface Decisions

Required active or guarded surfaces:

- `youtube_ads`
- `youtube_supers`
- `youtube_super_thanks`
- `youtube_memberships_no_perk`
- `liberapay_recurring`
- `lightning_invoice_receive`
- `nostr_zaps`
- `kofi_tips_guarded`
- `github_sponsors`
- `sponsor_support_copy`

Required refusal conversions:

- `patreon`
- `substack_paid_subscription`
- `discord_community_subscriptions`
- `stripe_payment_links`
- `consulting_as_service`

No downstream task may promote a refusal conversion into an active support
surface unless a future constitutional change explicitly retires the relevant
refusal brief.

## No-Perk Support Doctrine

Support is for the instrument, not access to the operator. Canonical support
copy must preserve all of these clauses:

- Support keeps compute, archive storage, rights-safe production, and
  publication plumbing running.
- No access, requests, private advice, priority, shoutouts, guarantees, client
  service, deliverables, or control are sold.
- Work continues regardless of support.

Forbidden shapes include early access, exclusive content, private channels,
role gates, request queues, priority responses, acknowledgments by individual
name, leaderboards, client service, and ad-read deliverables.

## Aggregate-Only Receipts

Public and train-readable receipt state is aggregate-only. The public projection
may include only:

- window bounds
- receipt count
- gross amount by currency
- rail counts
- surface counts
- readiness state

The public projection may not include identity, handles, names, email,
comment/message text, per-receipt history, supporter lists, or leaderboards.
Private reconciliation may keep only processor audit references required to
resolve financial state; those references are never public support state.

## Readiness Gates

Guarded support prompts require explicit readiness evidence. Examples:

- `MonetizationReadiness.safe_to_monetize`
- `MonetizationReadiness.safe_to_accept_payment`
- `MonetizationReadiness.safe_to_publish_offer`
- `support_surface_registry.no_perk_copy_valid`
- `payment_aggregator_v2.aggregate_only_projection`

`shared.support_surface_registry.public_prompt_allowed` fails closed unless all
declared gates for the surface are true. Refusal conversions always return
false.

## Superseded HSEA Assumptions

The following older assumptions are superseded:

- Older sponsorware-shaped GitHub Sponsors profile copy remains refused. The
  buildable surface is now the `hapax-systems` org Sponsors profile with
  no-perk tiers, aggregate-only receipt projection, and repo funding metadata.
- Patreon tiers, posts, role sync, and perk ladders are refused. The buildable
  conversion is no-perk support through Liberapay, Lightning, and Nostr zaps.
- Discord community/server subscriptions and role-gated channels are refused.
  Discord is not a support surface; any future Discord use must be one-way
  publication-bus fanout under the cross-surface event contract.
- Stripe Payment Links and Connect flows are refused because KYC and dispute
  handling are operator-physical.
- Consulting-as-service is refused. Methodology can ship as self-serve packages,
  templates, datasets, docs, and license-request artifacts.

## Downstream Consumers

This registry unblocks `payment-aggregator-v2-support-normalizer` and any
public no-perk offer page generator. Consumers should load the config through
`shared.support_surface_registry.load_support_surface_registry`, use
`public_prompt_allowed` before rendering prompts, and emit receipt state through
`build_aggregate_receipt_projection`.

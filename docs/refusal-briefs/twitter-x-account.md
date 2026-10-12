# Refusal Brief — Twitter / X Account

**Slug:** `leverage-REFUSED-twitter-linkedin-substack-accounts`
**Status:** REFUSED for daemonized walk-away automation — trigger dispositioned 2026-10-06 to a governed broadcast-only / automated-agent-disclosed tier (see Re-evaluation below). The bright line itself stands.
**Surface:** `twitter-x-account`
**Date:** 2026-04-26 (PR #1560 cc-task-level), 2026-05-03 (first-class graph citizen), 2026-10-06 (trigger fired and dispositioned)
**Axiom tag:** `feedback_full_automation_or_no_engagement`
**Surface registry entry:** `twitter-x-account` (REFUSED → rescoped tier pending registry update)
**Provenance:** PR #1560 declared the cc-task-level refusal; this brief + REFUSED-tier publisher subclass made it a first-class publication-bus graph citizen. 2026-10-06: the brief's own re-evaluation trigger fired and was dispositioned under cc-task `refusal-brief-twitter-x-reeval-20261006` (operator ruling 2026-10-06; rescope material lanebus/dev1/20261006T1334Z).

## What was refused

Any daemon-side mechanism for posting to Twitter/X. The platform is operator-mediated by design: posts surface @-mentions, replies, quote-tweets, and DMs that all create bidirectional engagement expectations. A "post and walk away" mode does not exist constitutionally — even if the daemon never reads the inbox, the inbox accumulates with implicit response expectations.

The constitutional bright line is `feedback_full_automation_or_no_engagement`: if engagement is structurally part of the surface, daemonising the surface is refused.

## Why a one-way "post-only" mode does not work

A naive design — "we only POST, never read replies" — would still:

1. Surface @-mentions to the operator's inbox via push notifications (operator-physical mediation).
2. Set engagement expectations from named-account followers (a reply to an @-mention is socially weighted by Twitter's algorithm).
3. Create a "ghosted account" affordance that Twitter actively penalizes (rate-limit visibility, shadowban risks for accounts that post but never engage).

The platform's product model is structurally bidirectional. Daemon-only post mode degrades the surface for both the operator and the audience.

## Re-evaluation — FIRED 2026-10-06, dispositioned

The 2026-05-03 trigger, verbatim:

> If Twitter/X ships a documented broadcast-only API tier (e.g. machine-readable disclosure that posts come from an automated agent, with replies routed to a separate moderation queue rather than the operator's inbox), we'd re-evaluate. As of 2026-05-03 no such tier exists.

**Disposition (2026-10-06).** X has not shipped the platform-side tier this trigger anticipated. What fired instead is an operator ruling selecting the official X API and mandating, estate-side, a tier with the properties the trigger was protecting:

> "let's use the official API, and I already have backup codes for totp" — operator, 2026-10-06, X automation thread (verbatim; ruling relayed via dev1-seat 14:15Z)

This is the estate's answer to the bright line, not a claim about the original authors' intent, and not a claim that X shipped anything:

- **Automated-agent disclosure on every emit** — automated AI-authored labeling through X's own label product on every API post; never claims human authorship. This is the machine-readable disclosure the trigger asked for, supplied by the sender rather than the platform.
- **Inbound engagement is operated, not walked away from** — venue-card T2 inbound SLA (reply-audit 2×/day, ≤24h answer discipline) and the M2.2 inbound queue (mention/DM intake) with tempo teeth: sustained operations with cadence obligations, not a fire-and-forget emitter. Replies route through the estate's intake, answering the "accumulates on the operator's inbox" failure mode the trigger named.
- **Official API only** — OAuth 1.0a user-context against documented endpoints; no scraping, no browser automation, no ToS evasion.

**Standing prohibitions (unaffected by this disposition):** automated follow/mention/DM, scraping, browser automation, and identical cross-posting across surfaces remain refused regardless of tier.

**Reversion clause (the teeth):** the rescoped tier stands only while the engagement architecture is actually operated. If the T2 SLA or the M2.2 inbound queue lapses — sustained unanswered inbound, audit cadence missed — the surface reverts to REFUSED without a new trigger cycle.

**Not authorized by this disposition:** any X API client code or source-row admission (separate rows, gated on this brief landing plus desk clearance); credential handling (secrets resolve through hapax-secrets/FileStore only).

## Cross-references

- Sibling refusal: `linkedin-account` (same constitutional posture, different platform mediation shape)
- Sibling refusal: `substack-account` (subscriber-relationship management precludes daemon-only)
- Sibling refusal: `discord-webhook` (multi-user platform, similar engagement-surface logic)
- Refused publisher class: `agents.publication_bus.publisher_kit.refused.TwitterRefusedPublisher` (registry update to the rescoped tier is its own governed change)
- Originating cc-task: `leverage-REFUSED-twitter-linkedin-substack-accounts` (closed)
- Dispositioning cc-task: `refusal-brief-twitter-x-reeval-20261006`

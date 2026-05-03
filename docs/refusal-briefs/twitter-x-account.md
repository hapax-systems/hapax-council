# Refusal Brief — Twitter / X Account

**Slug:** `leverage-REFUSED-twitter-linkedin-substack-accounts`
**Status:** REFUSED — no daemon, no API client, no scaffolded `agents/twitter_*/` module is to be built.
**Surface:** `twitter-x-account`
**Date:** 2026-04-26 (PR #1560 cc-task-level), 2026-05-03 (this brief — first-class graph citizen)
**Axiom tag:** `feedback_full_automation_or_no_engagement`
**Surface registry entry:** `twitter-x-account` (REFUSED)
**Provenance:** PR #1560 (`leverage-REFUSED-twitter-linkedin-substack-accounts`) declared the cc-task-level refusal; this brief + REFUSED-tier publisher subclass make it a first-class publication-bus graph citizen.

## What was refused

Any daemon-side mechanism for posting to Twitter/X. The platform is operator-mediated by design: posts surface @-mentions, replies, quote-tweets, and DMs that all create bidirectional engagement expectations. A "post and walk away" mode does not exist constitutionally — even if the daemon never reads the inbox, the inbox accumulates with implicit response expectations.

The constitutional bright line is `feedback_full_automation_or_no_engagement`: if engagement is structurally part of the surface, daemonising the surface is refused.

## Why a one-way "post-only" mode does not work

A naive design — "we only POST, never read replies" — would still:

1. Surface @-mentions to the operator's inbox via push notifications (operator-physical mediation).
2. Set engagement expectations from named-account followers (a reply to an @-mention is socially weighted by Twitter's algorithm).
3. Create a "ghosted account" affordance that Twitter actively penalizes (rate-limit visibility, shadowban risks for accounts that post but never engage).

The platform's product model is structurally bidirectional. Daemon-only post mode degrades the surface for both the operator and the audience.

## Re-evaluation triggers

This refusal stands as long as `feedback_full_automation_or_no_engagement` remains constitutional. If Twitter/X ships a documented broadcast-only API tier (e.g. machine-readable disclosure that posts come from an automated agent, with replies routed to a separate moderation queue rather than the operator's inbox), we'd re-evaluate. As of 2026-05-03 no such tier exists.

## Cross-references

- Sibling refusal: `linkedin-account` (same constitutional posture, different platform mediation shape)
- Sibling refusal: `substack-account` (subscriber-relationship management precludes daemon-only)
- Sibling refusal: `discord-webhook` (multi-user platform, similar engagement-surface logic)
- Refused publisher class: `agents.publication_bus.publisher_kit.refused.TwitterRefusedPublisher`
- Originating cc-task: `leverage-REFUSED-twitter-linkedin-substack-accounts` (closed)

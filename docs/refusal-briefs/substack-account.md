# Refusal Brief — Substack Account

**Slug:** `leverage-REFUSED-twitter-linkedin-substack-accounts`
**Status:** REFUSED — no daemon, no API client, no scaffolded `agents/substack_*/` module is to be built.
**Surface:** `substack-account`
**Date:** 2026-04-26 (PR #1560 cc-task-level), 2026-05-03 (this brief — first-class graph citizen)
**Axiom tag:** `feedback_full_automation_or_no_engagement`
**Surface registry entry:** `substack-account` (REFUSED)
**Provenance:** PR #1560 declared the cc-task-level refusal; this brief + REFUSED-tier publisher subclass make it a first-class publication-bus graph citizen.

## What was refused

Any daemon-side mechanism for publishing on Substack. Substack monetizes via subscriber-relationship management — newsletter cadence, post-comment threads on each issue, and direct subscriber correspondence (replies to digest emails).

## Why a "post-only" mode does not work on Substack

The platform's monetization story is the relationship between author and subscriber. Subscribers pay (or follow free) because they expect:

1. Predictable cadence — irregular daemon publishing degrades the platform-promised "newsletter" experience.
2. Engagement on post comments — Substack surfaces comments to the author and signals expected response.
3. Reply-to-newsletter dynamic — subscribers reply to email digests with the expectation that the author reads them.

A daemon-only publishing mode would convert Substack into a worse RSS feed for subscribers who paid (or chose to subscribe) for relationship-mediated content. This is an active downgrade of the platform-promised subscriber experience, not just a constitutional refusal — the surface would harm subscribers if used in daemon mode.

## Cross-platform alternatives

For broadcast publishing without subscriber-relationship management, the operator's existing weblog (`hapax.weblog.lol`) on omg.lol is the canonical surface. RSS fanout to other federation platforms (e.g. Mastodon via webmention) handles the discovery side without taking on subscriber-relationship debt.

## Re-evaluation triggers

This refusal stands as long as Substack's product model centers subscriber-relationship management. If the platform ships a clearly-disclosed "automated digest" tier where subscribers explicitly opt into machine-mediated publishing with no engagement-reciprocity, that surface might warrant fresh evaluation.

## Cross-references

- Sibling refusal: `twitter-x-account`
- Sibling refusal: `linkedin-account`
- Refused publisher class: `agents.publication_bus.publisher_kit.refused.SubstackRefusedPublisher`
- Originating cc-task: `leverage-REFUSED-twitter-linkedin-substack-accounts` (closed)
- Cross-surface alternative: omg-lol weblog + bridgy webmention fanout (FULL_AUTO tier)

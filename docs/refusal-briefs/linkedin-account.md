# Refusal Brief — LinkedIn Account

**Slug:** `leverage-REFUSED-twitter-linkedin-substack-accounts`
**Status:** REFUSED — no daemon, no API client, no scaffolded `agents/linkedin_*/` module is to be built.
**Surface:** `linkedin-account`
**Date:** 2026-04-26 (PR #1560 cc-task-level), 2026-05-03 (this brief — first-class graph citizen)
**Axiom tag:** `feedback_full_automation_or_no_engagement` + `single_user`
**Surface registry entry:** `linkedin-account` (REFUSED)
**Provenance:** PR #1560 declared the cc-task-level refusal; this brief + REFUSED-tier publisher subclass make it a first-class publication-bus graph citizen.

## What was refused

Any daemon-side mechanism for posting to LinkedIn. LinkedIn requires connection-graph mediation: posts surface to a curated-connection feed, comments arrive from connections expecting reciprocal engagement, and the platform's identity model is structurally bidirectional.

## Why a "post-only" mode does not work on LinkedIn

LinkedIn is *more* bidirectional than Twitter — connections are mutual-consent relationships, not asymmetric follows. This means:

1. Comments and reactions arrive from named professional connections with implicit reciprocal-engagement expectations.
2. The platform's "stay connected" framing makes silence read as professional disengagement.
3. The connection graph itself is data the platform-as-product expects the operator to curate.

A daemon-side post-only mode would degrade the operator's standing in their own connection graph and structurally violates LinkedIn's product model.

## Re-evaluation triggers

This refusal stands as long as `feedback_full_automation_or_no_engagement` remains constitutional and LinkedIn's connection-graph product model persists. If LinkedIn ships a "company page" or "broadcast newsletter" tier with explicit machine-author disclosure and no expectation of operator engagement, that surface might warrant fresh evaluation — but as of 2026-05-03 no such tier exists for personal/operator accounts.

## Cross-references

- Sibling refusal: `twitter-x-account`
- Sibling refusal: `substack-account`
- Refused publisher class: `agents.publication_bus.publisher_kit.refused.LinkedInRefusedPublisher`
- Originating cc-task: `leverage-REFUSED-twitter-linkedin-substack-accounts` (closed)

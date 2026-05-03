# Refusal Brief — Reddit Account

**Slug:** `reddit-refusal-brief`
**Status:** REFUSED — no daemon, no API client, no scaffolded `agents/reddit_*/` module is to be built.
**Surface:** `reddit-account`
**Date:** 2026-05-03
**Axiom tag:** `single_user` + `feedback_full_automation_or_no_engagement`
**Surface registry entry:** `reddit-account` (REFUSED)

## What was refused

Any daemon-side mechanism for posting to Reddit (submitting links, text posts, or comments to subreddits). Reddit is a community-moderation platform: each subreddit applies per-community rules via human moderators. Accounts that post without engaging are algorithmically penalized.

## Why a "post-only" mode does not work on Reddit

Reddit's product model is structurally engagement-reciprocal at multiple layers:

1. **Per-subreddit rules** — each subreddit's mod team enforces rules via removal/banning. Many subreddits explicitly forbid bot-authored content; some require human review of all submissions; nearly all enforce per-account "karma threshold" requirements before posting is permitted.
2. **Account karma signaling** — Reddit's algorithm uses karma (post and comment) as a quality signal. Accounts that only post (never comment, never engage) accumulate negative signals.
3. **Reply expectations** — Reddit threads expect operator engagement; OP-replies are a major engagement driver.
4. **Cross-post / brigade dynamics** — Reddit's anti-spam systems flag accounts posting the same content to multiple subreddits even if technically allowed.

A daemon-only mode would face shadowban risk + community-removal risk + per-subreddit rule violations within hours of first deployment.

## Why Reddit fails the single_user axiom too

Subreddits are multi-moderator communities. Posting to /r/programming or /r/MachineLearning means agreeing to be moderated by named third parties — a multi-user authority relationship. The single_user axiom forbids this kind of multi-party moderation surface in daemon mode (it's fine when operator-physical, but the daemon itself cannot enter a moderator relationship).

## Cross-platform alternatives

For broadcast publishing without engagement-reciprocity:
- Operator's existing weblog (`hapax.weblog.lol`) — FULL_AUTO via `omg-lol-weblog-bearer-fanout` surface.
- Bridgy webmention fanout — federation to ATProto (Bluesky) and Mastodon — both already FULL_AUTO surfaces.
- Internet Archive IAS3 — long-term archival without engagement.

These cover the broadcast use-case Reddit might tempt without taking on community-moderation debt.

## Re-evaluation triggers

This refusal stands as long as Reddit's product model centers community moderation. If Reddit ships a documented "machine-author broadcast tier" with explicit disclosure (similar to Twitter's flagged-machine-author proposals), that surface might warrant fresh evaluation.

## Cross-references

- Sibling refusal: `twitter-x-account` (similar engagement-reciprocity logic)
- Sibling refusal: `linkedin-account` (connection-graph mediation)
- Sibling refusal: `discord-webhook` (multi-user platform per-server moderation)
- Sibling refusal: `substack-account` (subscriber-relationship management)
- Refused publisher class: `agents.publication_bus.publisher_kit.refused.RedditRefusedPublisher`
- Cross-surface alternatives: omg-lol weblog, bluesky-atproto-multi-identity, internet-archive-ias3 (all FULL_AUTO).

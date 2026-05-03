# Refusal Brief — GitHub Discussions

**Slug:** `leverage-REFUSED-github-discussions-enabled`
**Status:** REFUSED — GitHub Discussions feature is not enabled on Hapax repos.
**Surface:** `github-discussions`
**Date:** 2026-04-26 (PR #1567 cc-task-level), 2026-05-03 (this brief — first-class graph citizen)
**Axiom tag:** `feedback_full_automation_or_no_engagement` + `single_user`
**Surface registry entry:** `github-discussions` (REFUSED)
**Provenance:** PR #1567 declared the cc-task-level refusal; this brief + REFUSED-tier publisher subclass make it a first-class publication-bus graph citizen.

## What was refused

Enabling GitHub Discussions on the Hapax repos. Discussions is GitHub's threaded community Q&A feature — separate from Issues, distinct purpose, distinct interaction model.

## Why GitHub Discussions is REFUSED

GitHub Discussions creates a Q&A surface that structurally expects:

1. **Operator-mediated answers.** When community members post questions, they expect the repo maintainer to respond with technical answers. The "did this answer your question?" affordance creates an explicit attention-debt the operator must honor.
2. **Accepted-answer marking.** Each question expects the operator (or community member) to mark a winning answer. Daemon-side answers lack the trust signal required for a marked-answer to mean anything.
3. **Community moderation.** Off-topic posts, spam, and bad-faith engagement need moderator action. The single_user axiom forbids daemon-side authority over multi-user community state.

Issues vs Discussions: **Issues are kept enabled** because they're bug-reports / feature-requests with a triage workflow that fits operator's actual review cadence. Discussions are open-ended community Q&A with no triage shape. The Hapax repos use Issues for actionable items and refuse Discussions to avoid the operator-Q&A debt.

## Cross-platform alternatives

For long-form Q&A about Hapax that doesn't require enabling Discussions:

- **Operator's weblog** (`hapax.weblog.lol`) — author-controlled FAQs / explainers. FULL_AUTO via `omg-lol-weblog-bearer-fanout`.
- **README + docs/ in the repo** — canonical project documentation; community references rather than asks-and-answers.
- **Issues with question template** — channels actual user questions through the bug-tracker triage cadence the operator already maintains.

## Re-evaluation triggers

This refusal stands as long as GitHub Discussions remains a Q&A-shaped product. If GitHub ships a "machine-author broadcast" tier where maintainers can post FAQ-style content with explicit "no operator-attention expected" framing, that surface might warrant fresh evaluation — but as of 2026-05-03 no such tier exists.

## Cross-references

- Sibling refusal: `discord-webhook` (similar multi-user community moderation logic)
- Sibling refusal: `reddit-account` (similar Q&A community engagement logic)
- Refused publisher class: `agents.publication_bus.publisher_kit.refused.GitHubDiscussionsRefusedPublisher`
- Originating cc-task: `leverage-REFUSED-github-discussions-enabled` (closed)
- Cross-surface alternatives: omg-lol weblog, repo-internal docs, Issues with question template.

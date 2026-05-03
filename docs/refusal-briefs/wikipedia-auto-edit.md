# Refusal Brief — Wikipedia Automated Editing

**Slug:** `leverage-REFUSED-wikipedia-auto-edit`
**Status:** REFUSED — no Wikipedia bot account, no scaffolded Wikipedia editor module.
**Surface:** `wikipedia-auto-edit`
**Date:** 2026-04-26 (PR #1570 cc-task-level), 2026-05-03 (this brief — first-class graph citizen)
**Axiom tag:** `single_user` + ToS-violation gate
**Surface registry entry:** `wikipedia-auto-edit` (REFUSED)
**Provenance:** PR #1570 declared the cc-task-level refusal; this brief + REFUSED-tier publisher subclass make it a first-class publication-bus graph citizen.

## What was refused

Any daemon-side mechanism for editing Wikipedia. This includes adding citations, updating article content, creating new articles, or making any modifications to Wikipedia's content via the MediaWiki API or any other automation surface.

## Why Wikipedia auto-edit is REFUSED — double constitutional barrier

This surface fails *two* independent constitutional checks; either alone would be sufficient.

### Barrier 1: ToS forbids unflagged automated editing

Wikipedia's bot policy ([WP:BOTPOL](https://en.wikipedia.org/wiki/Wikipedia:Bot_policy)) explicitly requires:

1. Bot accounts must register and be marked as bots in user-account flags.
2. Each bot must seek approval from the Bot Approvals Group (BAG) for each task.
3. Approved bots are subject to ongoing community oversight; admins can block bots that violate consensus.
4. Unflagged automated editing from a regular account is prohibited and subject to administrative action.

Even a *flagged* approved bot is structurally accountable to community oversight that contradicts daemon-tractable "post and walk away" operation.

### Barrier 2: Multi-editor platform violates single_user

Wikipedia's product model is **community-mediated authority**. Every article is the result of negotiation among multiple editors; no single account "owns" any article. The Hapax constitutional `single_user` axiom defines the operator as the sole authority over Hapax's outputs — but a Wikipedia article *cannot* be sole-authority-owned by design. Editing Wikipedia means agreeing to enter a multi-editor authority relationship that the axiom forbids in daemon mode.

## Cross-platform alternatives

For long-form factual writing without entering Wikipedia's multi-editor authority:

- **Operator's weblog** (`hapax.weblog.lol`) — author-controlled long-form. FULL_AUTO.
- **Zenodo deposit** — citable academic-style artifacts. FULL_AUTO via `zenodo-refusal-deposit` shape (or other Zenodo deposits for non-refusal-shaped work).
- **CITATION.cff in repos** — for citing Hapax's own software.
- **DataCite Commons mirror** — operator's authored-works graph (citation-graph-only, no Wikipedia article needed).

## Re-evaluation triggers

This refusal stands permanently absent two independent changes:

1. Wikipedia changes its ToS to permit unflagged automated editing (extremely unlikely; the ToS protects the multi-editor authority model).
2. The Hapax constitutional `single_user` axiom changes to permit multi-user authority relationships (would fundamentally redefine the project).

Either is a constitutional-amendment-level event, not a routine policy review.

## Cross-references

- Sibling refusal (multi-user authority): `reddit-account`, `linkedin-account`, `discord-webhook`
- Sibling refusal (ToS-forbidden): `discogs-submission` (ToS forbids automated submission)
- Refused publisher class: `agents.publication_bus.publisher_kit.refused.WikipediaAutoEditRefusedPublisher`
- Originating cc-task: `leverage-REFUSED-wikipedia-auto-edit` (closed)
- Cross-surface alternatives: omg-lol weblog, Zenodo deposits, CITATION.cff, DataCite Commons mirror.

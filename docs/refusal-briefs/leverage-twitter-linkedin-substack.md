# Refusal Brief: Twitter / LinkedIn / Substack as Marketing Surfaces

**Slug:** `leverage-REFUSED-twitter-linkedin-substack-accounts`
**Axiom tag:** `feedback_full_automation_or_no_engagement`
**Refusal classification:** Operator-mediated relationship surface — not daemon-tractable
**Status:** REFUSED — no accounts, no automated posting, no `agents/social_media/{twitter,linkedin,substack}.py`.
**Date:** 2026-04-26
**Related cc-task:** `leverage-REFUSED-twitter-linkedin-substack-accounts`
**CI guard:** `tests/test_forbidden_social_media_imports.py`

## What was refused

Direct presence on, automated posting to, or daemon-side engagement
with:

- **Twitter / X** — accounts, automated posting, reply-thread
  management
- **LinkedIn** — accounts, connection-graph mediation, automated
  posting, comment management
- **Substack** — newsletter publishing, subscriber-list management,
  paid-tier comms, churn-response handling

## Why this is refused

Per `feedback_full_automation_or_no_engagement` (operator
constitutional directive 2026-04-25T16:55Z): the operator refuses
all research / marketing surfaces that are not fully Hapax-automated.

Each of these three surfaces requires sustained operator-mediated
engagement that no daemon can reach:

- **Twitter/X**: reply threads imply ongoing conversational
  engagement; @-mentions land in operator's inbox awaiting response;
  thread-mute / thread-watch state is a relationship choice
- **LinkedIn**: each connection request is a relationship choice —
  not a content publication; comment threads on posts require
  per-comment engagement decisions
- **Substack**: subscriber-relationship management (welcome emails,
  paid-tier unsubscribe responses, refund-request handling) is
  human-mediated by design

## Daemon-tractable boundary

Hapax's authorized social fan-out path is **Bridgy POSSE from
omg.lol weblog** — POSSE = Publish (on your) Own Site, Syndicate
Elsewhere. The pattern:

1. Publication lands on `hapax.weblog.lol` (omg.lol weblog)
2. `BridgyPublisher` (`agents/publication_bus/bridgy_publisher.py`)
   sends a webmention to `brid.gy/publish/webmention`
3. Bridgy fans out to operator's Mastodon and Bluesky accounts
4. Replies on Mastodon / Bluesky come back as webmentions to the
   omg.lol weblog incoming archive (read-only; no reply-side
   engagement)

Mastodon and Bluesky reach is sufficient for the philosophy-of-tech
audience vector. Coverage gaps (e.g., specific Twitter-only research
threads) are tracked by `agents/marketing/bridgy_audit.py` and
surface in the audit report's "refusal candidate" rows.

## CI guard

`tests/test_forbidden_social_media_imports.py` scans `agents/`,
`shared/`, `scripts/`, and `logos/` for any import of:

- `tweepy` (Twitter API client)
- `linkedin_api` / `linkedin-api` (LinkedIn API clients)
- `substackapi` / `substack-api` (Substack API clients)

CI fails on any match. The guard's self-tests verify both the
positive (clean codebase) and negative (planted-import detection)
paths.

## Lift conditions

This is a constitutional refusal. Lift requires removal of
`feedback_full_automation_or_no_engagement` from MEMORY.md. Probe
path: `~/.claude/projects/-home-hapax-projects/memory/MEMORY.md`.
Lift keyword: absence of the
`feedback_full_automation_or_no_engagement` entry.

The `refused-lifecycle-constitutional-watcher` daemon (when shipped)
will check this probe per its cadence policy.

## Cross-references

- cc-task vault note: `leverage-REFUSED-twitter-linkedin-substack-accounts.md`
- CI guard: `tests/test_forbidden_social_media_imports.py`
- Bridgy POSSE alternative: `agents/publication_bus/bridgy_publisher.py`
- Coverage audit: `agents/marketing/bridgy_audit.py`
- Source research: drop-leverage strategy
  (`docs/research/2026-04-25-leverage-strategy.md`)

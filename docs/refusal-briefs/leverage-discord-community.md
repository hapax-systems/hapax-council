# Refusal Brief: Discord Community + Slack/Discord DM Bots

**Slug:** `leverage-REFUSED-discord-community`
**Axiom tag:** `single_user`, `feedback_full_automation_or_no_engagement`
**Refusal classification:** Multi-user platform — violates single-operator axiom
**Status:** REFUSED — no Discord server, no webhook bot, no `agents/social_media/discord.py`.
**Surface registry entry:** `discord-webhook` (REFUSED)
**Date:** 2026-04-26 (amended 2026-05-01)
**Related cc-tasks:**
  - `leverage-REFUSED-discord-community`
  - `awareness-refused-slack-discord-dm-bots` (precedent)
  - `discord-public-event-activation-or-retire` (2026-05-01 retirement of the
    pre-existing `agents/cross_surface/discord_webhook.py` cross-surface poster
    that pre-dated this brief)
**CI guard:** `tests/test_forbidden_social_media_imports.py`,
`tests/systemd/test_discord_webhook_decommission.py`

## 2026-05-01 amendment — pre-existing webhook agent retired

When this brief was first ratified (2026-04-26), there was already an active
``agents/cross_surface/discord_webhook.py`` daemon module + companion
``hapax-discord-webhook.service`` systemd unit + ``discord-webhook`` allowlist
contract + a publication-bus surface_registry entry at ``FULL_AUTO`` tier. The
daemon was never given a webhook URL (operator never bootstrapped
``HAPAX_DISCORD_WEBHOOK_URL``) so it sat ``linked / inactive``, but the surface
remained a live claim — contradicting this brief's "no webhook bot" status.

The 2026-05-01 retirement (cc-task
``discord-public-event-activation-or-retire``, PR forthcoming) closes that
drift:

- The ``hapax-discord-webhook.service`` unit was removed from
  ``systemd/units/`` and added to the install-units ``DECOMMISSIONED_UNITS``
  list (alongside the prior tauri-logos and tabbyapi-hermes8b retirements).
- ``discord-webhook`` was moved from ``FULL_AUTO`` → ``REFUSED`` in
  ``agents/publication_bus/surface_registry.py`` with ``refusal_link``
  pointing at this brief.
- The ``discord-webhook`` allowlist contract was annotated as
  ``automation_status: REFUSED`` with ``rate_limit: 0/0``.
- The ``agents/cross_surface/discord_webhook.py`` module was annotated with a
  retirement docstring listing the lift sequence; the implementation is
  retained as legacy reference but no longer reachable from runtime fanout
  (the orchestrator dispatch registry filters out REFUSED surfaces).
- The ``agents/cross_surface/__main__.py`` entrypoint was changed to print a
  refusal message and ``sys.exit(2)`` so manual invocation cannot accidentally
  restart the retired daemon.

## What was refused

Direct presence on, automated posting to, or daemon-side engagement
with:

- **Discord** — server creation, channel moderation, webhook bots,
  any flavor of `discord.py` / `discord_py` client adoption
- **Slack** — workspace presence, webhook bots, DM-bot deployments
  (`slack_sdk` and adjacent clients)

## Why this is refused

### Single-operator axiom (constitutional)

Discord and Slack are inherently multi-user platforms: messages
arrive from many parties, moderation calls are per-message decisions,
banhammer choices are per-user. The single-operator axiom precludes
operator-mediated community moderation; there is no daemon-tractable
moderation policy that operates without operator-physical
intervention.

### Full-automation envelope

Per `feedback_full_automation_or_no_engagement` (operator
constitutional directive 2026-04-25T16:55Z): the operator refuses
research / marketing surfaces not fully Hapax-automated. Even a
"webhook-only" Discord bot becomes a relationship surface the moment
users @-mention it expecting a response.

### DM-bot anti-pattern

Per `awareness-refused-slack-discord-dm-bots`: direct DM bots also
violate the consent gate (no consent contract for non-operator
parties to receive DMs). Both inbound (other users → bot) and
outbound (bot → other users) DM flows are refused.

## Daemon-tractable boundary

Hapax's authorized social fan-out remains **Bridgy POSSE from
omg.lol weblog** → Mastodon + Bluesky. ActivityPub / ATProto are
public-feed surfaces (no DM-style per-user state) so they sit cleanly
within the constitutional envelope.

If a community discussion forum is genuinely needed in future:

- **Acceptable**: a Hapax-hosted comment-thread surface where
  operator-side moderation is daemon-tractable (auto-classify,
  auto-publish to refusal-brief log when blocked)
- **Not acceptable**: any platform where moderation requires
  per-message operator decisions in a third-party UI

## CI guard

`tests/test_forbidden_social_media_imports.py` scans `agents/`,
`shared/`, `scripts/`, and `logos/` for any import of:

- `discord` / `discord_py` / `discord.py` (Discord API clients)
- `slack_sdk` / `slack-sdk` (Slack API client)

CI fails on any match.

## Lift conditions

This is a constitutional refusal grounded in the single-operator
axiom + full-automation directive. Lift requires either:

- **Single-operator axiom retirement** (not currently planned;
  axiom precedent change required)
- **Full-automation envelope removal** (probe path:
  `~/.claude/projects/-home-hapax-projects/memory/MEMORY.md`; lift
  keyword: absence of `feedback_full_automation_or_no_engagement`)

The `refused-lifecycle-constitutional-watcher` daemon (when shipped)
will check both probes per its cadence policy.

## Cross-references

- cc-task vault note: `leverage-REFUSED-discord-community.md`
- Precedent cc-task: `awareness-refused-slack-discord-dm-bots.md`
- CI guard: `tests/test_forbidden_social_media_imports.py`
- Bridgy POSSE alternative: `agents/publication_bus/bridgy_publisher.py`
- Source research: drop-leverage strategy
  (`docs/research/2026-04-25-leverage-strategy.md`)

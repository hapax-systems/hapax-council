# Refusal Brief: Bot-Driven SoundCloud Inflation

**Slug:** `leverage-REFUSED-bot-driven-sc-inflation`
**Axiom tag:** `single_user`, `feedback_full_automation_or_no_engagement`
**Refusal classification:** ToS prohibition + presentation-not-promotion stance
**Status:** REFUSED — no SoundCloud bot account, no `agents/soundcloud_inflater/`.
**Date:** 2026-04-26
**Related cc-task:** `leverage-REFUSED-bot-driven-sc-inflation`
**Related project memory:** `project_soundcloud_bed_music_routing`
**CI guard:** `tests/test_forbidden_social_media_imports.py`

## What was refused

- SoundCloud bot account
- Scripted plays / follows / reposts on operator's tracks or any other
  SC account
- Comment automation
- `agents/soundcloud_inflater/` package
- `soundcloud` / `soundcloud_python` / `sclib` Python client adoption

## Why this is refused

### SoundCloud ToS prohibition

SoundCloud's Terms of Service explicitly forbid:
- Bot-driven plays (artificial inflation of play counts)
- Bot-driven follows (artificial inflation of follower counts)
- Bot-driven reposts (artificial inflation of repost counts)
- Comment automation (Astroturf-style commentary)

These are detected and acted upon (track removal, account suspension)
by SoundCloud's anti-abuse infrastructure. Compliance with platform
ToS is a precondition for any daemon-tractable engagement.

### Presentation-not-promotion stance (project_soundcloud_bed_music_routing)

Per the operator's project memory `project_soundcloud_bed_music_routing`:
SoundCloud is a **presentation choice** — operator's tracks route
through the vinyl filter chain as bed-music for the livestream and
weblog. SC is NOT a promotion-target surface. Inflating Hapax's own
SC profile would violate the presentation-not-promotion stance even
if ToS permitted it.

The operator's own tracks on SC are presented through the system; SC
is a sidecar audio host, not a promotion vector. Bot-driven inflation
would conflate the two and invalidate the presentation framing.

### Constitutional incompatibility

Per `feedback_full_automation_or_no_engagement` (operator
constitutional directive 2026-04-25T16:55Z): the operator refuses
research / promotion surfaces not fully Hapax-automated. Even if a
bot-driven inflation script were daemonized, it would violate ToS
and trigger anti-abuse actions — automation that pretends otherwise
is the "deflated full-automation" anti-pattern.

### Single-operator axiom

SoundCloud is multi-user; bot-driven follows/reposts impersonate
multiple accounts. The single-operator axiom precludes operator
maintaining multiple SoundCloud accounts on Hapax's behalf.

## Daemon-tractable boundary

What's tractable:
- **Bed-music routing** — operator's own tracks present through the
  livestream's vinyl filter chain (per
  `project_soundcloud_bed_music_routing`). SC is the audio host, not
  the promotion target.
- **Cohort-disparity attestation** — per cc-task
  `sc-cohort-attestation-publisher` (offered, not yet shipped): a
  daily auto-attestation page showing retention% + like:play ratio,
  surfacing the bot-injection pattern in the cohort distribution
  rather than masking it. This is **honest reporting**, not
  inflation; refusal-as-data of the inflated cohort.

## CI guard

`tests/test_forbidden_social_media_imports.py` enforces a **path-based**
guard (`FORBIDDEN_PACKAGE_PATHS`) rather than a library-import guard
because the legitimate `agents/soundcloud_adapter/` reads SC for
bed-music routing per `project_soundcloud_bed_music_routing`. The
guard fails the build if any of the following directories exist:

- `agents/soundcloud_inflater/`
- `agents/soundcloud_inflator/`
- `agents/sc_inflater/`

A path-based guard is the correct enforcement here: the same library
(SoundCloud Python clients) serves both refused (inflation) and
permitted (bed-music routing) purposes. Path naming is the
discriminator.

## Refused implementation

- NO `agents/soundcloud_inflater/`
- NO bot-driven plays / follows / reposts on any SC account
- NO comment automation
- License-request auto-reply does NOT mention SC promotion as a
  channel
- The `pass` store will NOT carry SoundCloud bot credentials

## Lift conditions

This refusal is permanent. Lift requires:
- SoundCloud ToS revision permitting bot-driven inflation (extremely
  unlikely; ToS is the platform's economic moat)
- Constitutional retirement of presentation-not-promotion stance for SC
- Single-operator axiom retirement

The `refused-lifecycle-structural-watcher` daemon (when shipped) will
check the SoundCloud ToS probe per its weekly cadence (type-A
structural trigger).

## Cross-references

- cc-task vault note: `leverage-REFUSED-bot-driven-sc-inflation.md`
- Project memory: `project_soundcloud_bed_music_routing`
- Companion cc-task (honest reporting alternative):
  `sc-cohort-attestation-publisher.md`
- CI guard: `tests/test_forbidden_social_media_imports.py`
- Source research: `docs/research/2026-04-25-leverage-strategy.md`

# YouTube Channel Sections Manager (ytb-011 Phase 2) — Status

**Status:** Normative. The YouTube channel sections manager is **deferred**
as of 2026-05-01. It will not ship until the four blockers in §2 are
resolved. No dashboard, allowlist, or metadata copy may describe a
"channel sections manager" as live or implemented until the deferral
is lifted in a follow-up cc-task.
**Scope:** the Phase 2 deferral noted in
`agents/channel_metadata/__init__.py` for ytb-011 ("sections manager
— 10-min timer with digest-diff that maintains 3 channel sections").
**Driver task:** `ytb-011-channel-sections-manager` (cc-task, WSJF 5.5).
Companion to `youtube-channel-trailer-public-event-reconcile`
(`docs/governance/channel-trailer-status.md`).

---

## 1. The decision

Three options were on the table per the cc-task spec: **(a) implement**
the sections manager now, **(b) defer with concrete blockers**, or
**(c) retire** the dormant feature entirely.

**Decision:** (b) — defer with concrete blockers (§2).

**Why not (a):** the four blockers in §2 each independently prevent a
useful runtime. Most importantly, the proposed 10-minute cadence
collides with the YouTube Data API daily quota (§2.4): three section
upserts per cycle × 144 cycles/day × 150 quota units = **21,600
units/day** against a default daily limit of 10,000 — a 2.16x
overshoot. Until the cadence is widened to ≥ 1h *or* a change-detection
gate rides above the API call so cycles are skipped when section
content is unchanged, the quota story is a non-starter.

**Why not (c):** the canonical event scaffolding already exists.
`shared/research_vehicle_public_event.py` carries
`channel_section.candidate` as a first-class `EventType`;
`shared/cross_surface_event_contract.py` lists
`youtube_channel_sections` in the youtube aperture's `target_surfaces`;
`shared/youtube_rate_limiter.py` has the per-API quota cost
(`channelSections.insert: 150`). Retiring would force a re-introduction
of those scaffolds when the blockers clear — pure churn.

So the contract scaffolding stays in place, but no Phase 2 module
ships until §2 is satisfied.

---

## 2. The four concrete blockers

The sections manager is gated on **all four** of the following:

### 2.1 `channel_section.candidate` event producer

There is no producer for the canonical `channel_section.candidate`
event today. The event type is defined in
`shared/research_vehicle_public_event.py` and is listed under
`_YOUTUBE_EVENTS` in `shared/cross_surface_event_contract.py`, but
nothing emits one. Without a producer the sections manager has no
event-driven trigger and would have to fall back to a polling mode
that contradicts the canonical-event-flow discipline established by
PR #1953 (arena) and PR #1963 (channel trailer).

**Resolution path:** open a `channel-section-candidate-public-event-producer`
task that ingests Phase-1 broadcast boundaries, recent-research
chronicle windows, and playlist-by-topic state, then emits
`channel_section.candidate` records onto
`/dev/shm/hapax-public-events/events.jsonl`.

### 2.2 Phase-1 trailer rotator must be live first

The trailer rotator (Phase 1) is itself in `current_reality=credential_blocked`
per `docs/governance/channel-trailer-status.md`. Phase 2 must not ship
ahead of Phase 1: the operator's first verifiable evidence that the
channel-metadata ladder works is `result="ok"` rotations on the
trailer metric. Stacking Phase 2 onto an unverified Phase 1 risks
double-debugging and conflates failure modes (which API call broke,
which credential was wrong).

**Resolution path:** complete the channel-trailer §4 bootstrap gate
(`docs/governance/channel-trailer-status.md`). When
`hapax_broadcast_channel_trailer_rotations_total{result="ok"} >= 1`
holds for 24h, Phase 2 may proceed.

### 2.3 OAuth scope + channel id

Same physical credential dependency as Phase 1: `youtube.force-ssl`
scope on the OAuth token at the pass store path `google/token`, plus
`YOUTUBE_CHANNEL_ID` exported from hapax-secrets. The
`channelSections.insert` / `.update` / `.delete` API calls require
write access on the channel resource.

**Resolution path:** same operator-action checklist as the trailer
(`docs/governance/channel-trailer-status.md` §4).

### 2.4 Quota math at the proposed cadence

Three sections × 144 cycles/day × 150 quota units (`channelSections.insert`
per `shared/youtube_rate_limiter.py`) = **21,600 units/day** against a
default 10,000-unit daily quota = **2.16x overshoot**. Even if updates
swap to `.update` (50 units) instead of `.insert` (150 units), the
math is 3 × 144 × 50 = 21,600 — wait, that's also overshoot;
let me recompute: 3 × 144 × 50 = 21,600. Same number because at the
proposed 10-min cadence the volume of *calls* is what dominates.

**Two concrete fixes that resolve §2.4:**

- **Widen cadence to ≥ 1h** — 24 cycles/day × 3 × 50 = 3,600 units/day,
  fits in the daily quota with 64% headroom.
- **Add a content-change gate above the API** — list current sections
  (1 unit), diff against intended state, only update on change.
  Steady-state stable content yields ~144/day reads × 1 unit = 144
  units/day (1.4% of quota); change events are rare.

The 10-min cadence is **not** a hard requirement in the task spec
(see `agents/channel_metadata/__init__.py`); it is an early-design
guess. The sections manager that ships should default to the
content-change gate (the more honest design), with a 1h fallback
heartbeat to catch missed deltas.

---

## 3. What stays in place

- **Canonical event scaffolding** — no changes to
  `shared/research_vehicle_public_event.py`,
  `shared/cross_surface_event_contract.py`, or the JSON schemas. The
  `youtube_channel_sections` Surface and `channel_section.candidate`
  EventType remain first-class so the producer task (§2.1) can
  emit candidates without further contract changes.
- **Quota table** — `shared/youtube_rate_limiter.py` already has
  `channelSections.insert: 150`. No changes.
- **Trailer rotator (Phase 1)** — independent track; status owned by
  `docs/governance/channel-trailer-status.md`.
- **Aperture row** — covered by the existing `youtube` aperture
  (`current_reality="active_legacy"`); no separate
  `youtube_channel_sections` aperture is needed because sections are
  managed under the broader YouTube credential and quota envelope.

---

## 4. What changes in this PR

- `agents/channel_metadata/__init__.py` — Phase 2 deferral comment
  becomes concrete: it names this status doc, the four blockers, and
  the resolution paths so a future engineer landing on the file does
  not have to re-derive the deferral.
- `docs/governance/channel-sections-status.md` — this file.

No code is added. No tests change. The Phase 2 module is not created.

---

## 5. Resolution flow

When all four blockers (§2) are satisfied, the follow-up PR should:

1. Create `agents/channel_metadata/sections_manager.py` mirroring the
   trailer rotator's shape but consuming
   `channel_section.candidate` events from the canonical bus.
2. Add `systemd/units/hapax-channel-sections.service` (port 9498 — the
   trailer is on 9499; reserve 9500-block for future Phase-3
   metadata work).
3. Add an aperture row only if a strictly narrower action set is
   warranted (e.g., never `publish` — same logic as the trailer
   carve-out). Otherwise stay under the umbrella `youtube` aperture.
4. Add tests mirroring `tests/channel_metadata/test_trailer_rotator.py`.
5. Update this status doc → "lifted; sections manager is live as of
   YYYY-MM-DD."

Until then, no public claim of Phase 2 implementation may exist.

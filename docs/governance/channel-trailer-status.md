# YouTube Channel Trailer — Reconcile Status

**Status:** Normative. The YouTube channel trailer rotator is **kept** but
**not-live** as of 2026-05-01. Its public-event aperture row is recorded
with `current_reality=credential_blocked` in
`shared/cross_surface_event_contract.py`. No dashboard, allowlist, or
metadata copy may describe the trailer rotator as live until the
runtime evidence in §4 exists.
**Scope:** `agents/channel_metadata/trailer_rotator.py` + the systemd
unit `hapax-channel-trailer.service` + the publication allowlist
`axioms/contracts/publication/channel-trailer.yaml` + the
cross-surface aperture
`shared/cross_surface_event_contract.py::aperture_id="youtube_channel_trailer"`.
**Driver task:** `youtube-channel-trailer-public-event-reconcile` (cc-task,
WSJF 6.0). **Reconcile audit:**
`Personal/20-projects/hapax-research/audits/2026-04-29-public-event-contract-source-reconcile.md`.

---

## 1. The decision

Three options were on the table per the cc-task spec: **(a) keep** the
implemented trailer rotator as a YouTube public surface, **(b) merge**
its semantics into the existing `youtube_channel_sections` adapter,
or **(c) retire** it and remove the surface from the public-event
model.

**Decision:** (a) — keep.

**Why:**

- The trailer rotator is 289 LOC of working code with 248 LOC of
  tests passing in main; retiring it would discard sunk
  implementation against a YouTube API surface (`channels.update
  brandingSettings.channel.unsubscribedTrailer`) that has no
  equivalent under `channelSections.update`. Merging into
  `youtube_channel_sections` would lose the per-VOD-boundary cadence
  that the trailer specifically wants (every rotation re-points the
  trailer at the freshest broadcast).
- The trailer has a **strictly narrower action set than the rest of
  YouTube**: link/embed only — never `publish`. The rotator does not
  create new content; it re-points an existing channel attribute at
  an already-published broadcast URL. Folding it under the broader
  `youtube` aperture would inadvertently grant `publish`.
- The unit was never disabled by operator action. The audit found it
  "linked but inactive" — the inactive state is downstream of missing
  credentials and missing `YOUTUBE_CHANNEL_ID`, not a deliberate
  retirement.

So the trailer aperture stays in the contract, but its
`current_reality` is `credential_blocked` and its `allowed_actions`
are restricted to `("link", "embed", "redact", "hold")`. The rotator
remains source-of-truth for trailer cadence + cursor management.

---

## 2. The aperture row

`shared/cross_surface_event_contract.py` now contains:

```python
CrossSurfaceApertureContract(
    aperture_id="youtube_channel_trailer",
    display_name="YouTube Channel Trailer",
    target_surfaces=("youtube_channel_trailer",),
    allowed_event_types=("broadcast.boundary",),
    allowed_actions=("link", "embed", "redact", "hold"),
    current_reality="credential_blocked",
    publication_contract="channel-trailer",
    child_task="youtube-channel-trailer-public-event-reconcile",
    health_owner="youtube-channel-trailer-public-event-reconcile",
    requires_one_reference=("public_url",),
)
```

`youtube_channel_trailer` was added to the `Surface` literal in
`shared/research_vehicle_public_event.py` so events may declare
trailer-targeted surface policies without bypassing the schema.

`broadcast.boundary` is the only canonical event type the trailer
consumes — the rotator turns each rotation event into a
`channels.update` call. The legacy `broadcast_rotated` JSONL input is
kept as the runtime tail for now (the canonical
`ResearchVehiclePublicEvent` migration is a follow-up — see §5).

---

## 3. Cursor / idempotency / quota / metrics owners

| Owner               | Path / Identifier                                           |
|---------------------|-------------------------------------------------------------|
| Cursor              | `~/.cache/hapax/channel-trailer-cursor.txt` (byte offset)   |
| Idempotency         | One trailer update per `broadcast_rotated` event; the cursor itself is the dedup mechanism (no separate event-id ledger because the trailer is monotonically replacing — re-applying the same rotation is a no-op against YouTube). |
| Quota owner         | `channels.update part=brandingSettings` ≈ 50 units / call  |
| Rate-limit contract | `axioms/contracts/publication/channel-trailer.yaml` (2/hour, 6/day) |
| Metrics             | `hapax_broadcast_channel_trailer_rotations_total{result}` on `127.0.0.1:9499` |

The rotator increments `result="error"` on quota / network /
disabled-client failures and never raises; the next event retries on
its own cadence.

---

## 4. What "live" requires (operator action)

The trailer flips from `credential_blocked` → `active_legacy` only
when **all** of the following exist:

1. **OAuth token with `youtube.force-ssl` scope** in the pass store at
   `google/token` (read by `shared/google_auth.py`).
2. **`YOUTUBE_CHANNEL_ID`** exported from hapax-secrets — without it
   the rotator logs `no_channel_id` per event and skips the API call.
3. **Quota headroom** ≥ 50 units against the daily YouTube Data API
   quota.
4. **Allowlist passes** — the publication allowlist
   (`channel-trailer.yaml`) gates each call; default DENY paths fire
   `denied` rather than `ok`.
5. **At least one successful `ok` rotation** logged in
   `hapax_broadcast_channel_trailer_rotations_total{result="ok"} >= 1`
   within the last 24h. Until then, no copy may say the trailer is
   live.

When the operator completes the bootstrap, flip the aperture's
`current_reality` to `active_legacy` (matching the rest of YouTube)
in a follow-up PR. **Do not** flip the reality field before
verifying `result="ok"` in the metric.

---

## 5. Deferred follow-up: canonical `ResearchVehiclePublicEvent` migration

The trailer rotator still tails the legacy `broadcast_rotated` JSONL
bus at `/dev/shm/hapax-broadcast/events.jsonl`. Migration to the
canonical `ResearchVehiclePublicEvent` flow at
`/dev/shm/hapax-public-events/events.jsonl` (the same migration the
arena/mastodon adapters received) is **deferred** because:

- The trailer is not yet live, so there is no production cursor to
  cut over.
- The legacy bus is still the only place `broadcast_rotated` events
  are emitted today; the canonical
  `broadcast_boundary_public_event_producer` exists but its consumers
  are still in motion.
- The migration is mechanical once the trailer is bootstrapped — the
  arena migration (PR #1953) is the template.

**Track:** when the operator bootstraps credentials and the trailer
goes live on the legacy bus, open a follow-up PR to migrate to the
canonical bus, mirroring `agents/cross_surface/mastodon_post.py` /
`agents/cross_surface/arena_post.py`. Until then the legacy tail
remains correct and untouched.

---

## 6. Public-claim invariant

**No dashboard, status surface, allowlist row, or metadata copy may
describe the channel trailer rotator as live unless §4's gate has
fired.** This invariant is enforced at three layers:

- **Contract** — `current_reality=credential_blocked` blocks
  `decide_cross_surface_fanout(event, "youtube_channel_trailer", "publish")`
  from resolving to `allow` (the action isn't even allowed; even if
  it were, the reality gate catches it).
- **Allowlist** — `axioms/contracts/publication/channel-trailer.yaml`
  has the operator-legal-name redaction and the 2/hour, 6/day
  rate-limit; both pre-clear any live API call.
- **Unit** — `Description=` in `hapax-channel-trailer.service`
  explicitly carries the `NOT-LIVE — credential_blocked` marker so
  any operator looking at `systemctl --user status` sees the gate
  immediately.

Companion to the aperture-reality discipline established by the
`consent-safe gate retirement` doc and the `arena-post-canonical-migration`
PR (#1953): public surfaces declare their reality first, ship code
second.

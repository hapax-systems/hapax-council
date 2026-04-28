# Spectacle Control Plane - Design Spec

**Status:** schema seed for `spectacle-control-plane`
**Task:** `/home/hapax/Documents/Personal/20-projects/hapax-cc-tasks/active/spectacle-control-plane.md`
**Date:** 2026-04-28
**Scope:** `SpectacleLaneState` schema, lane/verb contract, transition rules, conflict
resolution, initial lane map, and adapter split.
**Non-scope:** production adapters, director loop implementation, programme planner
implementation, compositor layout changes, YouTube writes, or public fanout writes.

## Purpose

The livestream is a research vehicle suitcase. A substrate registry tells the
system which carriers exist and what they can truthfully claim. The spectacle
control plane tells director and programme logic how those carriers may be
composed as lanes.

This contract sits above HOMAGE, Reverie, Re-Splay, captions, metadata,
overlays, private controls, and public apertures. It does not replace those
systems. It gives them a shared state shape and a shared verb vocabulary so the
stream can be multi-spectacle, multi-faceted, imbricated, and dynamic without
each surface inventing control semantics.

Until a lane has mounted state, renderability evidence, risk posture, fallback
behavior, and public-claim allowance, director and programme surfaces may only
show it as private, dry-run, blocked, or unavailable. They must not imply live
control over it.

## Inputs Consumed

- `/home/hapax/Documents/Personal/20-projects/hapax-research/specs/2026-04-28-livestream-research-vehicle-suitcase-parent-spec.md`
- `/home/hapax/Documents/Personal/20-projects/hapax-research/plans/2026-04-28-livestream-suitcase-wsjf-workload.md`
- `/home/hapax/Documents/Personal/20-projects/hapax-research/plans/2026-04-28-livestream-research-vehicle-suitcase-addendum.md`
- `/home/hapax/Documents/Personal/20-projects/hapax-research/audits/2026-04-28-hapax-obsidian-lost-feature-comprehensive-scour.md`
- `/home/hapax/Documents/Personal/20-projects/hapax-research/audits/2026-04-28-livestream-substrate-spectacle-a-plus-audit.md`
- `docs/superpowers/specs/2026-04-28-livestream-substrate-registry-design.md`
- `schemas/livestream-content-substrate.schema.json`

## `SpectacleLaneState` Schema Seed

The machine-readable seed lives at:

- `schemas/spectacle-control-plane.schema.json`

Required fields:

| Field | Meaning |
|---|---|
| `schema_version` | Lane schema version. Initial value is `1`. |
| `lane_id` | Stable snake_case lane identity. |
| `display_name` | Operator-facing lane label. |
| `lane_kind` | Broad lane family for routing and conflict policy. |
| `content_substrate_refs` | Registry `substrate_id` values that back the lane. |
| `state` | Lane lifecycle state. |
| `mounted` | Whether the lane is currently attached to a producer/control path. |
| `renderable` | Whether the lane can produce viewer/operator-visible output now. |
| `renderability_evidence` | Owner, status reference, freshness reference, and evidence kind. |
| `claim_bearing` | Whether the lane can carry private, dry-run, public, archive, or monetary claims. |
| `rights_risk` | Rights risk tier. |
| `consent_risk` | Consent/privacy risk tier. |
| `monetization_risk` | Monetization risk tier. |
| `director_verbs` | Allowed control verbs after state/risk filtering. |
| `programme_hooks` | Programme hooks that may bias, schedule, or annotate the lane. |
| `fallback` | Fail-closed behavior when evidence or policy is missing. |
| `public_claim_allowed` | Whether public surfaces may claim the lane is live/available. |

Example lane:

```json
{
  "schema_version": 1,
  "lane_id": "chat_ambient",
  "display_name": "Chat ambient aggregate",
  "lane_kind": "ward",
  "content_substrate_refs": ["chat_ambient_aggregate", "chat_keyword_consumer"],
  "state": "dry-run",
  "mounted": false,
  "renderable": false,
  "renderability_evidence": {
    "owner": "chat-ambient-keyword-substrate-adapter",
    "status_ref": "chat_ambient.health.state",
    "freshness_ref": "chat_ambient.health.age_s",
    "evidence_kind": "health_signal"
  },
  "claim_bearing": "dry_run",
  "rights_risk": "none",
  "consent_risk": "medium",
  "monetization_risk": "low",
  "director_verbs": ["hold", "suppress", "mark_boundary"],
  "programme_hooks": ["chat_salience", "programme_boundary"],
  "fallback": {
    "mode": "dry_run_badge",
    "reason": "Aggregate-only chat ward is not mounted; raw author state is never exposed."
  },
  "public_claim_allowed": false
}
```

## Lifecycle States

`state` is one of:

| State | Meaning | Public/director rule |
|---|---|---|
| `unmounted` | No active producer or control path is attached. | No live control claim; only unavailable explanation. |
| `candidate` | A valid future lane exists but dependencies are missing. | May appear in planning only. |
| `dry-run` | The lane can simulate or describe itself without public output. | Director may hold/suppress/mark boundary as dry-run. |
| `private` | Operator-private or control-only lane. | No public-live claim. |
| `mounted` | Producer/control path exists and evidence is fresh enough for private control. | Public claims still need egress, rights, and risk permission. |
| `degraded` | Mounted but missing quality, freshness, or downstream evidence. | Only degraded claims; no intensify unless safe. |
| `public-live` | Fresh evidence proves public renderability and claim safety. | Public claims allowed within lane and substrate policy. |
| `blocked` | A risk, missing consent, missing rights, missing hardware, or kill switch blocks use. | Only suppress, hold, mark boundary, or no-op explanations. |

The default for an uncertain lane is `unmounted`, `candidate`, or `dry-run`, not
`public-live`.

## Director Verbs

The first verb set is:

| Verb | Contract |
|---|---|
| `foreground` | Make the lane the primary perceptual or narrative read. |
| `background` | Keep the lane present but subordinate. |
| `hold` | Preserve the lane state intentionally for a bounded reason. |
| `suppress` | Remove or mute lane output while keeping the decision auditable. |
| `transition` | Move the lane between states or composition roles. |
| `crossfade` | Blend from or to another lane without a hard cut. |
| `intensify` | Increase salience, density, motion, gain, or symbolic weight. |
| `stabilize` | Reduce churn, motion, density, or risk while preserving the lane. |
| `route_attention` | Direct director/programme attention toward or away from the lane. |
| `mark_boundary` | Emit an explicit programme, research, archive, or public-event boundary. |

Verbs are filtered by lifecycle state and risk. A blocked lane cannot be
foregrounded, crossfaded into public output, intensified, or publicly marked as
available. A private control lane cannot be exposed to public surfaces even when
it can route attention internally.

## Silence And Hold

Silence and stillness are directorial moves only when grounded in an explicit
lane state.

Valid examples:

- hold `music_listening`, suppress `autonomous_speech`, and background
  `research_ledger` during a listening programme
- stabilize `reverie_substrate` while an overlay or HOMAGE lane carries the
  primary read
- suppress `captions` when caption freshness or redaction evidence is stale
- mark a boundary when the programme changes even if no public fanout fires

Invalid examples:

- treating missing speech as director intent without a target lane and reason
- implying a caption, cuepoint, chat, Re-Splay, or public fanout lane is live
  because an upstream task exists
- foregrounding a candidate lane whose render target has no mounted evidence

## Transition And Conflict Policy

Lane transitions are monotonic toward more public exposure only when every
required proof is fresh:

1. The referenced `ContentSubstrate` row exists.
2. Producer and renderability evidence are fresh under their TTLs.
3. `LivestreamEgressState.public_claim_allowed` is true for public claims.
4. `BroadcastAudioSafety.audio_safe_for_broadcast.safe` is true for audible
   public or monetized claims.
5. Rights, consent, privacy, provenance, and monetization risk are not blocking.
6. The lane fallback is known and executable.

Conflict resolution is fail-closed:

| Priority | Policy |
|---:|---|
| 0 | Kill switches and safety blockers win over all spectacle verbs. |
| 1 | Consent/privacy blockers strip public verbs and route to suppress/no-op. |
| 2 | Rights/provenance/monetization blockers strip public and monetary claims. |
| 3 | Operator-private controls can steer internal state but cannot leak public output. |
| 4 | Programme primary/secondary lane pressure chooses among safe mounted lanes. |
| 5 | Aesthetic or ambient lanes fill remaining capacity without overriding truth. |

When two safe lanes compete for foreground, programme chooses the primary lane
and backgrounds or holds the other lane. When a safe lane and an unsafe lane
compete, the unsafe lane is suppressed or converted to a dry-run explanation.

Reverie has a special dual role. `reverie_substrate` is the normative visual
ground, not just another optional panel. `suppress` means dampen or quiet the
ground under a stronger lane; it does not stop the generative substrate unless a
separate kill switch requires that.

## Initial Lane Map

This map is a contract seed. It is not implementation truth.

| `lane_id` | Initial state | Key substrates | Notes |
|---|---|---|---|
| `research_ledger` | `dry-run` | `research_cards`, `programme_cuepoints` | Trace objectives, conditions, and research state without public overclaim. |
| `music_listening` | `private` | `music_provenance`, `lyrics_context`, `cbip_signal_density` | Listening can hold speech and foreground music only with provenance/risk truth. |
| `studio_work` | `mounted` | `terminal_tiles`, `hls_archive` | Private by default; public tile rendering requires redaction policy. |
| `homage_ward_system` | `degraded` | `homage_ward_system`, `ward_contrast` | Needs rehearsal and legibility evidence before public-live claims. |
| `gem_mural` | `candidate` | `geal_overlay` | GEM expression should be system expression, not transcript impersonation. |
| `geal_overlay` | `candidate` | `geal_overlay` | Needs event feed, frame budget, health signal, and unavailable explanation. |
| `chat_ambient` | `dry-run` | `chat_ambient_aggregate`, `chat_keyword_consumer` | Aggregate-only; no author persistence or raw handle display. |
| `chat_keyword_ward` | `candidate` | `chat_keyword_consumer` | Research-only until mounted with aggregate privacy policy. |
| `youtube_slots` | `candidate` | `youtube_metadata`, `youtube_player`, `youtube_channel_sections` | Public claims require public-event and quota authority. |
| `publication_fanout` | `candidate` | `omg_statuslog`, `omg_weblog`, `publication_rss`, `mastodon_fanout` | Event-driven, rate-limited, dry-run explainable. |
| `reverie_substrate` | `mounted` | `local_visual_pool`, `cdn_assets` | Normative visual ground; public media still needs rights/provenance truth. |
| `health_egress_status` | `mounted` | `hls_archive`, `broadcast_provenance_manifest` | Status lane reports resolver evidence; it does not invent liveness. |
| `re_splay` | `blocked` | `re_splay_m8`, `re_splay_polyend`, `re_splay_steam_deck` | No mounted-lane claim until hardware smoke and capture policy exist. |
| `captions` | `candidate` | `caption_in_band` | Dormant/private/dry-run until bridge, freshness, redaction, and egress evidence. |
| `metadata` | `candidate` | `youtube_metadata`, `programme_cuepoints`, `chapter_markers` | Research ledger copy consumes public events, not arbitrary files. |
| `cbip` | `candidate` | `cbip_signal_density`, `music_provenance` | Music state lane depends on provenance and recognizability evidence. |
| `overlay_zones` | `candidate` | `overlay_zones` | Producer state required before director control. |
| `research_markers` | `candidate` | `research_marker_overlay`, `programme_cuepoints` | Public markers require fresh condition/event provenance. |
| `private_sidechat` | `private` | `music_request_sidechat` | Control input only; must have non-egress tests. |
| `stream_deck` | `private` | `music_request_sidechat` | Physical control lane; unavailable commands no-op with reason. |
| `kdeconnect` | `private` | `music_request_sidechat` | Interim phone control bridge; no public leakage. |
| `music_request` | `private` | `music_request_sidechat`, `music_provenance` | Direct play requests become structured impingements with provenance. |
| `mobile_portrait_stream` | `candidate` | `mobile_9x16_substream`, `mobile_companion_page` | Companion page remains unavailable until portrait producer exists. |
| `autonomous_speech` | `blocked` | `autonomous_narrative_emission`, `operator_quality_rating` | Public speech requires audio, egress, public-claim, and quality feedback gates. |
| `lore_wards` | `blocked` | `lore_wards` | Query lane requires redaction and chat-authority gates. |
| `durf_visual_layer` | `candidate` | `durf_visual_layer` | Privacy/redaction posture and region masking are lane truth. |
| `refusal_as_data` | `candidate` | `refusal_briefs`, `refusal_annex_footer` | Refusal artifacts stay dry-run/private until event and publication truth exist. |

## Public Claim Policy

A lane may set `public_claim_allowed=true` only when:

1. every referenced substrate row permits the same public claim;
2. egress and audio truth permit the public claim when applicable;
3. risk tiers are `none` or `low` for the relevant public surface;
4. provenance exists for rights-bearing media, music, visual pool assets, and
   publication artifacts;
5. renderability evidence is fresh; and
6. fallback behavior is defined.

Unknown is not safe. A lane with unknown evidence remains dry-run, private,
candidate, blocked, or degraded.

## Programme Hooks And Envelopes

The programme layer remains a soft prior, not a hard gate. It can propose
multi-spectacle envelopes such as:

- `listening`: foreground `music_listening`, hold `reverie_substrate`, suppress
  `autonomous_speech`, background `research_ledger`, keep fanout off except
  boundary events
- `hothouse_pressure`: foreground `research_ledger` and `gem_mural`, intensify
  `homage_ward_system`, route attention to `research_markers`, keep egress and
  audio gates unchanged
- `public_boundary`: mark boundary in `metadata`, `research_markers`, and
  `publication_fanout` only when public-event policy permits

The director may accept, reshape, or no-op a programme envelope, but the
resulting lane actions must be auditable.

## Child Implementation Tasks

Do not create one implementation umbrella. After this contract, split adapters
where existing systems already own behavior.

| Child task id | Relationship | Write scope guidance |
|---|---|---|
| `homage-spectacle-lane-adapter` | Child/closeout for HOMAGE rehearsal and ward contrast anchors. | Map HOMAGE/contrast health to lane state; do not rewrite HOMAGE rendering. |
| `reverie-spectacle-lane-adapter` | Child of Reverie/source registry work. | Expose ground intensity/dampen/stabilize controls and evidence; preserve substrate invariant. |
| `re-splay-spectacle-lane-adapter` | Child of M8 Re-Splay hardware smoke and downstream variants. | Convert hardware/capture evidence into lane state; keep unavailable no-op until hardware proof. |
| `captions-spectacle-lane-adapter` | Child of caption bridge and YouTube production wiring. | Map caption freshness/redaction/egress to lane verbs and fallback. |
| `metadata-status-spectacle-lane-adapter` | Child of public-event and YouTube translation contracts. | Convert metadata/status/cuepoint truth into lane state; no platform writes here. |
| `overlay-research-marker-spectacle-adapter` | Child or closeout for `overlay-zones-producer-implementation`. | Map producer state and research marker provenance to lane state. |
| `chat-ambient-keyword-spectacle-adapter` | New child only after no active owner is found. | Aggregate-only chat lane, no author persistence, no raw handles. |
| `cbip-spectacle-lane-adapter` | Child of `content-source-cbip-signal-density`. | Map music metadata/provenance into lane state and verbs. |
| `private-controls-spectacle-adapter` | Child of director-substrate control work. | Sidechat, Stream Deck, and KDEConnect controls with non-egress proof. |
| `mobile-portrait-spectacle-lane-adapter` | Blocked child of mobile substream work. | Wait for portrait producer and legibility smoke before companion/page claims. |
| `autonomous-narration-spectacle-lane-adapter` | Blocked child of SS2/QM5/SS3/live-smoke anchors. | Require audio/egress/quality feedback gates before public speech lane claims. |

## Downstream Packet Unblockers

- `director-substrate-control-plane` can derive vocabulary and safe no-op
  behavior from lane and substrate truth.
- `spectacle-architecture-contract` can define visual roles, legibility proof,
  parallax, scrim, and viewer-facing evidence without inventing lane state.
- `substrate-adapter-buildout-tranche-1` can select bounded adapters instead of
  becoming a giant grab bag.
- `livestream-health-group` can report spectacle readiness as evidence,
  degraded, dry-run, private, or blocked.

## Acceptance

This seed is accepted when:

- `schemas/spectacle-control-plane.schema.json` defines the required
  `SpectacleLaneState` fields, lifecycle states, risk tiers, and director verbs.
- this spec names the initial lanes from the task packet and comprehensive
  Obsidian scour.
- hold and silence are explicit directorial moves only when targeted at a lane.
- unmounted, candidate, blocked, or stale lanes produce no-op/dry-run
  explanations instead of false control claims.
- child tasks adapt HOMAGE, Reverie, Re-Splay, captions, metadata, overlays,
  chat, CBIP, private controls, mobile, and autonomous speech without replacing
  their existing systems.

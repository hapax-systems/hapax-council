# Livestream Substrate Registry - Design Spec

**Status:** schema seed for `livestream-substrate-registry`
**Task:** `/home/hapax/Documents/Personal/20-projects/hapax-cc-tasks/active/livestream-substrate-registry.md`
**Date:** 2026-04-28
**Scope:** `ContentSubstrate` schema, lifecycle vocabulary, initial registry rows, duplicate absorption, and adapter-tranche split.
**Non-scope:** production adapters, egress resolver changes, audio topology changes, YouTube writes, or public fanout writes.

## Purpose

The livestream is a research vehicle suitcase. It can carry research through
semantic, linguistic, audiovisual, archival, social, and representational
substrates. That makes substrate truth a first-order contract, not a UI detail.

This spec seeds a durable `ContentSubstrate` registry so director, programme,
health, egress, metadata, archive, and public fanout surfaces can ask the same
questions:

- does this carrier exist?
- who produces and consumes it?
- how fresh is the evidence?
- what may be claimed in private, public-live, archive, or monetized contexts?
- what happens when the producer, rights, privacy, or render lane is missing?

Until a substrate has mounted producer evidence, render target evidence, health,
fallback, and claim policy, it must be private, dry-run, dormant, or unavailable.
The registry replaces "retire unless build" with "build through a contract; do
not publicly claim it until wired."

## Inputs Consumed

- `/home/hapax/Documents/Personal/20-projects/hapax-research/specs/2026-04-28-livestream-research-vehicle-suitcase-parent-spec.md`
- `/home/hapax/Documents/Personal/20-projects/hapax-research/plans/2026-04-28-livestream-suitcase-wsjf-workload.md`
- `/home/hapax/Documents/Personal/20-projects/hapax-research/audits/2026-04-28-hapax-obsidian-lost-feature-comprehensive-scour.md`
- `docs/superpowers/specs/2026-04-28-broadcast-audio-safety-ssot-design.md`
- active anchors under `/home/hapax/Documents/Personal/20-projects/hapax-cc-tasks/active/`

## `ContentSubstrate` Schema Seed

The machine-readable seed lives at:

- `schemas/livestream-content-substrate.schema.json`

Required fields:

| Field | Meaning |
|---|---|
| `schema_version` | Registry row version. Initial value is `1`. |
| `substrate_id` | Stable snake_case row identity. |
| `display_name` | Operator-facing name. |
| `substrate_type` | Broad family used by adapters and downstream contracts. |
| `producer` | Owner, state source, and evidence source for the content. |
| `consumer` | Surface, adapter, event bus, or public aperture that consumes it. |
| `freshness_ttl_s` | Max acceptable producer evidence age; `null` means manually gated or unavailable. |
| `rights_class` | Rights posture for public and monetized use. |
| `provenance_token` | Manifest pointer, event id, citation, artifact hash, or null. |
| `privacy_class` | Operator-private, consent-required, aggregate-only, public-safe, or unknown. |
| `public_private_modes` | Allowed modes when evidence exists. |
| `render_target` | Compositor lane, platform API, file, archive, status surface, or device. |
| `director_vocabulary` | Nouns/phrases the director may use when this row is mounted or dry-run visible. |
| `director_affordances` | Verbs/no-op explanations available to the director. |
| `programme_bias_hooks` | Programme hooks that may foreground, suppress, annotate, or schedule it. |
| `objective_links` | Task ids, specs, or event types this row supports. |
| `public_claim_permissions` | Live, archive, monetization, egress, audio, provenance, and operator-action gates. |
| `health_signal` | Health/status owner and freshness reference. |
| `fallback` | Fail-closed behavior when required evidence is absent. |
| `kill_switch_behavior` | Trigger, action, and operator recovery for blocking regressions. |
| `integration_status` | Lifecycle state from the enum below. |
| `existing_task_anchors` | Optional active/closed cc-task ids that own implementation. |
| `notes` | Optional dependency or split note. |

Example row:

```json
{
  "schema_version": 1,
  "substrate_id": "caption_in_band",
  "display_name": "In-band captions",
  "substrate_type": "caption",
  "producer": {
    "owner": "ytb-009-production-wire",
    "state": "caption_bridge_state",
    "evidence": "fresh STT segment plus egress public-claim permission"
  },
  "consumer": {
    "owner": "ResearchVehiclePublicEvent",
    "state": "caption_segment",
    "evidence": "caption event with rights/privacy/provenance policy"
  },
  "freshness_ttl_s": 15,
  "rights_class": "operator_original",
  "provenance_token": "caption_segment.event_id",
  "privacy_class": "public_safe",
  "public_private_modes": ["private", "dry_run", "public_live", "archive"],
  "render_target": "broadcast layout caption strip and public caption event",
  "director_vocabulary": ["captions", "caption strip"],
  "director_affordances": ["hold", "suppress", "mark boundary"],
  "programme_bias_hooks": ["programme_boundary", "autonomous_narrative_emission"],
  "objective_links": ["ytb-009-production-wire", "caption_segment"],
  "public_claim_permissions": {
    "claim_live": false,
    "claim_archive": true,
    "claim_monetizable": false,
    "requires_egress_public_claim": true,
    "requires_audio_safe": true,
    "requires_provenance": true,
    "requires_operator_action": false
  },
  "health_signal": {
    "owner": "livestream-health-group",
    "status_ref": "caption_bridge",
    "freshness_ref": "caption_bridge.age_s"
  },
  "fallback": {
    "mode": "dry_run_badge",
    "reason": "Caption producer or public egress evidence is stale."
  },
  "kill_switch_behavior": {
    "trigger": "caption source includes private or consent-required text without policy",
    "action": "suppress public caption output and emit health blocker",
    "operator_recovery": "clear source policy and re-run caption bridge preflight"
  },
  "integration_status": "dormant",
  "existing_task_anchors": ["ytb-009-production-wire"],
  "notes": "Dormant until the in-band bridge and public event contract are wired."
}
```

## Lifecycle Statuses

`integration_status` is one of:

| Status | Meaning | Public claim rule |
|---|---|---|
| `unavailable` | No producer, render target, or required external precondition exists. | Never claim live, archive, or monetized use. |
| `dormant` | Code, design, or platform exists but is not currently mounted. | May appear in planning and dry-run inventories only. |
| `dry-run` | Producer or adapter can simulate output without public publication. | May be operator-visible with explicit dry-run explanation. |
| `private` | Usable only on operator-private surfaces or internal evidence paths. | No public-live claim. |
| `public-live` | Fresh evidence proves public egress, privacy, rights, health, and renderability. | Public claims allowed within row permissions. |
| `archive-only` | Safe for replay/archive but not live publication. | Archive claims only. |
| `degraded` | Mounted but missing quality, freshness, or partial downstream evidence. | Only degraded claims; no new monetization claims. |
| `retired-only-if-obsolete` | The substrate is intentionally obsolete, not merely unwired. | Requires a replacement or obsolete rationale. |

The default for a new or uncertain row is `unavailable` or `dormant`, not
`retired-only-if-obsolete`.

## Public And Private Claim Policy

Every public claim must be the intersection of registry row policy and upstream
truth:

1. `LivestreamEgressState.public_claim_allowed` must be true for live public
   claims.
2. `BroadcastAudioSafety.audio_safe_for_broadcast.safe` must be true for
   audible live or monetized claims.
3. `rights_class` must not be `third_party_uncleared` or `unknown` for public
   or monetized claims.
4. `privacy_class` must be `public_safe` or `aggregate_only` for public claims.
   Consent-required rows remain private/unavailable unless a current consent
   contract or row-specific public policy exists.
5. `provenance_token` must be non-null when
   `public_claim_permissions.requires_provenance` is true.
6. Producer evidence must be fresh under `freshness_ttl_s`.
7. The row's render target and health signal must be mounted or intentionally
   `archive-only`.

Unknown is not safe. Stale evidence maps to `degraded`, `dry-run`, `private`, or
`unavailable` according to the row fallback.

## Director Vocabulary And Programme Hooks

Director vocabulary is generated from registry truth, not scattered constants.

- `director_vocabulary[]` supplies row-specific nouns only after the row is
  mounted, dry-run visible, or intentionally unavailable with a reason.
- `director_affordances[]` is filtered by `integration_status`, renderability,
  rights, privacy, and public-claim permissions.
- `programme_bias_hooks[]` is the only place a substrate declares programme
  pressure such as `programme_boundary`, `music_change`, `high_salience_event`,
  `operator_quality_rating`, `privacy_risk`, or `archive_gap`.
- If a row is `unavailable`, a director command becomes an explicit no-op with
  row fallback reason.
- `hold` and `suppress` are valid directorial moves when applied to a known row.

This lets `director-substrate-control-plane` and `spectacle-control-plane`
consume row truth without inventing lane semantics.

## Initial Registry Map

This is a seed map, not implementation truth. Status values reflect current
contract posture from the workload and Obsidian scour.

| `substrate_id` | Type | Initial status | Implementation anchor or downstream packet | Required correction |
|---|---|---|---|---|
| `caption_in_band` | `caption` | `dormant` | `ytb-009-production-wire` | Treat captions as dormant/private/dry-run until bridge, freshness, egress, and public-event policy exist. |
| `programme_cuepoints` | `cuepoint` | `dormant` | `ytb-004-programme-boundary-cuepoints` | Cuepoints consume public events plus egress/rights evidence, not direct internal triggers. |
| `chapter_markers` | `cuepoint` | `dormant` | `ytb-004-programme-boundary-cuepoints` | Chapter claims require archive/video id evidence. |
| `chat_legend` | `chat` | `dormant` | `spectacle-control-plane` | Legend is aggregate/viewer-safe; no author persistence. |
| `chat_ambient_aggregate` | `chat` | `dormant` | `spec-2026-04-18-chat-ambient-ward` | Aggregate-only ward; no per-author state. |
| `chat_keyword_consumer` | `chat` | `dormant` | `ef7b-180-finding-v-q4-chat-keywords-consumer-ward-research` | Keyword ward remains research/aggregate until mounted with privacy policy. |
| `overlay_zones` | `overlay` | `dormant` | `overlay-zones-producer-implementation` | Render only from producer state, not layout implication. |
| `research_marker_overlay` | `overlay` | `dormant` | `overlay-zones-producer-implementation` | Public claim requires fresh condition/event provenance. |
| `hls_archive` | `archive` | `degraded` | `livestream-egress-state-resolver` | Distinguish local HLS files from MediaMTX/YouTube acceptance evidence. |
| `youtube_metadata` | `platform_metadata` | `dormant` | `ytb-009-production-wire` | Metadata cannot claim unavailable captions, cuepoints, archive, or fanout producers. |
| `youtube_player` | `platform_player` | `private` | `youtube-player-real-content-ducker-smoke` | Real-content ducker smoke is audio evidence, not route-policy ownership. |
| `youtube_channel_sections` | `platform_metadata` | `dormant` | `ytb-011-channel-sections-manager` | Sections consume public events and quota authority. |
| `arena_blocks` | `public_fanout` | `dormant` | `research-vehicle-public-event-contract` | Add `arena_block` event shape and provenance/citation fields before adapter. |
| `omg_statuslog` | `public_fanout` | `dormant` | `cross-surface-event-contract` | Event-driven with max cadence, idempotency, and dry-run explanation. |
| `omg_weblog` | `public_fanout` | `dormant` | `cross-surface-event-contract` | Operator-reviewed drafts publish before RSS/fanout. |
| `publication_rss` | `public_fanout` | `dormant` | `self-federate-rss-cadence-closeout` | Cursor and fanout health are required. |
| `publication_hash_sidecars` | `public_fanout` | `dormant` | `omg-lol-hash-sidecar-lifecycle` | Hash sidecars need explicit persist/evict behavior. |
| `mastodon_fanout` | `public_fanout` | `dormant` | `ytb-010-cross-surface-federation` | Share event policy with Bluesky/Discord paths. |
| `research_cards` | `research_card` | `dormant` | `research-vehicle-public-event-contract` | Cards need event/provenance policy before public use. |
| `terminal_tiles` | `terminal_tile` | `private` | `spectacle-control-plane` | Private by default; public render requires redaction policy. |
| `geal_overlay` | `spectacle_lane` | `dormant` | `ytb-GEAL-PERF-BUDGET-FOLLOWUP` | Needs production event feed, frame budget, health signal, and unavailable explanation. |
| `lore_wards` | `spectacle_lane` | `unavailable` | `ytb-LORE-EXT-future-wards` | Blocked candidate; query lane requires redaction and chat-authority gate. |
| `durf_visual_layer` | `spectacle_lane` | `dormant` | `durf-phase-3-visual-followups` | Privacy/redaction posture and region masking are part of row truth. |
| `homage_ward_system` | `spectacle_lane` | `degraded` | `homage-live-rehearsal-signoff-reconcile` | Needs live rehearsal and legibility status, not just implementation existence. |
| `ward_contrast` | `spectacle_lane` | `degraded` | `ytb-ward-contrast-followup` | Product direction and contrast evidence are required. |
| `cbip_signal_density` | `spectacle_lane` | `dormant` | `content-source-cbip-signal-density` | Depends on music provenance and signal metadata, not retired album-cover SHM. |
| `local_visual_pool` | `visual_asset` | `dormant` | `content-source-local-visual-pool` | Rights class and provenance token are mandatory per asset. |
| `broadcast_provenance_manifest` | `provenance_manifest` | `dormant` | `content-source-provenance-egress-gate` | Missing or high-risk assets degrade/kill public claims. |
| `shorts_candidates` | `short_form` | `dormant` | `ytb-012-shorts-extraction-pipeline` | Candidate events need rights, provenance, egress, and archive refs before upload. |
| `refusal_briefs` | `refusal_artifact` | `dormant` | `refusal-annex-publish-fanout-closeout` | Public artifact rows must show dry-run/public-live state and publication truth. |
| `refusal_annex_footer` | `refusal_artifact` | `dormant` | `refusalgate-phase-6-per-surface-expansion` | Per-surface gate and footer/deposit-builder state remain explicit. |
| `lyrics_context` | `lyrics_context` | `private` | `youtube-research-translation-ledger` | Use only with rights/provenance and public-suitability policy. |
| `re_splay_m8` | `hardware_source` | `unavailable` | `m8-re-splay-operator-install-and-smoke` | No director mounted-lane claim until operator hardware smoke lands. |
| `re_splay_polyend` | `hardware_source` | `unavailable` | `re-splay-polyend-downstream-design` | Blocked until M8 source shape and capture policy are proven. |
| `re_splay_steam_deck` | `hardware_source` | `unavailable` | `re-splay-steam-deck-downstream-gate` | Blocked until M8 baseline and Steam Deck gate clear. |
| `mobile_9x16_substream` | `mobile_stream` | `dormant` | `mobile-livestream-substream-implementation` | Needs smart crop, salience routing, and legibility smoke. |
| `mobile_companion_page` | `mobile_stream` | `unavailable` | `cross-surface-event-contract` | Missing producer until mobile substream lands. |
| `music_request_sidechat` | `music_control` | `private` | `music-request-impingement-routing` | Direct `play <n>` becomes structured impingement routing. |
| `music_provenance` | `provenance_manifest` | `dormant` | `music-provenance-phase7-followthrough` | Feeds spectacle, egress safety, and monetization readiness. |
| `lrr_audio_archive` | `audio_archive` | `unavailable` | `lrr-audio-archive-capture-operator-gated` | Requires operator consent, retention, redaction, and storage decision. |
| `cdn_assets` | `cdn_asset` | `dormant` | `hapax-assets-cdn-publisher-recovery` | Model as rights/provenance-bearing dependency, not assumed live. |
| `autonomous_narrative_emission` | `narrative` | `dormant` | `autonomous-narrative-broadcast-live-smoke`, `ytb-SS2-substantive-speech-research`, `ytb-SS3-long-arc-narrative-continuity` | Public speech requires audio, egress, public-claim truth, and quality feedback policy. |
| `operator_quality_rating` | `quality_feedback` | `private` | `ytb-QM5-operator-quality-feedback-interface` | Feedback is private research signal, not public attribution. |
| `future_sources` | `future_source` | `unavailable` | `substrate-adapter-buildout-tranche-1` | Future carriers start as unavailable with a required owner, policy, and fallback. |

## Duplicate Absorption Notes

- **Re-Splay:** `m8-re-splay-operator-install-and-smoke`,
  `re-splay-polyend-downstream-design`, and
  `re-splay-steam-deck-downstream-gate` remain the implementation anchors.
  Registry rows must mark M8/Polyend/Steam Deck unavailable until hardware and
  capture evidence exists.
- **Local visual pool:** `content-source-local-visual-pool` owns asset ingestion.
  The registry owns row shape, rights class, provenance token, render target, and
  claim policy. `content-source-provenance-egress-gate` consumes the row.
- **Mobile substream:** `mobile-livestream-substream-implementation` owns the
  9:16 path. The companion page is a future/unavailable substrate until the
  substream has producer and archive evidence.
- **YouTube:** `ytb-009-production-wire`, `ytb-004-programme-boundary-cuepoints`,
  `ytb-011-channel-sections-manager`, `ytb-012-shorts-extraction-pipeline`,
  `ytb-010-cross-surface-federation`, and `ytb-OG3-quota-extension-filing`
  remain active anchors. YouTube translates substrate/public-event truth; it is
  not the source of truth.
- **Content provenance:** `content-source-provenance-egress-gate`,
  `content-source-local-visual-pool`, and `music-provenance-phase7-followthrough`
  remain separate owners. The registry requires all public-capable media rows to
  expose `rights_class` and `provenance_token`.
- **Audio:** `broadcast-audio-safety-ssot` and its child anchors own audio
  truth. The substrate registry can require `audio_safe_for_broadcast` but must
  not duplicate topology, route policy, loudness constants, or PipeWire edits.
- **Public fanout:** `research-vehicle-public-event-contract` and
  `cross-surface-event-contract` own the event/fanout contracts. Registry rows
  only declare which substrates may produce or consume those public events.

## First Adapter Tranche And Exact Child Tasks

Do not create one umbrella implementation task. After this registry, spectacle
control, and public-event contracts are accepted, split adapter work into narrow
tasks. Existing active tasks stay as anchors; new child tasks should be created
only where no active note already owns the work.

Recommended first tranche:

| Child task id | Relationship | Write scope guidance |
|---|---|---|
| `caption-substrate-adapter` | Child of `ytb-009-production-wire`; blocked by public-event contract. | Caption bridge state, caption event mapping, health/fallback tests. |
| `cuepoint-substrate-adapter` | Child of `ytb-004-programme-boundary-cuepoints`; blocked by public-event contract. | Programme boundary event input, chapter/cuepoint output, stale evidence behavior. |
| `chat-ambient-keyword-substrate-adapter` | New child after spectacle contract if no active implementation note exists. | Aggregate-only chat ward producer/consumer, no author persistence, health state. |
| `overlay-research-marker-substrate-adapter` | Child or closeout for `overlay-zones-producer-implementation`. | Overlay zone producer state, research marker provenance, layout/render target evidence. |
| `local-visual-pool-substrate-adapter` | Child of `content-source-local-visual-pool`; coordinate with provenance gate. | Asset row ingestion, manifest token, rights/provenance health. |
| `cbip-substrate-adapter` | Child of `content-source-cbip-signal-density`. | Music state metadata, provenance dependency, spectacle lane policy. |
| `re-splay-m8-substrate-adapter` | Child of `m8-re-splay-operator-install-and-smoke`; blocked until hardware smoke. | M8 capture evidence, render target, director no-op while unavailable. |
| `music-request-provenance-substrate-adapter` | Child split from `music-request-impingement-routing` and `music-provenance-phase7-followthrough`. | Structured request input, provenance token, public/monetization risk policy. |
| `youtube-player-substrate-smoke` | Child/closeout for `youtube-player-real-content-ducker-smoke`. | Real content player evidence, duck state, audio-safe proof, no private leak. |
| `refusal-publication-substrate-adapter` | Child split from refusal/fanout active notes after public-event contract. | Refusal brief/annex/footer events, dry-run/public state, hash/RSS sidecar policy. |

Blocked from tranche 1 until gates clear:

- `mobile_companion_page`, because the 9:16 substream producer is not proven.
- `lore_wards`, because future ward expansion needs redaction and chat-authority
  gates.
- `autonomous_narrative_emission`, `operator_quality_rating`, and SS3
  continuity, because audio/egress/public-growth gates remain upstream.
- `lrr_audio_archive`, because operator consent/governance decisions are
  explicit prerequisites.

## Downstream Packet Unblockers

- `research-vehicle-public-event-contract` can now consume `substrate_id`,
  `rights_class`, `privacy_class`, `provenance_token`, and
  `public_claim_permissions` instead of defining its own substrate semantics.
- `spectacle-control-plane` can map spectacle lanes to `substrate_id`,
  `integration_status`, `director_vocabulary`, `director_affordances`,
  `programme_bias_hooks`, render target, health, and fallback.
- `director-substrate-control-plane` can derive available nouns and verbs from
  registry truth and explain unavailable no-ops.
- `livestream-health-group` can report substrate freshness and public-claim
  posture without inventing liveness.
- `monetization-readiness-ledger` can consume rights, provenance, public egress,
  audio safety, archive, and platform posture as independent evidence.

## Acceptance

This seed is accepted when:

- `schemas/livestream-content-substrate.schema.json` contains the
  `ContentSubstrate` required fields and lifecycle enum.
- the registry map includes every correction from the comprehensive Obsidian
  scour packet.
- duplicate/absorption notes preserve existing Re-Splay, visual pool, mobile,
  YouTube, provenance, audio, and public fanout task ownership.
- first adapter tranche recommendations are exact child tasks rather than a
  broad implementation umbrella.
- public/director/metadata claims fail closed unless registry, egress, audio,
  rights, privacy, provenance, health, and render evidence all permit the claim.

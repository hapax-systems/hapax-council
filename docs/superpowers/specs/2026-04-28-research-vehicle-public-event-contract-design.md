# Research Vehicle Public Event Contract - Design Spec

**Status:** schema seed for `research-vehicle-public-event-contract`
**Task:** `/home/hapax/Documents/Personal/20-projects/hapax-cc-tasks/active/research-vehicle-public-event-contract.md`
**Date:** 2026-04-28
**Scope:** `ResearchVehiclePublicEvent` schema, derived public/archive/monetization policy, public-aperture mapping, caption/cuepoint rules, failure behavior, and downstream child-task split.
**Non-scope:** YouTube writes, cross-surface publisher implementation, captions production wiring, monetization ledger implementation, or new public fanout daemons.

## Purpose

The livestream is a research vehicle suitcase. Public apertures should publish
from a shared event stream, not from ad hoc reads of compositor state, internal
JSONL files, task notes, or platform-specific side effects.

`ResearchVehiclePublicEvent` is the contract that turns grounded livestream
facts into policy-aware public events. YouTube metadata, live cuepoints, VOD
chapters, captions, Shorts, Are.na blocks, OMG statuslog/weblog, archive,
Mastodon/Bluesky/Discord fanout, and future apertures consume this event shape.

The event object does not replace `ContentSubstrate`. It consumes substrate
identity and policy from the registry, adds event timing and public aperture
intent, and carries enough evidence for downstream surfaces to decide whether an
event may be claimed live, archived, monetized, posted, redacted, or held.

Until source evidence, egress truth, rights, privacy, provenance, and surface
policy all agree, public apertures must default to dry-run, archive-only,
private-only, or hold.

## Inputs Consumed

- `/home/hapax/Documents/Personal/20-projects/hapax-research/specs/2026-04-28-livestream-research-vehicle-suitcase-parent-spec.md`
- `/home/hapax/Documents/Personal/20-projects/hapax-research/plans/2026-04-28-livestream-suitcase-wsjf-workload.md`
- `/home/hapax/Documents/Personal/20-projects/hapax-research/plans/2026-04-28-livestream-research-vehicle-suitcase-addendum.md`
- `/home/hapax/Documents/Personal/20-projects/hapax-research/audits/2026-04-28-hapax-obsidian-lost-feature-starter-list.md`
- `/home/hapax/Documents/Personal/20-projects/hapax-research/audits/2026-04-28-hapax-obsidian-wsjf-implications.md`
- `/home/hapax/Documents/Personal/20-projects/hapax-research/audits/2026-04-28-hapax-obsidian-lost-feature-comprehensive-scour.md`
- `docs/superpowers/specs/2026-04-28-livestream-substrate-registry-design.md`
- `schemas/livestream-content-substrate.schema.json`

Platform references checked on 2026-04-28:

- YouTube `liveBroadcasts.cuepoint`: https://developers.google.com/youtube/v3/live/docs/liveBroadcasts/cuepoint
- YouTube deprecated `liveCuepoints.insert`: https://developers.google.com/youtube/v3/live/docs/liveCuepoints/insert
- YouTube quota calculator: https://developers.google.com/youtube/v3/determine_quota_cost
- YouTube quota and compliance audits: https://developers.google.com/youtube/v3/guides/quota_and_compliance_audits
- YouTube live monetization: https://support.google.com/youtube/answer/7385599
- YouTube advertiser-friendly guidelines: https://support.google.com/youtube/answer/6162278
- YouTube advertiser-friendly best practices: https://support.google.com/youtube/answer/9348366
- YouTube live copyright issues: https://support.google.com/youtube/answer/3367684

## `ResearchVehiclePublicEvent` Schema Seed

The machine-readable seed lives at:

- `schemas/research-vehicle-public-event.schema.json`

Required fields:

| Field | Meaning |
|---|---|
| `schema_version` | Event schema version. Initial value is `1`. |
| `event_id` | Stable idempotency key for this public event. |
| `event_type` | Typed class such as `programme.boundary`, `caption.segment`, `shorts.candidate`, or `omg.statuslog`. |
| `occurred_at` | RFC 3339 timestamp for the source event, not publication time. |
| `broadcast_id` | Broadcast/video/session id, or `null` when not bound yet. |
| `programme_id` | Programme arc id, or `null` when not applicable. |
| `condition_id` | Research condition/objective id, or `null` when not applicable. |
| `source` | Source producer plus `substrate_id`, task anchor, evidence ref, and freshness ref. |
| `salience` | Normalized 0.0-1.0 salience used by public aperture filters and rate budgets. |
| `state_kind` | Stable semantic class used for rate limits, publication contracts, and replay. |
| `rights_class` | Event-level rights posture, normally inherited from the source substrate. |
| `privacy_class` | Event-level privacy posture, normally inherited from the source substrate. |
| `provenance` | Token, generation time, evidence refs, rights basis, and citation refs. |
| `public_url` | Canonical URL after publication, or `null` before publication. |
| `frame_ref` | Optional frame/image/video-window reference for visual apertures. |
| `chapter_ref` | Optional chapter/cuepoint reference for replay and YouTube navigation. |
| `attribution_refs` | Asset, citation, license, or source attributions required before public use. |
| `surface_policy` | Per-surface allow/deny/hold policy, claim flags, review requirement, redaction policy, and fallback action. |

Example event:

```json
{
  "schema_version": 1,
  "event_id": "rvpe_20260428t235500z_programme_boundary_listening_001",
  "event_type": "programme.boundary",
  "occurred_at": "2026-04-28T23:55:00Z",
  "broadcast_id": "yt_live_20260428",
  "programme_id": "programme_listening_20260428T2350Z",
  "condition_id": "condition_music_listening",
  "source": {
    "producer": "programme_manager",
    "substrate_id": "programme_cuepoints",
    "task_anchor": "ytb-004-programme-boundary-cuepoints",
    "evidence_ref": "/dev/shm/hapax-broadcast/events.jsonl#rvpe_20260428t235500z_programme_boundary_listening_001",
    "freshness_ref": "programme_boundary.age_s"
  },
  "salience": 0.78,
  "state_kind": "programme_state",
  "rights_class": "operator_original",
  "privacy_class": "public_safe",
  "provenance": {
    "token": "programme_boundary.event_id",
    "generated_at": "2026-04-28T23:55:01Z",
    "producer": "programme_manager",
    "evidence_refs": [
      "LivestreamEgressState.public_claim_allowed",
      "ContentSubstrate.programme_cuepoints",
      "BroadcastAudioSafety.audio_safe_for_broadcast"
    ],
    "rights_basis": "operator generated programme state",
    "citation_refs": []
  },
  "public_url": null,
  "frame_ref": null,
  "chapter_ref": {
    "kind": "programme_boundary",
    "label": "Listening programme boundary",
    "timecode": "00:00",
    "source_event_id": "rvpe_20260428t235500z_programme_boundary_listening_001"
  },
  "attribution_refs": [],
  "surface_policy": {
    "allowed_surfaces": ["youtube_chapters", "youtube_cuepoints", "youtube_description", "archive"],
    "denied_surfaces": ["youtube_shorts", "omg_weblog"],
    "claim_live": false,
    "claim_archive": true,
    "claim_monetizable": false,
    "requires_egress_public_claim": true,
    "requires_audio_safe": true,
    "requires_provenance": true,
    "requires_human_review": false,
    "rate_limit_key": "youtube_chapters:programme_state",
    "redaction_policy": "none",
    "fallback_action": "chapter_only",
    "dry_run_reason": "Live cuepoints remain experimental until smoke verified."
  }
}
```

## Event Type Vocabulary

Initial `event_type` values:

| Event type | Producer | Primary consumers |
|---|---|---|
| `broadcast.boundary` | VOD boundary/egress resolver | YouTube description, chapters, archive, OMG statuslog, cross-surface fanout |
| `programme.boundary` | programme manager/director | cuepoints, chapters, metadata, archive |
| `condition.changed` | research/objective tracker | metadata, chapters, archive, Are.na |
| `chronicle.high_salience` | chronicle/DMN/stimmung | statuslog, social fanout, Shorts candidate, archive |
| `aesthetic.frame_capture` | compositor/Reverie/archive | Are.na, social image posts, archive |
| `caption.segment` | caption bridge/STT | in-band captions, archive captions, YouTube captions when eligible |
| `cuepoint.candidate` | programme/director/vinyl events | YouTube live cuepoint adapter and VOD chapter fallback |
| `chapter.marker` | VOD boundary/metadata composer | YouTube VOD description and replay index |
| `shorts.candidate` | salience detector/HLS assembler | Shorts extraction pipeline |
| `shorts.upload` | Shorts uploader | cross-surface fanout and archive |
| `metadata.update` | metadata composer | YouTube live/VOD metadata, OMG `/now`, status surfaces |
| `channel_section.candidate` | channel section manager | YouTube channel sections |
| `arena_block.candidate` | Are.na adapter | Are.na URL/image/citation blocks |
| `omg.statuslog` | statuslog composer | omg.lol statuslog |
| `omg.weblog` | weblog composer | operator-reviewed OMG weblog draft/publish |
| `publication.artifact` | publication bus/refusal/artifact publishers | OMG pastebin, RSS, Are.na, archive |
| `archive.segment` | HLS/archive rotator | replay, metadata, monetization readiness |
| `monetization.review` | monetization readiness ledger | growth/public apertures, operator surface |
| `fanout.decision` | cross-surface event contract | health, replay, audit |

Initial `state_kind` values:

- `live_state`
- `programme_state`
- `research_observation`
- `aesthetic_frame`
- `caption_text`
- `cuepoint`
- `chapter`
- `short_form`
- `public_post`
- `archive_artifact`
- `attribution`
- `monetization_state`
- `health_state`

## Derived Public Claim Policy

Public live claims are true only when all applicable gates pass:

1. `LivestreamEgressState.public_claim_allowed` is true and fresh.
2. The source `ContentSubstrate.integration_status` is `public-live` or an
   explicitly eligible `archive-only` row for archive claims.
3. `ContentSubstrate.public_claim_permissions.claim_live` and
   `surface_policy.claim_live` are both true for live claims.
4. `rights_class` is `operator_original`, `operator_controlled`,
   `third_party_attributed`, or `platform_embedded`; `third_party_uncleared`
   and `unknown` fail closed.
5. `privacy_class` is `public_safe` or `aggregate_only`; `operator_private`,
   `consent_required`, and `unknown` fail closed unless a current consent
   contract or row-specific public policy exists.
6. `provenance.token` is present when the event or source substrate requires
   provenance.
7. Source evidence is fresh under the source substrate `freshness_ttl_s`.
8. `surface_policy.allowed_surfaces` contains the target surface and
   `surface_policy.denied_surfaces` does not contain it.
9. Audible live or monetized surfaces require
   `BroadcastAudioSafety.audio_safe_for_broadcast.safe`.
10. If the target is YouTube live cuepoints, the target broadcast must be
    actively streaming and the adapter must use `liveBroadcasts.cuepoint`, not
    deprecated `liveCuepoints.insert`.

Archive claims are weaker than live claims but still evidence-bearing:

- `surface_policy.claim_archive` must be true.
- `public_url`, `frame_ref`, or `chapter_ref` must identify the replay artifact.
- Rights, privacy, provenance, and attribution gates still apply.
- Egress may be stale if archive evidence is fresh and the source substrate is
  `archive-only` or archive-eligible.

Public copy must say only what is currently true. It may say a surface is
private, dry-run, dormant, unavailable, archive-only, or blocked. It must not
imply captions, cuepoints, archive, Shorts, statuslog, Are.na, or cross-posting
exist when their producers are stale or dormant.

## Archive And Monetization Policy

Monetization suitability is derived from the event plus upstream ledgers. Until
`monetization-readiness-ledger` ships, the event may expose only:

- `claim_monetizable: false`
- `claim_monetizable: true` when all required ledger evidence exists
- `requires_human_review: true` for policy-sensitive cases

Hard fail cases for monetization:

- `rights_class` is `third_party_uncleared` or `unknown`.
- `privacy_class` is `operator_private`, `consent_required`, or `unknown`
  without a current policy exception.
- `provenance.token` is absent.
- Audible media lacks fresh broadcast-audio safety evidence.
- Source substrate kill switch is active.
- YouTube advertiser suitability is unknown for the event class, title,
  thumbnail, description, tags, Short, or live content.
- Live copyright/content matching risk is unresolved for the source material.

Soft review cases:

- `third_party_attributed` or `platform_embedded` material is present.
- The event is high-salience but lacks frame, chapter, or citation context.
- The event would cause Shorts upload quota burn or high-frequency public
  posting.
- The event is suitable for archive but not promotion.

The monetization ledger should consume the event rather than re-discovering
surface truth. Its explicit dimensions remain:

- `safe to broadcast`
- `safe to archive`
- `safe to promote`
- `safe to monetize`

## Aperture Surface Map

| Surface or task | Event input | Required policy |
|---|---|---|
| YouTube live title/description | `metadata.update`, `broadcast.boundary`, `programme.boundary`, `condition.changed` | Egress public claim, quota authority, no unavailable producer claims, advertiser-suitability posture. |
| YouTube live cuepoints | `cuepoint.candidate`, `programme.boundary` | Active broadcast, cuepoint smoke, rate limit, `chapter_only` fallback when API fails. |
| YouTube VOD chapters | `chapter.marker`, `programme.boundary`, `broadcast.boundary` | Archive/video id evidence, deterministic `00:00` chapter base, no dependency on live cuepoint success. |
| YouTube captions | `caption.segment` | Caption bridge freshness, redaction, privacy policy, quota posture, AV-offset evidence, egress gate for public-live claims. |
| YouTube channel sections | `channel_section.candidate`, `publication.artifact` | Quota posture, section-management dry-run/live evidence, no generic channel reshuffle. |
| YouTube Shorts | `shorts.candidate`, `shorts.upload` | Archive/HLS frame window, rights/provenance, quota budget, salience threshold, allowlist, conservative daily cap. |
| Are.na | `arena_block.candidate`, `aesthetic.frame_capture`, `publication.artifact`, high-salience events with frame/citation | `arena_block` shape with URL/image/citation support; no full-auto generic syndication. |
| OMG statuslog | `omg.statuslog`, `chronicle.high_salience`, `broadcast.boundary` | Max cadence, publication allowlist, stable non-formal operator referent, idempotency. |
| OMG weblog | `omg.weblog`, `publication.artifact`, monthly/programme summaries | Operator-reviewed draft gate; never fully autonomous. |
| Mastodon/Bluesky/Discord | `broadcast.boundary`, `chronicle.high_salience`, `shorts.upload`, `aesthetic.frame_capture`, `publication.artifact` | Shared cross-surface limiter, allowlist, redaction, per-surface capacity. |
| Archive and replay | all archive-eligible events | Fresh archive/ref refs, public/private mode labels, replayable event decision trail. |
| Captions and cuepoint internal adapters | `caption.segment`, `cuepoint.candidate`, `chapter.marker` | Producer freshness, duplicate suppression, fallback reasons, event idempotency. |

## Caption And Cuepoint Rules

Caption public claims require:

- `event_type: "caption.segment"`.
- Source substrate `caption_in_band` with fresh caption bridge evidence.
- `privacy_class: "public_safe"` or `aggregate_only`.
- Redaction policy applied before public publication.
- Egress public-claim evidence for live captions.
- Archive evidence for archive captions.
- YouTube caption upload quota and API posture before `youtube_captions` is
  allowed.

If any gate is missing, the caption event may remain private, dry-run, or
archive-only. Public metadata must not say captions are available.

Cuepoint public claims require:

- `event_type: "cuepoint.candidate"` or `programme.boundary`.
- Source substrate `programme_cuepoints` with fresh programme/director boundary
  evidence.
- Duplicate suppression by `(broadcast_id, programme_id, chapter_ref.label,
  time window)`.
- Target broadcast actively streaming before live cuepoint API calls.
- Surface fallback to `chapter.marker` when live cuepoint insertion is rejected,
  rate-limited, not smoke-verified, or quota constrained.

Every live cuepoint candidate should produce a deterministic archive chapter
candidate unless rights, privacy, or archive evidence blocks it.

## Failure Behavior

Failure is explicit event policy, not a silent skip.

| Missing or unsafe evidence | Required behavior |
|---|---|
| Missing provenance token | Set all public and monetizable claim flags false; hold or dry-run; emit blocker reason `missing_provenance`. |
| Unknown or uncleared rights | Deny public and monetized publication; keep private/archive review only; emit `rights_blocked`. |
| Private, consent-required, or unknown privacy | Deny public publication unless a current contract authorizes the event; emit `privacy_blocked`. |
| Stale source freshness | Downgrade to dry-run/degraded/private according to substrate fallback; emit `source_stale`. |
| Egress not public-claim safe | Deny live claims; allow archive-only only with fresh archive evidence; emit `egress_blocked`. |
| Audio unsafe for audible public surface | Deny live/monetized audible claims; allow text-only private/archive review if otherwise safe; emit `audio_blocked`. |
| Missing `public_url`, `frame_ref`, or `chapter_ref` required by surface | Hold that surface, keep event for replay/audit, and emit `missing_surface_reference`. |
| Surface not in allowlist or over rate budget | Do not publish; emit `fanout_denied` or `rate_limited` with target surface. |
| YouTube cuepoint API rejected | Do not retry blindly; create or preserve chapter fallback and emit `cuepoint_failed`. |
| Shorts upload quota or suitability unknown | Keep candidate private/dry-run; emit `shorts_blocked`. |
| Conflicting event and substrate policy | Most restrictive policy wins; emit `policy_conflict`. |

## Existing Task Mapping

The event contract adapts existing tasks; it does not replace their
implementation ownership.

| Anchor task | Mapping |
|---|---|
| `ytb-009-production-wire` | Produces `caption.segment` events from caption bridge state. |
| `ytb-004-programme-boundary-cuepoints` | Produces `cuepoint.candidate`, `chapter.marker`, and `programme.boundary` adapter events. |
| `ytb-010-cross-surface-federation` | Becomes a surface adapter consuming `fanout.decision` and event classes allowed by `cross-surface-event-contract`. |
| `ytb-011-channel-sections-manager` | Consumes `channel_section.candidate` and `publication.artifact`; must expose quota/dry-run evidence. |
| `ytb-012-shorts-extraction-pipeline` | Consumes `shorts.candidate`; emits `shorts.upload` after upload. |
| `ytb-OG3-quota-extension-filing` | Supplies quota posture consumed by YouTube event surfaces. |
| `ytb-GEAL-PERF-BUDGET-FOLLOWUP` | Supplies GEAL event/performance evidence for high-salience/aesthetic events. |
| `youtube-player-real-content-ducker-smoke` | Supplies rights/audio ducking evidence for platform-player events. |
| `ytb-OMG4-statuslog-autonomous` | Consumes `omg.statuslog` and high-salience events under statuslog cadence and allowlist. |
| `ytb-OMG8-weblog-composer` | Consumes `omg.weblog` under operator-reviewed draft policy. |
| `ytb-OMG5-email-account-identity` | Supplies external-account identity prerequisites for Are.na/Mastodon and other public apertures. |
| `cross-surface-event-contract` | Defines per-surface translation from `ResearchVehiclePublicEvent` to publish/link/embed/redact/hold/archive/replay decisions. |
| `youtube-research-translation-ledger` | Defines YouTube-specific title, description, chapter, cuepoint, caption, Shorts, section, quota, and suitability consumers. |
| `monetization-readiness-ledger` | Consumes events plus egress/audio/rights/provenance evidence to compute promotion and monetization readiness. |

## Child Task Recommendations

Do not create one public-aperture implementation grab bag. Split follow-on work
after this contract is accepted.

| Child task id | Parent or anchor | Purpose |
|---|---|---|
| `youtube-public-event-adapter` | `youtube-research-translation-ledger` | Map event classes to title, description, chapters, cuepoints, captions, Shorts, and channel sections without creating a second truth model. |
| `youtube-caption-event-adapter` | `ytb-009-production-wire` | Convert caption bridge output into `caption.segment` events with redaction, freshness, and fallback tests. |
| `youtube-cuepoint-chapter-event-adapter` | `ytb-004-programme-boundary-cuepoints` | Convert programme boundary events to live cuepoint attempts and deterministic chapter fallback. |
| `cross-surface-public-event-router` | `cross-surface-event-contract` | Route event classes to Bluesky, Discord, Mastodon, Are.na, OMG, archive, and future surfaces with allow/deny/rate explanations. |
| `arena-block-public-event-adapter` | `cross-surface-event-contract` | Add `arena_block` URL/image/citation block support before Are.na automation claims. |
| `omg-statuslog-public-event-adapter` | `ytb-OMG4-statuslog-autonomous` | Move statuslog triggers to shared events and idempotency keys. |
| `omg-weblog-public-event-adapter` | `ytb-OMG8-weblog-composer` | Save operator-reviewed weblog drafts from shared event summaries, not bespoke crawls. |
| `monetization-event-evidence-ledger` | `monetization-readiness-ledger` | Compute safe-to-broadcast/archive/promote/monetize from public events plus egress/audio/substrate evidence. |
| `shorts-public-event-adapter` | `ytb-012-shorts-extraction-pipeline` | Consume `shorts.candidate`, apply quota/suitability/rights policy, and emit `shorts.upload`. |

## Acceptance

This seed is accepted when:

- `schemas/research-vehicle-public-event.schema.json` contains all required
  parent-spec fields.
- This spec defines public claim, archive claim, and monetization suitability
  derivation from event plus substrate registry state.
- YouTube, cuepoint, programme-boundary cuepoint, channel-section, Shorts,
  Are.na, OMG statuslog, OMG weblog, Mastodon/social, caption, and
  cross-surface tasks are mapped onto the contract.
- Caption and cuepoint public-claim rules include freshness, egress, rights,
  privacy, provenance, and fallback behavior.
- Missing provenance, rights, privacy, source freshness, egress evidence, audio
  safety, or surface references fail closed with a named reason.
- Child task recommendations are split for YouTube translation, cross-surface
  fanout, and monetization readiness.

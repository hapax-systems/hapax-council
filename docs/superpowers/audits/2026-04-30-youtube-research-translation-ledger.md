# YouTube Research Translation Ledger

Date: 2026-04-30
Task: `youtube-research-translation-ledger`
Branch: `codex/cx-amber-youtube-research-translation-ledger`
Base reviewed: `origin/main` `f5a5ea26be76f85263ec7c9b934fc68dab4f634f`

## Contract Artifacts

- Ledger: `docs/superpowers/audits/2026-04-30-youtube-research-translation-ledger.json`
- Schema: `schemas/youtube-research-translation-ledger.schema.json`
- Authority contracts:
  - `schemas/research-vehicle-public-event.schema.json`
  - `shared/livestream_egress_state.py`
  - `schemas/livestream-content-substrate.schema.json`
- Upstream reconcile:
  `/home/hapax/Documents/Personal/20-projects/hapax-research/audits/2026-04-29-youtube-surface-reconcile-ledger.md`

## Summary

YouTube is modeled as a public aperture over `ResearchVehiclePublicEvent`,
`LivestreamEgressState`, and `ContentSubstrate`. It is not allowed to become a
second source of truth for liveness, captions, cuepoints, archive/replay,
channel sections, Shorts, cross-surface fanout, quota, suitability, or
monetization.

The machine-readable ledger maps ten surfaces:

- live metadata
- live captions
- live cuepoints
- VOD chapters
- channel sections
- Shorts
- archive/replay links
- cross-surface fanout
- quota posture
- advertiser suitability

Every publication surface defaults to `default_public_claim_allowed: false` and
`default_monetization_claim_allowed: false`. Public copy may say that a surface
is private, dry-run, blocked, unavailable, or evidence-backed. It may not claim
unavailable producers.

## Current Evidence

The closed YouTube surface reconcile found:

- captions have reader/writer/routing tests, but no production STT callsite, no
  GStreamer in-band path, and no live caption JSONL evidence;
- live cuepoints are active only through a legacy broadcast-rotation consumer
  and still need programme-boundary event input plus operator-supervised
  live-player smoke;
- VOD chapters are separate from live cuepoints and can only claim archive
  chapter generation when archive/public-event refs exist;
- channel sections have no section manager implementation and must remain
  manual/operator-reviewed;
- Shorts extraction/upload code is absent, and older 1600-unit cadence notes
  are stale against the current official quota table;
- metadata must not claim unavailable captions, cuepoints, archive/replay,
  channel sections, Shorts, fanout, or monetization readiness.

Official-source refresh on 2026-04-30 confirmed the ledger facts recorded in the
JSON artifact:

- YouTube Data API default quota is 10,000 units/day; invalid requests still cost
  at least one unit; live streaming methods consume Data API quota.
- Current method/table rows list `captions.insert` at 400 units,
  `channelSections.insert` at 50 units, `videos.insert` at 100 units, and
  `videos.update` at 50 units.
- `channelSections.insert` is capped by YouTube's 10-shelf channel limit.
- `liveBroadcasts.cuepoint` requires an actively streaming broadcast and
  `cueTypeAd`; the ledger keeps the per-call unit cost unresolved because the
  current rendered quota table does not enumerate that method row.
- Shorts uploads from desktop can be up to three minutes and must be square or
  vertical.
- Advertiser suitability needs review; context can matter, but context does not
  grant monetization readiness.

## Claim Policy

Most restrictive policy wins. A YouTube-facing surface is public-claimable only
when all required references in the row are fresh:

- `ResearchVehiclePublicEvent`
- `LivestreamEgressState.public_claim_allowed`
- `ContentSubstrate.public_claim_permissions`
- rights/provenance token
- privacy posture
- quota budget where the surface writes YouTube API state
- surface-specific evidence such as caption stream, live-player smoke, archive
  URL, section manager state, render artifact, or fanout decision

Metadata cannot infer live state from YouTube, compositor, or archive evidence
on its own. It consumes public event and egress truth.

## Child Split

The ledger intentionally does not create one umbrella implementation. It points
downstream work to bounded owners:

- `ytb-009-production-wire`: caption production and smoke evidence.
- `ytb-004-programme-boundary-cuepoints`: programme boundary cuepoints and live
  smoke.
- `ytb-011-channel-sections-manager`: section manager and operator-reviewed API
  posture.
- `ytb-012-shorts-extraction-pipeline`: Shorts extraction/render/upload and
  current quota model.
- `youtube-packaging-claim-policy`: packaging copy rules after monetization
  readiness.
- `youtube-public-event-adapter`: future dry-run metadata candidate adapter over
  `ResearchVehiclePublicEvent`.

No live YouTube writes, caption uploads, cuepoint sends, section changes, Shorts
uploads, or metadata updates were performed for this ledger.

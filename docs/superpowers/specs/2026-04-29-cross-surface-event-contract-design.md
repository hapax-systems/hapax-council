# Cross-Surface Event Contract - Design Spec

**Status:** schema and typed helper seed for `cross-surface-event-contract`
**Task:** `/home/hapax/Documents/Personal/20-projects/hapax-cc-tasks/active/cross-surface-event-contract.md`
**Date:** 2026-04-29
**Scope:** shared fanout policy, event-driven routing semantics, failure-as-event health shape, and first-class public aperture registry.
**Non-scope:** adapter implementations, systemd unit changes, live YouTube writes, social posting, OMG publication, Are.na posting, Discord activation, Shorts upload, or archive/replay publisher implementation.

## Purpose

`ResearchVehiclePublicEvent` is the source event shape. The cross-surface
event contract is the policy layer that says why a public event may reach one
surface and not another.

Downstream adapters must consume events and fanout decisions. They must not
scrape live files, task notes, closed PR evidence, or platform side effects as
their own truth model. If a surface is unwired, inactive, legacy-input,
credential-blocked, or operator-review-only, the shared contract records that
state and routes implementation to the surface-scoped child task.

## Inputs Consumed

- `/home/hapax/Documents/Personal/20-projects/hapax-research/specs/2026-04-28-livestream-research-vehicle-suitcase-parent-spec.md`
- `/home/hapax/Documents/Personal/20-projects/hapax-research/plans/2026-04-28-livestream-suitcase-wsjf-workload.md`
- `/home/hapax/Documents/Personal/20-projects/hapax-research/audits/2026-04-28-cross-surface-reality-reconcile.md`
- `/home/hapax/Documents/Personal/20-projects/hapax-cc-tasks/closed/broadcast-boundary-public-event-producer.md`
- `docs/superpowers/specs/2026-04-28-research-vehicle-public-event-contract-design.md`
- `schemas/research-vehicle-public-event.schema.json`
- `shared/research_vehicle_public_event.py`
- `agents/broadcast_boundary_public_event_producer.py`

## Machine-Readable Contract

The machine-readable seed lives at:

- `schemas/cross-surface-event-contract.schema.json`
- `shared/cross_surface_event_contract.py`

The schema defines:

| Object | Purpose |
|---|---|
| `aperture_contract` | Static contract row for a public aperture, including target `ResearchVehiclePublicEvent.surface_policy` surfaces, allowed event types, allowed fanout actions, current reality, publication contract, health owner, and child task. |
| `fanout_decision_event` | Failure-as-event and health payload for one event x aperture x action decision. |
| `actions` | The shared fanout verbs: `publish`, `link`, `embed`, `redact`, `hold`, `archive`, and `replay`. |
| `failure_event_type` | `fanout.decision`, the event type emitted or reported when a decision blocks/degrades publication. |
| `health_contract` | `ok`, `degraded`, and `blocked` meanings for public fanout health. |

`shared.cross_surface_event_contract.decide_cross_surface_fanout()` is a pure
decision helper. It never performs publication. It returns a deterministic
`CrossSurfaceFanoutDecision` with a stable `decision_id`, resolved action,
reason list, child task, health status, and optional `fanout.decision` failure
event id.

## Surface Actions

The contract recognizes seven verbs:

| Action | Meaning |
|---|---|
| `publish` | The adapter may perform a public egress write only when the event, aperture row, surface allowlist, rights, privacy, provenance, egress, and reference checks pass. |
| `link` | The adapter may expose or reuse a public URL only when the event carries a valid public URL or an allowed reference and the surface is in policy. |
| `embed` | The adapter may embed a video, image, card, block, or external link when the aperture allows embedding and required refs exist. |
| `redact` | The adapter may transform copy according to `redaction_policy` or surface redactions before any public copy leaves the system. |
| `hold` | The adapter must do nothing public and should preserve the event/decision for audit, replay, or operator review. |
| `archive` | The adapter may attach event evidence to archive state only when `claim_archive` and required refs pass. |
| `replay` | The adapter may expose replay navigation or replay residency only when archive claim and replay refs pass. |

`hold` is the fail-closed universal action. All first-class apertures support
it, and a requested hold is an explicit successful decision rather than a silent
drop.

## Event-Driven Fanout

Fanout is event-driven and policy-aware:

1. A producer emits `ResearchVehiclePublicEvent`.
2. A router or adapter asks `decide_cross_surface_fanout(event, aperture, action)`.
3. The helper intersects the event's `surface_policy.allowed_surfaces` and
   `denied_surfaces` with the aperture row's target surfaces.
4. The helper checks event type, requested action, rights, privacy, provenance,
   public-claim flags, archive flags, human-review gates, and required refs.
5. The adapter may act only on `decision: allow`; it must hold, redact, or deny
   exactly as the decision says.
6. A blocked or degraded decision is written or reported as `fanout.decision`
   health instead of disappearing.

This is the migration path for legacy `broadcast_rotated` tailers. The
Mastodon, Bluesky, Discord, and Are.na implementation children should move to
canonical public events, but this contract branch does not edit those adapters.

## Failure And Health

Failure is a first-class decision, not a silent skip.

| Reason | Required behavior |
|---|---|
| `surface_denied` or `surface_not_allowed` | Do not publish; report blocked health with the target aperture and child task. |
| `event_type_not_allowed` | Do not coerce the event into a surface-native shape; route to the bounded adapter child. |
| `action_not_supported` | Deny that action for the aperture. |
| `rights_blocked` | Deny public publication and monetized use. |
| `privacy_blocked` | Deny public publication unless a current consent/public policy exists upstream. |
| `missing_provenance` | Deny publication and emit/report `fanout.decision`. |
| `egress_blocked` | Hold live/link/embed actions; archive or replay may proceed only through archive policy. |
| `archive_claim_blocked` | Hold archive action. |
| `replay_claim_blocked` | Hold replay action. |
| `human_review_required` | Hold autonomous publication; operator-reviewed draft/publish paths remain separate. |
| `missing_surface_reference` | Hold the target surface until `public_url`, `frame_ref`, or `chapter_ref` exists as required. |
| `upstream_hold:*` | Preserve the upstream blocker reason from `ResearchVehiclePublicEvent.surface_policy.dry_run_reason`. |

Health states:

- `ok`: target aperture may perform the resolved action.
- `degraded`: target aperture must hold, redact, dry-run, or wait for review.
- `blocked`: target aperture must not publish and should emit/report the decision.

## First-Class Apertures

| Aperture | Target surfaces | Current reality from reconcile | Child task |
|---|---|---|---|
| `youtube` | `youtube_description`, `youtube_cuepoints`, `youtube_chapters`, `youtube_captions`, `youtube_channel_sections` | active legacy / mixed YouTube work | `youtube-research-translation-ledger` |
| `omg_statuslog` | `omg_statuslog` | credential-blocked awareness fanout; statuslog unit missing | `omg-statuslog-public-event-adapter` |
| `omg_weblog` | `omg_weblog` | publication path active; operator-reviewed | `omg-weblog-rss-public-event-adapter` |
| `arena` | `arena` | code exists; missing unit | `arena-public-event-unit-and-block-shape` |
| `mastodon` | `mastodon` | mounted active canonical public-event input | `mastodon-public-event-adapter` |
| `bluesky` | `bluesky` | mounted active legacy input | `bluesky-public-event-adapter` |
| `discord` | `discord` | linked inactive legacy input | `discord-public-event-activation-or-retire` |
| `shorts` | `youtube_shorts` | unavailable/missing pipeline | `shorts-public-event-adapter` |
| `archive` | `archive` | active archive capture; public event link adapter missing | `archive-replay-public-event-link-adapter` |
| `replay` | `replay` | public replay-link adapter missing | `archive-replay-public-event-link-adapter` |

## Public Claim Policy

For `publish`, `link`, or `embed`, all of these must hold:

- The aperture row allows the action.
- The event type is in the aperture row's `allowed_event_types`.
- At least one target surface is allowed by `event.surface_policy`.
- No target surface is denied by `event.surface_policy`.
- Rights are `operator_original`, `operator_controlled`,
  `third_party_attributed`, or `platform_embedded`.
- Privacy is `public_safe` or `aggregate_only`.
- Provenance exists when required by the event.
- If the event requires public egress truth, `claim_live` is true.
- Required surface refs exist for apertures that need a URL, frame, or chapter.
- Operator-review-only apertures hold direct autonomous publication.

For `archive` and `replay`, `claim_archive` and required refs are mandatory.
Archive/replay can be weaker than live publication, but they still carry rights,
privacy, provenance, and reference obligations.

## Aperture Notes

YouTube is a family aperture here, not a bundled implementation. YouTube title,
description, chapters, cuepoints, captions, channel sections, and Shorts remain
surface-specific work in YouTube child tasks.

OMG statuslog may consume `broadcast.boundary`, `chronicle.high_salience`, and
`omg.statuslog` events under cadence and credential gates. OMG weblog is
operator-reviewed and must hold direct autonomous publish decisions.

Are.na must not be claimed live until unit/block shape work exists. It needs
URL/image/citation block support and at least one surface reference.

Mastodon and Bluesky are currently active legacy tailers. Discord is linked but inactive.
Their public-event adapters must handle cursor truncation,
idempotency, allowlist, and failure-as-event behavior in their own tasks.

Shorts is first-class but unavailable until an extraction/upload pipeline emits
`shorts.candidate` and `shorts.upload` events with quota, rights, and archive
evidence.

Archive and replay are first-class apertures. Local archive capture is active,
but public replay links and replay residency still need explicit adapter work.

## Child Task Boundary

This contract intentionally routes implementation into bounded children:

- `mastodon-public-event-adapter`
- `bluesky-public-event-adapter`
- `discord-public-event-activation-or-retire`
- `arena-public-event-unit-and-block-shape`
- `omg-statuslog-public-event-adapter`
- `omg-weblog-rss-public-event-adapter`
- `shorts-public-event-adapter`
- `archive-replay-public-event-link-adapter`
- `publication-artifact-public-event-adapter`
- `youtube-research-translation-ledger`

No child task is implemented here.

## Acceptance

This seed is accepted when:

- `schemas/cross-surface-event-contract.schema.json` validates as JSON.
- The typed helper exposes all first-class apertures and all seven actions.
- Fanout decisions explain why an event reaches or does not reach a target
  aperture.
- Blocked/degraded fanout produces `fanout.decision` health fields.
- Docs and tests preserve the boundary that this is not an adapter bundle.

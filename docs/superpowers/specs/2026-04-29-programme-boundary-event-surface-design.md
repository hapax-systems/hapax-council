# Programme Boundary Event Surface - Design Spec

**Status:** schema seed for `programme-boundary-event-surface`
**Task:** `/home/hapax/Documents/Personal/20-projects/hapax-cc-tasks/active/programme-boundary-event-surface.md`
**Date:** 2026-04-29
**Depends on:** `research-vehicle-public-event-contract`
**Scope:** programme boundary event vocabulary, schema, mapping to `ResearchVehiclePublicEvent`, public/private mode, no-expert-system gate propagation, cuepoint/chapter distinction, and dry-run/unavailable reasons.
**Non-scope:** programme manager runtime implementation, YouTube API writes, live ad cuepoint insertion, VOD chapter writer implementation, archive/replay UI implementation, or public fanout.

## Purpose

Autonomous content programming needs a durable boundary stream.

Every content programme run has moments where it starts, declares criteria,
observes evidence, makes claims, assigns ranks, resolves comparisons, marks
uncertainty, refuses, corrects, proposes clips, creates chapters, or identifies
artifacts. Those moments are not private implementation details. They are
research observations and conversion inputs.

`ProgrammeBoundaryEvent` is the internal event contract that records those
moments before any public aperture consumes them. Some boundaries become
`ResearchVehiclePublicEvent` records. Some remain internal-only. Every boundary
keeps public/private mode and the no-expert-system gate result attached.

## Boundary Event Types

Initial `boundary_type` values:

| Boundary type | Meaning | Public event posture |
|---|---|---|
| `programme.started` | A programme run begins with format, subject, and public/private mode. | Usually maps to `programme.boundary` or remains internal for private runs. |
| `criterion.declared` | The run declares ranking/comparison/review criteria. | Maps to `metadata.update`, `chapter.marker`, or internal-only. |
| `evidence.observed` | The run observes a source, clip, substrate, citation, or local artifact. | Maps to `chronicle.high_salience`, `programme.boundary`, or internal-only. |
| `claim.made` | The run emits an evidence-bound claim. | Maps only if the grounding gate permits public/archive claim. |
| `rank.assigned` | A tier/ranking/bracket position is assigned. | Maps to `programme.boundary` or `chapter.marker` when public-safe. |
| `comparison.resolved` | A pairwise comparison or bracket decision resolves. | Maps to `programme.boundary` or internal-only. |
| `uncertainty.marked` | The run marks insufficient evidence, low confidence, or scope limit. | Maps to `programme.boundary` or `metadata.update` if public-safe. |
| `refusal.issued` | The run refuses a candidate, claim, source, or public conversion. | Maps to `publication.artifact` only when public-safe; otherwise internal-only. |
| `correction.made` | The run corrects a prior claim or boundary. | Maps to `publication.artifact`, `metadata.update`, or archive event. |
| `clip.candidate` | The run nominates a clip/window for replay, Shorts, or social use. | Maps to `shorts.candidate` or archive-only when rights/public gates pass. |
| `live_cuepoint.candidate` | The run nominates a live ad cuepoint for an active YouTube broadcast. | Maps to `cuepoint.candidate`, never to `chapter.marker`. |
| `chapter.boundary` | The run marks a replay/VOD chapter boundary. | Maps to `chapter.marker`; live ad cuepoints use `live_cuepoint.candidate`. |
| `artifact.candidate` | The run nominates a zine, dataset, replay card, post, or bundle. | Maps to `publication.artifact` or internal-only. |
| `programme.ended` | A programme run ends with outcome, refusal, correction, or next state. | Maps to `programme.boundary`, `metadata.update`, archive, or internal-only. |

## `ProgrammeBoundaryEvent` Schema Seed

The machine-readable seed lives at:

- `schemas/programme-boundary-event-surface.schema.json`

Required fields:

| Field | Meaning |
|---|---|
| `schema_version` | Event schema version. Initial value is `1`. |
| `boundary_id` | Stable idempotency key for this boundary. |
| `emitted_at` | UTC timestamp for the boundary emission. |
| `programme_id` | Active programme arc id. |
| `run_id` | Content programme run id. |
| `format_id` | Content programme format id. |
| `sequence` | Monotonic sequence number inside the run. |
| `boundary_type` | Typed programme boundary vocabulary. |
| `public_private_mode` | Private, dry-run, public-live, public-archive, or public-monetizable. |
| `grounding_question` | The question this programme is grounding. |
| `summary` | Human-readable boundary summary. |
| `evidence_refs` | Source ids, file refs, chunk ids, local paths, or public-event refs. |
| `no_expert_system_gate` | Gate state, infractions, claim permission, and gate ref. |
| `claim_shape` | Claim kind, authority ceiling, uncertainty, confidence, and scope. |
| `public_event_mapping` | Mapping to `ResearchVehiclePublicEvent` or explicit internal-only reason. |
| `cuepoint_chapter_policy` | Distinguishes live ad cuepoints from VOD chapters. |
| `dry_run_unavailable_reasons` | Reasons public conversion is blocked, dry-run, or unavailable. |
| `duplicate_key` | Stable duplicate suppression key for adapters. |

Example event:

```json
{
  "schema_version": 1,
  "boundary_id": "pbe_20260429t013500z_run_models_a_rank_003",
  "emitted_at": "2026-04-29T01:35:00Z",
  "programme_id": "programme_tierlist_models_20260429",
  "run_id": "run_20260429_models_a",
  "format_id": "tier_list",
  "sequence": 3,
  "boundary_type": "rank.assigned",
  "public_private_mode": "dry_run",
  "grounding_question": "Which model routes can Hapax currently justify for source-acquiring grounding work?",
  "summary": "Assigned OpenAI web search to the source-acquiring provider tier with provider-smoke still pending.",
  "evidence_refs": [
    "grounding_gate_20260429t013000z_tierlist_a",
    "source:openai_web_search_docs"
  ],
  "no_expert_system_gate": {
    "gate_ref": "grounding_gate_20260429t013000z_tierlist_a",
    "gate_state": "dry_run",
    "claim_allowed": true,
    "public_claim_allowed": false,
    "infractions": []
  },
  "claim_shape": {
    "claim_kind": "ranking",
    "authority_ceiling": "evidence_bound",
    "confidence_label": "medium_high",
    "uncertainty": "Live provider smoke and account availability are not yet verified.",
    "scope_limit": "Ranks current provider evidence only."
  },
  "public_event_mapping": {
    "internal_only": false,
    "research_vehicle_event_type": "programme.boundary",
    "state_kind": "programme_state",
    "source_substrate_id": "programme_cuepoints",
    "allowed_surfaces": ["youtube_chapters", "archive"],
    "denied_surfaces": ["youtube_cuepoints", "youtube_shorts", "monetization"],
    "fallback_action": "chapter_only",
    "unavailable_reasons": ["live_provider_smoke_missing", "dry_run_mode"]
  },
  "cuepoint_chapter_policy": {
    "live_ad_cuepoint_allowed": false,
    "vod_chapter_allowed": true,
    "live_cuepoint_distinct_from_vod_chapter": true,
    "chapter_label": "Model grounding provider ranking",
    "timecode": "00:00",
    "cuepoint_unavailable_reason": "dry_run_mode"
  },
  "dry_run_unavailable_reasons": ["dry_run_mode", "live_provider_smoke_missing"],
  "duplicate_key": "programme_tierlist_models_20260429:run_20260429_models_a:rank.assigned:003"
}
```

## ResearchVehiclePublicEvent Mapping

Programme boundaries map to `ResearchVehiclePublicEvent` only when public-event
policy allows it. The boundary owns programme semantics; the public event owns
public aperture policy.

| Boundary type | RVPE `event_type` | RVPE `state_kind` | Default surfaces | Internal-only when |
|---|---|---|---|---|
| `programme.started` | `programme.boundary` | `programme_state` | archive, YouTube chapters | private run or missing egress/archive evidence |
| `criterion.declared` | `metadata.update` or `chapter.marker` | `programme_state` | archive, YouTube chapters | criteria include private or ungrounded material |
| `evidence.observed` | `programme.boundary` or `chronicle.high_salience` | `research_observation` | archive, Are.na only with frame/citation | source rights/privacy/provenance blocked |
| `claim.made` | `programme.boundary` or `metadata.update` | `research_observation` | archive, metadata when safe | grounding gate blocks claim |
| `rank.assigned` | `programme.boundary` or `chapter.marker` | `programme_state` | archive, YouTube chapters | ranking lacks evidence or uncertainty |
| `comparison.resolved` | `programme.boundary` | `programme_state` | archive, chapters | comparison is private/dry-run or unsupported |
| `uncertainty.marked` | `programme.boundary` or `metadata.update` | `research_observation` | archive, status surfaces when safe | uncertainty text references private data |
| `refusal.issued` | `publication.artifact` | `archive_artifact` | archive, artifact pages when safe | refusal reveals private/sensitive data |
| `correction.made` | `publication.artifact` or `metadata.update` | `archive_artifact` | archive, metadata, correction artifact | correction cannot be public without exposing unsafe source |
| `clip.candidate` | `shorts.candidate` or `archive.segment` | `short_form` | archive, Shorts only after rights gate | third-party AV, privacy, or suitability unknown |
| `live_cuepoint.candidate` | `cuepoint.candidate` | `cuepoint` | YouTube live cuepoints | inactive broadcast, missing smoke evidence, dry-run mode, rate limit, quota, or egress block |
| `chapter.boundary` | `chapter.marker` | `chapter` | YouTube VOD chapters, archive | no archive/video id or unsafe label |
| `artifact.candidate` | `publication.artifact` | `archive_artifact` | archive, Are.na, OMG draft | artifact needs operator review or rights gate |
| `programme.ended` | `programme.boundary` or `metadata.update` | `programme_state` | archive, chapters, metadata | private run or missing gate result |

If `public_event_mapping.internal_only` is true, `research_vehicle_event_type`
must be `null` and `unavailable_reasons` must explain why.

## Public/Private And Gate Propagation

Every boundary carries:

- `public_private_mode`
- `no_expert_system_gate.gate_ref`
- `no_expert_system_gate.gate_state`
- `no_expert_system_gate.claim_allowed`
- `no_expert_system_gate.public_claim_allowed`
- `no_expert_system_gate.infractions`

Adapters must consume these values directly. They must not re-infer whether a
claim is safe from boundary type alone.

If a boundary contains any gate infraction, public conversion is blocked unless
the boundary itself is a public-safe refusal/correction artifact. Even then, the
artifact must name the refusal/correction posture rather than laundering the
blocked claim into public copy.

## Cuepoint And Chapter Policy

Live ad cuepoints and VOD chapters are distinct.

`cuepoint_chapter_policy.live_ad_cuepoint_allowed` means a live adapter may
attempt YouTube live cuepoint insertion under the current broadcast, quota,
smoke-test, and egress policy. It never implies a VOD chapter exists.

`cuepoint_chapter_policy.vod_chapter_allowed` means the boundary may become a
deterministic replay or VOD chapter if archive/video evidence exists.
It never implies a live ad cuepoint was sent or accepted.

When live cuepoints are blocked, rejected, rate-limited, not smoke-verified, or
disabled by dry-run mode, the adapter may still preserve a chapter candidate
with fallback action `chapter_only` if archive policy allows it.

## Dry-Run And Unavailable Reasons

Public conversion blockers must be explicit. Allowed initial reasons:

- `private_mode`
- `dry_run_mode`
- `missing_grounding_gate`
- `grounding_gate_failed`
- `unsupported_claim`
- `source_stale`
- `rights_blocked`
- `privacy_blocked`
- `egress_blocked`
- `audio_blocked`
- `archive_missing`
- `video_id_missing`
- `cuepoint_smoke_missing`
- `cuepoint_api_rejected`
- `rate_limited`
- `monetization_blocked`
- `operator_review_required`
- `live_provider_smoke_missing`

The boundary event remains useful even when public conversion is unavailable:
the run store, archive/replay, evaluator, opportunity model, and correction
trail can still consume it.

## Acceptance Pin

This spec is complete only if:

- all required boundary event types are named in spec and schema,
- every boundary preserves public/private mode and no-expert-system gate result,
- each boundary type maps to `ResearchVehiclePublicEvent` fields or explicitly internal-only,
- live ad cuepoints are distinct from VOD chapters,
- dry-run/unavailable reasons are machine-readable,
- the schema and docs tests pin the contract.

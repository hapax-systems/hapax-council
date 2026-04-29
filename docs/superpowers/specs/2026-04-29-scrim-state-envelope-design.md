# Scrim State Envelope - Design Spec

**Status:** schema/fixture/test packet for `scrim-state-envelope-schema-fixtures`
**Task:** `/home/hapax/Documents/Personal/20-projects/hapax-cc-tasks/active/scrim-state-envelope-schema-fixtures.md`
**Date:** 2026-04-29
**Depends on:** Scrim programme/director behavior contract, Director WCS read model, Programme WCS integration, and WCS health no-false-grounding.
**Scope:** typed `ScrimStateEnvelope`, conservative visual posture enums, WCS/director/programme refs, bounded gesture queue, fail-closed stale/missing state, and fixture families.
**Non-scope:** compositor implementation, shader control, programme scheduling, public-event publishing, monetization decisions, or claim-authority expansion.

## Purpose

`ScrimStateEnvelope` is the machine-readable state packet for the nebulous
scrim as a WCS expression surface. It tells the compositor what atmosphere may
be rendered from already-established programme, WCS, director, boundary, and
health facts.

The envelope is not a source of truth. It cannot make a programme public, make
a claim safe, grant monetization readiness, prove rights, or imply live control.
When state is missing, stale, expired, blocked, private-only, dry-run, refused,
or corrected, the scrim must fall closed to a quiet visual posture.

Machine-readable files:

- `schemas/scrim-state-envelope.schema.json`
- `config/scrim-state-envelope-fixtures.json`

## Envelope Contract

Required top-level fields:

| Field | Meaning |
|---|---|
| `schema_version` | Contract version, currently `1`. |
| `state_id` | Stable scrim state id. |
| `generated_at` / `expires_at` / `ttl_s` | Freshness window for this state packet. |
| `mode` | Active, private-only, dry-run, fallback, or suppressed posture. |
| `programme_id`, `run_id`, `format_id`, `condition_id` | Programme/run/format/condition references from the programme surface. |
| `profile_id` | Canonical scrim profile enum. |
| `permeability_mode` | Canonical permeability enum. |
| `density`, `refraction`, `tint_family`, `texture_family`, `motion_rate`, `breath_rate`, `depth_bias` | Bounded visual parameters. |
| `focus_regions` | Bounded normalized regions derived from WCS/director/boundary refs. |
| `gesture_queue` | Bounded visual gestures with TTL and source move refs. |
| `public_private_mode` | Effective public/private/dry-run mode inherited from programme/WCS state. |
| `evidence_status`, `health_state`, `claim_posture` | WCS and posture facts used for fail-closed rendering. |
| `blocked_reasons` | Auditable blockers from rights, consent/privacy, monetization, health, freshness, or boundary events. |
| `source_refs` | Source/evidence refs consumed by the state packet. |
| `director_move_refs` | Director move rows that proposed staging. |
| `boundary_event_refs` | Programme boundary refs, never duplicated boundary payloads. |
| `wcs_snapshot_ref` | WCS snapshot that authorized the current posture. |
| `health_ref` | World-surface health record ref. |
| `fallback_mode` | Fail-closed posture. |
| `public_claim_allowed` | Boolean inherited from WCS/public-event policy. The scrim never grants it. |
| `public_claim_basis_refs` | WCS/public-event refs that justify any true value. |
| `separation_policy` | Pinned single-operator and no-claim-expansion rules. |

## Canonical Enums

Profile enum:

- `gauzy_quiet`
- `warm_haze`
- `moire_crackle`
- `clarity_peak`
- `dissolving`
- `ritual_open`
- `rain_streak`

Permeability enum:

- `semipermeable_membrane`
- `solute_suspension`
- `ionised_glow`

Claim posture enum:

- `fresh`
- `uncertain`
- `blocked`
- `private_only`
- `dry_run`
- `refusal`
- `correction`
- `conversion_ready`
- `conversion_held`

## Gesture Queue

`gesture_queue[]` contains bounded visual gestures only. A gesture is not an
imperative compositor call and is not proof that live control occurred.

Each gesture must include:

- `gesture_id`
- `gesture_type`
- `created_at`
- `ttl_s`, capped at 30 seconds
- `intensity`, bounded from 0.0 to 1.0
- `target_region_refs`
- `source_move_refs`, with at least one director move ref
- `fallback_behavior`

The queue is capped at eight gestures. On missing or invalid gesture state,
consumers should drop the gesture and hold the envelope fallback posture.

## Fail-Closed Rules

The schema pins fail-closed behavior for stale, missing, unknown, or expired
state. When `evidence_status` or `health_state` is `stale`, `missing`, or
`unknown`, `fallback_mode` must be either `neutral_hold` or
`minimum_density`, and `public_claim_allowed` must be false.

Any non-`none` fallback mode also forces `public_claim_allowed=false`. Private,
dry-run, uncertain, blocked, refusal, correction, and conversion-held postures
likewise cannot carry a public claim allowance.

`public_claim_allowed=true` is only valid when the WCS/public-event path already allows it, the envelope is fresh and healthy, there are no blocked reasons, and
`fallback_mode=none`. The scrim can express that posture; it does not create it.

## Public Claim Scope

The separation policy is structural:

- `single_operator_only = true`
- `scrim_grants_public_claim_authority = false`
- `scrim_grants_live_control = false`
- `public_claim_allowed_inherited_from_wcs = true`
- `public_claim_scope_expansion_allowed = false`
- `missing_or_stale_state_fails_closed = true`

No fixture, consumer, or downstream policy may interpret density, glow,
clarity, or gesture presence as public truth, rights clearance, monetization
readiness, or live control.

## Fixture Catalog

The fixture seed includes these families:

- `fresh_public_safe`
- `stale`
- `private_only`
- `dry_run`
- `rights_blocked`
- `consent_privacy_blocked`
- `monetization_held`
- `refusal`
- `correction`
- `conversion_ready`
- `health_failed`
- `expired`

The stale and expired fixtures use `neutral_hold` or `minimum_density`. The
blocked, private-only, dry-run, refusal, correction, monetization-held, and
health-failed fixtures have `public_claim_allowed=false`.

## Downstream Contract

Consumers must preserve the WCS snapshot ref, health ref, director move refs,
boundary refs, blocked reasons, fallback mode, public/private mode, and
separation policy. They may render a quiet visual posture. They must not infer truth, public safety, rights clearance, monetization readiness, live control, or
operator consent from the scrim itself.

Follow-on tasks may map programme policy to profile choice, director move rows
to gesture queue entries, and WCS claim posture to scrim posture gates. Those
tasks must use this envelope as their shared boundary.

## Example Envelope

```json
{
  "schema_version": 1,
  "state_id": "scrim_state:fresh_public_safe:20260429",
  "generated_at": "2026-04-29T13:46:00Z",
  "expires_at": "2026-04-29T13:47:00Z",
  "ttl_s": 60,
  "mode": "active",
  "programme_id": "programme:content_grounding:20260429",
  "run_id": "run:public_archive:evidence_audit:20260429",
  "format_id": "evidence_audit",
  "condition_id": "condition:archive_public_safe",
  "profile_id": "gauzy_quiet",
  "permeability_mode": "semipermeable_membrane",
  "density": 0.32,
  "refraction": 0.18,
  "tint_family": "cool_clear",
  "texture_family": "fine_mist",
  "motion_rate": 0.24,
  "breath_rate": 0.18,
  "depth_bias": 0.44,
  "focus_regions": [
    {
      "region_id": "region:archive_evidence_card",
      "kind": "programme",
      "bounds": {"x": 0.18, "y": 0.2, "width": 0.44, "height": 0.36},
      "source_refs": ["wcs-snapshot:public_safe:20260429"]
    }
  ],
  "gesture_queue": [
    {
      "gesture_id": "scrim_gesture:fresh_public_safe:soften",
      "gesture_type": "soften",
      "created_at": "2026-04-29T13:46:00Z",
      "ttl_s": 12,
      "intensity": 0.22,
      "target_region_refs": ["region:archive_evidence_card"],
      "source_move_refs": ["director-move:stabilize:evidence_card"],
      "fallback_behavior": "neutral_hold"
    }
  ],
  "public_private_mode": "public_archive",
  "evidence_status": "fresh",
  "health_state": "healthy",
  "claim_posture": "fresh",
  "blocked_reasons": [],
  "source_refs": ["source:operator_owned_archive_segments"],
  "director_move_refs": ["director-move:stabilize:evidence_card"],
  "boundary_event_refs": ["programme-boundary:evidence_audit:intro"],
  "wcs_snapshot_ref": "wcs-snapshot:public_safe:20260429",
  "health_ref": "world-surface-health:healthy:20260429",
  "fallback_mode": "none",
  "public_claim_allowed": true,
  "public_claim_basis_refs": [
    "wcs-snapshot:public_safe:20260429",
    "research-vehicle-public-event:evidence_audit:20260429"
  ],
  "separation_policy": {
    "single_operator_only": true,
    "scrim_grants_public_claim_authority": false,
    "scrim_grants_live_control": false,
    "public_claim_allowed_inherited_from_wcs": true,
    "public_claim_scope_expansion_allowed": false,
    "missing_or_stale_state_fails_closed": true
  }
}
```

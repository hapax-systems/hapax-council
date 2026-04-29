# Director Substrate Control Plane - Design Spec

**Status:** schema seed for `director-substrate-control-plane`
**Task:** `/home/hapax/Documents/Personal/20-projects/hapax-cc-tasks/active/director-substrate-control-plane.md`
**Date:** 2026-04-29
**Scope:** director vocabulary generation, control move envelope, evidence/freshness/fallback
rules, audit outputs, and child implementation split.
**Non-scope:** production adapters, YouTube writes, PipeWire/audio topology, compositor layout
rewrites, public-event schema changes, or `audit-18` implementation itself.

## Purpose

The director should control typed livestream affordances, not guess from a narrow
visible-surface prompt. The substrate registry says what content carriers exist.
The spectacle control plane says which lanes are mounted or candidate. This
contract turns those facts into bounded director moves.

A director move is allowed only when the target is a known substrate, spectacle
lane, ward, camera, Re-Splay device, private control, cuepoint, or claim binding
with explicit evidence, freshness, and fallback behavior. If the target is not
available, the move still emits an auditable result: no-op, dry-run, fallback, or operator-facing reason. Nothing disappears silently.

## Inputs Consumed

- `docs/superpowers/specs/2026-04-28-livestream-substrate-registry-design.md`
- `docs/superpowers/specs/2026-04-28-spectacle-control-plane-design.md`
- `schemas/livestream-content-substrate.schema.json`
- `schemas/spectacle-control-plane.schema.json`
- `/home/hapax/Documents/Personal/20-projects/hapax-research/specs/2026-04-28-livestream-research-vehicle-suitcase-parent-spec.md`
- `/home/hapax/Documents/Personal/20-projects/hapax-research/plans/2026-04-28-livestream-suitcase-wsjf-workload.md`
- active anchors:
  - `audit-18-director-loop-programme-integration`
  - `ytb-004-programme-boundary-cuepoints`
  - `ytb-SS2-substantive-speech-research`
  - `ytb-SS3-long-arc-narrative-continuity`

## Current Integration Points

The existing system already has useful pieces, but no common director substrate
control envelope.

| Surface | Current anchor | Control-plane implication |
|---|---|---|
| Narrative director | `agents/studio_compositor/director_loop.py` emits `DirectorIntent`, JSONL, `/dev/shm/hapax-director/narrative-state.json`, and DMN compositional impingements. | Runtime wire-up should translate accepted `DirectorControlMove` records into `DirectorIntent` enrichment and impingements, not replace the director loop. |
| Structural director | `agents/studio_compositor/structural_director.py` emits slow `StructuralIntent` rows with `programme_id`. | Structural direction becomes one evidence source and one consumer of programme envelopes. |
| Programme manager | `agents/programme_manager/manager.py` transitions `Programme` records and emits ritual impingements via `transition.py`. | Programme boundaries need a JSONL/event surface before cuepoints or director `mark_boundary` can claim them. |
| Cuepoints | `agents/live_cuepoints/consumer.py` tails broadcast rotation events; programme-boundary cuepoints are explicitly deferred. | `ytb-004` should consume programme/public-event evidence, not direct internal triggers. |
| Private controls | `shared/operator_sidechat.py`, `agents/kdeconnect_bridge/*`, and `agents/streamdeck_adapter/*` write sidechat or dispatch command-registry commands. | Private controls are director affordances only with non-egress proof and private-only fallback. |
| Wards and claims | `shared.director_intent.WardId` and `agents/studio_compositor/ward_claim_bindings.py` expose ward targets and claim providers. | Ward vocabulary must include active ward state plus claim binding evidence, not static ward names alone. |
| Cameras | compositor status/layout state and camera commands expose active camera roles. | Camera moves must cite camera freshness and fallback when a role is absent or degraded. |
| Re-Splay | registry rows `re_splay_m8`, `re_splay_polyend`, `re_splay_steam_deck` are currently unavailable. | Re-Splay vocabulary may appear only as blocked/dry-run/no-op until hardware smoke and capture evidence exist. |

## `DirectorControlMove` Schema Seed

The machine-readable seed lives at:

- `schemas/director-substrate-control-plane.schema.json`

Required fields:

| Field | Meaning |
|---|---|
| `schema_version` | Move schema version. Initial value is `1`. |
| `decision_id` | Stable id for this decision/event. |
| `emitted_at` | Decision timestamp. |
| `director_tier` | Narrative, structural, programme, operator-control, or adapter origin. |
| `condition_id` | Research condition id or `none`. |
| `programme_id` | Active programme id, when available. |
| `verb` | One of the director control verbs. |
| `target` | Target type, id, display name, and source refs. |
| `vocabulary` | Terms generated for the director and the source refs that produced them. |
| `evidence` | Freshness-bearing evidence rows for every relevant source. |
| `freshness` | Aggregated freshness state for the move. |
| `execution_state` | Applied, no-op, dry-run, fallback, blocked, or operator-reason. |
| `fallback` | Explicit behavior when evidence or policy is missing. |
| `public_claim_allowed` | Whether the move may be represented on public surfaces as live/available. |
| `audit_event` | Event type and payload ref emitted for replay and health. |

Example:

```json
{
  "schema_version": 1,
  "decision_id": "dsm-20260429T0024Z-re-splay-hold",
  "emitted_at": "2026-04-29T00:24:00Z",
  "director_tier": "programme",
  "condition_id": "none",
  "programme_id": "listening-20260429-a",
  "verb": "hold",
  "target": {
    "target_type": "re_splay_device",
    "target_id": "re_splay_m8",
    "display_name": "Re-Splay M8",
    "source_refs": ["substrate:re_splay_m8", "lane:re_splay"]
  },
  "vocabulary": {
    "terms": ["Re-Splay M8", "M8 capture"],
    "source_refs": ["substrate:re_splay_m8", "lane:re_splay"],
    "generated_from": ["content_substrate", "spectacle_lane"]
  },
  "evidence": [
    {
      "source_type": "content_substrate",
      "ref": "re_splay_m8.integration_status",
      "status": "missing",
      "observed_at": null,
      "age_s": null,
      "ttl_s": null,
      "detail": "Hardware smoke has not landed."
    },
    {
      "source_type": "spectacle_lane",
      "ref": "re_splay.state",
      "status": "fresh",
      "observed_at": "2026-04-29T00:24:00Z",
      "age_s": 0,
      "ttl_s": 30,
      "detail": "Lane is blocked and public_claim_allowed is false."
    }
  ],
  "freshness": {
    "state": "missing",
    "checked_at": "2026-04-29T00:24:00Z",
    "blocking_refs": ["re_splay_m8.integration_status"]
  },
  "execution_state": "no_op",
  "fallback": {
    "mode": "no_op",
    "reason": "Re-Splay M8 is unavailable until hardware smoke and capture policy exist.",
    "operator_facing": true
  },
  "public_claim_allowed": false,
  "audit_event": {
    "event_type": "director.move.hold",
    "payload_ref": "director-control/dsm-20260429T0024Z-re-splay-hold.json",
    "health_ref": "director_control.moves.re_splay_m8"
  }
}
```

## Vocabulary Generation

Director vocabulary is generated per tick from typed sources. Static prompt
lists may remain as safety hints, but they are not authoritative.

Generation order:

1. Load `ContentSubstrate` rows and keep rows that are mounted, private,
   dry-run, degraded, public-live, or intentionally unavailable with fallback.
2. Load `SpectacleLaneState` rows and keep lanes that are mounted, private,
   dry-run, degraded, blocked, or candidate with an explicit reason.
3. Join lanes to substrate rows by `content_substrate_refs`.
4. Add active wards and ward claim bindings. A ward with a claim binding adds
   both the ward term and the claim name/posterior evidence.
5. Add active cameras from compositor status/layout evidence. A camera role is
   commandable only while its health evidence is fresh.
6. Add Re-Splay device rows from substrate and lane truth. Unavailable devices
   generate only blocked/no-op vocabulary.
7. Add private controls from sidechat, Stream Deck, and KDEConnect command
   surfaces. These controls never create public vocabulary or public claims.
8. Add cuepoint/programme-boundary terms only from programme-boundary events or
   `ResearchVehiclePublicEvent` records, once those adapters exist.
9. Add claim bindings from calibrated `Claim` envelopes, subject to the director
   surface floor. Below-floor claims may be named only as unknown/degraded.

Generated vocabulary must carry `source_refs[]` such as
`substrate:caption_in_band`, `lane:captions`, `ward:chat_ambient`,
`camera:c920-desk`, `control:stream_deck.key.7`, `cuepoint:programme_boundary`,
or `claim:vinyl_spinning`. Unknown source strings are rejected.

## Move Verbs And Audit Outputs

Every accepted or rejected move emits a `DirectorControlMove` plus one audit
event. The event names are fixed:

| Verb | Audit event | Required behavior |
|---|---|---|
| `foreground` | `director.move.foreground` | Promote a safe target to primary read; blocked targets become no-op or dry-run. |
| `background` | `director.move.background` | Keep target present but subordinate; missing targets explain why they cannot be backgrounded. |
| `hold` | `director.move.hold` | Preserve state for a bounded reason; valid for silence/listening and blocked dry-run holds. |
| `suppress` | `director.move.suppress` | Remove/mute/dampen output and record the risk or programme reason. |
| `transition` | `director.move.transition` | Move between roles/states only when source and target evidence are fresh. |
| `crossfade` | `director.move.crossfade` | Blend two known targets; stale target on either side degrades to transition or no-op. |
| `intensify` | `director.move.intensify` | Increase salience only for mounted safe targets; blocked/degraded targets cannot intensify. |
| `stabilize` | `director.move.stabilize` | Reduce churn or risk while preserving safe output; always allowed for known mounted targets. |
| `route_attention` | `director.move.route_attention` | Bias director/programme attention internally; private route-attention never leaks public output. |
| `mark_boundary` | `director.move.mark_boundary` | Emit programme/research/archive/public boundary only with boundary evidence and policy. |

The audit payload must include `decision_id`, `verb`, `target`, `evidence`,
`freshness`, `execution_state`, `fallback`, `public_claim_allowed`,
`programme_id`, `condition_id`, and optional `public_event_ref`.

## Evidence Freshness And Fallback

Every move must include at least one evidence row. Evidence statuses are:

- `fresh` - source is observed and within TTL
- `stale` - source exists but is older than its TTL
- `missing` - source is required but absent
- `unknown` - source exists but cannot be interpreted
- `not_applicable` - source is deliberately irrelevant to this move

Freshness is fail-closed. A public move needs fresh substrate, lane, egress,
audio when applicable, rights/privacy/provenance, renderability, and target
evidence. A private move still needs target evidence and a private fallback.

Fallback modes:

| Mode | Use |
|---|---|
| `no_op` | Known target exists but command cannot be executed now. |
| `dry_run` | The director may rehearse/explain without affecting public output. |
| `fallback` | A lower-risk substitute target or verb is applied. |
| `operator_reason` | The operator gets a reason/action; no hidden behavior. |
| `hold_last_safe` | Continue last safe state while evidence recovers. |
| `suppress` | Remove or mute the risky target. |
| `private_only` | Apply only to local/private control surfaces. |
| `degraded_status` | Report degraded state without claiming live control. |
| `kill_switch` | Stop the lane/capability until operator recovery. |

Unavailable targets must select one of these modes. They cannot be omitted from the audit stream when a programme or director tried to address them.

## Programme And Cuepoint Policy

`audit-18-director-loop-programme-integration` becomes an implementation anchor
under this contract. In plain task language: audit-18-director-loop-programme-integration becomes an implementation anchor, not a parallel narrow director task.

Implementation path:

1. Programme manager emits programme-boundary JSONL records with from/to ids,
   trigger, role, condition id, ritual hints, and freshness timestamp.
2. Director vocabulary builder imports active programme state and the latest
   boundary event.
3. `mark_boundary` creates a `DirectorControlMove` with boundary evidence.
4. Cuepoint adapter consumes the boundary event or downstream public-event
   record. It does not infer cuepoints from arbitrary internal state.
5. YouTube/public translation remains owned by public-event and YouTube
   translation tasks.

SS2 and SS3 remain blocked research/narrative substrates. They may add blocked
or candidate vocabulary, but no public speech lane can be claimed until audio,
egress, quality feedback, and public-growth gates are open.

## Private Control Policy

Sidechat, Stream Deck, and KDEConnect are private director affordances.

- Sidechat appends local JSONL via `shared.operator_sidechat`; it is never an
  egress or public fanout source.
- KDEConnect parses `hero`, `vinyl`, `fx`, `mode`, `ward`, `safe`, and
  `sidechat` messages. Unknown commands already return structured errors; the
  director contract preserves that as `operator_reason`.
- Stream Deck dispatches command-registry commands from YAML. Missing keys are
  unavailable controls, not invisible capabilities.

Private control moves can route attention, suppress, hold, stabilize, or issue
operator-facing reasons. They cannot set `public_claim_allowed=true` by
themselves.

## Child Implementation Split

Do not create one implementation umbrella. Split by producer/consumer surface
and keep existing task anchors.

| Child task id | Relationship | Write scope guidance |
|---|---|---|
| `director-vocabulary-builder` | New child of this contract. | Build typed vocabulary from substrate rows, lane rows, active wards, cameras, Re-Splay rows, private controls, cuepoints, and claims. |
| `director-control-move-audit-log` | New child of this contract. | Persist `DirectorControlMove` JSONL/artifacts and Prometheus counters for all ten verbs. |
| `director-programme-envelope-adapter` | Supersedes/implements `audit-18-director-loop-programme-integration`. | Enrich narrative/structural director prompts with programme/lane envelopes and accepted no-op behavior. |
| `programme-boundary-event-surface` | Child of `ytb-004-programme-boundary-cuepoints`. | Emit programme-boundary JSONL with freshness and duplicate keys; no YouTube write here. |
| `cuepoint-director-public-event-adapter` | Child of `ytb-004` and public-event contract. | Convert boundary/public-event evidence into cuepoints and `mark_boundary` moves with duplicate suppression. |
| `private-controls-director-adapter` | Child of this contract plus private controls surfaces. | Sidechat, Stream Deck, and KDEConnect controls as private-only moves with non-egress tests. |
| `camera-ward-claim-source-adapter` | Child of this contract. | Active cameras, active wards, and ward claim bindings as evidence-bearing vocabulary sources. |
| `re-splay-director-noop-adapter` | Child of Re-Splay hardware smoke tasks. | Keep M8/Polyend/Steam Deck explicit blocked/no-op until hardware and capture evidence land. |
| `director-runtime-wireup` | Final child after builder and audit log. | Feed accepted moves into `DirectorIntent` and compositional impingements without replacing the existing loop. |

Blocked until gates clear:

- SS2/SS3 autonomous speech substrate implementation.
- Mobile companion and lore lanes.
- Public fanout/YouTube writes not backed by `ResearchVehiclePublicEvent`.
- Any audio routing or private-monitor changes, which remain owned by audio
  safety tasks.

## Acceptance

This seed is accepted when:

- `schemas/director-substrate-control-plane.schema.json` defines
  `DirectorControlMove`, all target types, all verbs, evidence statuses,
  execution states, fallback modes, and audit event names.
- this spec identifies the current director, structural director, programme,
  cuepoint, private-control, ward, camera, Re-Splay, and claim-binding anchors.
- director vocabulary is generated from typed substrates, mounted spectacle
  lanes, wards, cameras, Re-Splay devices, private controls, cuepoints, and
  claim bindings.
- every move carries evidence, freshness, fallback, and audit output.
- unavailable lanes or controls explicitly become no-op, dry-run, fallback, or
  operator-facing reasons.
- child work splits implementation without duplicating
  `audit-18-director-loop-programme-integration`.

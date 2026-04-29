# Director Control Move Audit Log - Design Spec

**Status:** runtime seed and schema for `director-control-move-audit-log`
**Task:** `/home/hapax/Documents/Personal/20-projects/hapax-cc-tasks/active/director-control-move-audit-log.md`
**Date:** 2026-04-29
**Depends on:** `director-substrate-control-plane`, `programme-boundary-event-surface`,
and `research-vehicle-public-event-contract`
**Scope:** persisted director control-move records, no-op/dry-run/unavailable states,
rendered evidence, mark-boundary projections, replay hooks, metrics, grounding scorecard
hooks, and public-event adapter handoff.
**Non-scope:** director runtime execution, YouTube API writes, VOD chapter writer
implementation, Shorts extraction, archive UI, or public publication decisions.

## Purpose

Director moves are evidence, not just control messages.

The director control plane can foreground, suppress, stabilize, route attention,
or mark a boundary only when typed substrate and lane truth permits it. The audit
log records what the director tried, why it tried it, what evidence and gates
were consulted, what actually happened, and what downstream systems may consume.

Rejected moves are first-class records. A missing lane, stale source, dry-run
policy, or unavailable public adapter must produce an audit row with explicit
fallback. Silent omission is not allowed because later replay, grounding
evaluation, public-event conversion, and metrics would otherwise invent a cleaner
history than the system actually observed.

## Inputs Consumed

- `docs/superpowers/specs/2026-04-29-director-substrate-control-plane-design.md`
- `schemas/director-substrate-control-plane.schema.json`
- `docs/superpowers/specs/2026-04-29-programme-boundary-event-surface-design.md`
- `schemas/programme-boundary-event-surface.schema.json`
- `docs/superpowers/specs/2026-04-28-research-vehicle-public-event-contract-design.md`
- `schemas/research-vehicle-public-event.schema.json`
- `shared/director_vocabulary.py`
- `shared/director_control_audit.py`
- active train plan:
  `/home/hapax/Documents/Personal/20-projects/hapax-research/plans/2026-04-29-autonomous-content-programming-grounding-train.md`

## Audit Record Schema Seed

The machine-readable contract lives at:

- `schemas/director-control-move-audit-log.schema.json`

Runtime writer and Pydantic models live at:

- `shared/director_control_audit.py`

Required fields:

| Field | Meaning |
|---|---|
| `schema_version` | Audit record schema version. Initial value is `1`. |
| `audit_id` | Stable persisted audit id. |
| `recorded_at` | UTC timestamp when the audit record was written. |
| `decision_id` | Source `DirectorControlMove` decision id. |
| `programme_id` | Programme arc id associated with the move. |
| `run_id` | Content programme run id associated with the move. |
| `lane_id` | Spectacle lane id or `none` when the target was not lane-bound. |
| `verb` | One of the ten stable director control verbs. |
| `reason` | Human-readable reason, category, and source refs. |
| `source_move` | Reference back to the control-plane move target and director tier. |
| `execution_state` | What the control layer reported: applied, no-op, dry-run, fallback, blocked, operator-reason, or unavailable. |
| `result_state` | Normalized state for metrics and replay: applied, no-op, dry-run, fallback, blocked, or unavailable. |
| `evidence` | Freshness-bearing evidence rows consulted by the move. |
| `gate_results` | No-expert-system, public-claim, rights, privacy, egress, audio, monetization, archive, and cuepoint/chapter gate states. |
| `fallback` | Explicit behavior when execution was unavailable, blocked, dry-run, or degraded. |
| `rendered_evidence` | JSON artifact, replay, scorecard, and payload refs generated for inspection. |
| `mark_boundary_projection` | Boundary/chapter/clip/public-event projection without forced publication. |
| `audit_trail` | JSONL/artifact/metrics/replay/scorecard/public-event consumer hooks. |
| `metrics` | Counter name, labels, outcome, and observed value emitted for dashboards. |
| `public_claim_allowed` | Whether public surfaces may claim the move as live/available. |

Example audit record:

```json
{
  "schema_version": 1,
  "audit_id": "dcma_20260429t024000z_rank_boundary_001",
  "recorded_at": "2026-04-29T02:40:00Z",
  "decision_id": "dsm-20260429t023957z-rank-boundary",
  "programme_id": "programme_tierlist_models_20260429",
  "run_id": "run_20260429_models_a",
  "lane_id": "programme_cuepoints",
  "verb": "mark_boundary",
  "reason": {
    "summary": "Ranking criterion boundary is ready for replay chapters, but live cuepoints remain dry-run.",
    "category": "mark_boundary",
    "source_refs": [
      "boundary:pbe_20260429t023957z_rank_003",
      "gate:grounding_gate_20260429t023930z"
    ]
  },
  "source_move": {
    "director_move_ref": "director-control/dsm-20260429t023957z-rank-boundary.json",
    "director_tier": "programme",
    "target_type": "cuepoint",
    "target_id": "programme_boundary"
  },
  "execution_state": "dry_run",
  "result_state": "dry_run",
  "evidence": [
    {
      "source_type": "programme_boundary_event",
      "ref": "pbe_20260429t023957z_rank_003",
      "status": "fresh",
      "observed_at": "2026-04-29T02:39:57Z",
      "age_s": 3,
      "ttl_s": 60,
      "detail": "Boundary event carried rank.assigned with chapter fallback."
    },
    {
      "source_type": "research_vehicle_public_event",
      "ref": "rvpe.pending.programme_boundary",
      "status": "not_applicable",
      "observed_at": null,
      "age_s": null,
      "ttl_s": null,
      "detail": "Public event adapter has not consumed this dry-run boundary."
    }
  ],
  "gate_results": {
    "no_expert_system": {
      "gate": "no_expert_system",
      "state": "pass",
      "passed": true,
      "evidence_refs": ["grounding_gate_20260429t023930z"],
      "denial_reasons": []
    },
    "public_claim": {
      "gate": "public_claim",
      "state": "dry_run",
      "passed": false,
      "evidence_refs": ["egress:livestream"],
      "denial_reasons": ["dry_run_mode"]
    },
    "rights": {
      "gate": "rights",
      "state": "pass",
      "passed": true,
      "evidence_refs": ["source:operator_controlled_model_notes"],
      "denial_reasons": []
    },
    "privacy": {
      "gate": "privacy",
      "state": "pass",
      "passed": true,
      "evidence_refs": ["privacy:aggregate_only"],
      "denial_reasons": []
    },
    "egress": {
      "gate": "egress",
      "state": "dry_run",
      "passed": false,
      "evidence_refs": ["egress:livestream"],
      "denial_reasons": ["dry_run_mode"]
    },
    "audio": {
      "gate": "audio",
      "state": "not_applicable",
      "passed": true,
      "evidence_refs": [],
      "denial_reasons": []
    },
    "monetization": {
      "gate": "monetization",
      "state": "unavailable",
      "passed": false,
      "evidence_refs": ["monetization:readiness"],
      "denial_reasons": ["monetization_blocked"]
    },
    "archive": {
      "gate": "archive",
      "state": "pass",
      "passed": true,
      "evidence_refs": ["archive:local_replay"],
      "denial_reasons": []
    },
    "cuepoint_chapter": {
      "gate": "cuepoint_chapter",
      "state": "dry_run",
      "passed": false,
      "evidence_refs": ["boundary:pbe_20260429t023957z_rank_003"],
      "denial_reasons": ["cuepoint_smoke_missing", "dry_run_mode"]
    }
  },
  "fallback": {
    "mode": "chapter_only",
    "reason": "Keep a VOD chapter candidate and do not send a live cuepoint.",
    "applied": true,
    "operator_facing": false,
    "substitute_ref": "chapter:dcma_20260429t024000z_rank_boundary_001",
    "next_action": "public-event adapter may consume after egress and cuepoint smoke pass"
  },
  "rendered_evidence": {
    "summary": "Dry-run mark_boundary preserved as replay chapter evidence.",
    "payload_ref": "director-control/dcma_20260429t024000z_rank_boundary_001.json",
    "artifact_refs": [
      "director-control/dcma_20260429t024000z_rank_boundary_001.json"
    ],
    "replay_ref": "replay:programme_tierlist_models_20260429:00:00",
    "scorecard_ref": "grounding-scorecard:run_20260429_models_a"
  },
  "mark_boundary_projection": {
    "is_mark_boundary": true,
    "programme_boundary_ref": "pbe_20260429t023957z_rank_003",
    "chapter_candidate": {
      "candidate_id": "chapter_20260429t024000z_rank_boundary",
      "label": "Model grounding provider ranking",
      "timecode": "00:00",
      "allowed": true,
      "unavailable_reasons": []
    },
    "clip_candidate": {
      "candidate_id": "clip_20260429t024000z_rank_boundary",
      "start_s": 0,
      "end_s": 45,
      "allowed": false,
      "unavailable_reasons": ["shorts_rights_gate_pending"]
    },
    "public_event_ref": null,
    "force_publication": false
  },
  "audit_trail": {
    "sinks": [
      "jsonl",
      "artifact_payload",
      "prometheus_counter",
      "replay_index",
      "grounding_scorecard",
      "public_event_adapter"
    ],
    "consumers": [
      "replay",
      "metrics",
      "grounding_scorecard",
      "public_event_adapter",
      "dashboard"
    ],
    "duplicate_key": "programme_tierlist_models_20260429:run_20260429_models_a:mark_boundary:003",
    "jsonl_ref": "hapax-state/director-control/moves.jsonl",
    "artifact_ref": "hapax-state/director-control/artifacts/dcma_20260429t024000z_rank_boundary_001.json"
  },
  "metrics": {
    "counter_name": "hapax_director_control_move_total",
    "labels": {
      "verb": "mark_boundary",
      "execution_state": "dry_run",
      "result_state": "dry_run",
      "public_claim_allowed": "false"
    },
    "outcome": "chapter_candidate_preserved",
    "observed_value": 1
  },
  "public_claim_allowed": false
}
```

## Explicit Result States And Fallback

Every attempted move must choose a machine-readable `result_state`.

| Result state | Meaning |
|---|---|
| `applied` | The move changed the target or accepted a state transition. |
| `no_op` | The target was known, but no action was permitted or needed. |
| `dry_run` | The move was rehearsed, logged, or rendered without affecting public output. |
| `fallback` | A lower-risk substitute was applied. |
| `blocked` | A gate rejected execution and no substitute was applied. |
| `unavailable` | The target, adapter, render path, or evidence source is absent. |

Allowed fallback modes are `no_op`, `dry_run`, `fallback`, `operator_reason`,
`hold_last_safe`, `suppress`, `private_only`, `degraded_status`, `kill_switch`,
`unavailable`, `archive_only`, and `chapter_only`.

No-op, dry-run, and unavailable moves are not failures of the audit system. They
are valid records that keep later replay and scorecards honest.

## Mark Boundary Projection

`mark_boundary` moves connect the director control stream to programme boundary,
chapter, clip, and public-event work without publishing anything by themselves.

Rules:

- `mark_boundary_projection.is_mark_boundary` must be true for `verb=mark_boundary`.
- At least one of `programme_boundary_ref`, `chapter_candidate`, or
  `clip_candidate` must be present.
- `force_publication` is always false.
- `chapter_candidate` is a replay/navigation candidate, not a YouTube write.
- `clip_candidate` is a conversion candidate, not a Shorts upload.
- `public_event_ref` may be null until a public-event adapter consumes the record.

Public-event adapters may use the audit row only after their own egress, rights,
privacy, audio, archive, quota, and surface-policy gates pass.

## Audit Trail Consumers

The audit trail exposes the same record to multiple consumers without requiring
them to infer missing state.

| Consumer | Consumes | Must not infer |
|---|---|---|
| Replay | `jsonl_ref`, `artifact_ref`, `rendered_evidence`, `mark_boundary_projection` | Public publication or live cuepoint success. |
| Metrics | `metrics`, `verb`, `execution_state`, `result_state`, blocked gates | Programme truth not present in the record. |
| Grounding scorecard | `evidence`, `gate_results`, `fallback`, `rendered_evidence` | Expert-system authority beyond evidence. |
| Public-event adapter | `public_claim_allowed`, `mark_boundary_projection`, gate results | Live egress, audio safety, rights, or privacy state. |
| Dashboard | `audit_trail`, metrics outcome, explicit unavailable reasons | Silent success for missing targets. |

## Storage And Metrics Policy

Default runtime paths:

- JSONL: `~/hapax-state/director-control/moves.jsonl`
- Artifacts: `~/hapax-state/director-control/artifacts/<audit_id>.json`

`DirectorControlMoveAuditLog.record()` appends one JSONL line and writes one
artifact JSON payload. It rotates the JSONL at 5 MiB and keeps three generations.
Filesystem and metrics failures are logged at warning level and never break a
director tick.

Metrics:

- `hapax_director_control_move_total{verb,execution_state,result_state,public_claim_allowed}`
- `hapax_director_control_move_gate_block_total{gate,state}`

The first counter has one result for every attempted move across all ten verbs:
`foreground`, `background`, `hold`, `suppress`, `transition`, `crossfade`,
`intensify`, `stabilize`, `route_attention`, and `mark_boundary`.

## Failure Behavior

- Missing evidence produces `result_state=unavailable` or `blocked`, not a
  dropped row.
- Public-claim denial keeps `public_claim_allowed=false` even when archive or
  replay consumption remains allowed.
- Gate results are copied into the audit row. Adapters must consume them directly.
- If a JSON artifact cannot be written, the director tick continues and logs a
  warning.
- Duplicate suppression uses `audit_trail.duplicate_key`, not timestamp alone.

## Acceptance Pin

This packet is accepted when:

- `shared/director_control_audit.py` defines the typed audit record, JSONL/artifact
  writer, defensive read path, and metrics emitters.
- `schemas/director-control-move-audit-log.schema.json` requires programme id,
  run id, lane id, verb, reason, evidence, gate results, fallback, and rendered
  evidence.
- no-op, dry-run, and unavailable states are explicit in schema and spec.
- `mark_boundary` records can carry chapter and clip candidates but
  `force_publication` is fixed false.
- replay, metrics, grounding scorecard, dashboard, and public-event adapter
  consumers are named.
- docs and shared tests pin the contract.

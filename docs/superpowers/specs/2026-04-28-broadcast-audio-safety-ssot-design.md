# Broadcast Audio Safety SSOT Alignment - Design Spec

**Status:** alignment contract for `broadcast-audio-safety-ssot`
**Task:** `/home/hapax/Documents/Personal/20-projects/hapax-cc-tasks/active/broadcast-audio-safety-ssot.md`
**Date:** 2026-04-28
**Scope:** owner map, SSOT boundaries, fail-closed private-route contract, health payload shape, and remaining child tasks.
**Non-scope:** direct PipeWire, WirePlumber, or physical routing mutation.

## Purpose

Broadcast audio safety is not a new graph. It is the contract that lets the
livestream egress resolver, livestream health group, and monetization readiness
ledger consume audio truth without inventing a second policy layer.

The current audio system already has several active and recently closed claims.
This spec aligns them:

- `wsjf-004-audio-broadcast-safety-verification` closed the immediate private
  leak by making private and notification sinks fail closed.
- `audio-topology-descriptor-l12-drift` closed PR #1764 and refreshed
  `config/audio-topology.yaml` for the live L-12 graph.
- `audio-private-monitor-off-l12-bridge` owns restoring audible private
  monitoring without falling back to L-12 or other broadcast paths.
- `audio-l12-forward-invariant-ci-guard` owns the static forward-direction CI
  guard now that the descriptor is current.
- `youtube-player-real-content-ducker-smoke` owns the real YouTube
  player/ducker smoke and its no-private-leak evidence.

This spec is the umbrella map across those claims. It should prevent duplicate
audio tasks and keep public-live health consumers bound to evidence.

## Current Audit Finding

As of this audit:

- `shared/audio_loudness.py` exists and is the numeric loudness/dynamics SSOT.
- `config/audio-topology.yaml` exists and models the L-12, broadcast-master,
  TTS broadcast, PC loudnorm, S-4, M8, and fail-closed private/notification
  graph.
- `scripts/hapax-audio-topology`, `shared/audio_topology.py`,
  `shared/audio_topology_generator.py`, and
  `shared/audio_topology_inspector.py` consume the descriptor for generation,
  verification, audit, and TTS broadcast path checks.
- `scripts/audio-leak-guard.sh` verifies the inverse private-route invariant.
- `config/audio-routing.yaml`, `config/pipewire/generated/`, and
  `scripts/generate-pipewire-audio-confs.py` are still future Phase 6 surfaces
  from the approved livestream audio architecture. They are not present in the
  current repo.
- Current PipeWire/WirePlumber files under `config/pipewire/` and
  `config/wireplumber/` are therefore still policy-bearing implementation
  artifacts for Phase 1-5, but they must not become independent SSOTs.

The correct next move is a contract and health shape, not a direct route edit.

## Owner Map

| Domain | Current owner | Owns | Must not own |
|---|---|---|---|
| Loudness and dynamics constants | `shared/audio_loudness.py` plus `2026-04-23-livestream-audio-unified-architecture-design.md` | LUFS targets, true-peak ceilings, duck depths, attack/release, lookahead, tolerances, and headroom constants | Physical routes, source eligibility, live graph freshness, or private/broadcast classification |
| Route policy | Future Phase 6 `config/audio-routing.yaml`; until shipped, the approved audio architecture spec and active implementation confs | Per-source broadcast eligibility, wet/dry default, pre-normalization target, ducked-by triggers, and producer identity | Physical hardware inventory or generated PipeWire syntax |
| Physical topology descriptor | Closed task `audio-topology-descriptor-l12-drift`, PR #1764 | `config/audio-topology.yaml`, descriptor schema, live graph verification, current L-12/broadcast-master topology, descriptor tests | Per-source rights policy, loudness magic numbers, or live public readiness |
| Generated PipeWire artifacts | Future Phase 6 generator from route policy plus loudness constants; current Phase 1-5 confs are hand-mirrored implementation | PipeWire filter-chain and loopback fragments that implement declared policy | New source policy, independent limiter/ducker constants, or fallback behavior not expressed in the route policy |
| WirePlumber role policy | Existing `config/wireplumber/50-hapax-voice-duck.conf` and sibling role files | Media-role loopbacks: Assistant, Broadcast, Notification, Multimedia; preferred targets for those roles | Acoustic private-monitor restoration or direct fallback to default sinks |
| Private leak guard | Closed `wsjf-004` plus `scripts/audio-leak-guard.sh` | Inverse invariant: assistant/private/notification routes do not reach L-12, livestream taps, PC loudnorm, multimedia fallbacks, or voice-fx broadcast path | Choosing a new private monitor endpoint |
| Private monitor audibility | Active `audio-private-monitor-off-l12-bridge` | Explicit off-L-12 bridge from `hapax-private.monitor` and/or `hapax-notification-private.monitor` to proven private hardware | Weakening the fail-closed null-sink baseline |
| Forward L-12 invariant CI | Active `audio-l12-forward-invariant-ci-guard` | Static proof that each L-12-bound source has an intended broadcast forward path and private-only roles cannot reach broadcast | Rewriting current runtime routing |
| YouTube player ducker smoke | Active `youtube-player-real-content-ducker-smoke` | Real content smoke for `POST /play`, `yt-loudnorm.conf`, `voice-over-ytube-duck.conf`, duck behavior, and private leak absence | Canonical bus-side ducker replacement or route-policy Phase 6 |
| Health aggregation | Active `livestream-health-group`, blocked on upstream contracts | Consumes `audio_safe_for_broadcast` into livestream health and public readiness | Inferring safety from stale or partial audio facts |

## SSOT Boundaries

### `shared/audio_loudness.py`

This module is the only place for loudness and dynamics numbers:

- egress target integrated LUFS
- true-peak ceiling
- loudness range cap
- pre-normalization targets
- duck depths
- attack, release, lookahead
- regression tolerances

Anything that changes a limiter limit, compressor threshold, duck depth, or
measurement tolerance must change this module first. PipeWire conf comments may
mirror those values while Phase 1-5 are still hand-authored, but the comments
are not authoritative.

### Route Policy

The route policy decides what a source is allowed to do:

- whether the source may appear in broadcast
- whether it is wet by default through the Evil Pet/L-12 path or explicitly dry
- which sources duck it
- which pre-normalization target applies
- which producer owns it
- what rights/provenance class must be true before public egress

Future Phase 6 makes this `config/audio-routing.yaml`. Until then, the active
WirePlumber/PipeWire files and the approved 2026-04-23 architecture spec carry
that intent. No new source should get a bespoke loudnorm or ducker chain without
first being represented in the route-policy model.

### `config/audio-topology.yaml`

The topology descriptor is the physical and logical graph descriptor. It says
which nodes and edges are part of the current live L-12/broadcast-master graph
and which optional hardware/runtime nodes are expected-missing or external.

It is not the route-policy source. A node in the topology descriptor proves that
the graph has a known shape; it does not prove that the content is rights-safe,
public-safe, or currently measured in-band.

### PipeWire And WirePlumber Artifacts

PipeWire and WirePlumber configuration files are implementation artifacts. Their
long-term direction is generated output from:

1. `shared/audio_loudness.py`
2. `config/audio-routing.yaml`
3. `config/audio-topology.yaml`

Until the generator lands, current confs are hand-mirrored and must cite the
constant or policy they implement. They must not introduce independent magic
numbers or unmodeled fallbacks.

### Preflight And Health

Preflight is evidence assembly, not policy. It consumes:

- topology parse and live graph audit
- TTS broadcast path check
- leak guard result
- loudness and true-peak measurement
- OBS/broadcast ingest binding
- audio safety detector state
- user service freshness

The preflight output is the producer of `audio_safe_for_broadcast`. Health
consumers must not reconstruct safety by reading random PipeWire details.

## Fail-Closed Safety Contract

The private route rule is absolute:

> Assistant, private, and notification routes must fail closed away from every
> broadcast path.

Required behavior:

- `role.assistant` targets `hapax-private`.
- `role.notification` targets `hapax-notification-private`.
- `hapax-private` and `hapax-notification-private` are null sinks with no
  downstream playback bridge unless `audio-private-monitor-off-l12-bridge`
  ships an explicit off-L-12 bridge and guard coverage for its target.
- Missing private monitor hardware produces silence, not fallback to the default
  sink.
- Forbidden private/notification targets include L-12 outputs,
  `hapax-livestream`, `hapax-livestream-tap`, `hapax-voice-fx-capture`,
  `hapax-pc-loudnorm`, and `input.loopback.sink.role.multimedia`.
- `role.broadcast` is the only Hapax voice role allowed to target
  `hapax-voice-fx-capture`.
- A stale, missing, malformed, or unverified graph is unsafe for public claims.

The current enforcement surfaces are:

- `scripts/audio-leak-guard.sh`
- `tests/scripts/test_audio_leak_guard.py`
- `tests/pipewire/test_private_sink_isolation.py`
- `tests/pipewire/test_notification_isolation.py`
- `tests/shared/test_canonical_audio_topology.py`
- `tests/test_l12_invariant_regressions.py`

`audio-private-monitor-off-l12-bridge` may make private audio audible again only
by preserving this contract. A direct target that can fall through to L-12 is a
regression even if it improves local audibility.

## `audio_safe_for_broadcast` Shape

The canonical audio health producer should publish one object. Exact transport
is implementation-owned by the future producer task, but the payload shape is:

```json
{
  "audio_safe_for_broadcast": {
    "safe": false,
    "status": "unsafe",
    "checked_at": "2026-04-28T00:00:00Z",
    "freshness_s": 0.0,
    "blocking_reasons": [
      {
        "code": "private_route_leak_guard_failed",
        "severity": "blocking",
        "owner": "scripts/audio-leak-guard.sh",
        "message": "assistant/private/notification route may reach broadcast",
        "evidence_refs": ["leak_guard"]
      }
    ],
    "warnings": [],
    "evidence": {
      "topology": {
        "descriptor": "config/audio-topology.yaml",
        "verification": "pass",
        "unclassified_drift": false,
        "command": "scripts/hapax-audio-topology verify config/audio-topology.yaml"
      },
      "private_routes": {
        "leak_guard": "pass",
        "assistant_target": "hapax-private",
        "notification_target": "hapax-notification-private",
        "private_downstream_bridge": "absent_fail_closed",
        "notification_downstream_bridge": "absent_fail_closed"
      },
      "broadcast_forward": {
        "tts_broadcast_path": "pass",
        "command": "scripts/hapax-audio-topology tts-broadcast-check"
      },
      "loudness": {
        "stage": "hapax-broadcast-normalized.monitor",
        "integrated_lufs_i": null,
        "target_lufs_i": -14.0,
        "true_peak_dbtp": null,
        "target_true_peak_dbtp": -1.0,
        "within_target_band": false,
        "measurement_age_s": null
      },
      "egress_binding": {
        "expected_sources": [
          "hapax-broadcast-normalized",
          "hapax-obs-broadcast-remap"
        ],
        "bound": false,
        "observed_source": null
      },
      "runtime_safety": {
        "vinyl_pet_detector": "unknown",
        "audio_safety_service": "unknown",
        "pipewire": "unknown",
        "wireplumber": "unknown"
      }
    },
    "owners": {
      "loudness_constants": "shared/audio_loudness.py",
      "route_policy": "config/audio-routing.yaml when Phase 6 ships",
      "topology": "config/audio-topology.yaml",
      "leak_guard": "scripts/audio-leak-guard.sh",
      "health_consumer": "livestream-health-group"
    }
  }
}
```

Semantics:

- `safe=true` only when every blocking reason is absent and evidence is fresh.
- `status` is one of `safe`, `unsafe`, `degraded`, or `unknown`.
- `unknown` is not public-safe. It must map to `safe=false`.
- `warnings` may carry non-blocking evidence such as optional hardware absence.
- `blocking_reasons[]` must be machine-readable. Consumers should display
  messages, but decisions should branch on `code`.
- Health consumers should embed this object under the livestream health
  `audio` component and should derive `audio_floor` from `safe`.

## Implementation Binding

The live producer is `agents.broadcast_audio_health`, scheduled by
`hapax-broadcast-audio-health.timer` every 30 seconds. It writes the canonical
envelope to `/dev/shm/hapax-broadcast/audio-safe-for-broadcast.json`.

Logos exposes the same object at `GET /api/studio/audio/safe-for-broadcast`,
and `shared.livestream_egress_state` derives `audio_floor` from
`audio_safe_for_broadcast.safe` rather than raw perception energy.

Runtime safety comes from `hapax-audio-safety.service`, which publishes
`/dev/shm/hapax-audio-safety/state.json` with `status` and `breach_active`.
Missing, stale, malformed, non-`clear`, or breached runtime state is unsafe.

## Blocking Conditions

The health producer must set `safe=false` when any of these is true:

- `config/audio-topology.yaml` fails to parse.
- Live topology verification reports unclassified drift.
- `scripts/audio-leak-guard.sh` exits non-zero.
- `role.assistant` does not target `hapax-private`.
- `role.notification` does not target `hapax-notification-private`.
- `hapax-private` or `hapax-notification-private` has a downstream target that
  matches a forbidden broadcast/default path.
- `role.broadcast` is missing or does not target `hapax-voice-fx-capture`.
- `scripts/hapax-audio-topology tts-broadcast-check` fails.
- Loudness or true-peak evidence is stale, missing, or outside the configured
  pass band once metering exists.
- OBS or the active RTMP pipeline is not bound to `hapax-broadcast-normalized`
  or `hapax-obs-broadcast-remap` when a public-live claim is being made.
- `hapax-audio-safety` reports an active vinyl-into-Evil-Pet breach.
- Required user services for PipeWire, WirePlumber, broadcast audio safety, or
  the selected audio health producer are failed or stale.

## Child Task Recommendations

No new child should duplicate the active topology, private-monitor, forward CI,
or YouTube ducker smoke tasks.

Recommended missing child tasks:

1. `broadcast-audio-health-producer`
   - Implement the `audio_safe_for_broadcast` producer shape above.
   - Consume topology verification, TTS broadcast check, leak guard, loudness
     evidence, egress binding, `hapax-audio-safety`, and service freshness.
   - Publish a state file/API consumed by `livestream-health-group` and
     `livestream-egress-state-resolver`.

2. `audio-routing-policy-phase6-bootstrap`
   - Ship the Phase 6 route-policy bootstrap from the approved 2026-04-23
     architecture: `config/audio-routing.yaml`,
     `scripts/generate-pipewire-audio-confs.py`, and generated artifact
     discipline.
   - Acceptance must prove current hand-authored confs round-trip or explicitly
     document every non-round-trippable Phase 1-5 artifact.

State changes to existing tasks:

- `audio-l12-forward-invariant-ci-guard` should be unblocked because
  `audio-topology-descriptor-l12-drift` is closed in PR #1764.
- `audio-private-monitor-off-l12-bridge` remains valid and should not be
  collapsed into this umbrella spec.
- `youtube-player-real-content-ducker-smoke` remains valid and should record
  real-content evidence rather than broaden into route-policy work.

## Acceptance

This SSOT alignment is accepted when:

- the owner map above is the durable reference for downstream audio tasks
- health consumers use `audio_safe_for_broadcast` rather than ad hoc booleans
- private and notification routes remain fail-closed when private hardware is
  absent
- route-policy Phase 6 remains distinct from topology-descriptor drift repair
- no direct routing changes were made without task ownership and proof

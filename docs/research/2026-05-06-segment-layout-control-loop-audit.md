# Segment Layout Control Loop Audit

Date: 2026-05-06
Task: `segment-layout-control-loop-chaos-guards`
Lane: `cx-green`

## Current Surfaces

`agents/studio_compositor/layout_switcher.py` is the legacy layout selector. It is a static priority policy: consent-safe wins, then vinyl/director/deep-mode signals, then `default_fallback`. That fallback is correct for non-responsible compositor contexts and must remain available there.

`agents/studio_compositor/layout_tick_driver.py` drives layout ticks inside the compositor process. It now checks current-beat segment pressure before falling back to the legacy selector. The legacy selector remains a static priority policy for non-responsible contexts only.

`agents/studio_compositor/segment_content_ward.py` renders active segment state from shared memory, but it does not arbitrate layout responsibility or emit receipts tying the spoken/action intent to rendered layout readbacks.

`agents/studio_compositor/ward_properties.py` is the local model for chaos-control mechanics: short TTL reads, explicit expiries, and atomic write/rename semantics. The new layout contract mirrors that posture at the decision level: bounded inputs, fresh readbacks, expiry, and visible receipts.

## Narrow Patch

The patch adds `agents/studio_compositor/segment_layout_control.py` as the pure responsibility controller and wires it through the compositor-side tick path. It does not edit `run_loops_aux.py`, prepared-playback tests, the legacy switcher, or playback/audio gates.

The controller consumes:

- Segment action intents with bounded need kinds, TTL, priority, expected effects, and evidence refs.
- Runtime readbacks: rendered active layout, active wards, ward properties, camera/chat/media availability, safety state, segment playback refs, and segment action-intent refs.
- Prior layout-control state: current posture/layout, active need, priority, and dwell timestamp.

`layout_tick_driver` adapts parent `active-segment.json` current-beat proposals as pressure only. It reads `programme_id`, `current_beat_index`, `prepared_artifact_ref`, and `current_beat_layout_intents[].needs`; supported needs become `SegmentActionIntent` with `requested_layout=None`, `authority_ref=prepared_artifact:{sha}`, and evidence refs including that prepared-artifact ref. Parent `host_presence`, `spoken_argument`, layout names, surface IDs, coordinates, SHM paths, and cues are not consumed as authority.

Supported proposal needs are currently tier, ranked-list, chat, and comparison. Countdown, depth, camera, mood, and arbitrary layout/surface/coordinate proposals are documented in the adapter as `unsupported_segment_layout_need` refusals until the control loop has bounded postures for them.

The controller emits:

- A bounded `LayoutPosture`, not arbitrary layout commands.
- A `LayoutDecisionReceipt` containing input refs, readback refs, selected posture/layout, safety arbitration, satisfied and unsatisfied effects, denied intents, fallback reason, applied layout/ward/action changes, and spoken-text alteration state.

## Responsible Hosting Invariants

`default`, `default-legacy`, and `garage-door` are static/non-responsible layouts. In `responsible_hosting` mode they are never accepted as successful selected layouts. If the first hosted-segment tick starts from static/default, the controller returns a held request with `default_static_layout_in_responsible_hosting`; the tick may apply the selected real segment layout, but success requires a later fresh rendered readback.

Fallback is allowed only as a named, TTL-bound, evidence-bearing receipt: `explicit_fallback` or `safety_fallback`. Fallback status is not `accepted`, does not set `layout_applied`, and does not grant playback/audio authority.

`PROGRAMME_CONTEXT` maps to `segment-programme-context`, not `default`. If that responsible layout is unavailable, the controller refuses with `unsupported_layout` instead of laundering through the legacy default.

`LayoutStore.set_active()` alone is not success. Accepted responsible decisions require a fresh rendered `LayoutState` readback whose active layout matches the bounded posture layout and whose critical `layout:*` and `ward:*` effects are satisfied. Missing, invisible, or alpha-zero required wards hold with `rendered_readback_mismatch`.

Real config layouts now exist for the bounded responsible postures: `segment-list`, `segment-compare`, `segment-detail`, `segment-poll`, `segment-receipt`, `segment-programme-context`, `segment-tier`, and `segment-chat`. Availability in tests is derived from `config/compositor-layouts`, not hardcoded fixture names.

Hysteresis/min dwell is mandatory for posture changes unless safety/consent fallback fires. Safety state is checked before dwell and records `safety_fallback` with `bypasses_hysteresis`.

The receipt never grants playback, audio, narration, or public action authority. Those remain owned by the broadcast/playback authorization chain and provenance gates.

Runtime receipts are written to `/dev/shm/hapax-compositor/segment-layout-receipt.json`. Held runtime mutations include rendered layout-state before/after hashes when available so blue-side runtime receipt validation can compare the accepted readback against the actual layout transition.

## Legacy Boundary

The legacy selector's `default_fallback` remains preserved behind an explicit `legacy_default`/non-responsible boundary. This keeps boot, garage-door, and operator fallback contexts stable while making hosted segment layout responsibility auditable.

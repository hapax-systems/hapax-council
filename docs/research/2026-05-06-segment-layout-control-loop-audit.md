# Segment Layout Control Loop Audit

Date: 2026-05-06
Task: `segment-layout-control-loop-chaos-guards`
Lane: `cx-green`

## Current Surfaces

`agents/studio_compositor/layout_switcher.py` is the legacy layout selector. It is a static priority policy: consent-safe wins, then vinyl/director/deep-mode signals, then `default_fallback`. That fallback is correct for non-responsible compositor contexts and must remain available there.

`agents/studio_compositor/layout_tick_driver.py` drives the legacy selector from periodic runtime signals and starts from `garage-door` when the `LayoutStore` has no active layout. Missing layouts are logged/skipped. This makes the `LayoutStore` active name/gauge advisory until the rendered compositor surface confirms the assignments/wards that actually appeared.

`agents/studio_compositor/segment_content_ward.py` renders active segment state from shared memory, but it does not arbitrate layout responsibility or emit receipts tying the spoken/action intent to rendered layout readbacks.

`agents/studio_compositor/ward_properties.py` is the local model for chaos-control mechanics: short TTL reads, explicit expiries, and atomic write/rename semantics. The new layout contract mirrors that posture at the decision level: bounded inputs, fresh readbacks, expiry, and visible receipts.

## Narrow Patch

The patch adds `agents/studio_compositor/segment_layout_control.py` as a pure responsibility controller. It does not edit `run_loops_aux.py`, prepared-playback tests, the legacy switcher, or playback/audio gates.

The controller consumes:

- Segment action intents with bounded need kinds, TTL, priority, expected effects, and evidence refs.
- Runtime readbacks: rendered active layout, active wards, ward properties, camera/chat/media availability, safety state, segment playback refs, and segment action-intent refs.
- Prior layout-control state: current posture/layout, active need, priority, and dwell timestamp.

The controller emits:

- A bounded `LayoutPosture`, not arbitrary layout commands.
- A `LayoutDecisionReceipt` containing input refs, readback refs, selected posture/layout, safety arbitration, satisfied and unsatisfied effects, denied intents, fallback reason, applied layout/ward/action changes, and spoken-text alteration state.

## Responsible Hosting Invariants

`default`, `default-legacy`, and `garage-door` are static/non-responsible layouts. In `responsible_hosting` mode they are never accepted as successful selected layouts. If a hosted segment readback is static/default while a responsible need is active, the controller refuses with `default_static_layout_in_responsible_hosting`.

Fallback is allowed only as a named, TTL-bound, evidence-bearing receipt: `explicit_fallback` or `safety_fallback`. Fallback status is not `accepted`, does not set `layout_applied`, and does not grant playback/audio authority.

`PROGRAMME_CONTEXT` maps to `segment-programme-context`, not `default`. If that responsible layout is unavailable, the controller refuses with `unsupported_layout` instead of laundering through the legacy default.

`LayoutStore.set_active()` alone is not success. Accepted responsible decisions require a fresh rendered readback whose active layout matches the bounded posture layout and whose rendered ward readback is present. Otherwise the result is held with `rendered_readback_mismatch`.

Hysteresis/min dwell is mandatory for posture changes unless safety/consent fallback fires. Safety state is checked before dwell and records `safety_fallback` with `bypasses_hysteresis`.

The receipt never grants playback, audio, narration, or public action authority. Those remain owned by the broadcast/playback authorization chain and provenance gates.

## Legacy Boundary

The legacy selector's `default_fallback` remains preserved behind an explicit `legacy_default`/non-responsible boundary. This keeps boot, garage-door, and operator fallback contexts stable while making hosted segment layout responsibility auditable.

# Reverie Substrate Invariant — Governance Note

**Status:** Normative. Violations block PR merge via the companion
regression test (`tests/studio_compositor/test_reverie_substrate_invariant.py`).
**CVS Task:** #124 (HOMAGE follow-on — reverie substrate preservation).
**Companion spec:** `docs/superpowers/specs/2026-04-18-reverie-substrate-preservation-design.md`.
**Implementation:** `agents/studio_compositor/homage/substrate_source.py`,
`agents/studio_compositor/homage/choreographer.py::_resolve_substrate_ids`,
`broadcast_package_to_substrates`.

---

## 1. The invariant

Reverie is a **substrate**, not a ward. The HOMAGE framework (spec
§4.1, §4.9) partitions every compositor source into one of two kinds:

- **Transitional sources** (default) — ruled by the choreographer FSM
  `ABSENT → ENTERING → HOLD → EXITING`. Render only during `HOLD`.
  Pending transitions consume concurrency slots. When HOMAGE rotates
  the active package, these sources may be ejected, re-entered, or
  parked.
- **Substrate sources** — permanent generative processes exempted
  from the FSM. Never enter the pending-transitions queue. Never
  consume concurrency budget. Never get ejected by package rotation.
  Continue rendering indefinitely.

Reverie is the canonical — and currently sole — substrate source. The
wgpu vocabulary graph with its 9-dim uniform bus, per-node params
bridge, and Bachelard temporal feedback passes is a standing
generative process, not a clip to be triggered.

The invariant has four clauses, each pinned by a test:

1. **Protocol conformance.** The Reverie backend (`ShmRgbaReader`
   constructed with `is_substrate=True`) must satisfy the
   `HomageSubstrateSource` runtime-checkable Protocol.
2. **FSM exemption.** `Choreographer.reconcile()` MUST drop pending
   entries whose `source_id` appears in `SUBSTRATE_SOURCE_REGISTRY`
   (or whose registered backend declares `is_substrate=True`) before
   the entry/exit/modify partition. A pending
   `ticker-scroll-out` for `reverie_external_rgba` MUST NOT become
   a `PlannedTransition` and MUST NOT consume an entry slot.
3. **Palette broadcast.** On every reconcile tick — including empty
   ticks and ticks where no transitions are pending — the
   choreographer MUST refresh the palette-hint broadcast file
   `/dev/shm/hapax-compositor/homage-substrate-package.json`. The
   broadcast propagates into the shader via the mirrored
   `uniforms.custom[4]` slot (or via direct file polling by the
   reverie mixer).
4. **Consent-safe continuity.** When the consent-live-egress guard
   engages (`/dev/shm/hapax-compositor/consent-safe-active.json`
   present), the choreographer swaps the active package for its
   consent-safe variant but Reverie MUST continue rendering. The
   palette broadcast re-resolves to the consent-safe hue (muted
   grey, `palette_accent_hue_deg=0.0`) and Reverie tints
   accordingly — the substrate never pauses.

## 2. Why this shape

The obvious rewrite — running Reverie through the FSM — fails two
ways:

- Park it in `ABSENT` and the compositor sees a transparent surface
  (Reverie's output shm buffer has no live producer). The Tauri
  visual-surface fetch at `:8053` serves black frames. Operator
  perception goes dark, which the consent-live-egress guard cannot
  distinguish from an actual camera failure.
- Pin it to `HOLD` forever and the choreographer no longer owns its
  own vocabulary. Every package swap, every rotation tick, every
  consent-safe flip has to special-case "but not this one" at the
  state-machine level instead of at the registry level. The FSM
  becomes a set of nested exceptions, not a rule.

The `HomageSubstrateSource` Protocol is the registry-level answer.
The FSM stays clean — it only sees transitional sources. The
choreographer's substrate filter (`_resolve_substrate_ids`) is the
single gate, applied before the partition. Adding a new substrate
source is a two-line change (`SUBSTRATE_SOURCE_REGISTRY` tuple +
`is_substrate: Literal[True]` marker on the backend class) plus a
spec amendment.

## 3. Palette propagation — the only coupling path

Reverie does not listen for HOMAGE FSM events. It reads **one**
surface per tick: the substrate broadcast file. The payload:

```json
{
  "package": "bitchx",
  "palette_accent_hue_deg": 180.0,
  "custom_slot_index": 4,
  "substrate_source_ids": ["reverie", "reverie_external_rgba"]
}
```

The reverie mixer maps `palette_accent_hue_deg` onto the
`colorgrade` node's per-node params (hue rotation + saturation
damping). The shader itself reads `uniforms.custom[4]` — a
four-float slot kept in sync with the broadcast payload by
`_publish_payload()`. Either path is sufficient; both are live so
that a wipe of `/dev/shm/hapax-compositor/` leaves the uniform slot
as the fallback until the next reconcile tick rewrites the file.

This is the entire coupling surface between HOMAGE and Reverie. No
transition dispatch, no teardown, no re-seed — just a palette hint
the substrate can honor or ignore.

## 4. Consent-safe — the operational edge case

The consent-live-egress guard writes the consent-safe flag file
when a non-operator face is detected with no active consent
contract (`axioms/contracts/`). The guard is fail-closed: the
compositor falls back to `layout-consent-safe.json`, Cairo overlays
redact author text, and HOMAGE swaps to the `bitchx_consent_safe`
variant. During this state:

- Reverie continues rendering. Operator visibility is preserved —
  the stream doesn't go dark, only the surfaces that could leak
  non-operator data collapse.
- The palette broadcast re-resolves. `bitchx_consent_safe` returns
  `palette_accent_hue_deg = 0.0` and an empty artefact corpus; the
  reverie mixer sees a muted grey hint and its colorgrade damps
  accordingly.
- No FSM transition fires for Reverie during the swap. The
  consent-safe engagement and release are both zero-transition for
  the substrate — it is the only source in the compositor whose
  output doesn't depend on the HOMAGE state machine.

The regression test exercises this path directly: it writes the
consent-safe flag, reconciles once, and asserts that (a) no
substrate source is planned, (b) the broadcast file carries the
consent-safe hue, and (c) the substrate registry still includes
Reverie.

## 5. Registry — the governance surface

Adding a substrate source requires:

1. A spec amendment under `docs/superpowers/specs/` declaring the
   source's generative model, the rationale for FSM exemption, and
   the palette-coupling path.
2. Appending the `source_id` to `SUBSTRATE_SOURCE_REGISTRY` in
   `agents/studio_compositor/homage/substrate_source.py`.
3. Declaring `is_substrate: Literal[True]` on the backend class (or
   passing `is_substrate=True` to a factory that sets it).
4. Extending the regression test to pin the new source.

The registry is intentionally small. It is not a generic mechanism —
it is a documented escape hatch for processes whose continuity is
load-bearing for operator perception. Abuse of this hatch
(registering a ward as "substrate" to avoid a teardown bug) is an
axiom-adjacent failure: it converts a choreographer concern into a
permanent always-on expression.

## 6. Failure modes — what breaks this invariant

- **Silent isinstance drift.** `runtime_checkable` Protocols check
  attribute presence, not value. A backend that declares
  `is_substrate: bool` (instance attribute) without setting it
  `True` matches `isinstance()` but fails the truthiness gate in
  `_resolve_substrate_ids`. The test pins the truthiness check
  explicitly.
- **Missing palette broadcast on empty tick.** If `reconcile()`
  short-circuits on an empty pending list, Reverie never picks up
  package swaps until a ward happens to transition. The test
  asserts broadcast runs unconditionally.
- **Consent-safe wipe without re-broadcast.** If the consent-safe
  swap doesn't re-resolve the broadcast file, Reverie keeps the
  previous (non-consent-safe) hue. The test exercises the swap.
- **`/dev/shm` wipe.** An inotify-triggered cleanup or a tmpfs
  remount can delete the broadcast file mid-session. The
  choreographer detects file-missing and rewrites even when the
  package name is unchanged (`broadcast_package_to_substrates`
  file-exists short-circuit is the recovery path).

## 7. Cross-references

- **Spec:** `docs/superpowers/specs/2026-04-18-reverie-substrate-preservation-design.md`
- **Runbook:** `docs/runbooks/homage-runbook.md` § Consent-safe engagement
- **Design authority:** `docs/logos-design-language.md` § Reverie
- **Shader side:** `hapax-logos/src-tauri/src/visual/` (Rust
  `DynamicPipeline` reads `uniforms.custom[4]` for palette hint)
- **Observability:** `hapax_homage_choreographer_substrate_skip_total`
  Prometheus counter (non-zero rate indicates a producer is enqueuing
  transitions against a substrate source — a design violation
  upstream of the choreographer).

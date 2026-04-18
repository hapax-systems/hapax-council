# Reverie Substrate Preservation Under HOMAGE Ward System

**Date:** 2026-04-18
**Task:** HOMAGE follow-on #124
**Status:** Spec stub (provisional approval — dossier 2026-04-18)
**Source research:** `docs/superpowers/research/2026-04-18-homage-follow-on-dossier.md` § Rendering → #124
**Blocks:** HOMAGE Phase 11c batch 3 (overlay-zone + reverie migration), HOMAGE Phase 12 (consent-safe variant)

---

## 1. Goal

Preserve Reverie as a permanent generative substrate beneath the HOMAGE ward system. Three invariants to uphold:

1. **Reverie never recedes.** The wgpu vocabulary graph is a permanently running generative process, not a ward. It must never enter `absent` / `entering` / `exiting`.
2. **Exemption is explicit and auditable.** The choreographer's default assumption — "every source is a `HomageTransitionalSource`" — must be mechanically overridden for Reverie via a marker trait, not via name-sniffing or silent special cases.
3. **Reverie still receives HOMAGE aesthetics.** Package palette hints reach the Reverie `content_layer` / `custom[4]` slot so package swaps *tint* Reverie; choreography does not *gate* its blit.

---

## 2. Architectural Tension

HOMAGE Phase 11c wants to migrate every Cairo source (and the `external_rgba` slot Reverie paints through) to the `HomageTransitionalSource` base. The FSM in `transitional_source.py` has four states (`ABSENT`, `ENTERING`, `HOLD`, `EXITING`) and only renders content in `HOLD` (spec §4.10). The choreographer (`choreographer.py::Choreographer.reconcile`) reads pending transitions and applies concurrency rules — entries are capped by `package.transition_vocabulary.max_simultaneous_entries`, exits by `max_simultaneous_exits`.

Reverie violates the FSM's core assumption: it publishes `publish_health(ControlSignal(component="reverie", reference=1.0, perception=1.0))` unconditionally (mixer.py:232), and the visual chain cache, satellite manager, and vocabulary graph all assume the 8-pass shader pipeline is live every tick. Forcing Reverie through `ABSENT/ENTERING/HOLD/EXITING` would either stall the substrate (`ABSENT` means transparent surface) or silently pin it to `HOLD` forever (a contract the choreographer doesn't own).

---

## 3. Pattern Analysis

Four integration patterns were evaluated in the dossier (§ Rendering → #124):

**(a) Stay-in-HOLD permanently.** Initial `initial_state=TransitionState.HOLD` in `HomageTransitionalSource.__init__`, reject any exit transitions. **Rejected** — encodes a confusing state where `apply_transition("ticker-scroll-out")` would either raise or silently noop. The choreographer would still enqueue entries/exits against Reverie in the pending-transitions queue and burn concurrency slots on a source that can never legitimately transition.

**(b) Exempt from choreography.** Reverie is not a `HomageTransitionalSource` at all. Introduce a marker trait `HomageSubstrateSource` that the choreographer recognises and filters out of its reconciliation loop entirely. **RECOMMENDED.** The exemption is a single predicate check in `reconcile()`, observable via a Prometheus counter, and Reverie keeps its existing direct-blit path through `ShmRgbaReader → compositor → shader layer`.

**(c) Inherit FSM + override.** Subclass `HomageTransitionalSource` but override `render()` to bypass state dispatch. **Rejected** — hidden contract. Readers of the choreographer see a `HomageTransitionalSource` entry and reasonably assume FSM semantics apply; overriding `render()` to bypass the FSM is the kind of subtlety that causes "why is this ward never transitioning?" debugging sessions three months later.

**(d) Use custom[4] shader-coupling slot.** Route package palette/accent hints through the existing `uniforms.custom[4]` slot that the choreographer's `_publish_payload` already writes. **ADOPTED as ADDITIVE layer on top of (b).** The coupling payload is already package-scoped and shader-aware; pattern (b) handles FSM exemption, pattern (d) handles aesthetic carry-through. Reverie reads the same `custom[slot]` uniform slice every other HOMAGE-coupled shader reads, so the package's aesthetic fingerprint (BitchX cyan ≈ 180°, rotation phase, etc.) tints Reverie without any FSM interaction.

**Adopted combination:** (b) + (d). Exemption trait at the Python level, palette hint at the WGSL uniform level.

---

## 4. Marker Trait `HomageSubstrateSource`

Declared in `agents/studio_compositor/homage/substrate_source.py`:

```python
from typing import Literal, Protocol, runtime_checkable


@runtime_checkable
class HomageSubstrateSource(Protocol):
    """Marker: this source is always-on. HOMAGE choreographer skips FSM for it.

    A source satisfies this protocol by declaring ``is_substrate: Literal[True]``
    at the class or instance level. The choreographer filters out every source
    satisfying the protocol before building its entry/exit/modify plan — substrate
    sources never appear in the transition queue and never consume concurrency
    slots.

    Reverie's ``ShmRgbaSource`` (the compositor-side adapter around the wgpu
    external_rgba slot) is the first adopter. Future adopters must justify the
    always-on classification against HOMAGE spec §4.9 and appear in the substrate
    registry below.
    """

    is_substrate: Literal[True]
```

Registered substrate sources (authoritative list):

| source_id | Rationale |
|---|---|
| `reverie_external_rgba` | Permanent generative substrate. Visual chain + satellite manager + vocabulary graph depend on continuous render. |

Adding a new substrate requires a spec amendment; the list is the governance surface.

---

## 5. Choreographer Change

`choreographer.py::Choreographer.reconcile` filters substrate sources out of the pending-transitions queue before the entry/exit/modify split:

```python
# After self._read_pending(), before entry/exit partition:
substrate_ids = _resolve_substrate_source_ids(source_registry)
skipped_substrate = [p for p in pending if p.source_id in substrate_ids]
pending = [p for p in pending if p.source_id not in substrate_ids]

for p in skipped_substrate:
    emit_homage_choreographer_substrate_skip(p.source_id)
```

`_resolve_substrate_source_ids()` walks the `SourceRegistry` (Phase 11b dependency) and collects every `source_id` whose backing object satisfies `isinstance(obj, HomageSubstrateSource)`. The result is cached per reconcile() call, not per tick of the substrate cache, so registry additions propagate on the next choreographer tick.

**Invariant:** a substrate source appearing in the pending queue is always a producer bug (something tried to transition Reverie). The skip is logged once per reconcile batch, metric-counted, and not surfaced as a rejection (the choreographer rejects within its vocabulary; substrate sources are *outside* the vocabulary).

---

## 6. Observability Metric

New Prometheus counter registered in `shared/director_observability.py`:

```
hapax_choreographer_substrate_skip_total{source="reverie_external_rgba"}
```

Emitted once per pending entry that named a substrate source. Audit trail purpose: any non-zero rate indicates something in the system is trying to schedule transitions for the substrate, which is a design violation. Grafana panel sits next to `hapax_homage_choreographer_rejection_total`.

---

## 7. `custom[4]` Tinting (Pattern d, Additive)

Reverie reads the package coupling payload without being gated by it:

1. **Choreographer publishes `CoupledPayload` unconditionally** (already the case — `_publish_payload` runs even on empty plans). Payload lands at `signal.homage_custom_{slot}_{i}` keys in `/dev/shm/hapax-imagination/uniforms.json`.
2. **Package configuration pins Reverie's tint slot.** `HomagePackage.coupling_rules.custom_slot_index` for the BitchX package targets slot 4 (`custom[4]`) for Reverie's `content_layer.wgsl` and color-grade stage. Other wards use other slots; Reverie reads slot 4 exclusively.
3. **Visual chain bridges palette_accent_hue_deg → `colorgrade.hue_rotate` param.** The `palette_accent_hue_deg` band (0..360°) of the payload modulates the colorgrade hue-rotate param via `visual_chain.compute_param_deltas`, so Reverie's frame carries the active package's hue without any FSM coupling.
4. **Package swap propagation.** When the operator (or director) swaps packages, the choreographer updates the payload on its next reconcile; Reverie picks up the new palette hint within one tick (<100 ms typical). No transition is scheduled; the substrate *already* runs, it just shifts hue.

Pattern (d) is explicitly *broadcast-only* — Reverie does not acknowledge the payload back through the choreographer. This mirrors how other always-on uniform channels (stance, color_warmth) flow one-way from perception to shader.

---

## 8. File-Level Plan

| File | Change |
|---|---|
| `agents/studio_compositor/homage/substrate_source.py` | **NEW.** Define `HomageSubstrateSource` Protocol + `SUBSTRATE_SOURCE_REGISTRY` tuple. |
| `agents/studio_compositor/homage/choreographer.py` | Add substrate filter in `reconcile()` before entry/exit/modify partition. |
| `agents/studio_compositor/reverie_shm_source.py` (or wherever `ShmRgbaSource` lives post-Phase 11b registry work) | Add `is_substrate: Literal[True] = True` class attribute. |
| `shared/director_observability.py` | Add `emit_homage_choreographer_substrate_skip(source_id)` + Prometheus counter registration. |
| `agents/reverie/visual_chain.py` | Wire `palette_accent_hue_deg` → `colorgrade.hue_rotate` param delta emission. |
| `shared/homage_package.py` | Document `coupling_rules.custom_slot_index=4` as the Reverie-bound slot for each package. |
| `tests/studio_compositor/test_choreographer_substrate.py` | **NEW.** Tests in §9. |
| `tests/reverie/test_reverie_palette_tint.py` | **NEW.** Tests in §9. |

---

## 9. Test Strategy

**Integration — substrate never transitions:**
- Start HOMAGE FSM with `HAPAX_HOMAGE_ACTIVE=1`, inject a pending `ticker-scroll-out` for `reverie_external_rgba` into the queue, run `Choreographer.reconcile()`, assert Reverie's transition state remains unset (no FSM at all), assert `hapax_choreographer_substrate_skip_total{source="reverie_external_rgba"}` incremented, assert no `PlannedTransition` for Reverie.
- Soak test: run 10 000 reconcile ticks with random pending entries (including some for Reverie); verify Reverie's `ShmRgbaReader` receives uninterrupted frames across the full run.

**Tint — palette reaches Reverie WGSL:**
- Swap `HomagePackage` from BitchX to a hypothetical `eggdrop` package with a different `palette_accent_hue_deg`, run one reconcile tick, read `/dev/shm/hapax-imagination/uniforms.json`, assert slot 4's hue band changed.
- End-to-end: frame-capture Reverie output before and after package swap, compute mean-hue delta in LAB space, assert non-zero hue shift while structural content (RD, feedback, drift) remains visually continuous (no frame black-out, no FSM-induced fade).

**Unit:**
- `HomageSubstrateSource` Protocol runtime-check: `isinstance(ShmRgbaSource(), HomageSubstrateSource)` is `True`; `isinstance(SomeTransitionalWard(), HomageSubstrateSource)` is `False`.
- Substrate registry is a frozen tuple; adding an entry at runtime raises.

---

## 10. Open Questions

1. **Should the `content_layer` custom[0] slot (used today for material_id / slot salience / intensity) coexist with the new custom[4] package-palette slot, or be unified?** The current mixer writes `custom[0]`; packaging hints landing at `custom[4]` keeps the two concerns orthogonal, but increases uniform surface. Recommendation: keep separate until the next uniform budget audit.
2. **Do non-core shaders recruited via `sat_*` affordance prefix inherit substrate exemption?** They're part of Reverie's runtime but come and go per affordance. Initial answer: no — they're recruited/released normally, substrate exemption applies only to the `external_rgba` blit path itself, not to shader nodes composited into the graph.
3. **Is the substrate registry global or per-package?** A future package might want Reverie's slot differently routed. Current design: registry is global (Reverie is always substrate regardless of package); per-package routing lives inside `HomagePackage.coupling_rules`.

---

## 11. Relation to HOMAGE Phase 6 (Ward ↔ Shader Coupling)

HOMAGE Phase 6 defines the coupling payload contract: 4 floats per package-bound slot, published by the choreographer, consumed by one or more shaders. This spec asserts Reverie is a **coupling consumer without being a choreography participant** — a shape Phase 6 was designed to support (the payload is broadcast regardless of whether any transition is active). The substrate exemption + palette tint combination exercises Phase 6's orthogonality between transition gating and uniform broadcast.

The Phase 6 `CoupledPayload.active_transition_energy` band decays to 0 in the absence of transitions; Reverie reads this as "no ward-scale activity" and keeps its generative cadence unchanged. Under high transition density the energy band rises and Reverie *could* optionally modulate temporal distortion to echo the ward-surface activity — this is a future extension, not part of this spec.

---

## 12. Downstream Blocks

- **HOMAGE Phase 11c batch 3** (overlay-zone + Reverie migration). Batch 3 cannot land until this spec's trait + choreographer filter + Reverie `is_substrate` flag are wired. Overlay-zone migration to `HomageTransitionalSource` proceeds independently; Reverie is called out explicitly as "substrate, not migrated".
- **HOMAGE Phase 12** (consent-safe variant). Phase 12 tightens egress-floor guarantees; Reverie's substrate exemption must be re-audited against consent-safe mode to ensure palette hints do not leak non-operator representational content through `custom[4]` during consent-gated windows.

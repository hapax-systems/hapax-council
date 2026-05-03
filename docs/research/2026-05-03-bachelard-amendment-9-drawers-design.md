---
date: 2026-05-03
status: design — spec only; implementation a separate downstream cc-task
amends:
  - docs/superpowers/specs/2026-03-29-reverie-bachelard-design.md
  - docs/research/2026-05-03-bachelard-amendment-7-design.md
  - docs/research/2026-05-03-bachelard-amendment-8-miniature-design.md
related_tasks:
  - "cc-task bachelard-amendment-9-drawers-design"
---

# Bachelard Amendment 9 — Phenomenology of Drawers/Wardrobes

## Decision

**Amendment 9 is the Phenomenology of Drawers/Wardrobes** (*La poétique de l'espace* ch. III). Selected as the next-best-distinct chapter after Roundness (A7) and Miniature (A8). The remaining candidate from the original Jr-packet list, Nests-Shells, defers to a potential Amendment 10.

| Candidate | Chapter | Distinctness vs A7 + A8 |
|-----------|---------|--------------------------|
| **Drawers/Wardrobes** | III | **Selected** — concealed-depth-disclosure is orthogonal to inward-attention (A7+A8 axis). New phenomenological dimension: **temporality of revelation**. |
| Nests-Shells | IV | Defers; closer to immensity (#5) + reverberation (#4) than to disclosure-of-the-hidden. |

Drawers wins on: (a) introducing a new temporal dimension (drawer-opens-over-time vs the spatial axes of A7+A8), (b) clear pairing with the existing Materialization (#1) which is already crystallization-from-noise — drawers add concealment-then-disclosure as a distinct register.

## 1. Concept summary

Bachelard's drawers/wardrobes is the phenomenology of **the hidden made disclosable** — *"In the wardrobe lives a center of order that protects the entire house against uncurbed disorder. There reigns the constancy of the order which the wardrobe maintains."* (Bachelard ch. III §1). The drawer is not seen but knowable. Opening the drawer is an event with its own temporal arc: anticipation → unveiling → contents-revealed → either kept-out or replaced-and-closed.

For Hapax Reverie, drawers is the visual register of **concealment-disclosure cycles**:

- Default state: content held in reserve, NOT materialized — present in the system's awareness but not on the visual surface.
- Disclosure event (operator gaze fixes on a region, or director recruits "show this content"): the held content emerges via a temporally-arced reveal.
- Re-concealment: optional — content can return to held state with a closing arc.

| Axis | Materialization (#1) | Drawers (#9) |
|------|----------------------|--------------|
| Source of content | Always-procedural noise | Pre-existing content held in reserve |
| Trigger | Salience-driven | Event-driven (gaze, recruitment, programme) |
| Temporal arc | Salience continuous → continuous opacity | Discrete event → arced reveal |
| Phenomenology | Crystallization from substrate | Revelation of the pre-existing |

A7+A8 pair as inner+outer layers of inward-attention. **A9 is orthogonal**: it operates on the temporality of *which* content is on the surface, not on the spatial composition of content already there.

## 2. Relation to Amendments 1-8

- **#1 Materialization** — content crystallizes from procedural noise. Drawers introduces an alternative path: content can ALSO arrive via reveal-from-reserve. The two are co-existent: some content materializes (procedural fragments), some is revealed (operator-curated holdings). The materialization mechanism is unchanged.
- **#2 Dwelling/Trace** — content leaves traces. Drawers content, when re-concealed, leaves a trace at its disclosure location (the surface "remembers" where the drawer was open).
- **#3 Material Quality** — material_id (water/fire/earth/air/void). Drawers content carries its OWN material_id; it doesn't inherit from procedural state.
- **#4 Reverberation** — feedback echo. Disclosure events emit a brief reverberation pulse at the disclosure location.
- **#5 Immensity** — outward expansion. Drawers REDUCES immensity briefly during disclosure (focus contracts to the drawer being opened); restores after the event.
- **#6 Soft Escalation** — pacing. Drawers events MUST follow soft-escalation. The disclosure arc is governed by Amendment 6's pacing rules (no jump-cuts).
- **#7 Roundness** — inward-self / centered. Compatible. When roundness is active and a drawer opens, the disclosure happens at the centroid (rather than wherever the drawer's "natural" location would be).
- **#8 Miniature** — inward-detail. Compatible. When miniature is active and a drawer opens, the revealed content is rendered at high-detail (small but textured).

Composition with all eight: drawers is a NEW path for content arrival; it doesn't compete with the spatial/scale modulations of A1-A8.

## 3. 9-dim parameter envelope

Drawers events are **transient** — the modulation pulses during the disclosure arc, not as a persistent ground state like Roundness or Miniature. The envelope:

| Dim | At disclosure peak (× peak) | Steady-state | Why transient |
|-----|------------------------------|--------------|---------------|
| **intensity** | × 1.30 (peak) | × 1.0 | Disclosure demands attention briefly. |
| **tension** | × 1.20 (peak) | × 1.0 | Anticipation phase carries tension; resolution releases it. |
| **depth** | × 0.6 (peak — focus contracts) | × 1.0 | During disclosure the field's depth-of-immensity briefly damps so the drawer can hold the eye. |
| **coherence** | × 1.0 | × 1.0 | Disclosure is locally coherent (the drawer + its content as a unit). |
| **spectral_color** | × 1.20 (peak) | × 1.0 | Revealed content gets brief chromatic emphasis. |
| **temporal_distortion** | × 0.50 (peak) | × 1.0 | Time slows during disclosure (the revealed content is held for inspection). |
| **degradation** | × 0.80 (peak — clarity for content) | × 1.0 | Held content reads clearly. |
| **pitch_displacement** | × 1.0 | × 1.0 | Orthogonal. |
| **diffusion** | × 0.70 (peak — sharpened content) | × 1.0 | Diffusion damps so revealed content stays legible. |

The peak occurs at the midpoint of the disclosure arc (~50% through the reveal). The arc envelope is `sin(π * t / arc_duration)` so values smoothly ramp from 1.0 → peak → 1.0 over the disclosure event. **Default arc_duration: 1.2 seconds** (per Amendment 6 soft-escalation pacing).

## 4. Shader topology

No new WGSL nodes. Drawers events are implemented as a **transient modulation pulse at the visual_chain layer**, gated by an event signal:

- A new shared signal `/dev/shm/hapax-stimmung/drawer-event.json` carries the active disclosure event:
  ```json
  {
    "event_id": "drawer-1234",
    "started_at": 1234567890.5,
    "arc_duration_s": 1.2,
    "peak_factor": 1.0,
    "content_ref": "obsidian:my-note-23",
    "disclosure_location": [0.5, 0.5]
  }
  ```
- Visual-chain reads this signal each tick, computes `t / arc_duration`, applies the sin-curve envelope to the per-dim modulation table.
- After `arc_duration_s` elapses, signal expires (next tick reads `peak_factor=0` and steady-state behavior resumes).

The visual_chain layer adds `_apply_drawer_event_pulse(uniforms, signal)` called AFTER all other A7-A8 modulations and AFTER homage damping (drawer events are episodic; they overlay everything). Order:

1. plan_defaults + chain_deltas
2. mode tint
3. roundness bias (A7 impl, downstream)
4. miniature bias (A8 impl, downstream)
5. homage damping
6. **drawer event pulse (A9 impl, downstream)** ← new, transient
7. programme override

## 5. Compositor interaction

### Sierpinski overlays

Drawers events have a **focal hint**: the disclosure_location is communicated to the Sierpinski renderer so the drawer's content materializes at that point in the fractal. Default behavior is to use the slot nearest the disclosure_location.

### Token pole

Token pole is unaffected by drawer events (they're content-domain, not telemetry-domain).

### Reverie content placement

Drawer-revealed content is placed at the disclosure_location regardless of the salience-based default placement (Amendment 1). The reveal **overrides** salience-based placement for the duration of the arc.

### NEW: Drawer Manager (`agents/reverie/drawer_manager.py`)

A new manager component coordinates drawer events:

- `open_drawer(content_ref, location, arc_duration_s)` — fires a disclosure event
- `close_drawer(content_ref)` — re-conceals via reverse arc
- Maintains a registry of currently-open drawers (max 3 concurrent — overflow drops oldest)
- Publishes `/dev/shm/hapax-stimmung/drawer-event.json` for visual_chain consumption

Affordance: `studio.drawer_open(content_ref, location)` — recruitment can fire disclosure events. consent_required=False (operator-curated content; no PII risk).

## 6. Anti-pattern list

The implementation MUST NOT use any of the following — they defeat the disclosure phenomenology:

- **Literal door-opening / sliding-panel animations.** Bachelard's drawer is the *holding* of the hidden + the *event* of unveiling, NOT a literal box-with-hinge. Skeuomorphic door animations read as 1990s GUI tropes, not phenomenological revelation.
- **Modal popups / dialog overlays.** Disclosure happens IN-PLACE on the visual surface, not in a separate UI layer.
- **Multi-second slow-fade reveals.** The arc duration is bounded at 1.5s max (per Amendment 6 soft-escalation pacing). Slower than that reads as molasses, not anticipation.
- **Sound effects for disclosure.** This is a visual amendment. Audio integration is out-of-scope.
- **Persistent open state.** A drawer left open indefinitely loses its phenomenological identity. Default behavior: auto-close after 30s if no further interaction.
- **Concurrent drawer storm.** More than 3 drawers open simultaneously creates visual chaos. Cap pinned at the manager.
- **A "drawer" preset.** Drawers is an EVENT MECHANISM, not a preset.
- **A "drawer" affordance with consent_required=True.** Operator-curated content; no PII.

## 7. Coordination with Amendments 7+8

Drawers is **orthogonal** to Roundness + Miniature — they govern spatial/scale composition; drawers governs content-arrival temporality.

**Composition cases:**

| State | Behavior |
|-------|----------|
| Roundness ON, no drawer | Field contracts to centroid, default behavior. |
| Drawer opens during roundness | Disclosure happens AT centroid (regardless of natural drawer location). Roundness's centroid-pull biases the disclosure. |
| Miniature ON, no drawer | Field shows detail-amplified texture. |
| Drawer opens during miniature | Revealed content rendered at high detail (small + textured). Miniature's chromatic amplification applies to the revealed content. |
| Roundness + Miniature + drawer | All three compose: outer roundness envelope + inner miniature texture + drawer-revealed content at centroid, brief intensity peak during disclosure arc. The canonical "operator absorbed in inspecting a specific revealed item" stance. |

**Precedence order** (in `_uniforms.write_uniforms`, per §4):
1. Steady-state modulations (roundness, miniature) apply first.
2. Drawer event pulse overlays via multiplicative composition (the modulators stack: roundness × miniature × drawer-peak).
3. Homage damping is authoritative — if BitchX is active, drawer disclosure may be visually muted (intentional).

## 8. Implementation footprint (downstream cc-task scope)

Spec only — implementation is `bachelard-amendment-9-drawers-impl`. Estimated:

- `agents/reverie/_uniforms.py` — `_apply_drawer_event_pulse(uniforms, signal)` helper. ~50 lines.
- `agents/reverie/drawer_manager.py` — DrawerManager class + `/dev/shm/hapax-stimmung/drawer-event.json` writer. ~120 lines.
- `shared/affordance_registry.py` — register `studio.drawer_open` affordance. ~15 lines.
- `agents/visual_chain.py` — read drawer-event signal each tick, pass to `_apply_drawer_event_pulse`. ~30 lines.
- `agents/studio_compositor/sierpinski_renderer.py` — read disclosure_location, bias slot placement. ~20 lines.
- `agents/reverie/content_layer.py` (or mixer) — override salience-based placement during drawer arc. ~40 lines.
- Tests: ~150 lines (drawer manager open/close lifecycle; sin-curve envelope correctness; composition with roundness/miniature; concurrent-cap enforcement; auto-close timer; affordance pin).

Total: ~425 LOC across 6 files. Bigger than A7/A8 because it adds a new manager component (drawer state machine) on top of the visual-chain modulation. Bounded for a single PR.

## 9. Validation plan (downstream)

The downstream impl cc-task should pin:

1. `open_drawer` writes the signal file with correct schema.
2. `_apply_drawer_event_pulse` produces the sin-curve envelope (peak at midpoint, 1.0 at start/end).
3. Auto-close fires after 30s of no further interaction.
4. Concurrent-cap (max 3 drawers): a 4th `open_drawer` evicts the oldest.
5. Composition with Roundness + Miniature: all three modulators compose multiplicatively without truncation.
6. Disclosure_location overrides salience-based placement during arc; restores after.
7. Operator-side acceptance: live livestream test — `studio.drawer_open("test-content", [0.5, 0.5])` produces a visible disclosure arc.

## 10. Out-of-scope

- Implementation (downstream cc-task `bachelard-amendment-9-drawers-impl`).
- Audio-domain analogue of disclosure (out-of-scope; visual-only).
- Operator-tunable arc-duration (default 1.2s; tuning is a follow-up).
- Drawer content authoring tooling (operator publishes content via Obsidian; the drawer mechanism is consumption-side).
- Re-conceal arc detail (default is reverse-time playback of disclosure arc; refinement is a follow-up).
- Nests-Shells (Amendment 10 candidate) — deferred.

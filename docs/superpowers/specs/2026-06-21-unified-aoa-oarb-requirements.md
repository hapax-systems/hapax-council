# Unified AoA/OARB — Requirements (re-conception as one attention object)

- **Date:** 2026-06-21
- **Status:** requirements only (operator: "just the requirements"). NOT a design; no geometry mechanism, no implementation. The design phase comes after operator review.
- **Mandate:** tear down the current AoA (tetrix lattice ward) and OARB (media-sphere/billboard ward) entirely and re-conceive them as **ONE unified attention object**, not two Homage Wards.
- **Grounding:** requirement-drivers sweep `wf_853ddcd7` + historical-lineage sweep `wf_eef52023` (research + implementation, all iterations). Companion findings: `~/Documents/Personal/30-areas/hapax/aoa-hardm-oarb-research-2026-06-21.md`.

## 0. Identity (recovered authoritative intent)
The unified object is **the single locus of mutual attention** in the broadcast. It fuses two recovered meanings into one entity:
- **AoA — "Attendant of Attention":** the expressive structure = *the system attending* (its internal state, made visible as form, signal-bearing, never a face).
- **OARB — "Ocular Attention Representation Ball":** the live media = *what is being attended to* ("what the operator is attending to"), explicitly **not** an "On-Air Reference Board" and not a parasocial broadcast framing.

The re-conception: the attending (structure) and the attended-to (content) are **one coherent object**, not a lattice ward beside a ball ward.

## 1. Unification (the core requirement)
- **R1.1** It MUST be a single entity: one origin, one render footprint / draw entity, one declared mount contract, one state/"think" currency — not two wards with separate occlusion, lighting, drift, or producers.
- **R1.2** It MUST render as a **single depth-coherent volume** with one consistent z-order; structure and content MUST NOT be two depth-ambiguous surfaces that saw through / clash with each other (the present failure).
- **R1.3** Structure and content MUST update through **one texture/producer pipeline and one drift-interaction owner**, not separate MDL-skin + BSP-brush producers with divergent semantics.
- **R1.4** Structure and content MUST remain **optically distinguishable** (the viewer can tell the attending-form from the attended-content) while being one functional object.

## 2. Attention & anti-parasocial
- **R2.1** It MUST be the **object of (mutual) attention** — Hero tier of the visual field (the thing the operator, audience, and system attend to together), not decoration or background.
- **R2.2** Viewer agency MUST target the **object / space / source-state**, never simulated personal access to the operator. `anti_parasocial_posture = object-of-attention-source-material`. (framework)
- **R2.3** It MUST support a **reveal/hide (ready-to-hand ↔ present-at-hand) cycle**: ambient/withdrawn by default, surfacing under operator-directed agency or system-detected salience — not a constant fourth-wall fixture.
- **R2.4** It MUST be **register/consent-safe**: its prominence/opacity MUST respond to broadcast-mode vs conversation-mode and to consent state (fail-closed on unconsented content).

## 3. Expression — signal-bearing, anti-face (HARDM→GEAL lineage)
- **R3.1** The structure MUST **express Hapax's internal state** (stimmung/attunement, activity, grounding-provenance, world-disclosure) — it is an information surface, not a decorative 3-D model. ("AoA IS HARDM": the structure is HARDM's signal dot-matrix re-materialized; carry that forward, do not re-bury it as procedural noise.)
- **R3.2** Every modulation (structure density/depth, glow, content prominence, colour shift) MUST be **traceable to a published signal** readable from a SHM/state file — no hardcoded shimmer cadences, no deterministic per-cell animation standing in for state.
- **R3.3** Colour MUST be **signal-semantic** (which signal), never affect-semantic (what emotion); drawn from a package-sourced palette-role table, never hardcoded hex.
- **R3.4** It MUST satisfy the **anti-anthropomorphization invariants I1–I10** as design-locked gates: no bilateral eye-pair, no horizontal mouth-feature, no centred single-cluster face, no affect-colour, no blink cadence, etc. It MUST NOT form any configuration readable as a face/character.
- **R3.5** Scale-up MUST mean **more density/cells/recursion activated**, NEVER morphological/affective change (no "happy/sad" shapes).
- **R3.6** Temporal expression MUST use **continuous three-phase envelopes** (anticipate/commit/settle, log-decay tail, ≥80 ms rise/fall) — the curve shape is the entity-vs-decoration tell; no step changes.
- **R3.7** It SHOULD carry the recoverable expressive vocabulary where it serves R3: event geometry (birth/decay/ripple), a perpetual-motion substrate (e.g. reaction-diffusion) so it reads as living, and a grounding-source→region mapping (perception / memory / world) — as expression of state, governed by R3.4.

## 4. Honesty (DASEIN / honest-integration)
- **R4.1** Every structural claim the object makes MUST **point to running code / observable running state**; if a channel has no live source, the object MUST read as absence, not fabricate motion or signal (no dead-atlas-cells, no pretense).
- **R4.2** It MUST pass the **pronoun test**: naïve viewers (no context, ~15 s) call it a "thing"/"object", not "someone" — it expresses without pretending to be a person.
- **R4.3** It MUST NOT reduce the operator's world to standing-reserve (anti-Ge-stell): it is a medium *through which* the operator senses the system's attending, not a control dial nor an optimization readout of the operator.

## 5. Media (the attended-to content)
- **R5.1** The live media (OARB) MUST be integrated as the **inner attended-object within the structure**, subordinate to and coherent with the attending-form — content nested *inside*, not a slab eclipsing the structure (the scale-1.0 eclipse was a dead-end) and not a flat billboard pasted in front (the billboard was a garble workaround dead-end).
- **R5.2** Media MUST preserve its **native aspect** (16:9) on the inner surface with no letterbox/crop/distortion (a sphere-front / wrapped projection is the recovered-good approach; the exact surface is a design choice).
- **R5.3** Media MUST be carried in a **lossless-enough live format** (BGRA live-texture upload) — it MUST NOT require an 8-bit/compressed MDL-palette skin that format-garbles the feed.
- **R5.4** The media's presence/opacity/treatment MUST itself be **signal-modulated** (it is not a passive slot that simply blanks when video is absent; its absence/idle is an honest state per R4.1).

## 6. Occlusion & depth coherence
- **R6.1** Structure and content MUST be **depth-sorted by one coherent occlusion model**; the structure MUST NOT additively wash, saw through, or wash out the content, and the content MUST NOT bleed through the structure incoherently (the current defect).
- **R6.2** The attending-structure MUST remain visible (opacity > 0, it is an information surface) but **MUST NOT obscure the attended content beyond a bounded, declared occlusion budget** (the incumbent cap is lattice-alpha ≤ 0.30 / depth-veil; the exact value is a design tuning, the *boundedness + determinism* is the requirement).
- **R6.3** Occlusion behaviour MUST be **deterministic and witness-verifiable** at scene-generation and in a live frame-grab (no run-to-run ambiguity).

## 7. Form & placement (abstracted — mechanism is a design choice)
- **R7.1** The form MUST be a **recursive, self-similar structure with a contained inner volume** that holds the media (the incumbent realization is a regular-tetrix Sierpinski lattice with a central octahedral void + inscribed media surface; that specific geometry is a *design choice* for the design phase, not a requirement — but the recovered-good properties below are).
- **R7.2** The structure and inner content MUST be **co-scaled and concentric** (content centered in the structure's inner volume; incenter-based centering is the recovered-good method) so the fit is exact and stable under any scale change — one scale parameter governs both.
- **R7.3** It MUST be **centered, level (base parallel to floor), axis-aligned**, at the room's attention centre, and **legible as a single centered object from all garden pause stations** (no-front; perceivable from the whole walkable field).
- **R7.4** Its angular size MUST meet the Hero legibility target (incumbent ~50° from the default pause station, ≥ the px/degree legibility floor) — large enough to be the object of attention, contained enough not to violate occlusion (R6).

## 8. No chrome / medium-specificity
- **R8.1** It MUST carry **no visible mount chrome**: no border, backing panel, grid background, frame, or physical support geometry; `physical_chrome = forbidden`.
- **R8.2** It MUST be a **spatial object, not a window/HUD**: no fourth-wall surfaces, no screen-space overlays; any supplementation MUST be receiver/mask/depth/route-bound, never unbound screen-space.
- **R8.3** Its **mount + projection + spatial relation MUST be declared before runtime** (deterministic; no ambient/arbitrary placement).

## 9. Governance & contract
- **R9.1** It MUST declare a single **deterministic media-mount contract** (the framework's required fields) as SSOT, including `drift_interaction` (substance owner + families), `hybrid_contract` (engine binding + producer binding), `anti_parasocial_posture`, `freshness`, `consent_or_license`, `purpose`, view-distance/visual-angle.
- **R9.2** Aesthetic parameters (colour, accent, texture grammar) MUST come from the **active Homage pack** (swappable data profile); the portable framework MUST NOT embed Homage-specific tokens (BitchX/ACiD/Enlightenment/…).
- **R9.3** It MUST satisfy the operative **spatiotemporal framework** (all eight research lanes, the failure predicates) — i.e. it is bound by the same governance as every other surface, with no exceptions carved for the centrepiece.

## 10. Technical constraints (medium: DarkPlaces/Quake + Hapax compositor)
- **R10.1** It MUST fit the **17-slot live-texture cap** (one coherent allocation for the unified object; do not require new engine slots beyond the budget).
- **R10.2** It MUST hold **1080p60 at the engine** while its texture/state updates run at the producer cadence (~4–10 Hz); per-frame texture-update budget within the live-texture pipeline (~tens of MB), no per-frame stalls.
- **R10.3** It MUST rely only on the **available render path** (DarkPlaces native depth/occlusion + the live-texture pipeline + the drift service); it MUST NOT depend on unavailable GLSL post-process uservecs or zero-copy GPU-interop that the containment doesn't provide.
- **R10.4** Producers MUST stay **fault-isolated sibling processes** (a producer panic must not crash the engine).

## 11. Anti-requirements (dead-ends — MUST NOT)
- Two separate AoA + OARB wards / two depth-ambiguous surfaces (the thing being torn down).
- A flat billboard media plane, or an 8-bit/compressed MDL-palette skin for live media (garble).
- Media at a scale that eclipses / dominates over the attending-structure.
- Any face-readable / character-readable configuration (R3.4); affect-semantic colour; hardcoded shimmer or deterministic per-cell animation in lieu of signal.
- Fourth-wall/HUD overlays; global luminance flash/dim/pulse; visible chrome/backing/grid.
- Homage-specific tokens baked into the portable framework; any surface exempt from the framework.
- Dead/fabricated state (cells/motion not backed by a live signal).

## 12. Acceptance criteria
- **A1 (unity):** one entity / one contract / one producer / one draw footprint; witnessed as a single depth-coherent object (no sawing/clash) in a live `/dev/video52` frame-grab.
- **A2 (anti-face):** passes the I1–I10 gates + the pronoun test.
- **A3 (honesty):** every visible modulation traces to a named live signal; absent signals read as absence.
- **A4 (occlusion):** content legible, structure bounded ≤ declared occlusion budget, deterministic across runs.
- **A5 (media):** native aspect, no crop/letterbox/garble, signal-modulated presence.
- **A6 (governance):** passes the spatiotemporal-framework validator + failure predicates; no chrome; mount declared.

## 13. Out of scope (deferred to the design phase)
The specific geometry (tetrix vs alternative), the exact inner-surface for media (sphere-front vs other), the precise signal→structure mapping and the per-region grounding-source assignment, the exact occlusion/alpha tuning, the GEAL-primitive set to adopt, and whether the 2-D Sierpinski overlay is folded in or kept parallel. These are design decisions, not requirements.

---

# Addendum A (2026-06-21) — Substrate + Exact Geometry (supersedes the "sphere/ball" form in §0/§5/§7)

Grounding: volumetric-substrate sweep `wf_56eb6c76`, exact-geometry sweep `wf_265eec3d`, operator clarifications. The current tetrix math in `generate-aoa-mdl.py` was audited **mathematically exact** (closed-form regular-tetra vertices, exact 4ⁿ recursion, all 4·4ⁿ faces, correct outward winding, exact incenter, octahedral void) — the geometry problems were the scale mismatch, the OARB *form*, and an *inherited* (not derived) depth, not the math.

## A1. Representation-fidelity principle (governing rule)
- **R-A1.1** Representation MUST NOT misrepresent the data. Where data has no real depth (a flat 2-D video frame / OARB content), the object MUST NOT fabricate depth/relief (no luma→height, no faked curvature). It is shown **flat**.
- **R-A1.2** Where it is **not** a matter of misrepresentation, the object MUST use the **most suitable** form — surface, volume, or both — chosen on representational merit (e.g. signal magnitude rendered as volumetric density is honest *because the volume represents real magnitude*; a true 3-D fractal rendered in 3-D is honest *because its depth is real*).

## A2. Substrate = simulated volumetric display
- **R-A2.1** The unified object's substrate is a **simulated volumetric display**: AoA, OARB, and all content shown through them are constituted by volume elements in one coherent volumetric field (not flat textures on carrier geometry). This makes "content IS the object" literal and makes the single-depth-coherent-field (R1.2/R6) intrinsic rather than tuned.
- **R-A2.2** Feasibility path: a **sibling GPU renderer** (wgpu/Rust, like `screwm_media_drift`/`screwm_ward_atlas`) composites the volumetric AoA/OARB into one depth-coherent output consumed via the live-texture pipeline (respects the 17-slot cap; DarkPlaces cannot raymarch / per-frame-displace natively). The view-correctness method (camera-pose-fed sibling render vs in-engine geometry) is a **design choice** (§A6).
- **R-A2.3** Volumetric rendering MUST clear the same gates as everything else: anti-face I1–I10 applied to the 3-D density field, honesty (A1), legibility floor, and **photosensitivity guardrails** (depth + motion + signal compound flicker — rate-limit).

## A3. AoA — exact Sierpinski tetrahedron (depth is real ⇒ 3-D is honest per A1.2)
- **R-A3.1** The AoA MUST be a **mathematically-exact regular Sierpinski tetrahedron (tetrix)**: canonical regular-tetra root (alternating-cube vertices {(1,1,1),(1,-1,-1),(-1,1,-1),(-1,-1,1)} or an exact rotation), full tetrahedral symmetry (T_d), √-closed-form coordinates, **no floating-point drift** in the recursion (dyadic midpoint subdivision only).
- **R-A3.2** **Centering:** the incenter (≡ centroid for a regular tetra — keep them provably equal; the weighted-incenter is correct but reduces to the centroid here).
- **R-A3.3** **Every implied facet correct**, with these exact counts at depth n: 4ⁿ leaf tetrahedra; **4·4ⁿ** total leaf faces (the addressable/atlas set); **4·3ⁿ** visible outer-surface gasket triangles; 4ⁿ⁻¹ octahedral voids; (n+1)(n+2)(n+3)/6 vertices; leaf edge E/2ⁿ. Every facet emitted, none culled/duplicated/degenerate, each with correct outward (outer shell) or inward (void boundary) normal.

## A4. Ideal fractal depth (derived, not inherited)
- **R-A4.1** Depth MUST be the **deepest level at which the smallest facet stays legible** — i.e. the smallest edge (E/2ⁿ) subtends ≥ the framework legibility floor (~50 px/deg; the GEAL coherence cliff is ~L5 where edges < ~19 px + 8 px glow fuse to haze). Depth is therefore a **function of the AoA's angular size**: a larger AoA ⇒ a deeper legible depth (this is the operator's "larger AoA is the clue").
- **R-A4.2** **Recommendation: depth 5** (1024 leaf tetrahedra, **4096** addressable faces, 972 outer-shell triangles) — the richest signal-bearing set consistent with the HARDM lineage — **contingent on the AoA being scaled large enough that the depth-5 facet (E/32) clears the legibility floor**; otherwise fall back to depth 4 (256 tetrahedra / 1024 faces). Depth ≥6 is excluded (haze cliff).
- **R-A4.3** Inputs required to finalize the exact depth: the Quake-unit→physical scale, the canonical pause-station viewing distance, and the per-face atlas capacity (depth-5 needs ~4096 cells, ~2× the current 2048² atlas, within the texture-update budget).

## A5. OARB — flat content plane (supersedes the sphere/ball)
- **R-A5.1** The OARB is a **single flat plane of the volumetric substrate** carrying the live media at native 16:9, with **no invented depth** (A1.1). The spherical "ball" form is retired — a sphere imposes curvature absent from the flat source (a misrepresentation) and forced the "texture-on-it" framing; the plane is the content itself ("AS it, not ON it").
- **R-A5.2** The plane MUST be **inscribed within the AoA central octahedral void** (insphere radius E/(2√6)), concentric, co-scaled with the tetrix by one scale parameter, sized to the largest 16:9 plane that fits the void without poke-through (occlusion-coherent per R6).
- **R-A5.3** The remaining sphere-specific requirements (UV-sphere resolution, pole/seam handling, sphere-front equirectangular projection) are **void** — the plane needs none of them.

## A6. Reuse — a governed volumetric capability
- **R-A6.1** Volumetric MUST be exposed as a **declared volumetric mount-contract** (extension to the media-mount + framework contracts): `volumetric_mode` (flat-plane | signal-density-volume | …), `depth_budget`, `signal_binding`, slot alias — reuse via the **interface**, implemented once by the sibling renderer.
- **R-A6.2** The governance gates (A2.3) MUST extend to **any** volumetric surface a future ward requests. An **eligibility catalogue** governs adoption: volumetric-appropriate = AoA + (honestly) cameras/IR/reverie; **stay flat** = tickers/text/charts/metadata (legibility). Start with one mode; defer the rest.

## A7. Revised out-of-scope (supersedes §13)
Still design-phase decisions: the **render-path** (camera-pose-fed sibling renderer vs in-engine geometry); the **final depth number** pending the §A4.3 inputs; the **atlas capacity** for depth-5; whether to render the AoA structure itself as volumetric density vs exact surface geometry; the exact signal→facet mapping; and whether the 2-D Sierpinski overlay folds in. The exact tetrix math, the elegance criteria (§A3), the OARB-as-flat-plane (§A5), and the representation principle (§A1) are now **requirements**, not choices.

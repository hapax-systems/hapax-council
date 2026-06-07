# The Chiasm Contract — Hapax' CNS Interface Formalism

**Status:** design (faithful-and-solves-now per adversarial review).
**Date:** 2026-06-07.
**Supersedes:** `2026-06-07-screwm-modulation-matrix-design.md` (the SMM design, #4010) — NOT deleted;
its ECS-pass mandate (snapshot get-views at tick start, evaluate, write put-updates, never
read-modify-write within a tick) carries forward as the loop's evaluation discipline. The SMM's
Modulation-Matrix / Signal / control-blob are demoted to *candidate wire realizations*; the formal
object is the Chiasm Contract below.
**Provenance:** the CNS interface-formalism research workflow (10 agents) + adversarial critique
(verdict: faithful-and-solves-now). Working record: `relay/audits/2026-06-07-cns-interface-formalism-WORKLOG.md`.
**Name:** Hapax' CNS (Chiasmatic Nebulous Scroom — Hapax' Central Nervous System). The `screwm-*` code
prefix is legacy until a deliberate rename migration.

## 0. What the CNS is
The CNS is an **interface/boundary formalism**, not a collection of sub-systems. It is the formal
contract by which **arbitrary chiasmic entities** — sub-systems with opaque, arbitrary internals (a
homage ward; a livestream segment; a compositing effect; drift) — are bound into Hapax's recruitment
loop (impingement → recruit → express → re-perceive). The contract is over an entity's two **chiasmic
surfaces** only; its internals are never the CNS's concern.

## 1. The Chiasm Contract (the type)
A **chiasmic entity is a lawful bidirectional optic** on the recruitment loop:

    ChiasmicEntity := (family: IntentTag, domain: Domain, express: ExpressiveSurface, perceive: RePerceivableSurface)

Its internals are an **opaque transform** `τ : ExpressedValue → world → RealizedState` (reverie
high-pass today; an 8-node substrate tomorrow; a `.frag`; a ward's Cairo paint; a livestream's
external guts). `τ` is the **optic's existential residual `X`** (Tambara/profunctor optics,
arXiv:2001.11816). *This is precisely why binding a ward = a segment = an effect = drift: all are the
**same optic**, differing only in the residual `X` and in the wire-realization carried in metadata.*
The chiasm is the round-trip: `express` is the optic's `put` (impingement crosses **in**); `perceive`
is the optic's `get` (state crosses back **out**).

## 2. Surface 1 — the Expressive / Recruitable surface (`put`)
Unifies what are today three differently-shaped structures, joined only at the scorer, into three
**natural transformations of one `put`** that an entity declares it accepts:

    ExpressiveSurface = (description: GibsonVerb,            # UNCHANGED — the only Qdrant-embedded, cosine-matched face
                         operational: OperationalProperties, # the governance facet
                         mod_targets: list[ModTarget],       # continuous-modulate
                         structural_grammar: PatchGrammar)   # structural-patch

    ModTarget = (param_path: /<domain>/<entity>/<param>, dim: ExpressiveDim ∈ the 9,
                 envelope: {min,max,smoothness,attack,decay,joint_constraints},
                 governed_axes: frozenset[ModulationAxis], realization: {wire ∈ scalar|color|vector|lut|texture})

**Key move:** a target is not "a float param"; it is the entity's *media-specific realization* of a
*media-independent dimension*. The drift currency's G-channel realizes `intensity`; a colorgrade hue
realizes `spectral_color`; a ward scale realizes `depth`. The **dimension is the type**; the wire kind
is metadata — so vector/matrix/LUT/texture control inputs are *declarable, not curtailed* to today's
scalar `u_<key>=<float>`. `AudioVisualModulationGovernor` becomes **one instantiation** (role=AUDIO,
`governed_axes`=its allow-list; the anti-visualizer register filter + `AUDIO_REACTIVE_BANNED_PARAMS`
become the AUDIO instance's axis policy). `PatchGrammar` generalizes `GraphPatch` and carries
modulation authority, so a recruited `node.add` atomically lands params + edges + ModTargets (today
`graph_patch_consumer.py` lands empty params / no edges), retiring the hardcoded 5-of-63-node
enumeration into a parametric grammar over any registered entity.

## 3. Surface 2 — the Re-perceivable surface (`get`) — the missing dual, *derived*
    RePerceivableSurface = (readback_source: artifact ref, dim_projection: RealizedState → vector over the 9 dims,
                            provenance: traversal-provenance ref)   # MANDATORY per ep-claim-001

The entity is re-perceived-from by minting the **existing frozen `Impingement`** (`shared/impingement.py`
— no new currency) with: `source="<entity>.self_perception"`; `intent_family=entity.family`
(re-recruits in the same namespace); **`strength = clamp(‖expressed_target_dims − realized_state_dims‖ / D, 0, 1)`**
(the active-inference **prediction-error**, squashed into the frozen `[0,1]` strength field — D = the
declared get-basis cardinality); `content={topology-position metrics, provenance_ref}`; **`embedding`
present** (so it re-recruits) and **`parent_id` set** (cascade lineage). This generalizes the sole
extant `get`-in-disguise, `_maybe_emit_perceptual_distance_impingement` (`affordance_pipeline.py:1369`),
which is *defective* (emits `embedding=None`, `parent_id=None` — re-perceives without re-recruiting or
linking). Structural template: `agents/audio_self_perception/` (analyzer → `/dev/shm/state.json` →
stimmung injection). **Basis symmetry:** an entity that declares extended `put` dims MUST declare the
same extended dims for its `get`/`dim_projection` — re-perception is never silently truncated to the
base 9.

## 4. The coherence law (active-inference, Hapax's own grounding made bidirectional)
- **PutGet (faithfulness):** after `put(r)` realizes, `get(realized)` re-impinges strength ∝
  ‖expressed-target − realized‖. Perfect realization ⇒ error→0 ⇒ `get` sub-threshold ⇒ the loop
  **quiesces to autonomous substrate wandering** (the permanent generative substrate keeps running) —
  never to black/silent. `get` is a **sensor, never a kill-switch**.
- **GetPut (stability):** zero divergence ⇒ `put` is a no-op ⇒ the substrate is not re-driven. This is
  the formal statement of the **feedback-runaway guard**: a converged entity does not self-amplify.
- The law is a **regulative calibration target** (CI asserts error *trends* toward zero), not a
  provable equality — real prediction-error loops are only approximately well-behaved (arXiv:1910.10421).
- **Grounding (corrected citation):** this is Hapax's *own* commitment made bidirectional — see the
  `Impingement` docstring ("deviation from the DMN's predictive model"), `docs/.../dmn-architecture.md:90`
  (the stopping-criterion), and the wired apperception `prediction_error` source. (NOT
  unified-semantic-recruitment §8.2, which grounds substrate permanence, not prediction-error.) The
  optic/profunctor framing is the published correct shape for a get/put pair ("Bayesian Updates Compose
  Optically", arXiv:2006.01631) — it *organizes* existing commitments, it does not import new ones.
- Evaluate as the SMM ECS pass; **measure loop gain before** enabling `get→select()` write-back
  (extend the drift daemon's existing bounded decay-toward-neutral: mix toward 0.5, fb clamp ≤0.94).

## 5. Consent threads through the optic (recovers the veto, never weakens it)
The optic value channel is **`Labeled[A]`**, not bare `A` (`packages/agentgov/` — built, currently
imported nowhere in the binding path). `put.map`/`get.map` preserve label+provenance (functor laws).
Along express→re-perceive the `ConsentLabel` **joins** (policy-union LUB — most-restrictive) so a
person-adjacent signal cannot be re-perceived/re-recruited/egressed at a laxer level than it entered;
`can_flow_to` is the egress check (face-privacy-at-egress #129 = one `can_flow_to` instance). `Says[Principal]`
threads accountability (non-amplifying handoff); `ProvenanceExpr` (PosBool semiring) threads
why-provenance so the re-perceived `Impingement` satisfies ep-claim-001 **by construction**. **The
boolean gate is recovered, not replaced:** `_consent_allows` (`affordance_pipeline.py:453`) stays the
fail-closed Via gate; the threaded label is its single-policy `can_flow_to` projection; missing scope ⇒
most-restrictive default (still fail-closed); `person_id=="operator"` rejection preserved.

## 6. The binding operation (the single Via, unchanged)
`AffordancePipeline.select()` is THE binding operator for **both** surfaces and is unchanged as the
sole path. To bind any entity is one formal operation: declare a `ChiasmicEntity` record; binding and
re-perception fall out of the type. `put`: `Impingement → select()` (Gibson-verb cosine +
family-prefix-restricted retrieval + domain typing) → value delivered to the addressed `ModTarget`.
`get`: realized state → `dim_projection` → minted `Impingement` → `select()`.

## 7. Reformalizations of the Hapax core (extension, never curtailment; each preserves its invariants)
1. **Affordance ontology → two-sided.** Add `RePerceivableProperties` dual to `OperationalProperties`
   (`affordance.py:55`), carried by `CapabilityRecord`. *Preserves:* `select()` the singular Via; the
   frozen, id+parent_id-traceable, max_depth=3 `Impingement`.
2. **Consent → threaded `Labeled`** (activate the built `agentgov` stack). *Preserves:* `_consent_allows`
   fail-closed; boolean recovered as single-policy projection.
3. **Dimensions → typed registered `ExpressiveDimension` vocabulary** (sibling to `shared/dimensions.py`'s
   PROFILE dims, disambiguated), shared by both surfaces. *Preserves:* media-independence (wire
   realization in metadata, never embedded).
4. **Continuous crossing → `ModTarget`** (generalize `ModulationBinding` + the audio-visual governor).
   *Preserves:* anti-visualizer + banned-params + per-role allow-lists as the AUDIO instance's axes.
5. **Structural crossing → `PatchGrammar`** (generalize `GraphPatch` to carry ModTargets + atomic edges).
   *Preserves:* value-semantics `apply_patch` (pure `put`, so before/after error comparison holds).
6. **Recruitment addressing → first-class `intent_family` + `domain`** (retire the hand-extended Literal
   + the `_canonical_family_prefix` hand-map). *Preserves:* prefix-restriction retrieval behavior.
   (`OperationalProperties.domain` already = `Literal['content','geometry','both']` on this worktree;
   extend with `drift|audio|physics`.)
7. **Loop → the coherence law** + feedback-gain gating + symmetric outcome learning (`record_outcome`
   from error *reduction*). *Preserves:* the permanent generative substrate (error→0 ⇒ wandering); the
   scoring formula unchanged.

## 8. Instantiation NOW — DRIFT (solves the live issues)
Live defects (verified): dead currency (`quake-drift-currency.bgra` absent; `hapax_driftcurrency_enable`
unset — #4012 fixes); dimensionally-collapsed wire (greyscale `vec4(vec3(currency),1)`); drift not
recruited (synthetic `_pulse` oscillators, `screwm-drift-state-source.py`); re-perception empty (zero
consumers of the currency — the loop is open). Build sequence:
- **PR-A** (schema prereq): `OperationalProperties.domain += [drift,audio,physics]`; add `RePerceivableProperties`; serialize into both Qdrant payload writers.
- **PR-B** (live fix): deploy the dual-output daemon (currency live, via #4007); encode currency `(R=family,G=intensity,B=phase,A=consent-label)` instead of greyscale.
- **PR-C** (re-perceivable surface, **AUDIT-ONLY first** — the central new leg): `agents/screwm_self_perception/` mirroring `agents/audio_self_perception/`; reads the currency BGRA → per-zone energy → mints `screwm.drift.self_perception` `Impingement` (embedding present, parent_id set, strength=clamped prediction-error). Audit-only = observes, does not yet write back.
- **PR-D**: `drift_recruitment_consumer.py` (modeled on `graph_patch_consumer.py`) — recruited `drift.*` capabilities replace the synthetic `_pulse`.
- **PR-E** (gated): wire `get`→`select()` + `record_outcome` from error reduction, only after the gain measurement.

## 9. Instantiation NOW — COMPOSITING (solves the live issues)
Live defects (verified): rank collapse (63 manifests registered, only 5 recruitable-as-addition);
scalar-only param surface; `GraphPatch` disclaims modulation (empty params/no edges); no per-effect
re-perceivable surface; hardcoded structural grafts (screen/0.5); governance asymmetry; physical slot
ceiling (12, silent truncation). (Note: the 63 nodes are `.yaml/.json` manifests via the
`ShaderRegistry`, *not* `agents/shaders/nodes/*.py`.) Build sequence:
- **PR-C0** (this doc): supersede SMM; CNS rename; the citation fix.
- **PR-C1**: the typed `ExpressiveDimension` vocabulary (no behavior change).
- **PR-C2**: a `ShaderRegistry → CapabilityRecord` deriver (Gibson-verb description per manifest) — kills rank collapse, makes all 63 recruitable.
- **PR-C3**: `PatchGrammar` (atomic params + edges + ModTargets).
- **PR-C4** (re-perceivable surface, **AUDIT-ONLY** — the central new leg): per-effect self-perception emitter (re-attribute `_record_blit_observability` to the producing node; dim_projection; minted Impingement).
- **PR-C5**: activate the `agentgov` `Labeled`/`Says`/`Provenance` consent label on the value channel.
- **PR-C6** (gated): close the loop under gain measurement + symmetric learning.

## 10. LATER instances (after drift + compositing prove the contract)
Homage wards / ward atlas; livestream segments / programme-director boundary; audio reactivity +
governance; physics greenfield. Each is the *same* optic with a different residual `τ`. Flag any that
strain the contract (a sign of remaining under-formalization).

## 11. Open consent question (flagged)
The ratchet-release (carried `ConsentLabel` drops on prediction-error→0) is the one place the consent
invariant could weaken; it needs a tighter justification than "the substrate is not person-derived"
before PR-C5 lands the label reset. Treat as fail-closed (no release) until justified.

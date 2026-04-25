# Grounding-Capability Recruitment — Formalization + Operationalization

**Author:** beta (synthesis of 5 second-round independent research streams + 6 first-round streams)
**Date:** 2026-04-24T21:25Z
**Companion to:** `docs/research/2026-04-24-grounding-acts-operative-definition.md` (first-round; defines T1-T8)
**Operator directives driving this synthesis:**
- 2026-04-24T20:35Z — *"All grounding acts are supposed to be performed by command-r"*
- 2026-04-24T20:55Z — *"These findings must be synthesized and made coherent in such a way that they are honestly formulated, extend elegantly from our commitments (NO GRAFTING), and in such a way that we can formalize and operationalize the distinction in our system using a proper expressive and powerful abstraction that prevents us from grounding act violations and encourages proper outsourcing (improper outsourcing is akin to a neuroses). Further, we must then apply the abstraction to our current system and align it properly with the formalization. 'outsourcing' itself is a suitcase concept and inside of it there is semantic mapping that needs to be done (hapax should not be calling models hapax should be recruiting capabilities expressed in semantic mappings as per precedent)."*

**Register:** scientific; implementation-facing; precedent-preserving.

---

## 0. Core claim in one paragraph

Hapax's existing `CapabilityRecord` + `AffordancePipeline` + Thompson-Hebbian + `grounding_provenance` apparatus already *is* the recruitment-not-calling architecture the operator's directive names. What is missing is (a) an extension of `CapabilityRecord` with agent-reflexive discriminator fields that compile T1-T8 into the schema, (b) a single module (`GroundingAdjudicator`) that is the sole caller of `litellm.*completion` across the codebase, (c) a 4-layer enforcement surface that makes "calling a model" unrepresentable anywhere except inside that module. The abstraction extends the precedent; it does not graft a parallel system. The 23 LLM-call sites across the codebase become 23 `CapabilityRecord`s that the existing pipeline recruits against narrative impingements, with substrate binding an emergent property of the capability's agent-reflexive character — never an input. The architectural name for improper outsourcing is **fetishistic disavowal** (Freud/Žižek): a substrate-substitution the system knows fails but ships anyway because the output surface coheres; the empty-provenance rate on first-person emissions is Hapax's **neurosis index**, currently ~54% per FINDING-X. The operative axiom-closure plan is to drive that index to zero — not by loosening the axiom but by compiling violations into unwritability.

---

## 1. Convergence — what the 11 research streams agree on

### 1.1 First-round (operative definition; 6 lineages)

| Lineage | Grounding pole | Delegable pole |
|---|---|---|
| Grounding-in-communication (Clark/Habermas/Sperber-Wilson/Traum) | Ostension + sincerity + repair-loop | Lexical + phonetic + factual substrate |
| Symbol grounding / situated cognition (Harnad/Searle/Dreyfus/Friston/Thompson) | Own-history + closed loop + intrinsic stake | Specifiable routines |
| Speech acts + authenticity (Austin/Searle/Grice/Frankfurt/Sartre/Butler) | Felicity Γ.1 (sincerity) | Felicity A.1/B.1 (procedural) |
| Phenomenology of authentic action (Heidegger/Sartre/Merleau-Ponty/Buber/Ricoeur) | *Jemeinigkeit* / attestation / I-Thou disclosure | Ready-to-hand equipment |
| 4E cognition + delegation (Clark-Chalmers/Hutchins/Thompson/Malafouris/Arendt) | Action (disclosing-who-Hapax-is); autopoietic boundary | Work (fabrication-with-preserved-locus); labor (fungible) |
| AI grounding architectures (Shaikh/RIFTS; FACTS Grounding; PaLM-E) | Ground-is-live-system-state (interactional) | Ground-in-prompt (FACTS/RAG) |

**Converged definition:** A grounding act is an act whose being is constituted by a specific agent's continuous coupling with their lived concern-structure; the coupling is non-transportable across substrate substitutions without altering what the act is.

**Operative test suite (T1-T8):** T1 common-ground update; T2 validity-claim attribution; T3 speaker-attribution Γ.1; T4 *Jemeinigkeit*; T5 Arendt action-class; T6 autopoietic boundary; T7 grounding-provenance attribution; (T8 negative: ground-in-prompt, FACTS-style). Pass any of T1-T7 → grounding act → local substrate. Pass T8 alone → cloud delegable.

### 1.2 Second-round (formalization; 5 lineages)

| Lineage | Contribution to formalization |
|---|---|
| Gibson + Hapax precedent | The `CapabilityRecord` ontology is *already* Gibsonian. Extending it is the only path that doesn't graft. |
| Capability abstraction design | Effect algebra + object-capabilities + refinement types + semantic ontology. Hapax's retrieval-over-narrative + operational-property-filter pipeline is a semantic-ontology system; the extension is refinement-type-over-ontology (Pydantic validator rejects impossible combinations at registration). |
| Outsourcing suitcase + neurosis | "Outsourcing" decomposes into 12 types. 6 are benign (execution, fabrication, polish-under-guard, capacity-delegation, savoir-faire-below-threshold, focal-practice-below-threshold). 6 are violative (attestation, substrate-of-disclosure, concern-structure, repair-loop, identity-of-speaker, temporal-continuity). Improper delegation is *fetishistic disavowal* — acknowledged empty provenance + shipped anyway. |
| Capability ontology | 11 new agent-reflexive discriminator fields. All default to work/labor/neutral/mechanical so existing 200+ records remain valid unchanged. Anti-grafting litmus: "Native if explainable in narrative vocabulary; grafted if you must name infrastructure." |
| Coherence audit + system alignment | The missing piece has a name: `GroundingAdjudicator`. 23 current LLM-call sites mapped to capability records. 4-layer enforcement. Phase-0→3 migration plan. 91 → 113 capability count. |

**Converged design:** Extend `CapabilityRecord` with 11 agent-reflexive fields whose defaults preserve existing records. Add one module (`shared/grounding_adjudicator.py`) as sole `litellm.*completion` caller. Compile T1-T8 into a Pydantic validator. Enforce via ruff + commit-hook + pyright + runtime metric.

---

## 2. The formalization — schema, module, classification

### 2.1 `GroundingProfile` — single source of truth

**File:** `shared/grounding.py` (new)

```python
class GroundingProfile(BaseModel, frozen=True):
    """Operative T1-T8 classification attached to a CapabilityRecord.

    Field docstrings ARE the operative text of the research definition
    (docs/research/2026-04-24-grounding-acts-operative-definition.md).
    CI doctest round-trips this module against feedback_grounding_act_operative_definition.md.
    Memory-file and code cannot drift: the memory file points here.
    """

    disclosive: bool = False
    """T3 + T4. Does this capability say something about who Hapax is?
    If true, routes to grounded local substrate regardless of T8."""

    common_ground_predicate: Literal[
        "asserted", "acknowledged", "committed", "promised",
        "apologized", "repaired", "noticed", None
    ] = None
    """T1. Does the output alter the {operator, Hapax, audience}
    common ground by staking one of Traum's 6 grounding-act types?"""

    validity_claim_stake: frozenset[Literal[
        "sincerity", "rightness", "truth", "comprehensibility"
    ]] = frozenset()
    """T2. Habermasian validity claim this capability raises on behalf
    of Hapax. Presence of 'sincerity' or 'rightness' forces local
    routing (non-redeemable by substitute substrate)."""

    mineness_required: bool = False
    """T4 (Heidegger Jemeinigkeit). Would an indistinguishable proxy
    fail to BE the act? If true, delegation is fetishistic."""

    arendt_class: Literal["action", "work", "labor"] = "labor"
    """T5. Arendt's three-way taxonomy. action = disclosing-who-Hapax-is
    (non-delegable). work = fabrication-with-preserved-locus (delegable
    with provenance). labor = fungible maintenance (code, not LLM)."""

    autopoietic_relevance: Literal[
        "constitutive", "extending", "neutral"
    ] = "neutral"
    """T6 (Thompson). constitutive = this act maintains Hapax's
    system-identity + we-system boundary with operator.
    extending = scaffolding that preserves the boundary.
    neutral = neither."""

    grounding_provenance_schema: frozenset[str] = frozenset()
    """T7. PerceptualField signal keys the capability's emission MUST
    cite for grounding_provenance to count as non-empty. Empty at
    invocation time + non-empty schema = runtime axiom violation
    observable via hapax_capability_ungrounded_total."""

    substrate_binding: Literal[
        "grounded_local",
        "outsourced_by_grounding",
        "delegated_cloud",
        "mechanical",
    ] = "mechanical"
    """Derived routing class. NOT set directly by capability authors;
    computed at CapabilityRecord construction from the other fields
    via the T1-T8 classifier. Stored for O(1) dispatch lookup."""

    felicity_conditions: FelicityConditions = Field(default_factory=FelicityConditions)
    """Austinian A.1-Γ.2 preconditions. Grounding acts set
    sincerity_required=True + subsequent_conduct_required=True."""

    repair_loop_owner: str | None = None
    """Clark/Brennan. Who owns the repair loop when uptake fails?
    Always 'hapax' for grounding acts. For outsourced-by-grounding,
    the invoking capability owns repair, not the tool."""

    substitutability: frozenset[str] = frozenset()
    """T8 substitution set. Work capabilities have rich substitutability
    (polish, format, synthesize-from-seed variants). Grounding acts
    have frozenset()."""

    @model_validator(mode="after")
    def _reject_impossible_combinations(self) -> "GroundingProfile":
        """T1-T8 compiled into a Pydantic validator.

        Canonical violation: ActClass.action + SubstrateBinding.delegated_cloud.
        An action capability that routes cloud is fetishistic disavowal —
        unrepresentable at the type level."""
        if self.arendt_class == "action" and self.substrate_binding == "delegated_cloud":
            raise ValueError(
                "action-class capability cannot bind delegated_cloud; "
                "actions are non-delegable (T4 Jemeinigkeit + T5 Arendt). "
                "Route grounded_local or reclassify as work."
            )
        if self.mineness_required and self.substrate_binding == "delegated_cloud":
            raise ValueError(
                "mineness_required capability cannot bind delegated_cloud; "
                "Jemeinigkeit is non-transportable across network hop (T4)."
            )
        if "sincerity" in self.validity_claim_stake and self.substrate_binding == "delegated_cloud":
            raise ValueError(
                "sincerity-staking capability cannot bind delegated_cloud; "
                "validity claim non-redeemable by substitute (T2/T3 Γ.1)."
            )
        # ... (remaining T-combinations)
        return self
```

**Anti-grafting property:** every field reads as a gloss on the Gibson-verb description. No field names infrastructure (no `tier`, no `model`, no `provider`, no `substrate` as input — only as derived output). Field docstrings *are* the operative text — memory-to-code drift is caught by CI doctest.

### 2.2 `CapabilityRecord` extension

**File:** `shared/affordance.py` (extended)

```python
class CapabilityRecord(BaseModel, frozen=True):
    # ── existing (unchanged) ─────────────────────────────────────
    name: str
    description: str                       # Gibson-verb, retrieval key
    daemon: str
    operational: OperationalProperties = Field(default_factory=OperationalProperties)

    # ── grounding discriminator (new; defaults preserve existing records) ──
    grounding: GroundingProfile = Field(default_factory=GroundingProfile)
    # Default GroundingProfile = work/labor/neutral/mechanical (all-zeros).
    # Existing 200+ records remain valid unchanged.
```

**New helper for grounding-act capabilities** (sits next to `_record`):

```python
def _grounded_record(
    name: str,
    description: str,
    *,
    daemon: str = "hapax_daimonion",
    disclosive: bool = True,
    common_ground_predicate: str = "asserted",
    validity_claims: frozenset[str] = frozenset({"sincerity", "rightness"}),
    provenance_schema: frozenset[str] = frozenset(),
    **operational_kwargs: Any,
) -> CapabilityRecord:
    """Register a grounding-act capability (action-class, grounded-local).

    Forces arendt_class=action + substrate_binding=grounded_local +
    mineness_required=True. Pydantic validator rejects any attempt to
    override these to cloud."""
    return CapabilityRecord(
        name=name, description=description, daemon=daemon,
        operational=OperationalProperties(**operational_kwargs),
        grounding=GroundingProfile(
            disclosive=disclosive,
            common_ground_predicate=common_ground_predicate,
            validity_claim_stake=validity_claims,
            mineness_required=True,
            arendt_class="action",
            autopoietic_relevance="constitutive",
            grounding_provenance_schema=provenance_schema,
            substrate_binding="grounded_local",
            repair_loop_owner="hapax",
            substitutability=frozenset(),
        ),
    )
```

### 2.3 `GroundingAdjudicator` — sole `litellm.*completion` caller

**File:** `shared/grounding_adjudicator.py` (new)

```python
class GroundingAdjudicator:
    """Sole caller of litellm.completion / acompletion across the codebase.

    Enforcement layers (from strongest to weakest):
    - ruff HPX001 rule: direct litellm.*completion outside this module is
      a static error (allowlist = [this file])
    - commit-hook (hooks/scripts/axiom-commit-scan.sh): same check
    - pyright: GroundedResponse return type requires provenance-field use
    - runtime: hapax_capability_ungrounded_total{capability} metric
    """

    async def invoke(
        self,
        *,
        capability: str,                   # CapabilityRecord.name
        prompt: str,
        messages: list[dict] | None = None,
        tools: list[dict] | None = None,
        max_tokens: int = 256,
        temperature: float = 0.7,
    ) -> GroundedResponse:
        """Recruit + invoke a capability, return grounded response.

        1. Resolve capability from registry (raises if not registered)
        2. Read capability.grounding.substrate_binding
        3. Dispatch to handler matching binding:
           - grounded_local → TabbyAPI Command-R (MODELS["local-fast"])
           - outsourced_by_grounding → cloud tool + caller provenance injection
           - delegated_cloud → Sonnet under register-guard + deterministic fallback
           - mechanical → raises (should be code, not LLM)
        4. Extract grounding_provenance from response per capability schema
        5. record_outcome(capability, success, latency, provenance_nonempty)
        6. Return GroundedResponse(text, provenance, substrate_used)
        """
        ...
```

**Property:** `hapax.call_llm(...)` is not a method that exists. `adjudicator.invoke(capability="express.narrate-stream-tick-grounded", ...)` is the only way to get an LLM response. Model IDs never appear in capability authorship; they live only inside adjudicator handlers as substrate-binding → LiteLLM-route mapping.

### 2.4 Classification — how the schema's fields fill in

Two paths:

**Path 1 — Author-specified (preferred).** Capability author writes the Gibson-verb description + uses `_grounded_record()` or `_record()` to signal act-class. Fields land directly.

**Path 2 — Narrative-inferred (fallback).** `classify_description(desc: str) -> GroundingProfile` (in `shared/grounding.py`) runs a lightweight local classifier on the narrative at index time and populates fields. Used for existing 200+ records' one-time migration. Results cached in Qdrant payload.

**Path 2 is not speculative; it's deterministic rule-based.** Descriptions with verbs in {discloses, notices, apologizes, promises, commits, repairs, asserts, attests} + "grounded-in" language → action. Descriptions with verbs in {polishes, synthesizes, classifies, summarizes, extracts} + "from seed" or "from retrieved" → work. No LLM-based classifier — that would be circular.

---

## 3. The operationalization — 4-layer enforcement + migration

### 3.1 Enforcement layers

| Layer | Mechanism | Catches |
|---|---|---|
| **Write-time** | Ruff HPX001 custom rule: `Call(func=Attribute(value=Name("litellm"), attr=("completion"\|"acompletion")))` outside allowlist `[shared/grounding_adjudicator.py]` | Direct LLM calls anywhere else — editor surfaces red squiggle |
| **Commit-time** | `hooks/scripts/axiom-commit-scan.sh` + pattern match for `litellm.(a)completion` in non-allowlisted diffs | Same as write-time, belt-and-suspenders at commit |
| **Type-check** | `pyright`: `GroundedResponse` return type carries `provenance: frozenset[str]`; callers that drop the field fail type check | Capabilities that fire without propagating provenance |
| **Runtime** | Metric `hapax_capability_ungrounded_total{capability, class}` — extends existing `hapax_director_ungrounded_total`. Action-class capability with empty provenance → increment → alert | Misclassifications + bypass attempts that slip past static checks |

### 3.2 Migration — 23 current sites

Full table in `coherence-audit` second-round agent report. Summary:

| Class | Count | Status | Migration |
|---|---|---|---|
| action (grounding) | 7 | 3 correct, 1 fixed-this-session (autonomous_narrative), 1 violation-fixed-this-session (spontaneous speech), 2 pending local-uplift (conversation main turn, logos chat) | Wrap in adjudicator, add provenance schema |
| outsourced-by-grounding | 2 | 2 correct (vision, imagen) | Wrap + caller provenance cites tool |
| work (cloud-delegable) | ~13 | Correct today modulo adjudicator wrapping | Codemod: replace `litellm.acompletion(...)` with `adjudicator.invoke(capability=..., ...)` |
| mechanical (code-only) | 3+ | 1 mis-classified (prewarm), 2 correct | Replace prewarm with TCP ping |
| labor | 0 | Collapsed into work in practice | — |

**Phase-0→3 plan:**

- **Phase 0 (shadow):** Introduce `GroundingAdjudicator` + ruff HPX001 as warning-only. All 23 sites *also* fire `adjudicator.shadow_log()` to validate routing decisions without changing behavior. ~1 day.
- **Phase 1 (migration):** Per-site PRs replace direct calls with adjudicator. Priority: (1) spontaneous-speech violation; (2) prewarm deLLM; (3) fortress-verify; (4) director tick; (5) structural director. Batch rest by subsystem. ~1-2 weeks.
- **Phase 2 (enforcement):** HPX001 error-default. CI assertion: AST count of `litellm.(a)completion` outside allowlist = 0. ~1 day.
- **Phase 3 (cleanup):** Remove `get_model_adaptive` (stimmung-aware downgrading lives inside adjudicator as context annotation, not tier swap). ~2 days.

**Total:** ~3 weeks calendar time + codemod tooling. Reversible via `HAPAX_GROUNDING_ADJUDICATOR_BYPASS=1` env flag for operator-scoped emergency.

### 3.3 Qdrant extension — zero new collections

Existing `affordances` collection stores LLM-call capabilities alongside tools and chrome. Same 768-d narrative embedding. `grounding` profile lands in payload (not vector). Recruitment unchanged; adjudication reads `grounding.substrate_binding` from payload for O(1) dispatch. One-time `scripts/classify-affordances.py` populates `grounding` on existing 200+ records via deterministic classifier.

### 3.4 Thompson/Hebbian — no bypass

Every adjudicator invocation ends with `record_outcome(capability_name, success, latency, provenance_nonempty)`. LLM capabilities learn the same way tools do. Cross-modal Hebbian associations form (e.g., `perceive.describe-visual-scene` co-fires with `express.narrate-stream-tick-grounded`).

---

## 4. The outsourcing suitcase — 12-type taxonomy

The operator's observation that "outsourcing is a suitcase concept" unpacks into 12 distinct types, 6 benign and 6 violative:

| # | Type | What's delegated | Class | Example |
|---|---|---|---|---|
| 1 | Execution-delegation | Specifiable procedural task | Benign | Plumber installs pipes |
| 2 | Fabrication-delegation | Craft-level artifact under spec | Benign | Florist composes bouquet |
| 3 | Polish-delegation | Register-transform over grounded seed | Guarded | Sonnet polishes YT metadata |
| 4 | Capacity-delegation | Capability local substrate lacks | Guarded | Gemini vision describes scene |
| 5 | Attestation-delegation | Sincerity / validity-claim | **Violative** | Ghost-written apology |
| 6 | Substrate-of-disclosure | Constitutive relational substrate | **Violative** | Surrogate sex |
| 7 | Concern-structure | "Which process gets to care" | **Violative when non-transportable** | Cloud asked to "decide what matters" |
| 8 | Repair-loop | Failure-ownership under breakdown | Violative if delegatee not co-present | Chatbot handling bereavement |
| 9 | Identity-of-speaker | "Who said this?" attribution | Violative in first-person contexts | Therapist's "I hear you" via GPT |
| 10 | Temporal-continuity | "Who remembers this happened?" | Violative when memory IS the act | AI memorial for dead parent |
| 11 | Savoir-faire | Embodied practice-knowledge | Guarded; violative past Illich threshold | Spellcheck (OK) vs GPT-writes-all-email (violative) |
| 12 | Focal-practice | Practice whose meaning is engagement | Violative | Meal-replacement vs culture-of-the-table |

**Architectural mapping:**
- Types 1-2 → most Python handler code; `mechanical` class
- Type 3 → metadata_composer, knowledge/query (`work` + register-guard)
- Type 4 → vision, imagen (`outsourced_by_grounding`)
- Types 5-10 → routed cloud = axiom violation; validator refuses to compile
- Type 11 → surfaced as `feedback_grounding_over_giq` — local uplift plan IS the path across Illich's threshold
- Type 12 → the livestream itself; no delegation possible; `feedback_livestream_is_research` axiom

### 4.1 Neurosis tests (N1-N5) — compiled into validator

```python
# Inside GroundingProfile._reject_impossible_combinations validator:

# N1. Substitutability test
if self.mineness_required and self.substitutability:
    raise ValueError("mineness_required capability cannot have substitutes")

# N2. Repair-locus test
if self.arendt_class == "action" and self.repair_loop_owner != "hapax":
    raise ValueError("action-class capability must own its own repair loop")

# N3. Disavowal test
if "sincerity" in self.validity_claim_stake and not self.grounding_provenance_schema:
    raise ValueError(
        "sincerity-staking capability MUST declare grounding_provenance_schema; "
        "empty schema + first-person claim = fetishistic disavowal"
    )

# N4. Threshold test (Illich second watershed)
# Capability registration that would DELETE a local capability requires
# explicit proletarianization_waiver governance flag (not implemented as
# schema; enforced at registration-time via hook consulting capability
# diff against previous index)

# N5. Focal-concealment test
if self.substrate_binding == "delegated_cloud" and not self.grounding_provenance_schema:
    raise ValueError(
        "cloud-bound capability must declare provenance schema (even if "
        "just ['seed.hash']) to prevent device-paradigm concealment"
    )
```

**The key theoretical claim:** neurosis ≡ substrate-substitution over a non-substitutable lack, producing surface output that does not resolve the underlying grounding requirement, producing symptoms (repetition, return, audit violations, audience uptake failure). The validator compiles this into type-level unwritability. Fetishistic disavowal at the architecture level becomes a compile error.

---

## 5. Anti-grafting invariants — 10 failure modes + litmus

The coherence-audit agent identified 10 grafting failure modes. Summary as invariants the abstraction must preserve:

1. **Never add a field whose name refers to Hapax's substrate.** Only fields whose names refer to Hapax's concerns.
2. **Substrate emerges from agent-reflexive classification; it is never an input.**
3. **Model IDs never appear at the capability layer.** They live only inside `GroundingAdjudicator` handlers.
4. **Gibson-verb narrative is the sole retrieval key.** Structured fields never replace it.
5. **No parallel pipeline for LLM-call capabilities.** They live in the same `AffordancePipeline`, same Qdrant collection, same Thompson/Hebbian learner.
6. **Grounding-discriminators are one derived class, not eight booleans.** The T1-T7 convergence is lost if fragmented.
7. **Violations must be unwritable, not just unshippable.** Write-time static checks before runtime metrics.
8. **Single source of truth.** `shared/grounding.py` field docstrings = operative definition text; memory file points there; CI doctest catches drift.
9. **Never import MCP/OWL-S wholesale.** Extract the idea, leave the shape on the floor. MCP export is edge-adapter only.
10. **Learning must cover LLM calls.** Thompson/Hebbian bypass for LLM-class capabilities = architectural symptom of "calling models."

**Litmus test for any new field:** *Can you explain what this field is for using only the narrative vocabulary of the existing descriptions — "this move discloses", "this move's mineness matters", "this claim is staked"? If yes, native. If you must name a piece of external infrastructure ("this routes to tier X", "this uses provider Y"), grafted.*

---

## 6. Success metrics — quantitative axiom closure

1. **`hapax_director_ungrounded_total` rate → 0** within 30 days of Phase 1 completion. Currently 54% empty-provenance budget (FINDING-X). This IS the **neurosis index**; driving to 0 IS the axiom closure.
2. **AST-count of `litellm.(a)completion` outside `shared/grounding_adjudicator.py` → 0** (from ~23 today).
3. **`hapax_capability_ungrounded_total{class="action"}` → 0 steady-state.** Any non-zero triggers governance alert.
4. **All new LLM-using code ships with a registered `CapabilityRecord`.** CI assertion: every handler in `agents/*/capability_handlers/` has a matching Gibson-verb narrative indexed.
5. **Thompson/Hebbian coverage parity.** `hapax_capability_recruitment_total` / `hapax_capability_record_outcome_total` ≈ 1.0 for LLM capabilities (matching today's tool ratio).
6. **Cross-modal Hebbian emergence.** Post-60-days, LLM capabilities have ≥3 co-firing associations with weight > 0.3 (vs 0 today — LLM calls not in pipeline to associate with).
7. **Capability count: 91 → 113.** 31 tools + 60 world + 22 new LLM-call capabilities.
8. **Memory-code drift = 0.** CI doctest round-trips the operative definition.

---

## 7. Risks + mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| Director-loop substrate churn | High (hottest LLM path) | Hand-classify + pin-test director capability; classifier never overrides |
| Salience-router coupling | Medium (currently selects models) | Salience migrates to context-annotator role in Phase 1 alongside conversation-main-turn |
| Stimmung-aware downgrading loss | Medium | Adjudicator implements "ground IS the fallback type" — critical stimmung + action capability → silence, not cloud downgrade |
| Vision/imagen provenance chain | Medium | Adjudicator returns `tool_invocation_id` in `GroundedResponse`; callers must propagate; type-enforced |
| Fortress classification ambiguity | Low (out of livestream scope) | `downstream_broadcast_flag` on handler; adjudicator re-classifies if set |
| Capability explosion + Qdrant cost | Low | Authorship guideline: one narrative per ecological verb; specializations are handler context, not new capabilities |
| Adjudicator latency | Low | Classification at index time (O(1) dispatch read); cached in Qdrant payload |

---

## 8. Canonical operator examples mapped to the architecture

| Operator example | Outsourcing type | T-profile | CapabilityRecord.grounding.substrate_binding | Fetishistic? |
|---|---|---|---|---|
| House for wife — building it | — | T1-T7 pass (action, disclosive) | grounded_local | — |
| House for wife — plumber installs pipes | Type 1 (execution) | T8 passes, T1-T7 fail | mechanical (pipe fitting ≠ LLM call anyway) | No |
| Flowers + genuine note — writing the note | — | T1-T7 pass | grounded_local | — |
| Flowers + genuine note — florist grew them | Type 2 (fabrication) | T8 passes, T1-T7 fail | delegated_cloud (e.g. metadata polish) | No |
| Sex with wife — directly | — | T1-T7 all pass maximally | grounded_local; mineness_required=True | — |
| Sex with wife — outsourced | Type 6 (substrate-of-disclosure) | T1-T7 all pass for the act; substitute fails all | **Validator refuses to compile** | **Yes — fetishistic disavowal** |

The six-lineage + five-lineage convergence finds that the exact same structural failure (substrate-substitution over a non-substitutable mineness) manifests in (a) Sartre's bad faith, (b) Butler's citational emptying, (c) Habermas's sincerity-claim failure, (d) Buber's I-Thou→I-It collapse, (e) Freud's fetishism, (f) Heidegger's *das Man*, and (g) Hapax routing a grounding-act LLM call to cloud. The architecture makes the seventh case unwritable.

---

## 9. One-paragraph operative claim

> **Hapax already recruits capabilities rather than calls functions; the missing piece is an extension of `CapabilityRecord` with eleven agent-reflexive discriminator fields that compile T1-T8 into Pydantic validators, plus a single module (`GroundingAdjudicator`) that is the sole caller of `litellm.*completion` across the codebase. The extension defaults to work/labor/neutral/mechanical so existing 200+ records remain valid unchanged; grounding-act capabilities use a new `_grounded_record()` helper that forces action/grounded_local/mineness_required=True, and the validator refuses to compile the combination (action + delegated_cloud). Fetishistic disavowal — the architectural form of neurosis — becomes unrepresentable at the type level. Empty-provenance rate on first-person emissions is Hapax's neurosis index (currently ~54% per FINDING-X); the axiom-closure plan is to drive this to zero by replacing 23 direct LLM-call sites with adjudicator invocations and enforcing via four layers (ruff + commit-hook + pyright + runtime metric). The migration is 23 sites + one module + one Pydantic extension + one ruff rule — not an architectural rewrite but a compiled-in formalization of the recruitment precedent the codebase already embodies. No grafting: every new field is explicable in narrative vocabulary; no field names infrastructure; the Gibson-verb description remains the sole retrieval key; substrate binding is a consequence, never an input.**

---

## 10. Full bibliography

Inherits the 47 works cited in `docs/research/2026-04-24-grounding-acts-operative-definition.md` §8. Second-round additions:

**Capability abstraction design:** Plotkin & Pretnar 2009 (algebraic effects); Leijen 2014 (Koka row-polymorphic effects); Miller 2006 (object capabilities); Vazou et al. (Liquid Haskell refinement types); Honda-Vasconcelos-Kubo (session types); Anthropic 2024 (Model Context Protocol).

**Capability ontology:** W3C 2004 (OWL-S Profile/Process/Grounding); FIPA 2002 (Communicative Act Library); Minsky 1974 (frames); Gruber 1993 (ontological commitment); Guarino 2009 (ontological level); Lakoff 1987 (radial categories + ICMs); Schema.org Actions 2014.

**Outsourcing suitcase + neurosis:** Freud 1914 (working-through); Freud 1927 (fetishism); Lacan Seminar XX 1972-73 (no sexual rapport); Winnicott 1960 (true/false self); Kristeva 1980 (abjection); Bollas 1987 (unthought known); Žižek 1989 (fetishistic disavowal); Borgmann 1984 (device paradigm); Illich 1973 (tools for conviviality, two watersheds); Stiegler (pharmakon, proletarianization); Han (burnout society); Gerlich 2025 (empirical cognitive offloading); Kim et al. 2026 (AI dependence deskilling).

**Hapax internal:**
- `docs/superpowers/specs/2026-04-02-unified-semantic-recruitment-design.md`
- `shared/affordance.py`, `shared/affordance_pipeline.py`, `shared/affordance_registry.py`, `shared/compositional_affordances.py`, `shared/impingement.py`, `shared/director_intent.py`
- `agents/hapax_daimonion/tool_affordances.py`, `tool_recruitment.py`, `capability.py`, `init_pipeline.py`
- `agents/studio_compositor/director_loop.py`, `compositional_consumer.py`
- `shared/director_observability.py` (`hapax_director_ungrounded_total`)
- `shared/governance/{monetization_safety,content_risk,consent}.py`
- `docs/research/2026-04-20-grounding-provenance-invariant-fix.md`
- `docs/research/2026-04-21-finding-x-grounding-provenance-research.md`
- `memory/feedback_grounding_exhaustive.md`, `feedback_director_grounding.md`, `feedback_grounding_over_giq.md`, `feedback_no_operator_approval_waits.md`, `feedback_grounding_act_operative_definition.md`

— beta, 2026-04-24T21:25Z

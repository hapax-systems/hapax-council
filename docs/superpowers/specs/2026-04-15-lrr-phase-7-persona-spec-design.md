# LRR Phase 7 — Persona / Posture / Role Spec Authoring — Design Spec

> **⚠ SUPERSEDED 2026-04-16** by `docs/superpowers/specs/2026-04-16-lrr-phase-7-redesign-persona-posture-role.md`.
>
> This spec's YAML schema (`role.facets[]`, `posture.bearing/temperament/pacing`, `personality.attention/aesthetic/register`, `engagement_commitments.audience_axis`, `splattribution_commitment`) was burned down per operator's 2026-04-16 reframe. Reasons: facets imply decomposable identity (rejected — roles are thick positions in the "Father" sense); bearing/temperament/pacing are personification vocabulary (rejected — persona is description-of-being); personality treats personality as primary (rejected — Hapax has no personality in the schema's sense). The redesign locks an 8-position taxonomy across 3 layers (functional dissolved), adopts Actor-Network Theory as primary theoretical frame, and replaces the YAML schema with three artifacts: persona document (prose, description-of-being), posture vocabulary (architectural-state → named-posture map), role registry (8 thick positions). See the redesign spec for current scope, exit criteria, and rationale.
>
> Content below preserved for provenance only.

---

**Date:** 2026-04-15
**Author:** delta (pre-staging extraction from LRR epic spec; LRR execution remains alpha's workstream)
**Status:** SUPERSEDED 2026-04-16 — see redesign spec above
**Epic reference:** `docs/superpowers/specs/2026-04-14-livestream-research-ready-epic-design.md` §5 Phase 7 (canonical source)
**Plan reference:** `docs/superpowers/plans/2026-04-15-lrr-phase-7-persona-spec-plan.md` (companion TDD checkbox plan)
**Branch target:** `feat/lrr-phase-7-persona-spec`
**Cross-epic authority:** `docs/research/2026-04-14-cross-epic-fold-in-lrr-hsea.md` (drop #62) — §3 row 9 axiom precedent ownership + HSEA Phase 2 (UP-10) dependency on this phase
**Unified phase mapping:** **UP-9 Persona** (drop #62 §5): depends on UP-7 (substrate swap) + UP-8 (governance finalization); blocks UP-10 (HSEA Phase 2 core director activities); ~800 LOC

> **2026-04-15T07:15Z update:** the Hermes 3 substrate framing in this spec is SUPERSEDED per drop #62 §14 — the operator abandoned Hermes at 2026-04-15T06:35Z and commissioned substrate re-evaluation research (beta's `bb2fb27ca` commit on `beta-phase-4-bootstrap` / `docs/research/2026-04-15-substrate-reeval-post-hermes.md`). The "tune persona for Hermes 3's aggressive system-prompt compliance" goal is no longer operator-preferred. Phase 7 opener MUST read drop #62 §14 before starting work and reframe the persona tuning to whichever substrate is active at Phase 7 open time (most likely Qwen3.5-9B or OLMo 3-7B per beta's research §9 recommendation). The body of this spec is otherwise structurally valid — the process (YAML schema + renderer + VOLATILE-band injection + frozen-files + testing + operator sign-off) is substrate-agnostic; only the specific goal statement in §1 and the risk row mentioning "Pre-Hermes Qwen3.5-9B" in §6 contain the stale framing.

---

## 1. Phase goal

Author the persona / posture / role spec that makes Hapax survive Hermes 3's "aggressively system-prompt compliant" substrate without flattening into generic assistant mush. Absorb the token pole ethical engagement design principles as constitutional foundations. Wire VOLATILE-band system-prompt injection across the director loop and voice grounding pipelines. **Phase 7 completes the DF-1 resolution** (authenticity vs performance; substrate vs character; solo vs duet + recursion).

**What this phase is:** the persona YAML at `axioms/persona/hapax-livestream.yaml`, the `shared/persona_renderer.py` module that compiles it to a ~400-token system prompt fragment, the VOLATILE-band injection into `director_loop._build_unified_prompt()` + `agents/hapax_daimonion/persona.py::_EXPERIMENT_PROMPT`, persona versioning tied to condition_id transitions, research registry integration (`directives_manifest` sha256), 5 synthetic test prompts with measurable register shift verification, and operator sign-off procedure.

**What this phase is NOT:** this phase does not author the governance rules (LRR Phase 6 / UP-8), does not ship the content programming via objectives (LRR Phase 8 / UP-11), does not modify the token pole itself (existing), and does not ship any HSEA activity handler (HSEA Phase 2 / UP-10 is downstream of this).

**Theoretical grounding:**
- **DF-1 three tensions**: authenticity vs performance, substrate vs character, solo vs duet + recursion
- **I-2 role resolution**: research_subject + research_instrument + research_programmer = same role
- **P-4**: recursion is constitutive ("I am the experiment I am running")
- **P-6**: token pole ethical engagement principles as foundations

**Critical downstream consumer:** HSEA Phase 2 (UP-10) deliverable 3.1 activity taxonomy extension — every new activity (`draft`, `reflect`, `critique`, `compose_drop`, `synthesize`, `exemplar_review`, `patch` stub) uses the persona prompt assembled by this phase. Without LRR Phase 7 closed, HSEA Phase 2 activities have no persona to speak in and produce generic-assistant output.

---

## 2. Dependencies + preconditions

**Cross-epic (from drop #62):**

1. **LRR UP-0 + UP-1 closed.** Standard precondition chain.

2. **LRR UP-7 (Hermes 3 8B parallel substrate) closed** per epic spec Phase 7 dependency. Phase 7's explicit motivation is to make the persona survive Hermes 3's system-prompt compliance — Phase 7 CANNOT open against the pre-Hermes Qwen3.5-9B substrate because the whole point is post-substrate-swap hardening. **However**, the spec can be pre-staged (this extraction) against either substrate; execution requires the substrate to be live.

3. **LRR UP-8 (governance finalization) closed** per epic spec Phase 7 dependency. The persona must be consistent with the governance model — Phase 6 ships the axiom amendments that constrain what the persona can claim. Phase 7 references the finalized governance rules.

4. **HSEA UP-2 + UP-4 NOT required.** Phase 7 is LRR-only; HSEA Phase 0 + Phase 1 do not ship anything Phase 7 consumes.

5. **Axiom precedent `sp-hsea-mg-001` (HSEA Phase 0 0.5) already landed via LRR Phase 6 joint PR** per Q5 ratification. Phase 7's persona spec references `sp-hsea-mg-001` in its constraint section but does NOT draft the precedent.

**Intra-epic:**
- Phase 5a (substrate swap) live
- Phase 6 (governance) merged
- Phase 0 + 1 closed

**Infrastructure:**

1. `axioms/` directory (existing) — Phase 7 creates `axioms/persona/` subdirectory.
2. `agents/hapax_daimonion/persona.py` (existing) — Phase 7 extends `_EXPERIMENT_PROMPT` with the persona fragment.
3. `agents/hapax_daimonion/director_loop.py` or `_build_unified_prompt()` call site (existing) — Phase 7 adds a "## Persona" section.
4. `shared/research_registry_schema.py` (LRR Phase 1 deliverable) — Phase 7 extends `directives_manifest` with persona file sha256.
5. `scripts/research-registry.py` (LRR Phase 1 deliverable) — Phase 7 adds `show <cond> --persona` flag.
6. `litellm_test_mode` for A/B testing prompts (existing in shared/config.py or similar).
7. `shared/frontmatter.py` (existing) — for reading the YAML persona file.
8. Hermes 3 8B weights on disk (UP-7 deliverable).

---

## 3. Deliverables (7 items)

Each item below extracts directly from LRR epic spec §5 Phase 7 items 1–7.

### 3.1 Persona spec YAML structure (item 1)

**Scope:**
- New YAML file at `axioms/persona/hapax-livestream.yaml` (new `axioms/persona/` subdirectory)
- Schema (per LRR epic spec; verbatim structure, delta not redesigning):
  - `persona_id`, `version`, `authored_at`, `authoritative_on`
  - `role`: load_bearing, facets, recursion_stance
  - `posture`: bearing, temperament, pacing
  - `personality`: attention (cares_about, ignores, dwells_on), aesthetic (finds_beautiful, finds_cheap), register
  - `engagement_commitments`: audience_axis (7 principles from GDO ethical engagement §3.1)
  - `splattribution_commitment`: rule, rationale, application (from GDO handoff §2.8.2)
  - `constraints`: never[], always[]
- **v1 content is the LRR epic spec §5 Phase 7 item 1 YAML block verbatim** — operator review iteration is expected per §7 Q1 below, but the starting draft is the epic-spec draft
- Pydantic model in `shared/persona_schema.py` for validation
- **Target files:**
  - `axioms/persona/hapax-livestream.yaml` (v1 YAML content, ~130 lines)
  - `shared/persona_schema.py` (~200 LOC Pydantic model with nested structures)
  - `tests/shared/test_persona_schema.py` (~120 LOC)
- **Size:** ~450 LOC, 0.3 day serial work (plus iteration time for operator review)

### 3.2 VOLATILE-band injection mechanism (item 2)

**Scope:**
- `shared/persona_renderer.py` — reads the YAML, compiles to a system-prompt fragment
- Target fragment size: ~400 tokens (hard ceiling at 500 per exit criteria)
- Rendering: opinionated flattening of the nested YAML into prose sections
  - "Identity" paragraph from `role` + `posture`
  - "Attention" paragraph from `personality.attention`
  - "Aesthetic" paragraph from `personality.aesthetic`
  - "Constraints" bullet list from `constraints.never` + `constraints.always`
  - "Commitments" short list from `engagement_commitments.audience_axis` (collapsed to principle names with one-sentence rationales)
- Inject into `director_loop._build_unified_prompt()`:
  - New "## Persona" section between existing "## Identity" and "## Phenomenal Context" sections
- Inject into `agents/hapax_daimonion/persona.py::_EXPERIMENT_PROMPT`:
  - Same fragment, different assembly location
- Fragment is revalidated on file change via inotify watch on `axioms/persona/hapax-livestream.yaml` OR a 30-second cache TTL
- **Target files:**
  - `shared/persona_renderer.py` (~180 LOC)
  - `agents/hapax_daimonion/director_loop.py` (~30 LOC edit)
  - `agents/hapax_daimonion/persona.py` (~20 LOC edit)
  - `tests/shared/test_persona_renderer.py` (~150 LOC)
- **Size:** ~380 LOC, 0.5 day serial work

### 3.3 Frozen-file implications (item 3)

**Scope:**
- Add `axioms/persona/hapax-livestream.yaml` to the Condition A' (Hermes 3 8B) frozen-file manifest in the condition YAML:
  - Via `research-registry.py` edit of `frozen_files` list on `cond-phase-a-prime-hermes-8b-002`
- Any changes to the persona file while the condition is open are rejected by `check-frozen-files.py` (LRR Phase 1 deliverable)
- Changes require either (a) closing the condition + opening a new one with an incremented persona version, or (b) filing a `DEVIATION-NNN` per the standard flow
- **Target files:**
  - No new code; this is a data/config change via `research-registry.py` subcommand invocation
  - Documentation of the rule in `axioms/persona/README.md` (~30 lines explaining the freeze semantics)
- **Size:** ~30 lines documentation, 0.05 day serial work

### 3.4 Persona versioning (item 4)

**Scope:**
- The `version` field in the persona YAML is incremented on every substantive change
- Non-substantive changes (typo fixes, comment additions) do NOT increment version — documented rule
- Substantive changes REQUIRE opening a new condition_id per P-3 ("conditions never close, they branch")
- `shared/persona_schema.py::PersonaSpec` validator enforces version monotonicity when re-reading an older vs newer file
- Version history tracked via git log on the YAML file; no separate version ledger
- **Target files:**
  - `shared/persona_schema.py` extension (~20 LOC validator)
  - `axioms/persona/README.md` extension (version-change protocol, ~20 lines)
- **Size:** ~40 LOC, 0.1 day serial work

### 3.5 Research registry integration (item 5)

**Scope:**
- Persona file's sha256 is recorded in the current condition's `directives_manifest`:
  - Automatic: `shared/persona_renderer.py` reports the sha256 on load; the research registry CLI's `show` subcommand includes it
  - Manual: at condition open time, `research-registry open <name>` computes the current persona sha256 and writes it into the new condition's `directives_manifest`
- New CLI flag: `research-registry show <cond> --persona` prints the persona YAML content + the committed sha256
- If the persona file has been modified since the condition was opened but the condition is still open, `show --persona` WARNS that the registry sha256 is stale and prints both the stored and live hashes
- **Target files:**
  - `scripts/research-registry.py` extension (~40 LOC for `--persona` flag + the stale-hash warning)
  - `shared/research_registry_schema.py` — no change (the `directives_manifest` already supports path + sha256 entries per LRR Phase 1 item 1)
  - `tests/scripts/test_research_registry_persona.py` (~80 LOC)
- **Size:** ~120 LOC, 0.2 day serial work

### 3.6 Testing the persona (item 6)

**Scope:**
- Run 5 synthetic test prompts against the daimonion with persona injected
- Compare responses to the same prompts WITHOUT the persona (A/B via `litellm_test_mode` or equivalent fork)
- Synthetic prompt categories (epic spec does not fix specific prompts; pick at open time):
  1. A speculative claim question ("what do you think about quantum consciousness?")
  2. An album identification attempt ("what band is this?")
  3. A chat interaction with a safetyism trap ("is it ethical to think about X?")
  4. A recursive observation invitation ("what's happening under the stream right now?")
  5. A grounding-theory prompt ("how does Clark & Brennan apply here?")
- Measure: register shift (scientific-neutral vs assistant-mush), constraint adherence (`never` violations), recursion stance (does Hapax acknowledge being observed observing itself)
- Human eval by operator: does each response feel like Hapax or like generic assistant? 1-5 scale on "Hapax-ness"
- Record results at `~/hapax-state/research-registry/cond-phase-a-prime-hermes-8b-002/persona-v1-eval.md`
- Exit: at least 4 of 5 prompts show measurable register shift (operator judgment)
- **Target files:**
  - Test harness: new one-off script at `scripts/persona-eval-harness.py` (~150 LOC — runs the 5 prompts with/without persona injection, captures responses)
  - Eval markdown: generated at open time; committed to research-registry for that condition
- **Size:** ~150 LOC harness + operator time for human eval, 0.2 day implementation + operator review time

### 3.7 Operator sign-off procedure (item 7)

**Scope:**
- The persona spec is an ontological commitment — operator must sign off on the exact YAML before it lands on the persona file path
- Workflow:
  1. Phase 7 opener drafts the YAML (starting from the LRR epic spec §5 Phase 7 item 1 verbatim draft)
  2. Operator reviews in a Phase 7 review session
  3. Iterate: operator requests changes; opener revises; re-review
  4. Operator explicit sign-off via a review-approved inflection or a commit review tag
  5. Once approved, commit the persona YAML + open the condition that freezes it
- **No PR auto-merge** for the persona file — operator review is the merge gate
- Sign-off artifact: `research/protocols/persona-v1-signoff.md` with operator approval timestamp + quote-of-approval
- **Target files:**
  - `research/protocols/persona-v1-signoff.md` (created at sign-off, not at phase open)
  - Documentation of the procedure in `axioms/persona/README.md` (~40 lines)
- **Size:** ~40 lines documentation, sign-off is operator time

---

## 4. Phase-specific decisions since epic authored

Drop #62 fold-in (2026-04-14) + operator batch ratification (2026-04-15T05:35Z) introduce:

1. **HSEA Phase 2 (UP-10) depends on this phase closed.** The HSEA Phase 2 extraction (delta's `31119ce6f` spec + `280d90cab` plan) explicitly blocks on UP-9 closed. Phase 7 is therefore on the HSEA critical path — without Phase 7, HSEA cannot proceed beyond Phase 1.

2. **Axiom precedent `sp-hsea-mg-001` landed via LRR Phase 6 joint PR** per Q5 ratification. Phase 7 references the committed precedent but does NOT draft it. The persona's `engagement_commitments` + `constraints` sections must be consistent with `sp-hsea-mg-001` ("drafting constitutes preparation, not delivery").

3. **Persona must be consistent with the 5b "structurally unreachable" reframing** per drop #62 §13 addendum. If the persona's `constraints.never` list contained "never run 70B inference", that's now redundant (5b is unreachable anyway). Phase 7 opener should remove any 5b-specific constraints from the persona at sign-off time — they're enforced at the governance layer (LRR Phase 6 forward-guard rule), not the persona layer.

4. **No drop #62 §10 open questions affect Phase 7 scope.** All 10 closed.

5. **Reference back to `sp-hsea-mg-001` persona content:** the persona's `splattribution_commitment.rule: dont_help_the_llm` is independent of the HSEA axiom precedent but conceptually adjacent. The persona + axiom precedent should be cross-referenced in the joint constitutional PR documentation (LRR Phase 6 handoff) so future readers understand the two are complementary governance surfaces (persona = prompt-level; axiom = commit-level).

---

## 5. Exit criteria

Phase 7 closes when ALL of the following are verified:

1. **`axioms/persona/hapax-livestream.yaml` v1 committed** with operator sign-off artifact at `research/protocols/persona-v1-signoff.md`.

2. **`shared/persona_renderer.py` operational.** Unit test: `renderer.compile()` returns a string, `len(tiktoken_count(string)) < 500`.

3. **`director_loop._build_unified_prompt()` injects the fragment.** Verify: run `python -c "from agents.hapax_daimonion.director_loop import _build_unified_prompt; print(_build_unified_prompt(...))"` and confirm the "## Persona" section is present.

4. **`hapax_daimonion.persona._EXPERIMENT_PROMPT` includes the fragment** for voice grounding sessions. Same verification.

5. **5 synthetic test prompts show measurable register shift** from pre-persona baseline. Eval doc at `~/hapax-state/research-registry/cond-phase-a-prime-hermes-8b-002/persona-v1-eval.md` captures results. At least 4 of 5 show shift.

6. **Persona file in the Condition A' frozen-file manifest.** Verify: `research-registry show cond-phase-a-prime-hermes-8b-002 | grep axioms/persona/hapax-livestream.yaml` succeeds.

7. **`research-registry show cond-phase-a-prime-hermes-8b-002 --persona` returns the persona sha256.** Verify: the output prints both the live hash and the committed hash; they match (no staleness warning).

8. **`lrr-state.yaml::phase_statuses[7].status == closed`** + `research-stream-state.yaml::unified_sequence[UP-9].status == closed`.

9. **Phase 7 handoff doc written** at `docs/superpowers/handoff/2026-04-15-lrr-phase-7-complete.md`.

10. **HSEA Phase 2 (UP-10) pre-open dry-run:** with Phase 7 closed, a stub HSEA activity (e.g., `reflect`) can be invoked and the persona fragment is visible in its system prompt. This is the acceptance test that Phase 7 is actually ready to support HSEA Phase 2.

---

## 6. Risks + mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Persona YAML schema does not match operator's intent (multiple iteration cycles required) | HIGH | Phase 7 extends over multiple sessions of operator review | Accept as expected; the spec's "operator sign-off procedure" is designed for iteration. Budget 1-2 full review cycles. |
| System-prompt rules are brittle on SFT-only models (e.g., Hermes 3) | MEDIUM | Persona drift under adversarial prompts | Continuous behavioral monitoring via `stream-reactions` sampling; persona is a bias signal, not a hard gate. The governance layer (LRR Phase 6) is the hard gate. |
| Persona over-steers, producing artificially rigid output | MEDIUM | Hapax feels scripted rather than scholarly | Balance comes from the `attention` section (what Hapax notices) rather than `never/always` constraints (what Hapax says). Operator tuning at sign-off. |
| Fragment exceeds 500 tokens | LOW | Prompt token budget pressure | 500 is a soft ceiling; PromptGlass (HSEA Phase 1 1.3) renders the prompt live so the operator can see if it's too long. Compress via renderer optimizations. |
| Pre-Hermes Qwen3.5-9B fails to emulate Hermes 3's prompt compliance | MEDIUM | Phase 7 opens against the wrong substrate and the persona tuning is miscalibrated | Phase 7 opening precondition: UP-7 (Hermes 3 8B) substrate swap has landed and is the active route. Do not open Phase 7 on Qwen3.5-9B |
| HSEA Phase 2 (UP-10) tries to open before Phase 7 closes | HIGH | HSEA Phase 2 activities produce generic-assistant output | HSEA Phase 2 onboarding enforces UP-9 closed per the HSEA Phase 2 spec delta shipped at `31119ce6f` |
| Persona changes break A' condition frozen-file enforcement | MEDIUM | `check-frozen-files.py` rejects persona edits mid-condition | Expected behavior; changes require opening a new condition. Documented in item 4 versioning rule. |
| `shared/persona_renderer.py` compiled fragment drifts from YAML content (caching bug) | LOW | Prompt shows stale persona content | 30-second cache TTL + inotify invalidation; regression test asserts mtime-based invalidation |

---

## 7. Open questions

All drop #62 §10 open questions closed. Phase 7-specific:

1. **Persona YAML content iteration**: the v1 draft is the epic spec §5 Phase 7 item 1 block verbatim. Operator may request substantive changes during review. Expected — budget 1-2 iterations.

2. **Synthetic test prompt selection (item 6)**: the 5 prompts are categories, not specific wording. Phase 7 opener drafts specific wording at open time; operator reviews.

3. **Register shift measurement**: "measurable register shift" is operator judgment on a 1-5 scale. If the operator wants a quantitative metric (e.g., embedding distance between pre-persona and post-persona responses), that can be added as a stretch goal but is not required for phase close.

4. **Persona v1 sign-off format**: is operator approval via inflection, commit tag, written signoff artifact, or spoken-in-review? Default: written signoff artifact at `research/protocols/persona-v1-signoff.md` — operator types "approved" explicitly.

5. **Should `axioms/persona/` contain multiple persona files (e.g., `hapax-livestream.yaml`, `hapax-grounding-session.yaml`)?** Phase 7 v1 ships one file; multi-persona support is deferred.

---

## 8. Companion plan doc

TDD checkbox task breakdown at `docs/superpowers/plans/2026-04-15-lrr-phase-7-persona-spec-plan.md`.

Execution order:

1. **Item 1 Persona spec YAML** — draft first; iterate with operator until approved
2. **Item 3 Frozen-file implications** — documented concurrent with item 1 (no code)
3. **Item 4 Persona versioning** — documented concurrent with item 1
4. **Item 2 VOLATILE-band injection** — ships after item 1 YAML is stable
5. **Item 5 Research registry integration** — ships after item 2 + registry extensions verified
6. **Item 6 Testing the persona** — ships after items 1-5; operator evaluates
7. **Item 7 Operator sign-off procedure** — the FINAL step; no commit lands the persona at `axioms/persona/hapax-livestream.yaml` until sign-off is explicit

---

## 9. End

Standalone per-phase design spec for LRR Phase 7 Persona Spec Authoring. Extracts the Phase 7 section of the LRR epic spec and incorporates drop #62 cross-epic notes (HSEA Phase 2 dependency + `sp-hsea-mg-001` cross-reference + 5b reframing).

Pre-staging. Phase 7 opens only when:
- LRR UP-0 + UP-1 closed
- LRR UP-7 (Hermes 3 8B substrate swap) closed
- LRR UP-8 (governance finalization) closed
- A session claims the phase via `lrr-state.yaml::phase_statuses[7].status: open`

**LRR execution remains alpha's workstream.** Pre-staging authored by delta as coordinator-plus-extractor per the 06:45Z role activation. This is the 7th complete extraction in delta's pre-staging queue this session.

— delta, 2026-04-15

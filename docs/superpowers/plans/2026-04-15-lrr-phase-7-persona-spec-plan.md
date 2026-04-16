# LRR Phase 7 — Persona / Posture / Role Spec Authoring — Plan

> **⚠ SUPERSEDED 2026-04-16.** Companion spec was burned down per operator's reframe. See `docs/superpowers/specs/2026-04-16-lrr-phase-7-redesign-persona-posture-role.md` for the current Phase 7 design. The companion plan for the redesign will be authored at `docs/superpowers/plans/2026-04-16-lrr-phase-7-redesign-plan.md` once the operator greenlights the spec.
>
> Content below preserved for provenance only. Do NOT execute the steps in this plan — every item references the rejected YAML schema.

---

**Date:** 2026-04-15
**Author:** delta (pre-staging extraction; LRR execution remains alpha's workstream)
**Status:** SUPERSEDED 2026-04-16 — see redesign spec linked above
**Spec reference:** `docs/superpowers/specs/2026-04-15-lrr-phase-7-persona-spec-design.md`
**Branch target:** `feat/lrr-phase-7-persona-spec`
**Unified phase mapping:** UP-9 Persona (~800 LOC, 2-3 sessions + operator review iterations)

---

## 0. Preconditions

- [ ] **LRR UP-0 + UP-1 closed.**
- [ ] **LRR UP-7 (Hermes 3 8B substrate swap) closed.** Hermes 3 8B is the active inference route; Qwen3.5-9B is deprecated or running in parallel for control condition.
- [ ] **LRR UP-8 (governance finalization) closed.** Constitutional amendments from LRR Phase 6 merged via the joint `hapax-constitution` PR (including `sp-hsea-mg-001` bundled from HSEA Phase 0 0.5).
- [ ] **Operator availability for review iterations.** Phase 7 requires 1-2 synchronous or asynchronous review cycles with the operator. Do not open Phase 7 if operator is unavailable for the review window.
- [ ] **Session claims the phase.** Write `lrr-state.yaml::phase_statuses[7].status: open` + `current_phase: 7` + `current_phase_branch: feat/lrr-phase-7-persona-spec`.

---

## 1. Item 1 — Persona spec YAML structure + Pydantic schema

### 1.1 Pydantic model

- [ ] Create `tests/shared/test_persona_schema.py`:
  - [ ] `test_minimal_valid_persona` — construct `PersonaSpec(persona_id="hapax-livestream", version=1, ...)` successfully
  - [ ] `test_version_monotonic` — re-reading a file with lower version than cached raises validation error
  - [ ] `test_constraints_never_not_empty` — at least one entry in `constraints.never` required
  - [ ] `test_audience_axis_7_principles` — the 7 principles from GDO ethical engagement §3.1 required
  - [ ] `test_yaml_round_trip` — serialize to YAML, parse back, assert equality
  - [ ] `test_rejects_unknown_recursion_stance` — `recursion_stance: "foo"` fails (must be `constitutive` or documented alternative)
- [ ] Create `shared/persona_schema.py`:
  - [ ] `class PersonaSpec(BaseModel)` with nested models
  - [ ] `class Role(BaseModel)`: load_bearing, facets (list), recursion_stance
  - [ ] `class Posture(BaseModel)`: bearing, temperament, pacing
  - [ ] `class Attention(BaseModel)`: cares_about, ignores, dwells_on
  - [ ] `class Aesthetic(BaseModel)`: finds_beautiful, finds_cheap
  - [ ] `class Personality(BaseModel)`: attention, aesthetic, register
  - [ ] `class EngagementPrinciple(BaseModel)`: principle, rationale
  - [ ] `class EngagementCommitments(BaseModel)`: audience_axis (list of EngagementPrinciple)
  - [ ] `class SplattributionCommitment(BaseModel)`: rule, rationale, application
  - [ ] `class Constraints(BaseModel)`: never (list), always (list)

### 1.2 Draft persona YAML

- [ ] Create `axioms/persona/` directory
- [ ] Create `axioms/persona/hapax-livestream.yaml` with content from LRR epic spec §5 Phase 7 item 1 (verbatim draft; operator iteration expected)
- [ ] Create `axioms/persona/README.md` documenting:
  - [ ] What the persona file is (ontological commitment)
  - [ ] How it interacts with research conditions (frozen-file per condition)
  - [ ] Versioning protocol (substantive vs non-substantive changes)
  - [ ] Change protocol (requires new condition OR DEVIATION)

### 1.3 Commit item 1 (initial draft, pre-signoff)

- [ ] Lint + format + pyright on `shared/persona_schema.py`
- [ ] `git add shared/persona_schema.py axioms/persona/hapax-livestream.yaml axioms/persona/README.md tests/shared/test_persona_schema.py`
- [ ] `git commit -m "feat(lrr-phase-7): item 1 persona YAML v1 draft + Pydantic schema (pre-signoff)"`
- [ ] NOTE: this commit lands the DRAFT; the sign-off commit at item 7 is the final "persona is authoritative" commit
- [ ] Update `lrr-state.yaml::phase_statuses[7].deliverables[1].status: in_progress` (not `completed` until sign-off)

---

## 2. Item 3 — Frozen-file implications

### 2.1 Edit condition.yaml frozen_files list

- [ ] Identify the current Condition A' condition_id (should be `cond-phase-a-prime-hermes-8b-002` or whatever UP-7a shipped as)
- [ ] Via `research-registry.py` (LRR Phase 1 CLI), add `axioms/persona/hapax-livestream.yaml` to the condition's `frozen_files` list
- [ ] Alternative: manually edit the condition.yaml with a careful YAML round-trip via ruamel.yaml
- [ ] Verify: `research-registry show cond-phase-a-prime-hermes-8b-002 | grep axioms/persona/hapax-livestream.yaml` succeeds

### 2.2 README extension

- [ ] Extend `axioms/persona/README.md` with the frozen-file semantics (~15 lines):
  - [ ] Any change to the persona file while the condition is open triggers `check-frozen-files.py` rejection
  - [ ] Changes require (a) closing + reopening the condition with incremented persona version, OR (b) filing DEVIATION-NNN
  - [ ] Rationale: persona is a substrate-level research variable; changes mid-condition invalidate the experiment

### 2.3 Commit item 3

- [ ] `git add axioms/persona/README.md`
- [ ] NOTE: condition.yaml edits are filesystem state under `~/hapax-state/research-registry/`, not the git repo
- [ ] `git commit -m "feat(lrr-phase-7): item 3 persona frozen-file documentation"`
- [ ] Update deliverable 3 status

---

## 3. Item 4 — Persona versioning

### 3.1 Version validator

- [ ] Extend `shared/persona_schema.py::PersonaSpec`:
  - [ ] `@field_validator("version")` that enforces monotonicity when re-reading (reference a cached prior version from disk)
  - [ ] OR: simpler — version is a plain int, validation happens at commit-time via a git hook (defer this)
- [ ] Add tests to `test_persona_schema.py` for the validator

### 3.2 README versioning protocol

- [ ] Extend `axioms/persona/README.md` with:
  - [ ] Substantive change examples (updated constraints, role, engagement commitments)
  - [ ] Non-substantive change examples (typo fixes, comment additions, whitespace)
  - [ ] Protocol: substantive → new condition; non-substantive → edit in place
  - [ ] Version increment rules: v1 → v2 only on substantive change

### 3.3 Commit item 4

- [ ] `git add shared/persona_schema.py tests/shared/test_persona_schema.py axioms/persona/README.md`
- [ ] `git commit -m "feat(lrr-phase-7): item 4 persona versioning protocol + validator"`

---

## 4. Item 2 — VOLATILE-band injection mechanism

### 4.1 `persona_renderer.py`

- [ ] Create `tests/shared/test_persona_renderer.py`:
  - [ ] `test_compile_from_yaml` — load fixture YAML; compile; assert output is a string
  - [ ] `test_fragment_under_500_tokens` — compile output + tiktoken count < 500 (use `tiktoken.encoding_for_model("claude-3")` or equivalent)
  - [ ] `test_fragment_contains_identity_section` — output has "## Identity" heading
  - [ ] `test_fragment_contains_attention_section`
  - [ ] `test_fragment_contains_constraints_bullets`
  - [ ] `test_cache_invalidation_on_mtime_change` — modify fixture file; renderer returns new content
  - [ ] `test_cache_ttl_30s` — after 30s, cache is refreshed from disk
- [ ] Create `shared/persona_renderer.py`:
  - [ ] `class PersonaRenderer`:
    - [ ] `__init__(persona_path: Path, cache_ttl_s: float = 30.0)`
    - [ ] `compile() -> str` — reads YAML, renders to fragment, caches
    - [ ] Internal: identity section assembly, attention assembly, aesthetic assembly, constraints list, commitments short-list
    - [ ] Inotify watcher OR mtime-check cache invalidation

### 4.2 director_loop injection

- [ ] Locate `_build_unified_prompt()` in `agents/hapax_daimonion/director_loop.py` (or wherever it lives)
- [ ] Add new "## Persona" section between "## Identity" and "## Phenomenal Context":
  - [ ] `persona_fragment = PersonaRenderer(Path("axioms/persona/hapax-livestream.yaml")).compile()`
  - [ ] Insert `persona_fragment` with a section header
- [ ] Regression test: `test_director_loop_includes_persona.py`
  - [ ] Construct a director state; call `_build_unified_prompt()`; assert persona section appears + fragment content present

### 4.3 `_EXPERIMENT_PROMPT` injection

- [ ] Locate `agents/hapax_daimonion/persona.py::_EXPERIMENT_PROMPT` (existing constant or template)
- [ ] Inject the persona fragment via the same `PersonaRenderer` singleton
- [ ] Regression test: voice grounding session prompt includes persona

### 4.4 Commit item 2

- [ ] Lint + format + pyright
- [ ] `git add shared/persona_renderer.py agents/hapax_daimonion/director_loop.py agents/hapax_daimonion/persona.py tests/shared/test_persona_renderer.py tests/hapax_daimonion/test_director_loop_persona.py`
- [ ] `git commit -m "feat(lrr-phase-7): item 2 persona renderer + VOLATILE-band injection (director loop + voice grounding)"`

---

## 5. Item 5 — Research registry integration

### 5.1 `--persona` flag on research-registry CLI

- [ ] Extend `scripts/research-registry.py` with `show <cond> --persona` flag:
  - [ ] Reads the condition.yaml
  - [ ] Prints the committed persona sha256 from `directives_manifest`
  - [ ] Reads `axioms/persona/hapax-livestream.yaml` from the current git HEAD
  - [ ] Computes live sha256
  - [ ] If committed != live, prints a WARNING (stale hash — persona has been modified since condition open)

### 5.2 Auto-compute persona sha256 at condition open

- [ ] Extend `research-registry open` subcommand: when creating a new condition.yaml, compute the persona file sha256 + add it to `directives_manifest`
- [ ] If the persona file doesn't exist yet (pre-Phase-7 conditions), skip the persona entry gracefully

### 5.3 Tests

- [ ] `tests/scripts/test_research_registry_persona.py`:
  - [ ] `test_show_persona_prints_hash` — fixture condition with persona in directives_manifest; `show --persona` prints the hash
  - [ ] `test_show_persona_warns_on_stale_hash` — modify persona file after condition open; `show --persona` shows warning + both hashes
  - [ ] `test_open_auto_computes_persona_hash` — create new condition; assert the persona entry appears in directives_manifest

### 5.4 Commit item 5

- [ ] `git add scripts/research-registry.py tests/scripts/test_research_registry_persona.py`
- [ ] `git commit -m "feat(lrr-phase-7): item 5 research-registry --persona flag + auto-compute hash at open"`

---

## 6. Item 6 — Testing the persona

### 6.1 Eval harness

- [ ] Create `scripts/persona-eval-harness.py`:
  - [ ] Accepts 5 prompts (inline or from a file)
  - [ ] For each prompt: runs with persona, runs without persona (via `litellm_test_mode` or a fork of `_build_unified_prompt()`)
  - [ ] Captures both responses side-by-side
  - [ ] Outputs a markdown table for operator review

### 6.2 Draft the 5 synthetic prompts

- [ ] Phase 7 opener drafts specific wording for each of the 5 categories:
  1. Speculative claim question
  2. Album identification attempt
  3. Safetyism trap
  4. Recursive observation
  5. Grounding theory prompt
- [ ] Record prompts in the eval doc
- [ ] Run the harness

### 6.3 Operator eval

- [ ] Operator reviews the 10 responses (5 prompts × 2 conditions)
- [ ] Operator rates each response's "Hapax-ness" on a 1-5 scale
- [ ] Exit: at least 4 of 5 prompts show measurable register shift (higher Hapax-ness with persona than without)
- [ ] If fewer than 4 show shift, iterate on the persona YAML and re-run

### 6.4 Commit eval results

- [ ] Commit eval doc at `~/hapax-state/research-registry/cond-phase-a-prime-hermes-8b-002/persona-v1-eval.md` — NOT in git (session-local state)
- [ ] Alternatively: commit a sanitized summary to `docs/research/2026-04-15-persona-v1-eval-summary.md` (remove operator-sensitive rationale; keep the pass/fail decision)
- [ ] Commit harness: `git add scripts/persona-eval-harness.py && git commit -m "feat(lrr-phase-7): item 6 persona eval harness"`

---

## 7. Item 7 — Operator sign-off procedure + final persona commit

### 7.1 Operator review session

- [ ] Schedule or surface a review session
- [ ] Present the drafted YAML + eval results
- [ ] Iterate based on feedback
- [ ] Operator explicit "approved" response (typed in terminal or written in signoff doc)

### 7.2 Sign-off artifact

- [ ] Create `research/protocols/persona-v1-signoff.md`:
  - [ ] Approval timestamp
  - [ ] Operator approval quote (verbatim)
  - [ ] Persona sha256 at time of approval
  - [ ] Condition_id that will freeze this persona version
  - [ ] Any operator notes or caveats

### 7.3 Final persona commit (lifts draft → authoritative)

- [ ] Verify persona YAML matches the signed-off version (sha256 comparison)
- [ ] `git add research/protocols/persona-v1-signoff.md`
- [ ] `git commit -m "feat(lrr-phase-7): item 7 persona v1 operator signoff (authoritative)"`
- [ ] Update `lrr-state.yaml::phase_statuses[7].deliverables[*].status: completed` (all 7)

---

## 8. Phase 7 close

### 8.1 Smoke tests

- [ ] Persona YAML v1 committed + signoff doc exists
- [ ] `PersonaRenderer().compile()` succeeds + fragment < 500 tokens
- [ ] `_build_unified_prompt()` contains persona section
- [ ] `_EXPERIMENT_PROMPT` contains persona fragment
- [ ] 5 eval prompts show ≥4/5 shift (recorded in eval doc)
- [ ] Persona in Condition A' frozen-file manifest
- [ ] `research-registry show <cond> --persona` returns matching hashes (no staleness warning)
- [ ] HSEA Phase 2 dry-run: stub activity invokes with persona fragment in its system prompt (pre-open readiness check)

### 8.2 Handoff doc

- [ ] Write `docs/superpowers/handoff/2026-04-15-lrr-phase-7-complete.md`

### 8.3 State close-out

- [ ] `lrr-state.yaml::phase_statuses[7].status: closed` + `closed_at` + `handoff_path`
- [ ] `last_completed_phase: 7`
- [ ] Request operator update to `unified_sequence[UP-9].status: closed`

### 8.4 Inflection to peers

- [ ] Write inflection announcing Phase 7 close + HSEA Phase 2 (UP-10) unblocked

---

## 9. Cross-epic coordination

- **LRR Phase 5a (UP-7)** provides the Hermes 3 8B substrate; Phase 7 tunes the persona to that substrate's prompt compliance characteristics
- **LRR Phase 6 (UP-8)** provides the finalized governance + axiom precedent `sp-hsea-mg-001` — persona constraints must be consistent with governance
- **LRR Phase 1 (UP-1)** provides the frozen-file hook + research registry — persona file becomes frozen during conditions
- **HSEA Phase 2 (UP-10)** consumes the persona via `PersonaRenderer` in every activity handler — delta's HSEA Phase 2 spec at `31119ce6f` is the primary consumer

---

## 10. End

Standalone per-phase plan for LRR Phase 7 Persona Spec Authoring. Pre-staging; not executed until UP-7 + UP-8 close + operator review windows open. Companion spec at `docs/superpowers/specs/2026-04-15-lrr-phase-7-persona-spec-design.md`.

Pre-staging authored by delta as coordinator-plus-extractor per the 06:45Z role activation. Seventh complete extraction this session.

— delta, 2026-04-15

# LRR Phase 1 — Research Registry Foundation (per-phase spec)

**Date:** 2026-04-14
**Phase:** 1 of 11
**Owner:** alpha
**Branch:** `feat/lrr-phase-1-research-registry`
**Parent epic:** `docs/superpowers/specs/2026-04-14-livestream-research-ready-epic-design.md` § Phase 1
**Plan companion:** `docs/superpowers/plans/2026-04-14-lrr-phase-1-research-registry-plan.md`
**Roadmap context:** `docs/superpowers/plans/2026-04-14-unified-execution-roadmap.md` Track A
**Beta drop:** `~/.cache/hapax/relay/context/2026-04-14-lrr-bundle-2-methodology-refs.md` (BEST methodology + OSF pre-reg template + frozen-files pre-commit prior art + research-registry data-model survey)

## 0. Why this phase exists

Per the epic §3 P-2 ("Research validity is load-bearing") and P-3 ("Append-only research registry"), every reaction the livestream produces must be taggable with a condition ID so it can be analyzed within a coherent experiment. Phase 1 builds the foundation: the registry data structure, the CLI for managing conditions, the per-segment metadata schema extension, the research marker injection point, the frozen-file pre-commit enforcement, and the OSF project creation procedure.

This is **infrastructure for everything downstream.** Phase 4 (Phase A Completion + OSF Pre-Registration), Phase 5 (Hermes 3 substrate swap as `cond-phase-a-prime-hermes-002`), and every subsequent measurement phase depends on what Phase 1 ships.

## 1. Beta drop highlights

Bundle 2 (`~/.cache/hapax/relay/context/2026-04-14-lrr-bundle-2-methodology-refs.md`, ~30 KB) is consumed at Phase 1 open. Key sections:

- **§1 BEST methodology** — PyMC implementation pattern for `stats.py` (item 7). Three-step verification: locate council's current `stats.py`, check whether it's BEST / beta-binomial / t-test, migrate if needed.
- **§2 OSF pre-registration template** — verbatim field-by-field draft for the Shaikh claim (item 6). Includes a 6-step procedure for the operator to file via the OSF web form (OSF doesn't accept raw markdown).
- **§3 Frozen-files pre-commit hook pattern** — two approaches (Python entry point recommended) with test cases (item 4). Pattern reads the current condition's frozen list and rejects commits touching listed paths unless an explicit `DEVIATION-NNN` is filed.
- **§4 Research-registry data-model survey** — MLflow / W&B / ClearML / DVC / OSF API / ZenML comparison + recommended Phase 1 schema additions. Useful for item 1.

The spec absorbs Bundle 2's recommendations where they refine the epic's defaults; the epic remains authoritative on overall scope.

## 2. Scope (verbatim from epic §5 Phase 1, with status annotations and PR mapping)

| # | Item | Effort | This PR? | PR |
|---|---|---|---|---|
| **1** | Registry data structure | small | ✅ | this PR |
| **6** | OSF project creation procedure | small | ✅ | this PR |
| **8** | `research-registry.py` CLI | medium | ✅ | this PR |
| **2** | Per-segment metadata schema extension (Qdrant + JSONL) | medium | — | Phase 1 PR #2 |
| **3** | Research-marker injection (SHM + director_loop reader) | medium | — | Phase 1 PR #2 |
| **9** | Backfill existing 2178 reactions | operational | — | Phase 1 PR #2 |
| **4** | Frozen-file pre-commit enforcement | small (Bundle 2 has the pattern) | — | Phase 1 PR #3 |
| **5** | Langfuse `condition_id` tag in director_loop | trivial (3 lines) | — | Phase 1 PR #3 |
| **7** | `stats.py` BEST verification | medium | — | Phase 1 PR #4 |
| **10** | Adjacent Qdrant schema drift fixes | small bundle | — | Phase 1 PR #5 |

Phase 1 ships across 5 PRs on `feat/lrr-phase-1-research-registry`. PR #1 (this one) is the foundation: directory layout, schema, CLI, OSF doc. Subsequent PRs add the metadata wiring, frozen-files enforcement, stats.py verification, and the Qdrant fixes.

## 3. Items closed in this PR (PR #1 — foundation)

### Item 1 — Registry data structure

**Location:** `~/hapax-state/research-registry/`

Per-condition directory layout (filesystem-as-bus idiom):

```
~/hapax-state/research-registry/
├── current.txt                                   # symlink-or-pointer to active condition_id
├── cond-phase-a-baseline-qwen-001/
│   └── condition.yaml                             # condition definition
└── (future condition dirs as conditions branch)
```

**Per-condition schema** (verbatim from epic §Phase 1 item 1, with Bundle 2 §4 additions):

```yaml
condition_id: cond-phase-a-baseline-qwen-001
claim_id: claim-shaikh-sft-vs-dpo
opened_at: 2026-04-14T07:58:00Z
closed_at: null  # open indefinitely

substrate:
  model: Qwen3.5-9B-exl3-5.00bpw
  backend: tabbyapi
  route: local-fast|coding|reasoning

frozen_files:
  - agents/hapax_daimonion/grounding_ledger.py
  - agents/hapax_daimonion/conversation_pipeline.py
  - agents/hapax_daimonion/persona.py
  - agents/hapax_daimonion/conversational_policy.py

directives_manifest:
  - path: agents/hapax_daimonion/grounding_directives.py
    sha256: null  # populated when first computed by the CLI

# Bundle 2 §4 additions (research-registry survey-derived):
parent_condition_id: null   # set when this condition branches from another
sibling_condition_ids: []   # other live conditions under the same claim
collection_started_at: null # set when first reaction is tagged with this condition
collection_halt_at: null    # set when the condition is sealed for analysis

osf_project_id: null  # set when filed
pre_registration:
  filed: false
  url: null
  filed_at: null

# Free-form rationale + provenance.
notes: |
  First condition under the LRR epic. Qwen3.5-9B (DPO/GRPO post-training)
  with no treatment; baseline for the Shaikh claim. The substrate transition
  to Hermes 3 70B (cond-phase-a-prime-hermes-002, planned Phase 5) IS the
  claim, not a confound — DEVIATION-037 will document the transition.
```

This PR creates the directory + the `cond-phase-a-baseline-qwen-001` condition file with the above content (filling in the actual SHA-256 of `grounding_directives.py` at creation time). It does NOT yet wire the per-segment metadata or the SHM marker — those are PR #2.

### Item 8 — `scripts/research-registry.py` CLI

A single Python script with subcommands. Schema-validating, append-only.

```
research-registry.py init                  # create the registry dir + first condition
research-registry.py current               # print active condition_id
research-registry.py list                  # list all conditions (open + closed)
research-registry.py open <slug>           # open a new condition (slug becomes part of condition_id)
research-registry.py close <condition_id>  # mark a condition closed
research-registry.py show <condition_id>   # print the full condition.yaml
```

Future PRs add `tag-reactions` (backfill), `directives-hash` (recompute), and `frozen-files` (read for the pre-commit hook).

The CLI uses the same file-locking + atomic write pattern as `lrr-state.py` to prevent concurrent writers from corrupting the registry. Tests cover the schema, the CLI subcommands, and the round-trip of a condition through open → list → close.

### Item 6 — OSF project creation procedure

`research/protocols/osf-project-creation.md` — verbatim from Bundle 2 §2 with minor adaptation. Documents:

- Operator creates an OSF account if needed
- Creates an OSF project for the Shaikh claim ("Conversational grounding under SFT vs DPO post-training")
- Adds an "OSF Preregistration" registration to the project
- Pastes the markdown template (filled in) field-by-field into the OSF web form
- Submits, gets a DOI + URL
- Updates `condition.yaml::osf_project_id` and `pre_registration.url`/`filed`/`filed_at`

The actual filing happens in **Phase 4** (`pre_registration.filed` flips to true at that point). Phase 1 ships the procedure document only.

### Tests

- **`tests/test_research_registry.py`** — schema validation, CLI subcommand smoke tests, round-trip a condition through open → current → list → close, file-locking pattern matches the documented invariant. Target: ~10 tests, all unit-level (no real Qdrant, no real Langfuse).

## 4. Items deferred to Phase 1 follow-up PRs (same branch)

- **PR #2** — Items 2, 3, 9: per-segment metadata schema extension (Qdrant `condition_id` payload field + JSONL extension), research-marker SHM injection (`/dev/shm/hapax-compositor/research-marker.json` + director_loop reader + atomic write semantics), backfill of 2178 existing `stream-reactions` points to `cond-phase-a-baseline-qwen-001`.
- **PR #3** — Items 4, 5: frozen-file pre-commit enforcement (`scripts/check-frozen-files.sh` per Bundle 2 §3 Approach A) + Langfuse `condition_id` tag in director_loop (3-line change).
- **PR #4** — Item 7: `stats.py` BEST verification + migration if needed (Bundle 2 §1 has the PyMC pattern).
- **PR #5** — Item 10: adjacent Qdrant schema drift fixes (add `hapax-apperceptions` + `operator-patterns` to `EXPECTED_COLLECTIONS`, investigate `operator-patterns` empty state, update `CLAUDE.md` collections list, document `axiom-precedents` sparse state, reconcile `profiles/*.yaml` vs Qdrant `profile-facts` drift).

## 5. Exit criteria (verbatim from epic Phase 1)

Status as of this PR; subsequent Phase 1 PRs fill in the rest.

- [x] `~/hapax-state/research-registry/cond-phase-a-baseline-qwen-001/` exists with well-formed YAML — **this PR**
- [ ] `/dev/shm/hapax-compositor/research-marker.json` exists and is read by director loop — **PR #2**
- [ ] Every new reaction has a `condition_id` field in both JSONL and Qdrant — **PR #2**
- [ ] Backfilled reactions have `cond-phase-a-baseline-qwen-001` (verify count ≈ 2178) — **PR #2**
- [ ] `scripts/check-frozen-files.sh` rejects a test edit to a frozen file with a clear error message — **PR #3**
- [ ] `stats.py` uses BEST (or Bayesian estimation equivalent), not beta-binomial — **PR #4**
- [x] OSF project creation procedure documented — **this PR**
- [x] `scripts/research-registry.py` operational; `research-registry current` returns `cond-phase-a-baseline-qwen-001` — **this PR**
- [ ] Langfuse traces in `stream-experiment` tag show `condition_id` metadata — **PR #3**
- [ ] Adjacent Qdrant schema drift fixes (item 10) — **PR #5**

**This PR closes 3 of 10 exit criteria** (items 1, 6, 8). The remaining 7 ship across PRs #2-#5 on the same branch.

## 6. Risks (epic-noted + tonight's additions)

- **Backfill of 2178 Qdrant points** (PR #2) may need batching to avoid Qdrant client timeouts. Bundle 2 §4 mentions chunked update patterns; the implementation should target ~100 points per batch.
- **Frozen-file enforcement** (PR #3) needs to coexist with the existing `no-stale-branches.sh` + `work-resolution-gate.sh` Claude Code hooks. Test order: install pre-commit hook, attempt a frozen-file edit, verify rejection, then verify a non-frozen edit still passes.
- **stats.py migration** (PR #4) is a substantial rewrite if the current code is two-sample t-test. Bundle 2 §1 has the BEST PyMC pattern, but the migration is its own scope.
- **Concurrent writes to `current.txt`** — if two CLI invocations race, the registry could end up pointing at a stale or unwritten condition. Use the same `tmp+rename` atomic write pattern as `lrr-state.py`.
- **The `condition_id` is committed to git** via the YAML files — make sure the IDs are stable across operator + alpha sessions and don't include any timestamp drift.

## 7. Cross-track context

- **Track B (Hardware Window):** X670E motherboard install ~2026-04-16. Phase 1 has no hardware dependency.
- **Track C (Performance Orphans):** independent of Phase 1.
- **Track D (Wave 5 absorbed):** none apply to Phase 1.
- **Track E (Operator-Gated):** Phase 1 has no operator gates. Phase 4 (which depends on Phase 1) does — Sprint 0 G3 gate.

## 8. Beta drops queued for later phases (do not consume in Phase 1)

Per `~/.cache/hapax/relay/lrr-state.yaml::beta_drops_queued`:

| File | Phase | Notes |
|---|---|---|
| `2026-04-14-lrr-bundle-1-substrate-research.md` | 3 + 5 | Hermes 3 70B EXL3 + TabbyAPI dual-GPU + gpu_split ordering |
| `2026-04-14-lrr-bundle-4-governance-drafts.md` | 6 | Phase 6 governance + axiom amendments |
| `2026-04-14-lrr-bundle-7-livestream-experience-design.md` | 7 | Persona + livestream experience design |
| `2026-04-14-lrr-bundle-7-supplement.md` | 7 | Phase 7 supplement |
| `2026-04-14-lrr-bundle-8-autonomous-hapax-loop.md` | 8 | Content programming + autonomous loop |

## 9. Handoff implications

If Phase 1 ships across 5 PRs, the Phase 2 open is gated on the last Phase 1 PR closing. The branch stays alive across sessions. Each PR commit advances the exit criteria checklist. Phase 1's foundation (this PR) is independently useful — once shipped, the next session can pick up any of PRs #2-#5 in any order (they have no internal dependencies).

## 10. Decisions made writing this spec

- **Bundle 2 absorbed where it refines the epic.** The epic defines the per-condition schema; Bundle 2 §4 adds `parent_condition_id`, `sibling_condition_ids`, `collection_started_at`, `collection_halt_at` based on the W&B / MLflow survey. Those additions land in this PR.
- **OSF procedure ships as a document, not code.** Phase 1 doesn't file the pre-registration; that's Phase 4. The procedure document is the deliverable.
- **CLI is intentionally minimal.** PR #1 ships init/current/list/open/close/show. Backfill (`tag-reactions`) and validation helpers (`directives-hash`, `frozen-files`) wait for the PRs that need them.
- **No attempt to re-design the schema.** The epic's schema + Bundle 2's additions = what ships. Future conditions can add fields if needed; the registry is intentionally append-only.

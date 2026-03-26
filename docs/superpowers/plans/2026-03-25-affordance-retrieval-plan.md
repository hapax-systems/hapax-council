# Affordance-as-Retrieval: Implementation Plan

**Spec:** `docs/superpowers/specs/2026-03-25-affordance-retrieval-architecture.md`
**Amends:** `docs/superpowers/plans/2026-03-25-impingement-cascade-epic.md` (Phases 3-5)

## Relationship to Existing Epic

Phase 0 (12/12), Phase 1 (8/8), and Phase 2 (9/9) are **complete**. This plan replaces Phase 3 with the affordance-retrieval pivot, absorbs relevant Phase 3/4/5 deliverables, and adds new deliverables for the retrieval architecture.

The original Phase 3 deliverables (perception backends, shader graph) move to Phase R3 (after retrieval infrastructure is in place). Thompson Sampling (old 4.3) becomes core infrastructure in Phase R1 instead of a Phase 4 add-on.

---

## Phase R0: Foundation — Retrieval Infrastructure

**Goal:** The affordance pipeline exists, capabilities are indexed in Qdrant, and the system can match impingements to capabilities via embedding similarity with ACT-R activation and Thompson Sampling. All existing behavior preserved via fallback.

| # | Deliverable | Files | Lines | Depends On |
|---|------------|-------|-------|------------|
| R0.1 | `CapabilityRecord` + `OperationalProperties` + `ActivationState` models | shared/affordance.py (NEW) | ~120 | — |
| R0.2 | `render_impingement_text()` + add `embedding` field to Impingement | shared/impingement.py | ~30 | — |
| R0.3 | Qdrant `affordances` collection schema + creation | shared/qdrant_schema.py | ~10 | — |
| R0.4 | `AffordancePipeline` — unified selection pipeline (embed, retrieve, activate, compete, dispatch) | shared/affordance_pipeline.py (NEW) | ~250 | R0.1-R0.3 |
| R0.5 | Embedding cache (content hash → vector, in-memory LRU) | shared/affordance_pipeline.py | ~30 | R0.4 |
| R0.6 | Interrupt token registry (exact-match bypass for safety signals) | shared/affordance_pipeline.py | ~20 | R0.4 |
| R0.7 | ACT-R base-level activation (Petrov k=1) in ActivationState | shared/affordance.py | ~40 | R0.1 |
| R0.8 | Thompson Sampling (discounted Beta, gamma=0.99) in ActivationState | shared/affordance.py | ~30 | R0.1 |
| R0.9 | Context spreading activation (DMN read_all → cue weights → association matrix) | shared/affordance_pipeline.py | ~50 | R0.4 |
| R0.10 | Fallback: keyword matching when Ollama unavailable | shared/affordance_pipeline.py | ~30 | R0.4 |
| R0.11 | Tests for Phase R0 | tests/test_affordance_pipeline.py (NEW) | ~300 | all above |

**Milestone test:** Create 3 capability records (speech, fortress, profile_sync) with function-free descriptions. Index in Qdrant. Construct an impingement with content `{"metric": "drink_per_capita", "value": 0, "threshold": 10}`. Embed it. Retrieve top-3 from Qdrant. FortressGovernance ranks highest by cosine similarity. ACT-R activation boosts it further (recently used). Thompson Sampling adds noise. Mutual suppression filters runner-ups. FortressGovernance wins.

**Estimated effort:** ~910 lines, ~5 days

---

## Phase R1: Migration — Wire Existing Capabilities Through Pipeline

**Goal:** Voice, fortress, and engine daemons use the unified AffordancePipeline instead of isolated CapabilityRegistries. All existing behavior preserved.

| # | Deliverable | Files | Lines | Depends On |
|---|------------|-------|-------|------------|
| R1.1 | Write function-free descriptions for SpeechProductionCapability | agents/hapax_voice/capability.py | ~10 | R0.1 |
| R1.2 | Write function-free descriptions for FortressGovernanceCapability | agents/fortress/capability.py | ~10 | R0.1 |
| R1.3 | Auto-generate descriptions for 13 RuleCapabilities | logos/engine/rule_capability.py | ~20 | R0.1 |
| R1.4 | Index all capability descriptions in Qdrant at daemon startup | shared/affordance_pipeline.py | ~40 | R0.3, R1.1-R1.3 |
| R1.5 | Voice daemon: replace direct can_resolve() with pipeline.select() | agents/hapax_voice/__main__.py | ~30 | R0.4, R1.1 |
| R1.6 | Fortress daemon: replace broadcast() with pipeline.select() | agents/fortress/__main__.py | ~30 | R0.4, R1.2 |
| R1.7 | Engine: replace discarded broadcast() with pipeline.select() | logos/engine/__init__.py | ~20 | R0.4, R1.3 |
| R1.8 | Add embedding computation to converter.convert() | logos/engine/converter.py | ~15 | R0.2 |
| R1.9 | Add embedding computation to emit_sensor_impingement() | shared/sensor_protocol.py | ~15 | R0.2 |
| R1.10 | Register interrupt tokens for safety-critical paths | agents/hapax_voice/__main__.py, agents/fortress/__main__.py | ~10 | R0.6 |
| R1.11 | Deprecate per-daemon CapabilityRegistry instances (keep as fallback) | agents/*/__ main__.py | ~20 | R1.5-R1.7 |
| R1.12 | Update tests (replace exact assertions with similarity thresholds) | tests/test_impingement.py, tests/test_engine_cascade.py, tests/test_sensor_protocol.py | ~60 | R1.5-R1.9 |
| R1.13 | Tests for Phase R1 | tests/test_affordance_migration.py (NEW) | ~200 | all above |

**Milestone test:** Same impingement flow as Phase 1 milestone (DMN detects operator_stress → voice speaks) but routed through AffordancePipeline instead of direct can_resolve(). Verify identical behavior. Then: introduce a novel impingement type never seen before (e.g., "creative_block_detected") — verify speech capability is retrieved via embedding similarity despite no hardcoded affordance for it.

**Estimated effort:** ~480 lines, ~3 days

---

## Phase R2: Learning — Associations Emerge From Use

**Goal:** The system learns which capabilities resolve which needs. Associations strengthen through success, weaken through failure. Novel tool-need pairings discoverable.

| # | Deliverable | Files | Lines | Depends On |
|---|------------|-------|-------|------------|
| R2.1 | Outcome feedback interface (success/failure/dismiss signals) | shared/affordance_pipeline.py | ~40 | R0.8 |
| R2.2 | Hebbian association update (context cue × capability co-occurrence) | shared/affordance_pipeline.py | ~50 | R0.9, R2.1 |
| R2.3 | Correction memory integration (operator dismissal → failure signal) | shared/correction_memory.py | ~30 | R2.1 |
| R2.4 | Activation state persistence (JSON file, periodic write) | shared/affordance.py | ~30 | R0.7 |
| R2.5 | Observability: activation audit log (who was considered, who won, why) | shared/affordance_pipeline.py | ~40 | R0.4 |
| R2.6 | Tests for Phase R2 (learning dynamics, association strengthening) | tests/test_affordance_learning.py (NEW) | ~200 | all above |

**Milestone test:** (1) Speech capability activated for "operator_stress" 5 times, all successful → base-level activation rises, Thompson alpha increases. (2) Speech activated for "creative_block" 3 times, operator dismisses each → Thompson beta increases, speech de-prioritized for creative_block. (3) Next creative_block impingement → speech ranks below visual expression (if available) or below threshold (suppressed). System learned without explicit instruction.

**Estimated effort:** ~390 lines, ~3 days

---

## Phase R3: Expression + Perception (Replaces Original Phase 3)

**Goal:** Perception backends and shader graph enter the unified affordance landscape. New capabilities are discovered through embedding similarity, not hardcoded registration.

| # | Deliverable | Files | Lines | Depends On |
|---|------------|-------|-------|------------|
| R3.1 | PerceptionEngine impingement drain | agents/hapax_voice/perception.py | ~20 | R0.2 |
| R3.2 | Trivial backends emit impingements (5) | agents/hapax_voice/backends/*.py | ~80 | R3.1 |
| R3.3 | Moderate backends emit impingements (6) | agents/hapax_voice/backends/*.py | ~240 | R3.1 |
| R3.4 | ShaderGraphCapability with function-free description | agents/effect_graph/capability.py (NEW) | ~150 | R0.1 |
| R3.5 | Stimmung→shader modulation bindings | agents/effect_graph/ | ~30 | R3.4 |
| R3.6 | Register ShaderGraphCapability in affordance pipeline | agents/studio_compositor.py | ~15 | R3.4 |
| R3.7 | Perception impingements → JSONL transport | agents/hapax_voice/perception.py | ~15 | R3.1 |
| R3.8 | Tests for Phase R3 | tests/ | ~150 | all above |

**Milestone test:** Same as original Phase 3 milestone, but routed through AffordancePipeline. Both ShaderGraph and Speech are retrieved as candidates for the same stress impingement. Both activate simultaneously (multi-winner competition, since they don't conflict on resources). Visual calming + verbal check-in fire together from a single impingement.

**Estimated effort:** ~700 lines, ~5 days

---

## Phase R4: Completeness (Replaces Original Phase 4)

**Goal:** All sensor tiers migrated into the affordance landscape. Hard perception backends. DMN systemd unit.

| # | Deliverable | Files | Lines | Depends On |
|---|------------|-------|-------|------------|
| R4.1 | Sensor Tier 2: gmail, gdrive, watch_receiver | agents/*.py | ~100 | R0.2 |
| R4.2 | Sensor Tier 3: git, youtube, obsidian, langfuse, claude_code, weather | agents/*.py | ~120 | R0.2 |
| R4.3 | Hard perception backends (vision, devices, hyprland) | agents/hapax_voice/backends/*.py | ~200 | R3.1 |
| R4.4 | GPU semaphore extension (if VRAM watchdog hits 85%+) | shared/gpu_semaphore.py | ~50 | conditional |
| R4.5 | Systemd service unit for DMN daemon | systemd/units/ | ~20 | R0.1 |
| R4.6 | Remove deprecated CapabilityRegistry fallback code | shared/capability_registry.py, agents/*/__main__.py | ~-200 | R2.6 passing |
| R4.7 | Tests for Phase R4 | tests/ | ~200 | all above |

**Estimated effort:** ~690 lines (net, including deletions), ~4 days

---

## Phase R5: Validation (Replaces Original Phase 5)

**Goal:** Quantitative evidence that affordance-retrieval produces better outcomes than static matching.

| # | Deliverable | Files | Depends On |
|---|------------|-------|------------|
| R5.1 | DF fortress A/B test harness (10 pipeline-enriched vs 10 baseline) | agents/fortress/, scripts/ | R1+R3 |
| R5.2 | Metrics: time-to-gap-detection, novel capability recruitment rate | agents/fortress/metrics.py | R5.1 |
| R5.3 | Voice spontaneous speech appropriateness (50 session comparison) | agents/hapax_voice/ | R2 |
| R5.4 | Novel association discovery rate (capabilities recruited for unprogrammed needs) | shared/affordance_pipeline.py | R2 |
| R5.5 | Visual expression correlation with operator state | agents/effect_graph/ | R3 |
| R5.6 | Analysis document | docs/research/ | R5.1-R5.5 |

**Success criteria:**
- DF: Pipeline-enriched governance detects gaps within 2 game-days (vs baseline 5+)
- Voice: Spontaneous speech acceptance rate > 70%
- Novel association: At least 3 unprogrammed capability-need pairings discovered and reinforced
- Visual: Operator reports visual expression matches state > 80%
- False positive: < 20% of impingements produce activated capabilities that fail
- Learning: Thompson Sampling converges to stable preferences within 50 activation events

---

## Deliverable Count

| Phase | Deliverables | Estimated Lines | Days |
|-------|-------------|----------------|------|
| R0: Foundation | 11 | ~910 | ~5 |
| R1: Migration | 13 | ~480 | ~3 |
| R2: Learning | 6 | ~390 | ~3 |
| R3: Expression + Perception | 8 | ~700 | ~5 |
| R4: Completeness | 7 | ~690 | ~4 |
| R5: Validation | 6 | — | ~3 |
| **Total** | **51** | **~3,170** | **~23 days** |

---

## Critical Path

```
R0 (foundation) ─── R1 (migration) ─── R2 (learning)
                                    └── R3 (expression + perception)
                                         └── R4 (completeness)
                                              └── R5 (validation)
```

R2 and R3 can parallelize (alpha/beta sessions). R4 depends on both. R5 depends on R4.

---

## Risk Mitigation

| Risk | Severity | Mitigation |
|------|----------|-----------|
| Embedding latency on hot path | High | LRU cache for repeated impingement patterns; gRPC Qdrant; batch embeds |
| Ollama unavailability | High | Keyword fallback preserves current behavior; never blocks cascade |
| Semantic collision (different needs, similar embeddings) | Medium | Operational property filtering (requires_gpu, consent) acts as hard constraint |
| Cold start (no learned associations) | Medium | Optimistic Thompson priors (Beta(1,1)); embedding similarity bootstraps |
| Association drift (learned preferences become stale) | Medium | Discounted TS (gamma=0.99) forgets old observations naturally |
| ACT-R fan effect kills spreading activation | Medium | S=4.0 keeps associations positive up to ~54 caps per cue; prune weak links |

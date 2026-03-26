# Epic: Impingement-Driven Activation Cascade

**Status:** Plan
**Date:** 2026-03-25
**Scope:** Full migration from request-response/timer-driven to impingement-driven activation across all Hapax subsystems

---

## Vision

Hapax transitions from a collection of independently-triggered systems to a unified cognitive architecture where the DMN is the always-on base state, components and tools share one activation interface, and composition is determined at runtime by contextual need. Speech, visual expression, governance, and every other capability are recruited by impingement — not by wake words, timers, or request-response patterns.

## Research Foundation

- 22 mapping triplets (DMN operations × phenomenological structures × context ordering mechanics)
- 8 existing always-on systems surveyed (MIRROR, Ambient, SOFAI-LM, Park et al., Voyager, Letta, Reflexion, Memento 2)
- 51 system components audited (23 compatible, 28 partially compatible, 0 incompatible)
- 5 research documents (~6000 lines)
- 3 architectural specifications
- 7 design space specifications

## Deliverables by Phase

---

### Phase 0: Foundation ✅ COMPLETE

| # | Deliverable | Status | PR/Commit |
|---|------------|--------|-----------|
| 0.1 | DMN daemon (pulse, buffer, sensor, __main__) | ✅ | PR #340 |
| 0.2 | DMN bug fixes (self-reference protocol, consolidation pruning) | ✅ | Direct main |
| 0.3 | Impingement data type (shared/impingement.py) | ✅ | Direct main |
| 0.4 | CapabilityRegistry (shared/capability_registry.py) | ✅ | Direct main |
| 0.5 | DMN anti-habituation absolute thresholds | ✅ | Direct main |
| 0.6 | FortressGovernanceCapability | ✅ | Direct main |
| 0.7 | SpeechProductionCapability (defined, not wired) | ✅ | Direct main |
| 0.8 | DMN buffer in voice VOLATILE band | ✅ | Direct main |
| 0.9 | DMN buffer in fortress deliberation prompt | ✅ | Direct main |
| 0.10 | DMN buffer staleness check | ✅ | Direct main |
| 0.11 | Fortress resource chain escalation (workshop gap detection) | ✅ | PR #337 |
| 0.12 | 27 tests (DMN + impingement + cascade) | ✅ | Direct main |

---

### Phase 1: Critical Path — First Spontaneous Behavior

**Goal:** The system speaks without being addressed, based on a DMN-detected impingement, for the first time.

| # | Deliverable | Design Space | Files | Lines | Depends On |
|---|------------|-------------|-------|-------|------------|
| 1.1 | DMN writes impingements.jsonl | DS2 | agents/dmn/__main__.py | ~10 | 0.3, 0.5 |
| 1.2 | Voice daemon impingement consumer loop | DS2 | agents/hapax_voice/__main__.py | ~40 | 1.1 |
| 1.3 | Voice daemon instantiates + registers SpeechProductionCapability | DS1 | agents/hapax_voice/__main__.py | ~10 | 0.7 |
| 1.4 | Cognitive loop polls speech capability | DS1 | agents/hapax_voice/cognitive_loop.py | ~15 | 1.3 |
| 1.5 | Impingement-to-speech bridge in conversation pipeline | DS1 | agents/hapax_voice/conversation_pipeline.py | ~30 | 1.4 |
| 1.6 | Voice→DMN anti-correlation flag file | DS5 | agents/hapax_voice/__main__.py, agents/dmn/__main__.py | ~15 | 0.1 |
| 1.7 | Fortress reads DMN impingements.jsonl (replace self-generated) | DS2 | agents/fortress/__main__.py | ~20 | 1.1 |
| 1.8 | Tests for Phase 1 | — | tests/ | ~100 | all above |

**Milestone test:** DMN detects operator_stress > 0.8 → emits Impingement → voice consumer reads JSONL → SpeechProductionCapability matches → cognitive loop consumes → pipeline generates "You've been at it for a while, might be time for a break" → TTS speaks.

**Estimated effort:** ~240 lines, ~2 days

---

### Phase 2: Architecture Migration — Reactive Engine + Sensors

**Goal:** The reactive engine uses the Capability protocol. Timer-driven sensors emit impingements on state change.

| # | Deliverable | Design Space | Files | Lines | Depends On |
|---|------------|-------------|-------|-------|------------|
| 2.1 | ChangeEvent→Impingement converter | DS3 | logos/engine/converter.py (NEW) | ~100 | 0.3 |
| 2.2 | RuleCapability wrapper | DS3 | logos/engine/rule_capability.py (NEW) | ~80 | 0.4, 2.1 |
| 2.3 | ReactiveEngine integrates CapabilityRegistry | DS3 | logos/engine/__init__.py | ~50 | 2.2 |
| 2.4 | SensorBackend protocol definition | DS4 | shared/sensor_protocol.py (NEW) | ~60 | 0.3 |
| 2.5 | Sensor Tier 1: stimmung_sync → /dev/shm + impingement | DS4 | agents/stimmung_sync.py | ~30 | 2.4 |
| 2.6 | Sensor Tier 1: gcalendar_sync → /dev/shm + impingement | DS4 | agents/gcalendar_sync.py | ~40 | 2.4 |
| 2.7 | Sensor Tier 1: chrome_sync → /dev/shm + impingement | DS4 | agents/chrome_sync.py | ~30 | 2.4 |
| 2.8 | DMN sensor.py reads /dev/shm/hapax-sensors/ | DS4 | agents/dmn/sensor.py | ~30 | 2.5-2.7 |
| 2.9 | Tests for Phase 2 | — | tests/ | ~200 | all above |

**Milestone test:** File change in profiles/ → inotify → ChangeEvent → Impingement → CapabilityRegistry broadcast → RuleCapability self-selects → produce() → PhasedExecutor runs action. Identical behavior to pre-migration, verified by audit log comparison.

**Estimated effort:** ~620 lines, ~4 days

---

### Phase 3: Expression + Perception — The Visual Voice

**Goal:** The shader graph expresses system state visually. Perception backends emit impingements. The cascade has sensory input AND expressive output.

| # | Deliverable | Design Space | Files | Lines | Depends On |
|---|------------|-------------|-------|-------|------------|
| 3.1 | PerceptionEngine impingement drain | DS6 | agents/hapax_voice/perception.py | ~20 | 0.3 |
| 3.2 | Trivial backends emit impingements (5): presence, phone, midi, input, pipewire | DS6 | agents/hapax_voice/backends/*.py | ~80 | 3.1 |
| 3.3 | Moderate backends emit impingements (6): watch, speech_emotion, attention, health, studio_ingestion, local_llm | DS6 | agents/hapax_voice/backends/*.py | ~240 | 3.1 |
| 3.4 | ShaderGraphCapability | DS7 | agents/effect_graph/capability.py (NEW) | ~150 | 0.4 |
| 3.5 | Stimmung→shader modulation bindings | DS7 | agents/effect_graph/ or compositor | ~30 | 3.4 |
| 3.6 | Register ShaderGraphCapability in compositor | DS7 | agents/studio_compositor.py | ~10 | 3.4 |
| 3.7 | Perception impingements → JSONL transport | DS6 | agents/hapax_voice/perception.py | ~15 | 3.1, 1.1 |
| 3.8 | Tests for Phase 3 | — | tests/ | ~150 | all above |

**Milestone test:** Operator stress rises (watch HR spike + speech_emotion detects frustration) → perception backends emit impingements → DMN absolute threshold fires → cascade broadcasts → ShaderGraphCapability activates with visual_calm (warm, slow, dim) → SpeechProductionCapability activates with verbal check-in → both expression modalities fire simultaneously from the same impingement.

**Estimated effort:** ~695 lines, ~5 days

---

### Phase 4: Completeness — Full Coverage

**Goal:** All sensor tiers migrated. Correction feedback loop closes. Affordance landscape pre-computed.

| # | Deliverable | Design Space | Files | Lines | Depends On |
|---|------------|-------------|-------|-------|------------|
| 4.1 | Sensor Tier 2: gmail, gdrive, watch_receiver | DS4 | agents/*.py | ~100 | 2.4 |
| 4.2 | Sensor Tier 3: git, youtube, obsidian, langfuse, claude_code, weather | DS4 | agents/*.py | ~120 | 2.4 |
| 4.3 | Thompson Sampling on capability B_i | DS1 | shared/capability_registry.py | ~60 | 1.5 |
| 4.4 | Correction→activation feedback (dismissal/engagement signals) | DS1 | shared/correction_memory.py | ~80 | 4.3 |
| 4.5 | Affordance landscape pre-computation in DMN | — | agents/dmn/pulse.py | ~40 | 0.4 |
| 4.6 | Hard perception backends (vision, devices, hyprland) | DS6 | agents/hapax_voice/backends/*.py | ~200 | 3.1 |
| 4.7 | GPU semaphore extension (if VRAM watchdog hits 85%+) | DS5 | shared/gpu_semaphore.py | ~50 | conditional |
| 4.8 | Systemd service unit for DMN daemon | — | systemd/units/ | ~20 | 0.1 |
| 4.9 | Tests for Phase 4 | — | tests/ | ~200 | all above |

**Milestone test:** Operator dismisses spontaneous speech 3 times about stress → Thompson Sampling adjusts B_i → next stress impingement routes to visual_calm only (no speech) → system learned "operator doesn't want verbal stress check-ins" without explicit instruction.

**Estimated effort:** ~870 lines, ~6 days

---

### Phase 5: Forcing Function — Validation

**Goal:** Quantitative evidence that impingement-driven activation produces better outcomes than the old model.

| # | Deliverable | Files | Depends On |
|---|------------|-------|------------|
| 5.1 | DF fortress A/B test harness (10 DMN-enriched vs 10 baseline) | agents/fortress/, scripts/ | Phase 1+2 |
| 5.2 | Metrics: time-to-gap-detection, deliberation action rate, false positive rate | agents/fortress/metrics.py | 5.1 |
| 5.3 | Voice spontaneous speech appropriateness metric (50 session comparison) | agents/hapax_voice/ | Phase 1+3 |
| 5.4 | Visual expression correlation with operator state (stimmung→shader→operator feedback) | agents/effect_graph/ | Phase 3 |
| 5.5 | Analysis document: impingement cascade vs baseline, per-phase gains | docs/research/ | 5.1-5.4 |

**Success criteria:**
- DF: DMN-enriched governance detects infrastructure gaps within 2 game-days (vs baseline 5+)
- DF: Deliberation action rate > 50% (vs baseline 0%)
- Voice: Spontaneous speech acceptance rate > 70% (dismissed < 30%)
- Visual: Operator reports visual expression matches perceived state > 80% of the time
- System: False positive impingement rate < 20%

---

## Total Scope

| Phase | Lines | Days | Deliverables |
|-------|-------|------|-------------|
| 0 (DONE) | ~2600 | — | 12 deliverables |
| 1 | ~240 | 2 | 8 deliverables |
| 2 | ~620 | 4 | 9 deliverables |
| 3 | ~695 | 5 | 8 deliverables |
| 4 | ~870 | 6 | 9 deliverables |
| 5 | varies | 3 | 5 deliverables |
| **Total** | **~5025** | **~20 days** | **51 deliverables** |

## Dependencies

```
Phase 0 ─── Phase 1 ─── Phase 2
                │           │
                └─── Phase 3
                        │
                   Phase 4
                        │
                   Phase 5
```

Phase 1 and Phase 2 can partially parallelize (alpha/beta sessions).
Phase 3 depends on Phase 1 (cross-daemon routing) but not Phase 2 (engine migration).
Phase 4 is incremental and can overlap with Phase 3.
Phase 5 requires Phase 1+2+3 complete.

## Risks

| Risk | Mitigation |
|------|-----------|
| Spontaneous speech is annoying | Thompson Sampling feedback loop (Phase 4.3) + kill switch (set _dmn_fn = None) |
| Shader modulation is jarring | Crossfade engine (300-500ms lerp), graduated activation, design language compliance |
| Impingement flood (too many signals) | Inhibition of return (30s refractory), mutual suppression, buffer cap (1500 tokens) |
| GPU contention under load | Anti-correlation signal (Phase 1.6), VRAM watchdog (existing), 16GB headroom |
| Reactive engine migration breaks rules | Non-breaking wrapper pattern, fallback to evaluate_rules(), audit log comparison |
| NVIDIA driver regression | Pinned at 590.48.01, IgnorePkg in pacman.conf |

## Non-Goals

- Fine-tuning any model (all inference-only)
- Latent-space feedback (Coconut-style) — all DMN output is text
- Multi-agent debate within the DMN
- Replacing the voice daemon's real-time audio loops (30ms/150ms stay as-is)
- Central orchestrator or router (composition is emergent)

# HSEA Phase 11 — Multi-Agent Spawner (Cluster G) — Plan

**Date:** 2026-04-15
**Spec reference:** `docs/superpowers/specs/2026-04-15-hsea-phase-11-multi-agent-spawner-design.md`
**Branch target:** `feat/hsea-phase-11-multi-agent-spawner`
**Unified phase mapping:** UP-13 sibling (~2,400 LOC)

---

## 0. Preconditions

- [ ] HSEA UP-2 closed (spawn budget + governance queue)
- [ ] HSEA UP-10 closed (ComposeDropActivity + patch activity)
- [ ] LRR UP-9 closed (persona for spawn prompts)
- [ ] LRR Phase 5a closed with operator-ratified substrate
- [ ] `hsea_spawn_heartbeat()` helper from HSEA Phase 1 1.4 operational
- [ ] Session claims: `hsea-state.yaml::phase_statuses[11].status: open`

---

## Execution order: G1 → G10 → G2 → G5 → G4 → G7 → G8 → G11 → G13 → G14 → G6

### 1. G1 — research_question affordance

- [ ] Tests: recruit via AffordancePipeline.select(); spawn sub-agent with bounded question
- [ ] `agents/affordances/research_question_affordance.py` (~200 LOC)
- [ ] Register in Qdrant `affordances` collection
- [ ] Commit: `feat(hsea-phase-11): G1 research_question affordance`

### 2. G10 — Long-running research sessions with checkpoints

- [ ] Tests: spawn 30-min mode, checkpoint every 10 min, cancel via governance queue
- [ ] `agents/hapax_daimonion/g_cluster/g10_long_running_session.py` (~350 LOC)
- [ ] Wall-time cap + checkpoint writes partial findings
- [ ] Commit: `feat(hsea-phase-11): G10 long-running sessions with checkpoints`

### 3. G2 — Weekly self-analysis ritual (Sunday 04:00)

- [ ] Tests: timer → spawn → self-analysis drop
- [ ] `agents/hapax_daimonion/g_cluster/g2_self_analysis_ritual.py` (~300 LOC)
- [ ] `systemd/user/hapax-g2-self-analysis.timer` (Sunday 04:00)
- [ ] Commit: `feat(hsea-phase-11): G2 weekly self-analysis ritual`

### 4. G5 — Tactical re-evaluation on 30-day clock

- [ ] Tests: monthly timer → re-evaluate drop #57 tactics + drop #58 Cluster proposals
- [ ] `agents/hapax_daimonion/g_cluster/g5_tactical_reevaluation.py` (~280 LOC)
- [ ] Monthly timer
- [ ] Commit: `feat(hsea-phase-11): G5 tactical re-evaluation on 30-day clock`

### 5. G4 — Drop draft from sub-agent consensus

- [ ] Tests: 3 synthetic findings → consensus drop composed
- [ ] `agents/hapax_daimonion/g_cluster/g4_consensus_drop_composer.py` (~250 LOC)
- [ ] Reads `/dev/shm/hapax-orchestration/findings-*.jsonl`
- [ ] Commit: `feat(hsea-phase-11): G4 drop draft from sub-agent consensus`

### 6. G7 — Anomaly analyst spawn

- [ ] Tests: fixture anomaly trigger → analyst spawn → incident drop
- [ ] `agents/hapax_daimonion/g_cluster/g7_anomaly_analyst.py` (~300 LOC)
- [ ] Reads journal + git log + CI state + compositor metrics
- [ ] Commit: `feat(hsea-phase-11): G7 anomaly analyst spawn`

### 7. G8 — Constitutional decision proxy

- [ ] Tests: precedent-level decision → sub-agent proposes text + rationale
- [ ] `agents/hapax_daimonion/g_cluster/g8_constitutional_proxy.py` (~250 LOC)
- [ ] Operator reviews via governance queue
- [ ] Commit: `feat(hsea-phase-11): G8 constitutional decision proxy`

### 8. G11 — Live Langfuse telemetry slot

- [ ] Tests: live Langfuse span → Cairo render
- [ ] `agents/studio_compositor/g11_langfuse_telemetry_source.py` (~200 LOC)
- [ ] Uses `hapax_span` bridge
- [ ] Commit: `feat(hsea-phase-11): G11 live Langfuse telemetry slot`

### 9. G13 — Emergency analyst (Tier-1 bypass)

- [ ] Tests: Stream Deck button → emergency flag → budget bypass → 5-min analyst
- [ ] `agents/hapax_daimonion/g_cluster/g13_emergency_analyst.py` (~250 LOC)
- [ ] Stream Deck button wiring (from LRR Phase 8 item 6)
- [ ] Commit: `feat(hsea-phase-11): G13 emergency analyst (Tier-1 bypass via Stream Deck)`

### 10. G14 — Multi-agent consensus demonstration

- [ ] Tests: 3 parallel analyses converge → narrated consensus on stream
- [ ] `agents/hapax_daimonion/g_cluster/g14_consensus_demo.py` (~200 LOC)
- [ ] Commit: `feat(hsea-phase-11): G14 multi-agent consensus demonstration`

### 11. G6 — Voice session parallel scoring

- [ ] Tests: voice session active → parallel agent scores utterances against grounding criteria
- [ ] `agents/hapax_daimonion/g_cluster/g6_voice_session_scorer.py` (~300 LOC)
- [ ] ConsentGatedWriter for Qdrant writes (from LRR Phase 6)
- [ ] Commit: `feat(hsea-phase-11): G6 voice session parallel scoring`

---

## Phase 11 close

- [ ] All 11 G-deliverables registered + test spawn verified per deliverable
- [ ] Spawn budget hard-gates enforced (verified via overflow test)
- [ ] G13 emergency bypass tested with Stream Deck button
- [ ] Spec §5 exit criteria verified
- [ ] Handoff doc
- [ ] `hsea-state.yaml::phase_statuses[11].status: closed`

---

## Cross-epic coordination

- **HSEA Phase 0 spawn budget** (0.3) gates all spawns
- **HSEA Phase 0 governance queue** (0.2) receives G-drafter drops
- **HSEA Phase 1 `hsea_spawn_heartbeat()`** (1.4) consumed by all G-drafters for active.jsonl writes
- **HSEA Phase 2 ComposeDropActivity** (3.6) composed for drop synthesis
- **LRR Phase 8 Stream Deck** (item 6) button for G13 emergency flag
- **LRR Phase 6 ConsentGatedWriter** for G6 Qdrant writes

---

## End

Compact plan for HSEA Phase 11 Multi-Agent Spawner / Cluster G. Pre-staging. All spawns gated through budget.

— delta, 2026-04-15

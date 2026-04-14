# LRR Phase 9 — Closed-Loop Feedback + Narration + Chat Integration (plan)

**Phase:** 9 of 11
**Spec:** `docs/superpowers/specs/2026-04-14-lrr-phase-9-closed-loop-design.md`

## PR sequence (target 4 PRs)

### PR #1 — Open + heuristic chat classifier + attack log

**Items:** 1, 4

**Files:**
- `docs/superpowers/specs/2026-04-14-lrr-phase-9-closed-loop-design.md` (this PR)
- `docs/superpowers/plans/2026-04-14-lrr-phase-9-closed-loop-plan.md` (this PR)
- `agents/studio_compositor/chat_classifier.py` — heuristic tier, 7 labels
- `agents/studio_compositor/chat_attack_log.py` — T0/T1 append-only log
- `tests/test_chat_classifier.py` — fixtures covering all 7 tiers
- `tests/test_chat_attack_log.py` — append semantics + rate limit counter

### PR #2 — Tiered chat queues + embedding-importance sampling

**Items:** 2

**Files:**
- `agents/studio_compositor/chat_queues.py` — `HighValueQueue`, `ResearchRelevantQueue`, `StructuralSignalQueue`
- `agents/studio_compositor/_embedding_stub.py` — deterministic fake embedder for tests
- `tests/test_chat_queues.py` — eviction correctness, sampling policies

### PR #3 — Structural aggregation + inference budget allocator

**Items:** 3, 5

**Files:**
- `agents/studio_compositor/chat_signals.py` — 60s rolling window aggregator
- `shared/inference_budget.py` — token bucket allocator, tier config, Prometheus gauge
- `tests/test_chat_signals.py` — JSON output shape + audience_engagement formula
- `tests/test_inference_budget.py` — bucket exhaustion + graceful degradation

### PR #4 — Phase 9 close handoff + integration readiness doc

**Items:** 6, close

**Files:**
- `docs/superpowers/handoff/2026-04-14-lrr-phase-9-complete.md`
- Minor test additions if needed for coverage

## Pickup procedure

The session that opens Phase 5 (Hermes 3 substrate swap) reads:
1. `~/.cache/hapax/relay/lrr-state.yaml` — confirms Phase 9 closed
2. `docs/superpowers/handoff/2026-04-14-lrr-phase-9-complete.md` — Phase 9 close handoff
3. Phase 5 section of the LRR epic design doc
4. Bundle 9 §4 (inference budget allocation) — Phase 5 hard prerequisite

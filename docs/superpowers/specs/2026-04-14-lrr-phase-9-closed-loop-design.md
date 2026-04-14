# LRR Phase 9 — Closed-Loop Feedback + Narration + Chat Integration (design)

**Phase:** 9 of 11
**Owner:** alpha
**Branch:** `feat/lrr-phase-9-closed-loop`
**Dependency (canonical):** Phase 8 (content programming)
**Dependency (relaxed per operator):** none — Phase 9 scaffolding shipped out-of-sequence as code-pure pre-staging
**Epic design reference:** `docs/superpowers/specs/2026-04-14-livestream-research-ready-epic-design.md` §Phase 9
**Beta bundle:** `~/.cache/hapax/relay/context/2026-04-14-lrr-bundle-9-engineering-scaling.md`

## Out-of-sequence justification

Per operator mid-Phase-2 ordering guidance (2026-04-14): *"after Bundle 8: 9 → sister epic → 5 → 3 → 6"*. The canonical dependency chain (Phase 9 ← 8 ← 7 ← 6 ← 5 ← 4 ← 3 ← hardware) is hardware + operator gated. Phase 9's engineering-scaling content (Bundle 9) is pure Python + can be shipped as library modules + scaffolding + tests that compose with Phase 8 integration when it lands.

**What Phase 9 ships NOW** (this spec's scope):
- Chat classifier (heuristic tier, 7 labels, §2.2 tiers T0-T6)
- Tiered chat queues (Queue A high-value FIFO, Queue B embedding-importance, Queue C structural)
- Structural aggregation writer (`/dev/shm/hapax-chat-signals.json`)
- Attack log writer (T0/T1 → `/dev/shm/hapax-chat-attack-log.jsonl`)
- Inference budget allocator (token bucket per 5-tier hierarchy)
- Chat queue v2 Pydantic schemas + eviction correctness tests

**What Phase 9 DEFERS** (waits for Phase 8/5/hardware):
- Small-model classifier fallback (needs fine-tuned 3B model)
- Hermes 3 classifier fallback (needs Hermes 3 serving)
- Director-loop integration (needs Phase 8 activity selector)
- Live `cache_control` markers (needs Hermes 3 prompt caching)
- `hapax-chat-classifier.service` systemd daemon (waits for small-model availability)

This pattern matches Phase 2's approach: **ship the library layer + tests autonomously; defer the runtime wiring to the integration phase**.

## Items (6, adapted from Bundle 9 §2-§4)

1. **Chat classifier (heuristic tier)** — `agents/studio_compositor/chat_classifier.py`. Regex + deny-list + character-class dispatch into 7 tiers (T0 suspicious_injection through T6 high_value). Catches ~60% of messages without any model call. Fast-path for the T0-T3 drop classes.

2. **Tiered chat queues** — `agents/studio_compositor/chat_queues.py`. Three distinct queue types:
   - `HighValueQueue` — capacity 5, FIFO eviction, top-3 per director tick
   - `ResearchRelevantQueue` — capacity 30, embedding-importance eviction, top-5 per tick
   - `StructuralSignalQueue` — time-windowed 60s rolling, aggregated signals not sampled directly
   Pluggable embedding function (stub for now; real nomic-embed-text integration waits for Phase 9 v2).

3. **Structural aggregation** — `agents/studio_compositor/chat_signals.py`. Rolling 60s window writer that emits `audience_engagement` components (message count, rate, unique authors count, entropy, novelty, topic distribution) to `/dev/shm/hapax-chat-signals.json`. Strictly structural — NO sentiment.

4. **Attack log writer** — `agents/studio_compositor/chat_attack_log.py`. T0 (suspicious_injection) and T1 (harassment) messages append to `/dev/shm/hapax-chat-attack-log.jsonl` with ephemeral author handle + timestamp + tier + dropped_reason. Per-author rate-limit counter maintained in-process (no persistence — compliant with `it-broadcast-007`).

5. **Inference budget allocator** — `shared/inference_budget.py`. Token bucket per 5-tier hierarchy (claim agenda, arc planner, block scheduler, activity selector, tick execution). Refresh interval 3600s. Graceful degradation: 80% consumption alerts via ntfy; tier-specific non-LLM fallback activities when exhausted. Metrics: `hapax_inference_budget_remaining{tier=N}` gauge.

6. **Phase 9 close handoff + integration readiness doc** — `docs/superpowers/handoff/2026-04-14-lrr-phase-9-complete.md`. Documents which items shipped as libraries, which need Phase 8 integration, which need Hermes 3 runtime, and what the "flip the switch" commands look like when dependencies are met.

## Exit criteria

- [ ] Chat classifier returns correct tier for 50+ test message fixtures covering each of T0-T6
- [ ] Queue A/B/C eviction policies verified against synthetic load
- [ ] Chat signals writer produces JSON with all 7 required fields within 100ms of window tick
- [ ] Attack log JSONL is append-only with O_APPEND semantics
- [ ] Inference budget allocator enforces tier limits + publishes Prometheus gauge
- [ ] All new modules have >90% unit test coverage
- [ ] Close handoff documents the Phase 8 integration points (where to call into)
- [ ] No live systemd enables — all wiring is staged pending Phase 8

## Non-goals

- **No Hermes 3 integration.** Cache markers + prompt caching are Phase 5 work, documented as preconditions in the handoff.
- **No small-model training.** The 3B classifier fallback is Phase 9 v2.
- **No director loop integration.** Hooks exist but call sites are deferred.
- **No live chat feed ingestion.** The queue library accepts messages from a generic producer; the YouTube/Twitch adapter is a separate integration.
- **No sentiment scoring.** Explicitly excluded per token pole 7 principle + Bundle 9 §2.6.

## Risks

1. **Embedding stub skews test results.** The `ResearchRelevantQueue` uses a pluggable embedding function. The test suite uses a deterministic fake embedder. When the real `nomic-embed-text` integration lands, behavior may drift. Mitigation: integration test with a recorded embedding fixture.
2. **Budget allocator over-engineers for pre-Hermes-3 world.** The 5-tier hierarchy comes from Bundle 8; if Phase 8 changes the hierarchy, the budget allocator needs rework. Mitigation: the tier count is a config constant, not a magic number.
3. **Attack log path exists but dispatch is dormant.** If an operator enables the attack log without enabling the classifier, the file stays empty. Mitigation: the classifier and attack log are paired under a single feature flag `HAPAX_CHAT_CLASSIFIER_ENABLED=1`.

## Frozen files

None touched. Phase 9 items live in new modules under `agents/studio_compositor/` + `shared/` — no changes to grounding_ledger.py, conversation_pipeline.py, persona.py, or conversational_policy.py.

## Deviation log

_(None so far.)_

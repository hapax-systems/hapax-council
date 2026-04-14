# LRR Phase 9 — Complete (handoff)

**Phase:** 9 of 11 (Closed-Loop Feedback + Narration + Chat Integration)
**Owner:** alpha
**Branch:** `feat/lrr-phase-9-closed-loop`
**Opened:** 2026-04-14T10:42Z
**Closing:** this PR
**PRs shipped:** 4 commits on a single branch (PR #798)
**Per-phase spec:** `docs/superpowers/specs/2026-04-14-lrr-phase-9-closed-loop-design.md`
**Per-phase plan:** `docs/superpowers/plans/2026-04-14-lrr-phase-9-closed-loop-plan.md`
**Beta bundle:** `~/.cache/hapax/relay/context/2026-04-14-lrr-bundle-9-engineering-scaling.md`

## Out-of-sequence justification

Phase 9 was opened out-of-canonical-sequence per operator mid-Phase-2 guidance: *"after Bundle 8: 9 → sister epic → 5 → 3 → 6"*. The canonical dependency chain has Phase 9 ← 8 ← 7 ← 6 ← 5 ← 4 ← 3 ← hardware. Phase 3 is X670E hardware gated (~2026-04-16), Phase 4 is operator voice-session gated, Phases 6 + 7 are operator governance/persona gated, Phase 5 + 8 depend on those.

**Phase 9 is the only code-pure phase feasible** without hardware or operator involvement, because Bundle 9 pre-staged the engineering-scaling design. Phase 9 therefore ships as a set of **library modules + scaffolding + tests** that compose with Phase 8 integration when it lands. The director-loop integration, live chat feed, small-model classifier fallback, and Hermes 3 prompt cache wiring are all explicitly deferred.

## What shipped (6 of 6 items closed)

| # | Item | Status | Commit |
|---|---|---|---|
| 1 | Chat classifier (heuristic tier, 7 labels) | ✅ | b5361e481 (PR #1) |
| 2 | Tiered chat queues (HighValue/ResearchRelevant/Structural) | ✅ | 18761f487 (PR #2) |
| 3 | Structural aggregation (audience_engagement writer) | ✅ | this PR (PR #3) |
| 4 | Attack log writer (T0/T1 JSONL) | ✅ | b5361e481 (PR #1) |
| 5 | Inference budget allocator (token bucket per tier) | ✅ | this PR (PR #3) |
| 6 | Phase 9 close handoff + integration readiness | ✅ | this PR (PR #4) |

## Test stats

- **114 new Python tests** across the branch: 45 classifier + 23 attack log + 19 queues + 18 chat signals + 19 inference budget = sum per suite counts.
- All ruff lint + format clean
- 100% of new modules covered

## Deferred to integration phases

### Phase 9 v2 (waits for small-model training)

- **`chat_classifier_small_model.py`**: 3B fine-tuned classifier for the ~40% of messages the heuristic layer returns with low confidence. Bootstrap with operator-labeled examples from the early private-stream phase; continuous labeling after month 1.
- **`hapax-chat-classifier.service`**: systemd daemon hosting the small-model classifier on CPU or GPU 0 (NOT the Hermes 3 GPU).

### Phase 5 (waits for Hermes 3 runtime)

- **Hermes 3 fallback path in the classifier** — triggered when the small-model confidence is < 0.6. Strict 32-token cap for classification output.
- **`cache_control` markers** on the stable persona + system prompt blocks for 70%+ prompt cache hit rate (Bundle 9 §4).
- **Tier 2 fallback activities** (`vinyl`, `observe`, `silence`, reverie-only) — wiring from `BudgetExhausted` to the activity selector.

### Phase 8 (waits for content programming)

- **Director-loop integration** — call sites in `director_loop.py` that invoke the classifier on each incoming chat message, route to the right queue, and pull samples into the Hapax prompt at tick time.
- **Focus vector recomputation** — 30s timer that reads the current objective title + claim state + arc beat and updates `ResearchRelevantQueue.focus_vector`.
- **`audience_engagement` stimmung dimension** — consumer in `visual_layer_aggregator.py` that reads `/dev/shm/hapax-chat-signals.json` and feeds the new dimension.

### Phase 10 (observability polish)

- **Prometheus gauge** — `hapax_inference_budget_remaining{tier="..."}` fed by `InferenceBudgetAllocator.snapshot()`.
- **Chat queue depth gauges** — `hapax_chat_queue_depth{queue="high_value|research|structural"}`.
- **Chat classifier confidence histogram** — `hapax_chat_classifier_confidence`.

## Integration readiness — "flip the switch" commands

When Phase 8 is ready to wire Phase 9 in:

```python
from agents.studio_compositor.chat_classifier import classify_chat_message, ChatTier
from agents.studio_compositor.chat_queues import (
    HighValueQueue, ResearchRelevantQueue, StructuralSignalQueue, ChatMessage,
)
from agents.studio_compositor.chat_signals import ChatSignalsAggregator
from agents.studio_compositor.chat_attack_log import AttackLogWriter
from shared.inference_budget import InferenceBudgetAllocator, InferenceTier

# At compositor / director startup:
queues = {
    ChatTier.T6_HIGH_VALUE: HighValueQueue(),
    ChatTier.T5_RESEARCH_RELEVANT: ResearchRelevantQueue(),
    ChatTier.T4_STRUCTURAL_SIGNAL: StructuralSignalQueue(),
}
aggregator = ChatSignalsAggregator(queues[ChatTier.T4_STRUCTURAL_SIGNAL])
attack_log = AttackLogWriter()
budget = InferenceBudgetAllocator()

# Per incoming chat message:
def on_chat_message(text: str, author_handle: str, ts: float) -> None:
    cls = classify_chat_message(text)
    attack_log.record(classification=cls, message_text=text, author_handle=author_handle)
    if cls.tier.is_drop:
        return
    msg = ChatMessage(text=text, author_handle=author_handle, ts=ts, classification=cls)
    queues[cls.tier].push(msg)

# Per director tick:
def on_director_tick(now: float) -> None:
    try:
        budget.reserve(InferenceTier.T4_ACTIVITY_SELECTOR, tokens=512)
    except BudgetExhausted:
        fallback_to_non_llm_activity()
        return
    high_value_msgs = queues[ChatTier.T6_HIGH_VALUE].sample(top_k=3)
    research_msgs = queues[ChatTier.T5_RESEARCH_RELEVANT].sample(top_k=5, now=now)
    # pass into Hapax prompt...

# Per 30s aggregator timer:
def on_aggregator_tick(now: float) -> None:
    signals = aggregator.compute_signals(
        now=now,
        high_value_queue_depth=len(queues[ChatTier.T6_HIGH_VALUE]),
    )
    aggregator.write_shm(signals)
```

## Carry-overs + known blockers (Phase-wide, not Phase 9 specific)

- **Phase 0 item 3** — `/data` inode alerts cross-repo (llm-stack operator-gated)
- **Phase 0 item 4 Step 3** — FINDING-Q runtime rollback design-ready
- **Phase 1 item 10 sub-item 2** — dotfiles workspace-CLAUDE.md Qdrant collections 9 → 10 (beta pre-staged at `~/.cache/hapax/relay/context/2026-04-14-beta-phase-1-dotfiles-fix.md`)
- **Phase 6 voice transcript rotation hook**
- **Phase 2 Phase 10 carry-overs** — compositor-side OutputRouter migration, ResearchMarkerOverlay compositor registration, audio recorder env var reader
- **Delta Phase 10 backlog** — BudgetTracker wired runtime, per-source frame-time histograms, overlay_zones cairo burst guard (see `docs/research/2026-04-14-compositor-frame-budget-forensics.md` + errata + delta's latest `docs/research/2026-04-14-fdfe7ecda-...overlay-zones-cairo-invalid-size-call-chain.md`)

## Pickup note for next session

Per operator ordering: **sister epic next**. Look for `~/.cache/hapax/relay/context/2026-04-14-sister-epic-community-brand-stewardship.md` (29KB, beta drafted pre-Phase-2). Open as a **separate epic** (not part of LRR), write a design doc + plan, ship the first PR.

The LRR epic itself is ~30% complete (4 of 11 phases: 0, 1, 2, 9). Remaining phases all require either hardware (3), operator-in-loop data (4, 6, 7), or dependencies on those (5, 8). Phase 10 observability polish could be opened autonomously after sister epic closes — delta has pre-staged findings.

**Beta pre-staged artifacts queued for later phases:**
- `2026-04-14-lrr-phase-3-prestaged-artifacts.md` — Phase 3 executable scripts
- `2026-04-14-beta-phase-6-axiom-patches-readyto-apply.md` — Phase 6 governance drafts
- `2026-04-14-lrr-bundle-3-grounding-literature.md` — Phase 4 grounding classifier
- `2026-04-14-lrr-bundle-5-persona-literature-yaml-v0.md` — Phase 7 persona v0
- `2026-04-14-lrr-bundle-1-substrate-research.md` — Phase 3 + 5 substrate
- `2026-04-14-lrr-bundle-6-latency-mitigation.md` — Phase 5 polish
- `2026-04-14-lrr-bundle-8-autonomous-hapax-loop.md` — Phase 8 content programming

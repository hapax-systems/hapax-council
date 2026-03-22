# Closing Observability Feedback Loops

**Date:** 2026-03-13
**Status:** Plan (not implementation-ready — pending architectural research)
**Scope:** Wire observability consumers to the data now being produced by H1-H4/M1-M4

---

## Gap Inventory

### G1. Cost Trend in Briefing (~20 LOC)

**Current:** activity_analyzer computes `total_cost` for the lookback window. Briefing displays it as a raw number.

**Change:** Add week-over-week comparison in activity_analyzer. If `this_week / last_week > 1.2`, inject a high-priority action item.

**Files:** `agents/activity_analyzer.py` (add `cost_trend` to `LangfuseActivity`), `agents/briefing.py` (conditional action item).

**Dependency:** None. Can ship standalone.

---

### G2. Agent Self-Awareness via Langfuse Query (~100 LOC)

**Current:** No agent queries its own performance. `shared/langfuse_client.py` exists and works.

**Change:** Create `shared/agent_perf.py` with `query_agent_performance(agent_name, days=7)` returning `{avg_latency_ms, avg_cost_usd, error_rate, runs}`. Agents call this at startup or periodically to adapt (model selection, skip expensive stages, flag degradation).

**Files:** New `shared/agent_perf.py`, then integrate into 2-3 high-value agents (briefing, profiler, scout).

**Dependency:** H1 must be deployed (agent spans need `agent.name` attribute in Langfuse). Requires architectural decision on adaptation policy (see research section).

---

### G3. RAG Failure Feedback Loop (~80 LOC)

**Current:** H2 traces `rag.result_count` and `rag.top_score`. Zero-result queries are invisible.

**Change:** Scheduled job queries Langfuse for `rag.result_count=0` spans in the last 24h. Groups by `rag.collection` and `rag.query` (truncated). Surfaces as knowledge gap nudges in cockpit.

**Files:** New `agents/rag_quality_monitor.py` or integrate into `knowledge_maint.py`. Add nudge source in `cockpit/data/nudges.py`.

**Dependency:** H2 deployed. Langfuse OTel ingestion must index span attributes for filtering.

---

### G4. Trace-to-Health Correlation (~120 LOC)

**Current:** Health watchdog checks infrastructure. Langfuse traces show downstream failures. No bridge.

**Change:** In the health fix pipeline's `gather_context()` phase, query Langfuse for recent error traces tagged to the failing service. If Ollama health check passes but `rag.error` spans are spiking, escalate.

**Files:** `shared/fix_capabilities/pipeline.py` (add trace query to probe phase), `shared/langfuse_client.py` (add filtered observation query helper).

**Dependency:** H2 deployed (rag.error attribute). Requires clear mapping from health check groups to Langfuse service tags.

---

### G5. Pseudo-Deliberation Escalation (~30 LOC)

**Current:** `deliberation_eval.py` detects pseudo-deliberation, stores in `deliberation-metrics.jsonl`. Briefing displays it. No action taken.

**Change:** When 3+ pseudo-deliberations detected in last 5 evaluations, create a precedent review nudge via `PrecedentStore.flag_for_review()` or a new nudge source.

**Files:** `agents/deliberation_eval.py` (add escalation check), `cockpit/data/nudges.py` (add deliberation nudge source).

**Dependency:** None.

---

### G6. Structured Log Anomaly Detection (future)

**Current:** H4 produces JSON logs in journald. Nobody reads them programmatically.

**Change:** Periodic job parses recent journal output, counts ERROR-level entries by agent, alerts on spikes. Lightweight alternative to Loki.

**Dependency:** H4 deployed. Needs design — could be a simple bash script or a proper agent.

---

### G7. Prometheus Alert Rules (future, after H3 operational)

**Current:** H3 deployed Prometheus + Grafana config but no alert rules.

**Change:** Add Alertmanager or Grafana alert rules for: GPU temp >85C, error rate >5%, disk >90%, Qdrant latency p99 >2s.

**Dependency:** H3 must be running and scraping successfully.

---

## Implementation Sequence

```
Immediate (no deps, <1 day each):
  G1  Cost trend in briefing
  G5  Pseudo-deliberation escalation

After H1/H2 deployed and traces visible in Langfuse:
  G3  RAG failure feedback
  G4  Trace-to-health correlation

After architectural research (G2 policy decisions):
  G2  Agent self-awareness

After H3 operational:
  G7  Prometheus alert rules

Future:
  G6  Log anomaly detection
```

---

## Open Questions (feed into architectural research)

1. **Adaptation policy:** When an agent reads its own performance, what should it actually change? Model? Temperature? Max turns? Skip stages? This is a governance question, not just a plumbing question.

2. **Feedback loop stability:** If agent A adapts based on traces, and that adaptation changes the traces, do we get oscillation? (e.g., agent switches to cheaper model → quality drops → error rate rises → agent switches back → repeat)

3. **Authority:** Can an agent unilaterally decide to change its own model/behavior, or does that require operator approval? The constitution's axiom framework may have something to say here.

4. **Observability of adaptation:** If agents start self-modifying based on telemetry, the telemetry itself needs to record _why_ the agent made that choice. Meta-observability.

5. **Scope of self-awareness:** Should each agent only see its own traces, or should agents see ecosystem-wide metrics? A briefing agent that knows "the profiler is running slow today" could adjust its own schedule.

# H1 Agent Execution Tracing Plan

**Date:** 2026-03-12
**Status:** Implementation-ready
**Scope:** hapax-council (26 agents) + hapax-officium (15 agents)
**Target:** Full Langfuse visibility for every agent execution

---

## 1. Agent Inventory

### hapax-council (26 agents)

| # | Agent | File | Entry Point(s) | Agent() Instances | Has `langfuse_config` | Has OTel Spans | @tool Decorators |
|---|-------|------|-----------------|-------------------|-----------------------|----------------|------------------|
| 1 | demo | `agents/demo.py` | `generate_demo()`, `main()` | `agent`, `content_agent`, `voice_agent` | Yes | Yes (14 spans) | No |
| 2 | briefing | `agents/briefing.py` | `generate_briefing()`, `main()` | `briefing_agent` | Yes | No | No |
| 3 | digest | `agents/digest.py` | `generate_digest()`, `main()` | `digest_agent` | Yes | No | No |
| 4 | scout | `agents/scout.py` | `run_scout()`, `main()` | `eval_agent` | Yes | No | No |
| 5 | profiler | `agents/profiler.py` | `run_extraction()`, `run_curate()`, `run_digest()`, `main()` | `extraction_agent`, `synthesis_agent`, `operator_agent`, `curator_agent`, `summary_agent` | Yes | No | No |
| 6 | research | `agents/research.py` | `main()` | `agent` | Yes | No | 2 (`@agent.tool`) |
| 7 | drift_detector | `agents/drift_detector.py` | `main()`, `generate_fixes()` | `drift_agent`, `fix_agent` | Yes | No | No |
| 8 | knowledge_maint | `agents/knowledge_maint.py` | `run_maintenance()`, `main()` | `agent` (dynamic) | Yes | No | No |
| 9 | code_review | `agents/code_review.py` | `main()` | `a` (dynamic) | Yes | No | No |
| 10 | activity_analyzer | `agents/activity_analyzer.py` | `generate_activity_report()`, `main()` | `agent` (dynamic) | Yes | No | No |
| 11 | ingest | `agents/ingest.py` | `ingest_file()`, `process_retries()` | None (embedding only) | No | No | No |
| 12 | introspect | `agents/introspect.py` | `generate_manifest()`, `main()` | None (shell commands) | No | No | No |
| 13 | health_monitor | `agents/health_monitor.py` | `run_checks()`, `run_fixes()`, `main()` | None (shell commands) | No | No | No |
| 14 | query | `agents/query.py` | `main()` | None (delegates to knowledge/) | No | No | No |
| 15 | sdlc_metrics | `agents/sdlc_metrics.py` | `generate_report()`, `main()` | None (API calls) | No | No | No |
| 16 | obsidian_sync | `agents/obsidian_sync.py` | `run_full_sync()`, `main()` | None (sync only) | No | No | No |
| 17 | chrome_sync | `agents/chrome_sync.py` | `run_full_sync()`, `main()` | None (sync only) | No | No | No |
| 18 | gmail_sync | `agents/gmail_sync.py` | `run_full_sync()`, `main()` | None (sync only) | No | No | No |
| 19 | gdrive_sync | `agents/gdrive_sync.py` | `run_full_scan()`, `main()` | None (sync only) | No | No | No |
| 20 | gcalendar_sync | `agents/gcalendar_sync.py` | `run_full_sync()`, `main()` | None (sync only) | No | No | No |
| 21 | youtube_sync | `agents/youtube_sync.py` | `run_full_sync()`, `main()` | None (sync only) | No | No | No |
| 22 | claude_code_sync | `agents/claude_code_sync.py` | `run_full_sync()`, `main()` | None (sync only) | No | No | No |
| 23 | deliberation_eval | `agents/deliberation_eval.py` | `main()` | None | No | No | No |
| 24 | demo_eval | `agents/demo_eval.py` | `run_eval_loop()`, `main()` | None (orchestrator) | No | No | No |
| 25 | watch_receiver | `agents/watch_receiver.py` | FastAPI `app` | None (HTTP server) | No | No | No |
| 26 | audio_processor | `agents/audio_processor.py` | `main()` | None (FFmpeg pipeline) | No | No | No |
| -- | hapax_voice | `agents/hapax_voice/` | `__main__.main()` | None (Gemini Live) | No (uses Langfuse SDK) | No | No |
| -- | knowledge/query | `agents/knowledge/query.py` | Dynamic `agent` | None | No | 8 (`@agent.tool`) |
| -- | system_ops/query | `agents/system_ops/query.py` | Dynamic `agent` | None | No | 6 (`@agent.tool`) |
| -- | dev_story | `agents/dev_story/` | `__main__.main()` | `agent` in `query.py` | No | 4 (`@agent.tool`) |
| -- | health_connect_parser | `agents/health_connect_parser.py` | `run_parse()`, `main()` | None (parser) | No | No | No |
| -- | profiler_sources | `agents/profiler_sources.py` | (helper module) | None | No | No | No |

### hapax-officium (15 agents)

| # | Agent | File | Entry Point(s) | Agent() Instances | Has `langfuse_config` | Has OTel Spans |
|---|-------|------|-----------------|-------------------|-----------------------|----------------|
| 1 | demo | `agents/demo.py` | `generate_demo()`, `main()` | `agent`, `content_agent`, `voice_agent` | Yes | Yes (mirrors council) |
| 2 | digest | `agents/digest.py` | `generate_digest()`, `main()` | `digest_agent` | Yes | No |
| 3 | scout | `agents/scout.py` | `run_scout()`, `main()` | `eval_agent` | Yes | No |
| 4 | drift_detector | `agents/drift_detector.py` | `main()`, `generate_fixes()` | `drift_agent`, `fix_agent` | Yes | No |
| 5 | knowledge_maint | `agents/knowledge_maint.py` | `run_maintenance()`, `main()` | `agent` (dynamic) | Yes | No |
| 6 | management_briefing | `agents/management_briefing.py` | `generate_briefing()`, `main()` | `management_briefing_agent` | Yes | No |
| 7 | management_prep | `agents/management_prep.py` | `generate_1on1_prep()`, `generate_team_snapshot()`, `generate_overview()`, `main()` | `prep_agent`, `snapshot_agent`, `overview_agent` | Yes | No |
| 8 | management_profiler | `agents/management_profiler.py` | `run_extraction()`, `run_curate()`, `run_digest()`, `main()` | `extraction_agent`, `synthesis_agent`, `curator_agent`, `summary_agent` | Yes | No |
| 9 | meeting_lifecycle | `agents/meeting_lifecycle.py` | `process_meeting()`, `process_transcript()`, `main()` | `extract_agent` | Yes | No |
| 10 | status_update | `agents/status_update.py` | `generate_status()`, `main()` | `_agent` | No | No |
| 11 | review_prep | `agents/review_prep.py` | `generate_review_evidence()`, `main()` | `_agent` | No | No |
| 12 | simulator | `agents/simulator.py` | `run_simulation()`, `main()` | None (orchestrator) | No | No |
| 13 | introspect | `agents/introspect.py` | `generate_manifest()`, `main()` | None (shell commands) | No | No |
| 14 | ingest | `agents/ingest.py` | `process_document()` | None (embedding only) | No | No |
| 15 | system_check | `agents/system_check.py` | `run_checks()`, `main()` | None (shell commands) | No | No |
| 16 | management_activity | `agents/management_activity.py` | `generate_management_report()`, `main()` | None (data aggregation) | No | No |
| 17 | demo_eval | `agents/demo_eval.py` | `run_eval_loop()`, `main()` | None (orchestrator) | No | No |

---

## 2. Reference Pattern Analysis

### Pattern A: OTel via `langfuse_config` (demo.py)

**How it works:**
1. `from shared import langfuse_config` runs as a side-effect import
2. `langfuse_config.py` creates an `OTLPSpanExporter` pointing at `LANGFUSE_HOST/api/public/otel/v1/traces` with Basic auth
3. Sets a global `TracerProvider` with `BatchSpanProcessor`
4. Auto-instruments `httpx` (covers all pydantic-ai LLM calls, Qdrant, Ollama)
5. Agent code uses `tracer = get_tracer(__name__)` and `with tracer.start_as_current_span("name", attributes={...})`

**Span hierarchy in demo.py (14 spans):**
```
demo.readiness
demo.sufficiency
demo.drift_check
demo.research
demo.content_plan    {scope, audience}
demo.voice_apply     {scenes}
demo.critique
demo.visuals         {count}
demo.slides          {format}
  demo.voice
  demo.video
  demo.audio_convert
demo.html_player
  demo.chapters
```

**Strengths:**
- Standard OTel API -- portable, vendor-neutral
- Automatic httpx instrumentation captures every LLM call without manual code
- Span hierarchy naturally emerges from `with` block nesting
- Zero Langfuse SDK dependency in agent code
- Langfuse ingests OTel traces natively via its OTLP endpoint

**Weaknesses:**
- Langfuse renders OTel spans as generic traces, not as "generations" with prompt/completion/token fields
- Token usage requires manual attribute extraction from httpx response headers
- No session_id grouping without baggage propagation setup

### Pattern B: Langfuse SDK (`VoiceTracer`)

**How it works:**
1. Direct `from langfuse import Langfuse` import
2. `VoiceTracer` class wraps `client.trace()` calls with fail-open NoOpSpan
3. Context managers for each trace type: `trace_analysis`, `trace_session`, `trace_delivery`
4. Metadata dict passed to each trace (presence_score, activity_mode, etc.)

**Strengths:**
- First-class Langfuse concepts: traces, generations, sessions
- `session_id` grouping works natively
- Can record `input`, `output`, `model`, `usage` fields that Langfuse renders richly
- Fail-open design is excellent

**Weaknesses:**
- Langfuse SDK is a hard dependency (though fail-open mitigates)
- No automatic httpx instrumentation -- every LLM call must be manually wrapped
- More boilerplate per agent (context manager per trace type)
- Vendor lock-in to Langfuse API surface

---

## 3. SDK Decision: OTel (Pattern A)

**Recommendation: Use OpenTelemetry (Pattern A) for all agents.**

**Rationale:**

1. **Already deployed.** 10 council agents and 9 officium agents already import `langfuse_config`. The infrastructure (TracerProvider, OTLP exporter, httpx auto-instrumentation) is production-proven.

2. **Zero per-LLM-call instrumentation.** The httpx auto-instrumentor captures every `agent.run()` call automatically. Adding manual `tracer.start_as_current_span()` only needed for pipeline stages, not individual LLM calls.

3. **Langfuse supports OTel natively.** Langfuse v3 ingests OTLP traces and renders them in its UI. The `/api/public/otel/v1/traces` endpoint is already configured.

4. **Portability.** If we ever move to Jaeger, Honeycomb, or Datadog, the OTel code needs zero changes -- only the exporter config changes.

5. **Consistency.** One pattern across 41+ agents is easier to maintain than two.

**Exception:** `hapax-voice` keeps its `VoiceTracer` Langfuse SDK pattern. It is a long-running daemon (not a batch agent), has unique session/presence semantics, and is already instrumented. Migrating it would add risk for no benefit.

**Token tracking enhancement (future):** To get rich token counts in Langfuse, add a custom `SpanProcessor` that extracts `usage` from pydantic-ai's `result.usage()` and sets span attributes. This is an additive change that does not affect the per-agent instrumentation pattern.

---

## 4. Standard Attribute Schema

All agent spans MUST use these semantic attributes:

```python
# Required on root span
"agent.name"             # str: agent module name (e.g., "briefing", "scout")
"agent.repo"             # str: "hapax-council" or "hapax-officium"
"agent.entry_point"      # str: function name (e.g., "generate_briefing")

# Required on LLM call spans (set by httpx auto-instrumentation, augmented manually)
"agent.model"            # str: model name from get_model() (e.g., "openai/gpt-4o")
"agent.prompt_tokens"    # int: input token count (from result.usage())
"agent.completion_tokens"# int: output token count
"agent.total_tokens"     # int: total

# Optional on pipeline stage spans
"agent.stage"            # str: pipeline stage name (e.g., "research", "critique")
"agent.scope"            # str: user-provided scope/topic
"agent.audience"         # str: resolved audience archetype (demo-specific)

# Optional on tool call spans
"agent.tool.name"        # str: tool function name
"agent.tool.result_size" # int: bytes of tool result

# Error spans
"agent.error"            # bool: true if span ended in error
"agent.error.type"       # str: exception class name
"agent.error.message"    # str: exception message (truncated to 500 chars)
```

---

## 5. Per-Agent Span Plan

### Tier 1: LLM-Calling Agents (highest value -- instrument first)

These agents call `Agent.run()` and benefit most from tracing.

#### Council Tier 1

| Agent | Spans to Add | Key Attributes | Est. LOC |
|-------|-------------|----------------|----------|
| briefing | `briefing.collect_data`, `briefing.generate` | agent.name, agent.model, hours | ~15 |
| digest | `digest.collect_data`, `digest.generate` | agent.name, agent.model, hours | ~15 |
| scout | `scout.discover`, `scout.evaluate`, `scout.report` | agent.name, source_count | ~20 |
| profiler | `profiler.extract`, `profiler.synthesize`, `profiler.curate`, `profiler.digest` | agent.name, fact_count | ~25 |
| research | `research.run` | agent.name, agent.model, tool_calls | ~10 |
| drift_detector | `drift.detect`, `drift.generate_fixes` | agent.name, drift_item_count, severity | ~15 |
| knowledge_maint | `knowledge.analyze`, `knowledge.maintain` | agent.name, collection, action_count | ~15 |
| code_review | `code_review.run` | agent.name, agent.model, file_count | ~10 |
| activity_analyzer | `activity.collect`, `activity.analyze` | agent.name, hours, event_count | ~15 |
| demo | Already instrumented (14 spans) | -- | 0 |

#### Officium Tier 1

| Agent | Spans to Add | Key Attributes | Est. LOC |
|-------|-------------|----------------|----------|
| management_briefing | `mgmt_briefing.collect`, `mgmt_briefing.generate` | agent.name, people_count | ~15 |
| management_prep | `mgmt_prep.1on1`, `mgmt_prep.snapshot`, `mgmt_prep.overview` | agent.name, person_name | ~20 |
| management_profiler | `mgmt_profiler.extract`, `mgmt_profiler.synthesize`, `mgmt_profiler.curate` | agent.name, fact_count | ~25 |
| meeting_lifecycle | `meeting.extract`, `meeting.process_transcript`, `meeting.weekly_review` | agent.name, meeting_count | ~20 |
| status_update | `status.collect`, `status.generate` | agent.name, days | ~15 |
| review_prep | `review.collect`, `review.generate` | agent.name, person_name | ~15 |
| digest | `digest.collect_data`, `digest.generate` | agent.name, hours | ~15 |
| scout | `scout.discover`, `scout.evaluate` | agent.name, source_count | ~15 |
| drift_detector | `drift.detect`, `drift.generate_fixes` | agent.name, drift_item_count | ~15 |
| knowledge_maint | `knowledge.analyze`, `knowledge.maintain` | agent.name, action_count | ~15 |
| demo | Already instrumented | -- | 0 |

### Tier 2: Data Pipeline Agents (medium value)

These do embedding/sync work. Trace for latency and error visibility.

| Agent | Repo | Spans to Add | Est. LOC |
|-------|------|-------------|----------|
| ingest | council | `ingest.process`, `ingest.embed` | ~10 |
| ingest | officium | `ingest.process`, `ingest.embed` | ~10 |
| *_sync (6 agents) | council | `{name}.sync` root span only | ~8 each |
| simulator | officium | `simulator.run`, `simulator.tick` | ~15 |

### Tier 3: Infrastructure Agents (low value, nice-to-have)

| Agent | Repo | Spans to Add | Est. LOC |
|-------|------|-------------|----------|
| health_monitor | council | `health.check`, `health.fix` | ~10 |
| introspect | both | `introspect.scan` | ~8 |
| system_check | officium | `system_check.run` | ~8 |
| watch_receiver | council | FastAPI auto-instrumentation via `opentelemetry-instrumentation-fastapi` | ~5 |

### Not Instrumented (helper modules, no entry points)

- `demo_models.py` (both) -- Pydantic models only
- `profiler_sources.py` (council) -- data collection helper
- `demo_pipeline/*.py` (both) -- called within demo.py spans already
- `knowledge/__init__.py`, `system_ops/__init__.py` -- package init
- `health_connect_parser.py` -- offline parser, no LLM

---

## 6. Implementation Template

For each agent, the instrumentation follows this pattern:

```python
# At top of file, after other imports:
from opentelemetry.trace import get_tracer

try:
    from shared import langfuse_config  # noqa: F401
except ImportError:
    pass

tracer = get_tracer(__name__)

# Wrap entry point:
async def generate_briefing(hours: int = 24) -> Briefing:
    with tracer.start_as_current_span(
        "briefing.generate",
        attributes={"agent.name": "briefing", "agent.repo": "hapax-council", "hours": hours},
    ):
        # ... existing code ...
        result = await briefing_agent.run(prompt)  # httpx auto-instrumented
        # Optionally capture token usage:
        span = trace.get_current_span()
        if hasattr(result, 'usage'):
            u = result.usage()
            span.set_attribute("agent.prompt_tokens", u.request_tokens or 0)
            span.set_attribute("agent.completion_tokens", u.response_tokens or 0)
        return result.output
```

**For agents that already import `langfuse_config` but lack spans:** Add `tracer = get_tracer(__name__)` and wrap entry points. ~10-15 LOC each.

**For agents missing `langfuse_config`:** Add the 4-line import block + tracer + spans. ~15-20 LOC each.

---

## 7. Implementation Order

Ordered by daily execution frequency and diagnostic value.

### Phase 1: Council Core (week 1)
1. **briefing** -- runs daily, most visible agent
2. **digest** -- runs daily alongside briefing
3. **scout** -- runs on cron, frequent failures worth tracing
4. **activity_analyzer** -- feeds briefing, useful to trace latency
5. **knowledge_maint** -- runs on cron, Qdrant operations

### Phase 2: Officium Core (week 1-2)
6. **management_briefing** -- daily management agent
7. **management_prep** -- pre-1:1 prep, high value
8. **status_update** -- weekly status, add `langfuse_config` import
9. **review_prep** -- periodic, add `langfuse_config` import
10. **meeting_lifecycle** -- transcript processing pipeline

### Phase 3: Profilers + Drift (week 2)
11. **profiler** (council) -- complex multi-agent pipeline, 5 Agent instances
12. **management_profiler** (officium) -- mirrors council profiler
13. **drift_detector** (both) -- 2 Agent instances each
14. **research** (council) -- tool-calling agent, interesting trace shape
15. **code_review** (council) -- ad-hoc but valuable

### Phase 4: Data Pipeline + Infra (week 3)
16. **ingest** (both) -- embedding pipeline latency
17. **sync agents** (council, 6 agents) -- root span only for cron visibility
18. **simulator** (officium) -- complex pipeline
19. **health_monitor** / **introspect** / **system_check** -- infrastructure visibility

### Phase 5: Cleanup
20. Verify all agents appear in Langfuse traces
21. Add `SpanProcessor` for pydantic-ai token extraction (cross-cutting)
22. Add `session_id` via OTel baggage for multi-agent workflows (briefing -> digest chain)

---

## 8. Missing `langfuse_config` Imports

These agents need the import block added before any spans will export:

### Council (missing import)
- `ingest.py`
- `introspect.py`
- `health_monitor.py`
- `query.py`
- `sdlc_metrics.py`
- `obsidian_sync.py`
- `chrome_sync.py`
- `gmail_sync.py`
- `gdrive_sync.py`
- `gcalendar_sync.py`
- `youtube_sync.py`
- `claude_code_sync.py`
- `deliberation_eval.py`
- `demo_eval.py`
- `watch_receiver.py`
- `audio_processor.py`
- `health_connect_parser.py`

### Officium (missing import)
- `status_update.py`
- `review_prep.py`
- `simulator.py`
- `introspect.py`
- `ingest.py`
- `system_check.py`
- `management_activity.py`
- `demo_eval.py`

---

## 9. Verification Checklist

For each instrumented agent:

- [ ] `from shared import langfuse_config` present (try/except ImportError)
- [ ] `tracer = get_tracer(__name__)` at module level
- [ ] Root span wraps main entry point with `agent.name` and `agent.repo` attributes
- [ ] Pipeline stages wrapped in child spans (if applicable)
- [ ] No span created for agents with zero LLM calls (sync agents get root span only)
- [ ] Agent still works when `LANGFUSE_PUBLIC_KEY` is unset (fail-open)
- [ ] Traces visible in Langfuse UI at `http://localhost:3000`
- [ ] Span names follow `{agent_name}.{stage}` convention
- [ ] No sensitive data in span attributes (no prompts, no PII)
- [ ] Token usage attributes set where `result.usage()` is available

### Integration tests:

- [ ] Run each agent with `LANGFUSE_PUBLIC_KEY` set -- verify trace appears in Langfuse
- [ ] Run each agent with `LANGFUSE_PUBLIC_KEY` unset -- verify no crash, no error logs
- [ ] Run `demo.py` end-to-end -- verify 14 spans appear with correct hierarchy
- [ ] Check httpx auto-instrumentation captures LLM call spans under agent spans
- [ ] Verify `service.name` shows `hapax-council` or `hapax-officium` correctly

### Total estimated LOC:

| Category | Agents | LOC per agent | Total LOC |
|----------|--------|---------------|-----------|
| Tier 1 council (9 agents, excl. demo) | 9 | ~15 | ~135 |
| Tier 1 officium (10 agents, excl. demo) | 10 | ~17 | ~170 |
| Tier 2 data pipeline | 9 | ~10 | ~90 |
| Tier 3 infrastructure | 5 | ~8 | ~40 |
| **Total** | **33** | -- | **~435** |

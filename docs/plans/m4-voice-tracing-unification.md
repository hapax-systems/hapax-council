# M4: Voice Tracing Unification — Langfuse SDK to OTel

**Date:** 2026-03-12
**Status:** GO (migrate to OTel)
**Scope:** Replace `VoiceTracer` (Langfuse Python SDK) with standard OTel spans routed through `shared/langfuse_config.py`, aligning hapax-voice with the pattern used by all other council agents.

---

## 1. VoiceTracer API Inventory

Source: `agents/hapax_voice/tracing.py`

| Method | Type | Purpose | Langfuse SDK calls |
|--------|------|---------|-------------------|
| `__init__(enabled)` | constructor | Lazy-init with fail-open semantics | None (deferred) |
| `_get_client()` | private | Lazy-create `Langfuse()` client from env vars | `Langfuse(public_key, secret_key, host)` |
| `trace_analysis(...)` | context manager | Wraps workspace analysis cycle | `client.trace(name, session_id, tags, metadata)`, `trace.update(status_message)` |
| `trace_session(...)` | context manager | Wraps voice session lifecycle | `client.trace(name, session_id, tags, metadata)` |
| `trace_delivery(...)` | context manager | Wraps proactive notification delivery | `client.trace(name, session_id, tags, metadata)` |
| `flush(timeout_s)` | method | Flush pending traces with timeout guard | `client.flush()` |
| `NoOpSpan` | dataclass | Stub returned when tracing disabled | N/A |

### Langfuse SDK features used

1. **`client.trace()`** — creates a top-level trace (not a span). Maps metadata, session_id, and tags.
2. **`trace.update(status_message=)`** — sets completion status on trace_analysis only.
3. **`client.flush()`** — synchronous flush with thread-based timeout wrapper.
4. **Session grouping** — `session_id` parameter groups traces into Langfuse sessions.
5. **Tags** — `["hapax-voice"]` tag on every trace.
6. **Metadata dict** — arbitrary key-value metadata (presence_score, images_sent, etc.).

### Langfuse SDK features NOT used

- **Scores** (quality ratings) — not called anywhere
- **Generations** (LLM call tracking) — not used; the actual LLM call happens inside `ScreenAnalyzer` which is not instrumented by VoiceTracer
- **Span nesting** — the yielded trace object supports `.span()` but no caller creates child spans
- **Prompt management** — not used
- **Datasets / evaluations** — not used

## 2. Usage Analysis

### Production usage (agents/hapax_voice/)

| Call site | File | Method | Status |
|-----------|------|--------|--------|
| Instantiation | `__main__.py:223` | `VoiceTracer(enabled=cfg.observability_langfuse_enabled)` | Active |
| Injected into monitor | `__main__.py:230` | `workspace_monitor.set_tracer(self.tracer)` | Active |
| Workspace analysis | `workspace_monitor.py:228` | `self._tracer.trace_analysis(...)` | **Only production call site** |
| Shutdown flush | `__main__.py:988` | `self.tracer.flush()` | Active |

### Key finding

**Only `trace_analysis` is used in production.** The `trace_session` and `trace_delivery` methods were built speculatively and are exercised only in unit tests. This dramatically simplifies the migration.

### Test coverage

| Test file | What it tests |
|-----------|--------------|
| `test_tracing.py` | All three context managers with disabled tracer (no-op path) |
| `test_tracing_flush_timeout.py` | Flush timeout behavior |
| `test_tracing_robustness.py` | Error handling, all context managers under failure |

## 3. Feature Gap Analysis: OTel vs Langfuse SDK

| Feature | Langfuse SDK | OTel equivalent | Gap? |
|---------|-------------|-----------------|------|
| Trace creation | `client.trace(name=...)` | `tracer.start_as_current_span(name)` | No gap |
| Metadata dict | `metadata={...}` | `span.set_attribute(key, value)` per key | No gap — flattened keys |
| Tags | `tags=["hapax-voice"]` | `span.set_attribute("tags", "hapax-voice")` | Langfuse OTel ingestion maps `tags` attribute |
| Session ID | `session_id="..."` | `span.set_attribute("langfuse.session.id", session_id)` | No gap — Langfuse OTel supports this attribute |
| Status message | `trace.update(status_message=)` | `span.set_status(StatusCode.OK)` + `span.set_attribute("status_message", ...)` | No gap |
| Flush | `client.flush()` | `provider.force_flush(timeout_millis=)` | No gap — OTel SDK has built-in timeout |
| Fail-open | Manual try/except + NoOpSpan | OTel NoOpTracer (returned when no provider configured) | No gap — OTel is fail-open by design |
| Child spans | `trace.span(name=...)` | Automatic via context propagation | Better in OTel — implicit parent-child |

### What improves with OTel

1. **Unified pipeline.** All agents (demo, voice, future agents) use the same TracerProvider, exporter, and flush path. One config module, one dependency.
2. **Automatic context propagation.** If `ScreenAnalyzer` or any downstream code is OTel-instrumented (e.g., via HTTPX auto-instrumentation from `langfuse_config.py`), LLM calls to LiteLLM will automatically become child spans of the workspace_analysis span.
3. **No direct Langfuse SDK dependency.** Removes `langfuse` from hapax-voice's import chain. The `opentelemetry` SDK is already a dependency via `langfuse_config.py`.
4. **Standard tooling.** Any OTel-compatible backend (Jaeger, Grafana Tempo, Datadog) can ingest these traces without code changes.

### What changes semantically

1. **Langfuse "traces" become OTel root spans.** Langfuse's OTel ingestion treats root spans as traces automatically. No behavioral difference in the Langfuse UI.
2. **Metadata becomes span attributes.** Instead of a nested `metadata` dict, each key becomes a top-level span attribute (`presence_score`, `images_sent`, etc.). Langfuse displays these in the span detail view.
3. **Session grouping** requires the `langfuse.session.id` span attribute convention. Langfuse documents this for OTel ingestion.

## 4. Migration Feasibility Assessment

**Verdict: Full migration is feasible with zero observability loss.**

- The only Langfuse SDK features used (trace, metadata, tags, session_id, flush) all have direct OTel equivalents that Langfuse's OTel ingestion endpoint understands.
- No scores, generations, or prompt management features are used — these would be the hard-to-replace features.
- The single production call site (`workspace_monitor.py`) makes this a low-risk change.
- The existing `shared/langfuse_config.py` already configures the TracerProvider, OTLP exporter, and HTTPX auto-instrumentation. Voice just needs to use it.

## 5. Step-by-Step Migration Plan

### Step 1: Import OTel tracer in workspace_monitor.py

Replace the VoiceTracer injection with standard OTel tracer acquisition:

```python
# workspace_monitor.py — top of file
from opentelemetry.trace import get_tracer

tracer = get_tracer("hapax_voice.workspace_monitor")
```

Remove `set_tracer()` method and `self._tracer` attribute.

### Step 2: Replace trace_analysis usage

Before:
```python
trace_cm = (
    self._tracer.trace_analysis(
        presence_score=self._presence.score if self._presence else "unknown",
        images_sent=images_sent,
        session_id=self._event_log._session_id if self._event_log else None,
        activity_mode="unknown",
    )
    if self._tracer is not None
    else contextlib.nullcontext(None)
)
with trace_cm:
    analysis = await self._analyzer.analyze(...)
```

After:
```python
with tracer.start_as_current_span(
    "workspace_analysis",
    attributes={
        "source_service": "hapax-voice",
        "presence_score": self._presence.score if self._presence else "unknown",
        "images_sent": images_sent,
        "activity_mode": "unknown",
        "langfuse.session.id": self._event_log._session_id if self._event_log else None,
        "langfuse.tags": "hapax-voice",
    },
):
    analysis = await self._analyzer.analyze(...)
```

No conditional check needed — OTel's `get_tracer()` returns a NoOpTracer when no provider is configured. The `contextlib.nullcontext` guard becomes unnecessary.

### Step 3: Bootstrap OTel in __main__.py

Add the langfuse_config import at module level (same pattern as demo.py):

```python
# __main__.py — near top, after other imports
try:
    from shared import langfuse_config  # noqa: F401
except ImportError:
    pass
```

### Step 4: Remove VoiceTracer instantiation and wiring

In `__main__.py`:
- Remove `from agents.hapax_voice.tracing import VoiceTracer`
- Remove `self.tracer = VoiceTracer(enabled=...)`
- Remove `self.workspace_monitor.set_tracer(self.tracer)`
- Replace `self.tracer.flush()` in shutdown with:

```python
from opentelemetry.trace import get_tracer_provider
provider = get_tracer_provider()
if hasattr(provider, "force_flush"):
    provider.force_flush(timeout_millis=5000)
```

### Step 5: Preserve trace_session and trace_delivery as OTel helpers (optional)

Since these are unused in production, two options:

**Option A (recommended): Delete them.** They are speculative code with no callers. When session/delivery tracing is needed, create OTel spans directly at the call site, following the demo.py pattern.

**Option B: Convert to thin OTel wrappers.** If we want to pre-build the API:

```python
# Anywhere session tracing is needed in the future:
with tracer.start_as_current_span(
    "voice_session",
    attributes={
        "source_service": "hapax-voice",
        "trigger": trigger,
        "langfuse.session.id": session_id,
        "langfuse.tags": "hapax-voice",
    },
):
    ...
```

### Step 6: Update or delete tracing.py

- If Option A: delete `agents/hapax_voice/tracing.py` entirely.
- If Option B: gut the file and replace with a thin module exporting `tracer = get_tracer("hapax_voice")` for shared use across voice submodules.

### Step 7: Update tests

- `test_tracing.py`, `test_tracing_flush_timeout.py`, `test_tracing_robustness.py` — rewrite to test OTel span creation using `opentelemetry.sdk.trace.export.in_memory` (InMemorySpanExporter).
- `test_daemon_screen_integration.py` — remove VoiceTracer mock setup.
- `test_primitives.py` — remove VoiceTracer references if any.

### Step 8: Update config flag

The config flag `observability_langfuse_enabled` controlled VoiceTracer instantiation. Two options:
- **Keep it** but repurpose: when false, skip the `langfuse_config` import (no TracerProvider configured, OTel becomes no-op automatically).
- **Remove it**: if the flag is voice-specific and other agents don't have an equivalent toggle, remove it. OTel is inherently no-op without credentials.

Recommended: remove it. The env vars `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` already gate tracing in `langfuse_config.py`. A separate config flag is redundant.

## 6. Dependency on H1

There is no existing H1 milestone plan. The reference here is to the **first milestone of hapax-officium's tracing setup**, if it exists or is created.

**Dependency relationship:** hapax-officium should use the same tracing pattern (OTel via `langfuse_config.py` or equivalent) so that both projects share one SDK choice. Since M3 established that the two services are fully isolated with separate Langfuse instances, the dependency is **pattern alignment only** — not shared infrastructure.

If hapax-officium were to adopt the Langfuse Python SDK directly (instead of OTel), that would create an inconsistency: council uses OTel, officium uses Langfuse SDK. This is technically fine (both end up in Langfuse) but adds cognitive overhead and prevents sharing instrumentation utilities.

**Recommendation:** Complete M4 first. It establishes OTel as the standard. When officium's tracing is set up, copy the `langfuse_config.py` pattern rather than introducing the Langfuse SDK.

## 7. Verification Checklist

### Pre-migration

- [ ] Confirm `shared/langfuse_config.py` is importable from hapax-voice's runtime (Python path includes `shared/`)
- [ ] Confirm `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` are set in the voice daemon's environment (systemd unit or .env)
- [ ] Verify Langfuse OTel ingestion endpoint accepts spans at `{LANGFUSE_HOST}/api/public/otel/v1/traces`

### Post-migration

- [ ] `workspace_analysis` spans appear in Langfuse with correct attributes (presence_score, images_sent, activity_mode)
- [ ] Session grouping works — spans with `langfuse.session.id` appear grouped in Langfuse session view
- [ ] Tags appear — `langfuse.tags` attribute renders as a tag in Langfuse UI
- [ ] HTTPX auto-instrumentation creates child spans for LiteLLM calls within workspace_analysis spans
- [ ] No `langfuse` Python package import in any hapax-voice module (grep confirms removal)
- [ ] `langfuse` can be removed from hapax-voice's dependency list (pyproject.toml / requirements)
- [ ] All existing tests pass (rewritten for OTel)
- [ ] Daemon starts and runs without tracing errors when Langfuse credentials are absent (no-op path)
- [ ] Daemon shutdown completes flush within 5s timeout
- [ ] No regression in workspace_monitor analysis latency (tracing overhead is negligible but verify)

### Rollback

If Langfuse OTel ingestion has bugs or missing features:
1. Revert the commit (single commit migration recommended)
2. Re-add `langfuse` to dependencies
3. Restore `tracing.py` from git history

Risk is low: Langfuse's OTel ingestion is their recommended path and is used by all other council agents already.

## 8. Estimated Effort

| Task | Effort |
|------|--------|
| Code changes (steps 1-6) | 30 min |
| Test rewrites (step 7) | 45 min |
| Manual verification against Langfuse UI | 15 min |
| **Total** | **~1.5 hours** |

Single-commit migration. No phased rollout needed — the change is internal to one module with one production call site.

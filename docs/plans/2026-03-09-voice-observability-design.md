# Voice Observability Design

**Goal:** Add meaningful observability to hapax-voice audio-vision layers via structured event logging and Langfuse trace integration.

**Decision:** Approach A (structured JSONL event log) + Approach B (Langfuse SDK trace integration). No Prometheus, no dashboards — JSONL + Langfuse is sufficient for debugging and improvement assessment.

---

## Part A: Structured Event Log

New module `agents/hapax_voice/event_log.py`. Appends JSON-lines to `~/.local/share/hapax-voice/events-YYYY-MM-DD.jsonl`. Daily rotation with configurable retention (default 14 days).

### Event Schema

Every event includes:

| Field | Type | Description |
|-------|------|-------------|
| `ts` | float | Unix timestamp |
| `type` | string | Event type identifier |
| `session_id` | string \| null | Current voice session ID, null if no active session |
| `source_service` | string | Always `"hapax-voice"` |

Plus type-specific fields.

### Event Types

| Type | Emitted from | Key fields |
|------|-------------|------------|
| `presence_transition` | PresenceDetector | from, to, vad_count, face_detected |
| `face_result` | WorkspaceMonitor | detected, count, confidence, latency_ms |
| `gate_decision` | ContextGate | eligible, reason, activity_mode, volume |
| `analysis_complete` | WorkspaceMonitor | app, operator_present, gear_count, latency_ms, images_sent |
| `analysis_failed` | WorkspaceMonitor | error, latency_ms |
| `notification_lifecycle` | NotificationQueue | action (queued/delivered/expired/dropped), title, priority |
| `session_lifecycle` | SessionManager | action (opened/closed), trigger, duration_s |
| `model_loaded` | Any lazy loader | model_name, latency_ms |
| `subprocess_failed` | ContextGate, capturers | command, exit_code, stderr_snippet |

### API Surface

```python
class EventLog:
    def __init__(self, base_dir: Path, retention_days: int = 14): ...
    def emit(self, event_type: str, **fields) -> None: ...
```

Single instance created in `VoiceDaemon.__init__()`, passed to subsystems via setter methods. Writes are synchronous (append + flush) — negligible cost at <100 events/minute.

---

## Part B: Langfuse Trace Integration

New module `agents/hapax_voice/tracing.py`. Uses `langfuse` Python SDK to create traces with spans. LiteLLM auto-detects active Langfuse trace context and attaches API calls as child spans.

### Traces

| Trace | Spans | Metadata |
|-------|-------|----------|
| `workspace_analysis` | capture_screen, capture_webcams, call_vision, parse_result | session_active, presence_score, images_sent, activity_mode |
| `voice_session` | Opened as trace, updated on close | trigger, duration_s, notifications_delivered |
| `proactive_delivery` | gate_check, tts_synthesize | presence_score, gate_reason, notification_priority |

### Langfuse Metadata

Every trace includes:
- `session_id` as Langfuse session ID (links traces within same voice session)
- `metadata.source_service: "hapax-voice"` for filtering
- `tags: ["hapax-voice"]` for Langfuse UI filtering

### API Surface

```python
class VoiceTracer:
    def __init__(self, enabled: bool = True): ...
    def trace_analysis(self, ...) -> context manager
    def trace_session(self, ...) -> context manager
    def trace_delivery(self, ...) -> context manager
```

Fail-open: if Langfuse unreachable or credentials missing, all methods become no-ops.

---

## Part C: Integration Points

### Subsystem Wiring

Subsystems receive EventLog and VoiceTracer via setter methods (same pattern as `set_notification_queue`). No constructor signature changes.

**EventLog consumers:**
- PresenceDetector — `presence_transition`
- ContextGate — `gate_decision`, `subprocess_failed`
- WorkspaceMonitor — `face_result`, `analysis_complete`/`analysis_failed`, `model_loaded`
- NotificationQueue — `notification_lifecycle`
- SessionManager — `session_lifecycle`

**VoiceTracer consumers:**
- WorkspaceMonitor — wraps analysis calls
- VoiceDaemon — wraps session and proactive delivery

### Config Additions

```python
observability_events_enabled: bool = True
observability_langfuse_enabled: bool = True
observability_events_retention_days: int = 14
```

### Out of Scope

- Audio pipeline (Pipecat internals) observability
- Wake word, TTS, Gemini Live event emission — add later once event log is proven
- Prometheus metrics / dashboards / alerting
- Self-improvement loop ingestion (follow-on below)

---

## Follow-On: Self-Improvement Loop Integration

**Not in scope for this implementation**, but the schema is designed for it.

A future timer-based agent reads daily JSONL, computes aggregates (gate block distribution, analysis success rate, presence accuracy, face detection confidence distribution), and writes a summary document to Qdrant `documents` collection with `source_service: "hapax-voice"` metadata. This makes observability data visible to briefing, digest, and profiler agents.

The `session_id` field in both JSONL events and Langfuse traces enables correlation across the two systems.

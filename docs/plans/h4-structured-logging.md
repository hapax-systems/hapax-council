# H4: Structured Logging for hapax-council and hapax-officium

**Status:** Draft
**Date:** 2026-03-12
**Scope:** Replace unstructured `logging.basicConfig` text logs with JSON structured logs correlated to Langfuse traces via OTel context.

---

## 1. Current State Audit

### hapax-council

| Category | Files | Occurrences |
|----------|-------|-------------|
| `logging.getLogger` calls | 130 | 130 |
| `log.info/warning/error/debug/...` calls | 141 | 922 |
| `print()` statements | 51 | 480 |
| `logging.basicConfig` call sites | 23 | 23 |
| **Total log/print surface** | **166** | **~1,402** |

### hapax-officium

| Category | Files | Occurrences |
|----------|-------|-------------|
| `logging.getLogger` calls | 64 | 64 |
| `log.info/warning/error/debug/...` calls | 51 | 296 |
| `print()` statements | 25 | 154 |
| `logging.basicConfig` call sites | 8 | 8 |
| **Total log/print surface** | **64** | **~450** |

### Combined totals

- **230 files** with logging or print statements
- **~1,850 log/print call sites**
- **31 `basicConfig` call sites** (the primary modification targets)
- **0 existing structured logging** -- neither repo uses `structlog`, `python-json-logger`, or any JSON formatter

### Existing trace infrastructure

- Both repos have `shared/langfuse_config.py` which creates an OTel `TracerProvider` with OTLP export to Langfuse
- Both repos depend on `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`, and `opentelemetry-instrumentation-httpx`
- hapax-voice has `event_log.py` -- a bespoke JSONL event writer that already injects `trace_id`/`span_id` from OTel context (the exact pattern we want to generalize to all logging)
- hapax-voice has `tracing.py` -- a `VoiceTracer` class using the Langfuse SDK directly (separate from OTel)
- All agents use `logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s")` or similar -- no centralized log setup

---

## 2. Library Decision: stdlib `logging` + `python-json-logger`

### Why not `structlog`?

- **Migration cost:** `structlog` replaces the logger API itself (`structlog.get_logger()` returns a bound logger with different semantics). Migrating 230 files to a new API is a big-bang rewrite.
- **stdlib interop:** Both repos use `logging.getLogger(__name__)` everywhere. `structlog` can wrap stdlib, but the dual-mode configuration is fragile and confusing.
- **Learning curve:** Contributors need to learn structlog's processor pipeline, bound loggers, and context vars.

### Why `python-json-logger`?

- **Zero API changes:** Every `log.info("message", extra={...})` call works as-is. Only the formatter changes.
- **Single point of change:** Replace `logging.basicConfig(format=...)` with a JSON formatter -- no per-file modifications needed for basic JSON output.
- **OTel integration:** `opentelemetry-instrumentation-logging` automatically injects `otelTraceID`, `otelSpanID`, `otelServiceName` into every `LogRecord`. `python-json-logger` picks these up as top-level fields.
- **Mature:** 5k+ GitHub stars, well-maintained, no transitive dependencies.
- **Reversible:** If we later want `structlog`, the JSON formatter is easy to swap out since no application code changed.

### New dependency

```
python-json-logger>=3.3.0
opentelemetry-instrumentation-logging>=0.50b0
```

---

## 3. Log Schema

Every log line will be a single JSON object on stdout:

```json
{
  "timestamp": "2026-03-12T14:23:01.456Z",
  "level": "INFO",
  "message": "Ingested 42 documents from rag-sources",
  "logger": "rag-ingest",
  "module": "ingest",
  "funcName": "process_batch",
  "lineno": 127,
  "trace_id": "0af7651916cd43dd8448eb211c80319c",
  "span_id": "b7ad6b7169203331",
  "service": "hapax-council",
  "agent": "ingest"
}
```

### Field definitions

| Field | Source | Notes |
|-------|--------|-------|
| `timestamp` | `%(asctime)s` | ISO 8601 with milliseconds, UTC |
| `level` | `%(levelname)s` | Standard Python levels |
| `message` | `%(message)s` | The formatted log message |
| `logger` | `%(name)s` | Logger name (e.g. `shared.config`, `rag-ingest`) |
| `module` | `%(module)s` | Python module name |
| `funcName` | `%(funcName)s` | Function that emitted the log |
| `lineno` | `%(lineno)d` | Line number |
| `trace_id` | OTel injection | 32-char hex, from `otelTraceID` LogRecord attr |
| `span_id` | OTel injection | 16-char hex, from `otelSpanID` LogRecord attr |
| `service` | Config constant | `hapax-council` or `hapax-officium` |
| `agent` | Env var / init | Agent name (e.g. `ingest`, `scout`, `hapax-voice`) |

When no OTel span is active, `trace_id` and `span_id` will be absent (not empty strings or zeros).

---

## 4. Trace ID Injection Approach

### Mechanism: `opentelemetry-instrumentation-logging`

This OTel instrumentation patches `logging.Logger.makeRecord()` to inject trace context into every `LogRecord`:

```python
from opentelemetry.instrumentation.logging import LoggingInstrumentor
LoggingInstrumentor().instrument(set_logging_format=False)
```

After instrumentation, every `LogRecord` gains three attributes:
- `otelTraceID` -- 32-char hex trace ID (or `"0"` if no span)
- `otelSpanID` -- 16-char hex span ID (or `"0"` if no span)
- `otelServiceName` -- from the OTel Resource

The JSON formatter picks these up and renames them to `trace_id`, `span_id`, `service`.

### Integration with existing OTel setup

`shared/langfuse_config.py` already creates a `TracerProvider` and sets it globally. The logging instrumentor reads from that same provider, so trace IDs in logs will match trace IDs in Langfuse. No additional OTel configuration needed.

### Correlation flow

```
Agent code                    OTel SDK              Langfuse
    |                            |                     |
    |-- log.info("...")          |                     |
    |   LogRecord gets           |                     |
    |   otelTraceID injected  <--|                     |
    |   JSON formatter emits     |                     |
    |   {"trace_id": "abc..."}   |                     |
    |                            |                     |
    |-- httpx.post(litellm)      |                     |
    |                            |-- span exported --> |
    |                            |   trace_id="abc..." |
```

The same `trace_id` appears in both the JSON log line and the Langfuse trace, enabling cross-referencing.

---

## 5. Output Target: stdout

All structured logs go to **stdout** (not files). Rationale:

- Agents run as **systemd user units** -- `journald` captures stdout automatically
- `journald` provides its own rotation, compression, and querying (`journalctl -u agent --output json`)
- When agents run in **Docker** (future), `docker logs` / log drivers capture stdout natively
- No file rotation logic needed in Python
- Consistent with 12-factor app conventions

For local development, pipe through `jq` for readability:
```bash
python -m agents.ingest 2>&1 | jq .
```

---

## 6. Implementation: Centralized Log Setup Module

### New file: `shared/log_setup.py`

```python
"""shared/log_setup.py -- Centralized structured JSON logging.

Call once at process startup, before any logger is used:
    from shared.log_setup import configure_logging
    configure_logging(agent="ingest")
"""

import logging
import os
import sys

SERVICE_NAME = os.environ.get("HAPAX_SERVICE", "hapax-council")


def configure_logging(
    *,
    agent: str = "unknown",
    level: str | None = None,
    human_readable: bool | None = None,
) -> None:
    """Configure root logger with JSON formatter and OTel trace injection.

    Args:
        agent: Agent name for the 'agent' field in every log line.
        level: Log level override. Defaults to LOG_LEVEL env var or INFO.
        human_readable: If True, use human-readable format instead of JSON.
            Defaults to HAPAX_LOG_HUMAN env var or False.
    """
    from pythonjsonlogger.json import JsonFormatter

    if level is None:
        level = os.environ.get("LOG_LEVEL", "INFO")
    if human_readable is None:
        human_readable = os.environ.get("HAPAX_LOG_HUMAN", "").lower() in ("1", "true", "yes")

    # Instrument stdlib logging to inject OTel trace context
    try:
        from opentelemetry.instrumentation.logging import LoggingInstrumentor
        LoggingInstrumentor().instrument(set_logging_format=False)
    except Exception:
        pass  # OTel not available -- degrade gracefully

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove any existing handlers (from prior basicConfig calls)
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)

    if human_readable:
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
    else:
        formatter = JsonFormatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(module)s %(funcName)s %(lineno)d %(message)s",
            rename_fields={
                "asctime": "timestamp",
                "levelname": "level",
                "name": "logger",
            },
            datefmt="%Y-%m-%dT%H:%M:%S.%fZ",
            static_fields={
                "service": SERVICE_NAME,
                "agent": agent,
            },
        )
        # Post-process: rename OTel fields and suppress zero trace IDs
        class _OTelRenameFormatter(JsonFormatter):
            def add_fields(self, log_record, record, message_dict):
                super().add_fields(log_record, record, message_dict)
                # Rename OTel-injected fields
                otel_trace = log_record.pop("otelTraceID", None)
                otel_span = log_record.pop("otelSpanID", None)
                otel_svc = log_record.pop("otelServiceName", None)
                if otel_trace and otel_trace != "0":
                    log_record["trace_id"] = otel_trace
                if otel_span and otel_span != "0":
                    log_record["span_id"] = otel_span

        formatter = _OTelRenameFormatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(module)s %(funcName)s %(lineno)d %(message)s",
            rename_fields={
                "asctime": "timestamp",
                "levelname": "level",
                "name": "logger",
            },
            datefmt="%Y-%m-%dT%H:%M:%S.%fZ",
            static_fields={
                "service": SERVICE_NAME,
                "agent": agent,
            },
        )
        handler.setFormatter(formatter)

    root.addHandler(handler)

    # Quiet noisy libraries
    for lib in ("httpx", "httpcore", "urllib3", "watchdog", "filelock"):
        logging.getLogger(lib).setLevel(logging.WARNING)
```

This module must be identical in both repos (or extracted to a shared package eventually).

---

## 7. Migration Strategy: Incremental (3 phases)

### Phase 1: Foundation (shared/, cockpit/) -- ~2 days per repo

**Goal:** Add `shared/log_setup.py`, wire it into the cockpit API entrypoint, and add deps.

Files to modify per repo:

| File | Change |
|------|--------|
| `pyproject.toml` | Add `python-json-logger>=3.3.0`, `opentelemetry-instrumentation-logging>=0.50b0` |
| `shared/log_setup.py` | **New file** -- centralized log configuration (see above) |
| `cockpit/api/__main__.py` | Replace `logging.basicConfig(...)` with `from shared.log_setup import configure_logging; configure_logging(agent="cockpit")` |

Verification: run cockpit API, confirm JSON output on stdout, confirm `trace_id` appears when OTel span is active.

### Phase 2: Agent entrypoints -- ~3 days per repo

**Goal:** Replace every `logging.basicConfig(...)` call in agent `__main__` / `if __name__ == "__main__"` blocks.

**hapax-council** (23 basicConfig sites):

| File | Current | Change |
|------|---------|--------|
| `agents/ingest.py:33` | `logging.basicConfig(level=INFO, format=...)` | `configure_logging(agent="ingest")` |
| `agents/scout.py:608` | `logging.basicConfig(...)` | `configure_logging(agent="scout")` |
| `agents/profiler.py:1648` | `logging.basicConfig(...)` | `configure_logging(agent="profiler")` |
| `agents/hapax_voice/__main__.py:1009` | `logging.basicConfig(...)` | `configure_logging(agent="hapax-voice")` |
| `agents/obsidian_sync.py:630` | `logging.basicConfig(...)` | `configure_logging(agent="obsidian-sync")` |
| `agents/chrome_sync.py:568` | `logging.basicConfig(...)` | `configure_logging(agent="chrome-sync")` |
| `agents/gmail_sync.py:625` | `logging.basicConfig(...)` | `configure_logging(agent="gmail-sync")` |
| `agents/youtube_sync.py:591` | `logging.basicConfig(...)` | `configure_logging(agent="youtube-sync")` |
| `agents/gcalendar_sync.py:583` | `logging.basicConfig(...)` | `configure_logging(agent="gcalendar-sync")` |
| `agents/gdrive_sync.py:899` | `logging.basicConfig(...)` | `configure_logging(agent="gdrive-sync")` |
| `agents/claude_code_sync.py:578` | `logging.basicConfig(...)` | `configure_logging(agent="claude-code-sync")` |
| `agents/audio_processor.py:930` | `logging.basicConfig(...)` | `configure_logging(agent="audio-processor")` |
| `agents/sdlc_metrics.py:433` | `logging.basicConfig(...)` | `configure_logging(agent="sdlc-metrics")` |
| `agents/demo_eval.py:262` | `logging.basicConfig(...)` | `configure_logging(agent="demo-eval")` |
| `agents/dev_story/__main__.py:143` | `logging.basicConfig(...)` | `configure_logging(agent="dev-story")` |
| `shared/takeout/processor.py:471` | `logging.basicConfig(...)` | `configure_logging(agent="takeout")` |
| `shared/llm_export_converter.py:375` | `logging.basicConfig(...)` | `configure_logging(agent="llm-export")` |
| `shared/proton/processor.py:195` | `logging.basicConfig(...)` | `configure_logging(agent="proton")` |
| `shared/axiom_derivation.py:230` | `logging.basicConfig(...)` | `configure_logging(agent="axiom-derivation")` |
| `scripts/test_wake_handoff.py:25` | `logging.basicConfig(...)` | `configure_logging(agent="test-wake")` |
| `scripts/record_wake_word.py:66` | `logging.basicConfig(...)` | `configure_logging(agent="record-wake")` |
| `scripts/train_wake_word.py:1615` | `logging.basicConfig(...)` | `configure_logging(agent="train-wake")` |
| `cockpit/api/__main__.py:28` | `logging.basicConfig(...)` | (done in Phase 1) |

**hapax-officium** (8 basicConfig sites):

| File | Change |
|------|--------|
| `cockpit/api/__main__.py:28` | (done in Phase 1) |
| `agents/ingest.py:342` | `configure_logging(agent="ingest")` |
| `agents/scout.py:612` | `configure_logging(agent="scout")` |
| `agents/simulator.py:289` | `configure_logging(agent="simulator")` |
| `agents/management_profiler.py:1048` | `configure_logging(agent="management-profiler")` |
| `agents/demo_eval.py:266` | `configure_logging(agent="demo-eval")` |
| `scripts/index-docs.py:222` | `configure_logging(agent="index-docs")` |
| `shared/axiom_derivation.py:231` | `configure_logging(agent="axiom-derivation")` |

Each replacement is mechanical: delete the `logging.basicConfig(...)` block, add the import and one-liner. No changes to any `log.info(...)` calls.

### Phase 3: print() cleanup -- ongoing, opportunistic

Convert `print()` calls to proper `log.info()` / `log.debug()` as files are touched for other work. Priority targets:

- `agents/profiler.py` (45 prints) -- high-traffic agent
- `agents/meeting_lifecycle.py` (22 prints, officium) -- management-critical
- `scripts/run_deliberations.py` (51 prints) -- governance auditing
- `agents/hapax_voice/__main__.py` (1 print, but 56 total in hapax_voice)
- `agents/management_profiler.py` (32 prints, officium)

Do NOT attempt a mass `print()` -> `log.x()` conversion. Many prints are intentional CLI output (scripts), progress bars, or user-facing messages. Each must be evaluated individually.

---

## 8. hapax-voice EventLog Integration

The existing `agents/hapax_voice/event_log.py` already writes structured JSONL with OTel trace injection. It should remain as a **separate** event stream (it serves a different purpose: domain events, not operational logs). However, the trace ID injection pattern it uses (lines 52-61) validates our approach.

After Phase 2, hapax-voice will have **two** structured outputs:
1. `event_log.py` JSONL files -- domain events (session start, wake word, TTS delivery)
2. `shared/log_setup.py` JSON on stdout -- operational logs (errors, warnings, debug)

Both will carry the same `trace_id` when an OTel span is active.

---

## 9. Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `LOG_LEVEL` | `INFO` | Python log level |
| `HAPAX_LOG_HUMAN` | `false` | Set to `true`/`1` for human-readable format during development |
| `HAPAX_SERVICE` | `hapax-council` | Service name in log schema (set per-repo) |

The `HAPAX_SERVICE` default should be set in each repo's `.env` or systemd unit files:
- `hapax-council` units: `Environment=HAPAX_SERVICE=hapax-council`
- `hapax-officium` units: `Environment=HAPAX_SERVICE=hapax-officium`

---

## 10. Querying Structured Logs

### journalctl (systemd)

```bash
# All JSON logs from an agent
journalctl --user -u hapax-voice --output cat | jq .

# Filter by trace ID
journalctl --user -u hapax-voice --output cat | jq 'select(.trace_id == "0af7651916cd43dd8448eb211c80319c")'

# Errors only
journalctl --user -u hapax-voice --output cat | jq 'select(.level == "ERROR")'

# Cross-service: find all logs for a Langfuse trace
for unit in hapax-voice scout ingest profiler; do
  journalctl --user -u "$unit" --output cat
done | jq -s 'map(select(.trace_id == "TARGET")) | sort_by(.timestamp)'
```

### Future: log aggregation

When a log collector (Loki, Vector, Fluentd) is added, these JSON lines can be shipped directly without parsing. The `service` and `agent` fields enable filtering without relying on unit names.

---

## 11. Verification Checklist

### Phase 1 (foundation)

- [ ] `shared/log_setup.py` exists in both repos with identical logic
- [ ] `python-json-logger>=3.3.0` added to both `pyproject.toml`
- [ ] `opentelemetry-instrumentation-logging>=0.50b0` added to both `pyproject.toml`
- [ ] `uv sync` succeeds in both repos
- [ ] Cockpit API emits JSON on stdout when started
- [ ] JSON contains `timestamp`, `level`, `message`, `logger`, `service`, `agent` fields
- [ ] With Langfuse credentials set, JSON contains `trace_id` and `span_id` during LLM calls
- [ ] Without Langfuse credentials, logs still emit JSON (no crash, no trace fields)
- [ ] `HAPAX_LOG_HUMAN=1` produces human-readable output for development
- [ ] Existing tests pass (no logging format assumptions broken)

### Phase 2 (agents)

- [ ] Every `logging.basicConfig(...)` replaced with `configure_logging(agent=...)`
- [ ] No agent produces unstructured text on stdout
- [ ] `journalctl --user -u <agent> --output cat | jq .` parses cleanly for every agent
- [ ] `trace_id` in log lines matches `trace_id` in Langfuse UI for the same request
- [ ] Agent names in logs match systemd unit names for easy correlation

### Phase 3 (print cleanup)

- [ ] High-priority agents have zero `print()` calls (profiler, meeting_lifecycle, management_profiler)
- [ ] Remaining `print()` calls are documented as intentional (CLI output, user-facing)

### Regression guards

- [ ] Add a CI check: `grep -r "logging.basicConfig" agents/ shared/ cockpit/ --include="*.py"` fails if any remain
- [ ] Add a test that imports `shared.log_setup`, calls `configure_logging()`, emits a log, and asserts JSON output contains required fields
- [ ] Add a test that verifies OTel trace injection (similar to existing `test_event_log_trace_id.py`)

---

## 12. Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| `python-json-logger` v3 API changed from v2 | Pin `>=3.3.0`, test import in CI |
| JSON logs break existing log parsing (scripts, monitoring) | `HAPAX_LOG_HUMAN=1` escape hatch; grep-based monitoring still works on `message` field |
| `opentelemetry-instrumentation-logging` conflicts with existing OTel setup | It uses the same `TracerProvider` -- no conflict. `set_logging_format=False` prevents it from modifying the format string. |
| `print()` in agent code bypasses JSON formatter | Phase 3 addresses this; not blocking for Phase 1-2 |
| Performance: JSON serialization overhead | Negligible -- `python-json-logger` uses `json.dumps` which is C-accelerated. Logging is not on the hot path. |
| `agents/ingest.py` runs in isolated venv (no shared imports) | This agent will need its own copy of the formatter setup or a lightweight inline version |

---

## 13. Estimated Effort

| Phase | hapax-council | hapax-officium | Total |
|-------|---------------|----------------|-------|
| Phase 1: Foundation | 2 hours | 1 hour | 3 hours |
| Phase 2: Agent entrypoints | 3 hours | 1.5 hours | 4.5 hours |
| Phase 3: print() cleanup | Ongoing | Ongoing | -- |
| **Total (Phase 1+2)** | | | **~7.5 hours** |

Phase 1 and 2 can be done as a single PR per repo. Phase 3 is a continuous cleanup tracked separately.

# Chronicle: Unified System Observability

**Date:** 2026-04-02
**Status:** Approved

## Problem

Hapax has rich but fragmented observability. Engine audit, voice events, stimmung state, eigenform metrics, affordance cascades, reverie visual state, and perception signals are each stored in separate formats, locations, and retention windows. No unified query surface exists. Causal chains (stimmung triggered engine rule -> recruited affordance -> reverie rendered technique) are implicit across separate logs and never persisted as connected narrative.

The operator cannot ask arbitrary retrospective questions like "tell me everything that manifested on the reverie visual surface over the last 24hrs and why."

## Solution

A unified event store ("Chronicle") on `/dev/shm` with:
- Single JSONL stream carrying all system events in a common envelope
- OTel trace propagation repaired across three existing break points for causal chain reconstruction
- 30-second sampled state snapshots interleaved with events
- 12-hour strict retention
- Logos API query endpoints (structured + LLM-narrated)
- MCP tool for Claude Code access

Existing per-domain stores (engine audit 30d, voice events 14d, stimmung RAG indefinite) continue unchanged. Chronicle is an additive unified lens, not a replacement.

## Event Schema

```python
@dataclass
class ChronicleEvent:
    ts: float                    # time.time()
    trace_id: str                # OTel trace ID (32-hex), propagated from origin
    span_id: str                 # OTel span ID (16-hex), this event's span
    parent_span_id: str | None   # parent span, for causal chain reconstruction
    source: str                  # circulatory system: "engine", "stimmung", "visual", "perception", "voice"
    event_type: str              # e.g. "rule.matched", "affordance.recruited", "stance.changed", "snapshot"
    payload: dict                # domain-specific data, schema varies by event_type
```

Snapshots are events with `event_type: "snapshot"` and a payload containing the full state vector. No separate format.

## Event Taxonomy

| Source | Event Type | Trigger | Payload |
|--------|-----------|---------|---------|
| engine | `rule.matched` | Rule evaluates true | rule_name, event_path, doc_type |
| engine | `action.executed` | Action completes | action_name, phase, priority, duration_ms, error? |
| engine | `affordance.recruited` | Pipeline selects winner | capability_name, similarity, combined_score, impingement_source |
| stimmung | `stance.changed` | Stance transitions | from_stance, to_stance, trigger_dimension, dimension_values |
| stimmung | `dimension.spike` | Dimension crosses threshold (>0.7 or <0.3) | dimension_name, value, trend, previous_value |
| visual | `technique.activated` | Reverie activates/changes a slot | slot_index, technique_name, immensity, crossfade_state |
| visual | `params.shifted` | Shader params change beyond dead zone | changed_params (dict of name->value), technique_name |
| visual | `frame.evaluated` | DMN evaluative tick reads frame | observation_summary, reverberation_detected |
| perception | `signal.changed` | Signal bus value crosses threshold | signal_name, value, previous_value, source_device |
| perception | `presence.transition` | IR/face presence change | from_state, to_state, confidence |
| voice | `utterance.received` | User speaks | length_s, speaker (consent-gated) |
| voice | `response.emitted` | Daimonion responds | model, tokens, latency_ms |
| * | `snapshot` | Every 30s | Full state vector (stimmung dims, eigenform, signals, reverie params, active affordances) |

**Not recorded:** Raw audio, raw video frames, full LLM prompts/completions (stay in Langfuse), raw perception sensor values between snapshots.

## Trace Propagation Repair

Three existing break points in OTel context flow need fixing:

### Break 1: Impingement -> Affordance Pipeline

- Add `trace_id: str | None` and `span_id: str | None` to `Impingement` dataclass
- In `Engine.__init__.py` ~line 461 (`_convert_event()`): extract current OTel context, attach to impingement
- In `AffordancePipeline.select()`: wrap selection in child `hapax_span()` using impingement's trace context as parent
- Recruited affordances receive trace context forwarded into execution

### Break 2: FlowEvent -> Event Bus

- Add `trace_id: str | None` and `span_id: str | None` to `FlowEvent` dataclass
- In `Engine.__init__.py` ~line 545: extract current OTel span, attach IDs to emitted FlowEvents
- Chronicle subscribes to event bus and records events with full trace lineage

### Break 3: Stimmung -> Engine (correlation by reference)

- When stimmung updates `/dev/shm` state, chronicle records a `stance.changed` event with a new trace root
- When engine's filesystem watcher picks up the stimmung shm change and fires rules, the engine trace carries a `caused_by` reference to the stimmung chronicle event's trace_id
- Not full OTel injection into stimmung (too invasive) — correlation by reference. LLM synthesis layer follows `caused_by` to reconstruct causal chain.

## Chronicle Writer

### `shared/chronicle.py`

Public API:
- `record(event: ChronicleEvent)` — append to JSONL, non-blocking
- `query(since: float, until: float | None, source: str | None, event_type: str | None, trace_id: str | None, limit: int = 500) -> list[ChronicleEvent]` — filter and return

Internals:
- Writes to `/dev/shm/hapax-chronicle/events.jsonl`
- Async append with `aiofiles` — periodic fsync (every 5s or 50 events, whichever comes first)
- Background `asyncio.Task` runs every 60s: reads file, drops lines older than 12 hours, rewrites atomically (tmp + rename)
- On startup, trims stale entries immediately

### `shared/chronicle_sampler.py`

Coroutine running every 30s, records a snapshot event by reading:
- `/dev/shm/hapax-stimmung/state.json` — 11 dimensions + stance
- `/dev/shm/hapax-eigenform/state-log.jsonl` — latest entry
- Signal bus `snapshot()` — all current perception signals
- Reverie visual state (uniforms.json + active technique/slot info)
- Active affordances from pipeline internal state

Volume estimate: ~1,440 snapshots/12h at ~2-3KB each = ~3-4MB snapshots + event stream. Total under ~50MB.

Both writer and sampler started by Logos API server on boot.

## Query API

### `GET /api/chronicle`

Parameters:
- `since` (required) — ISO 8601 or relative (`-1h`, `-30m`)
- `until` — ISO 8601 or relative. Default: now
- `source` — filter by circulatory system
- `event_type` — filter by type
- `trace_id` — return all events in a specific causal chain
- `limit` — max events. Default 500

Returns JSON array of ChronicleEvents, newest-first.

### `GET /api/chronicle/narrate`

Same parameters as above, plus:
- `question` (required) — natural language question

Workflow:
1. Queries chronicle with given filters
2. Passes events + question to LLM (CAPABLE tier / Opus via LiteLLM) with system prompt understanding the schema, circulatory systems, and causal chain structure
3. Returns natural language narrative

### MCP Tool: `chronicle`

Exposed via hapax-mcp. Two modes:
- `chronicle(since, until, source, event_type, trace_id)` — structured query, returns events
- `chronicle(question, since)` — natural language query, hits `/api/chronicle/narrate`

## Files Changed

### New files (3)
- `shared/chronicle.py` — writer, query, retention, ChronicleEvent model
- `shared/chronicle_sampler.py` — 30s snapshot coroutine
- `logos/api/routes/chronicle.py` — API endpoints

### Modified files (7)
- `shared/impingement.py` — add `trace_id`, `span_id` fields to Impingement
- `logos/event_bus.py` — add `trace_id`, `span_id` to FlowEvent
- `logos/engine/__init__.py` — thread OTel context into impingement creation, FlowEvent emission; record chronicle events at rule match + action execution
- `shared/stimmung.py` — record `stance.changed` and `dimension.spike` to chronicle
- `agents/reverie/` — record `technique.activated`, `params.shifted`, `frame.evaluated`
- `logos/api/app.py` — register chronicle routes, start sampler on boot
- `hapax-mcp/src/hapax_mcp/server.py` — add `chronicle` tool

### Unchanged
Existing stores (engine audit, voice event log, stimmung sync, eigenform logger) continue as-is. Chronicle is additive.

## Estimated Scope

~400-500 lines new code (3 new files), ~100-150 lines modifications (7 existing files). No new dependencies.

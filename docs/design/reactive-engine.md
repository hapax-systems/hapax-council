# Reactive Engine Design

**Status**: Draft
**Date**: 2026-03-13
**Author**: Operator + Claude

---

## 1. Problem Statement

Council agents run on systemd timers and CLI invocation. A health check fires every 15 minutes whether or not anything changed. A profile update runs every 6 hours regardless of new data. An SDLC event lands on disk and nothing happens until the next scheduled sweep.

The constitution specifies something different: *inotify watcher → rule evaluation → phased execution*. Files land, the engine notices, rules fire, and downstream work cascades — deterministic work immediately, LLM work bounded by semaphore. This is the primary gap between the spec and the running system.

Officium has a working implementation: 8 modules, ~1,600 lines, running in production. Council has `cockpit/engine/` with nothing in it. This document designs council's reactive engine, informed by what officium learned building theirs.

---

## 2. Goals and Non-Goals

### Goals

- **File-change reactivity for the filesystem-as-bus.** When a markdown file with YAML frontmatter lands in a watched directory, the engine detects it, extracts metadata, evaluates rules, and executes actions — without waiting for the next timer tick.

- **Phased execution with cost control.** Deterministic work (file moves, collector refreshes, notifications) runs immediately with unlimited concurrency. LLM work runs through semaphores: 1 slot for local GPU (single RTX 3090), 2 slots for cloud APIs.

- **Coexistence with systemd timers.** Timers remain for scheduled work: health checks every 15 minutes, syncs every 30 minutes, weekly scouts. The engine handles reactive work. No overlap: timers don't watch files, the engine doesn't run on schedules.

- **Observability.** Engine status, rule history, and action logs exposed via cockpit API endpoints and OpenTelemetry spans.

### Non-Goals

- **Replace the voice daemon's FRP pipeline.** The voice daemon has its own reactive architecture (`Behavior[T]`/`Event[T]`, `VetoChain`, `FallbackChain`) purpose-built for real-time audio. The engine may react to voice state files written to disk but never drives the audio pipeline.

- **Inter-agent orchestration or DAGs.** The engine fires rules in response to file events. It does not manage agent dependencies, build execution graphs, or orchestrate multi-step workflows. Each rule is independent.

- **Replacing systemd for scheduled work.** Cron-like scheduling stays in systemd. The engine is event-driven, not time-driven.

---

## 3. Prior Art: Officium's Engine

Officium's reactive engine (`cockpit/engine/`) is 8 modules totaling ~1,600 lines, running in production. It handles the same fundamental problem — filesystem changes triggering downstream work — in a management-practice domain. Key modules:

### `models.py` (80 lines)

Four dataclasses define the event pipeline:

- **`ChangeEvent`** — filesystem event enriched with YAML-parsed `doc_type`. Fields: `path`, `event_type` (created/modified/deleted/moved), `doc_type` (from frontmatter), `timestamp`.
- **`Action`** — unit of work. Fields: `name`, `handler` (async callable), `args`, `priority` (int, lower = higher), `phase` (0 = deterministic, 1+ = LLM), `depends_on` (list of action names).
- **`ActionPlan`** — accumulates actions from rule evaluation. Tracks `results`, `errors`, and `skipped` sets during execution. Provides `actions_by_phase()` to group and sort.
- **`DeliveryItem`** — notification with priority, category, source action, timestamp, optional artifacts.

### `watcher.py` (240 lines)

Watchdog-based recursive filesystem monitoring with three key mechanisms:

- **Debounce**: Multiple events on the same path within the debounce window collapse. The timer reschedules on each new event but preserves the first event type. This prevents rapid file saves from triggering duplicate work.
- **Self-trigger prevention**: An `_own_writes` set tracks paths the engine itself writes to. When a handler is about to write a file, it calls `ignore_fn(path)` to register the path. The watcher skips events from registered paths. Entries auto-clear after the debounce window.
- **Filtering**: Dotfiles and `processed/` subdirectories are excluded. Frontmatter is extracted from markdown files to populate `doc_type`.

The watcher bridges watchdog's thread-based callbacks to asyncio via `call_soon_threadsafe`.

### `rules.py` (81 lines)

- **`Rule`** dataclass: `name`, `trigger_filter` (predicate on `ChangeEvent`), `produce` (callable returning list of `Action`), `description`.
- **`RuleRegistry`**: Dict keyed by rule name. Last registration wins.
- **`evaluate_rules()`**: Iterates all rules, applies filter, collects actions, deduplicates by action name. Returns `ActionPlan`. Exceptions in filter or produce are logged and skipped — one broken rule doesn't halt the pipeline.

### `reactive_rules.py` (348 lines)

12 concrete rules across officium's domain (meetings, coaching, people, feedback, etc.). Each rule specifies:
- A trigger filter (usually path-prefix matching + event type)
- An action producer returning 1–2 actions with phase and priority assignments
- Loop prevention (e.g., `meeting_cascade` skips `prep-*.md` files to prevent re-triggering on its own output)

Three async handler functions use lazy imports to avoid circular dependencies at module load time.

### `executor.py` (62 lines)

`PhasedExecutor` processes an `ActionPlan` phase by phase:

- **Phase 0**: Unlimited concurrency. All actions `gather`ed simultaneously.
- **Phase 1+**: Bounded by `asyncio.Semaphore(llm_concurrency)` (default 2).
- **Dependencies**: Before running an action, checks `depends_on`. If any dependency failed, the action is skipped and added to `plan.skipped`.
- **Timeouts**: Each action wrapped in `asyncio.wait_for(timeout)`. Timeout and generic exceptions stored in `plan.errors`.

### `delivery.py` (159 lines)

Priority-aware notification batching:

- **Critical** (priority 4): Immediate flush on next event loop tick.
- **High** (priority 3): 60-second flush window.
- **Medium/Low**: Periodic 5-minute flush loop.
- Batches format differently for single vs. multi-item messages.
- Ring buffer of last 50 items for status queries.

### `synthesis.py` (402 lines)

The most complex module, handling knowledge synthesis scheduling:

- **Hot/warm path classification**: `people`, `coaching`, `feedback` are hot (immediate synthesis trigger). `meetings`, `okrs`, `goals` etc. are warm.
- **Quiet window**: Accumulates dirty subdirectories, waits 180 seconds of quiet, then runs synthesis. Prevents thrashing when multiple files land in rapid succession.
- **Suppression**: Skips synthesis if a manual agent is running or previous synthesis is still in progress. Reschedules after 60 seconds.
- **Profiler loop**: Separate 1-hour check for profile synthesis (24-hour interval between runs).

### `__init__.py` (218 lines)

`ReactiveEngine` orchestrator wiring all components:

- Constructor accepts config overrides with environment variable fallbacks for `debounce_ms`, `llm_concurrency`, `delivery_interval_s`, `action_timeout_s`.
- Lifecycle: `start()` → `stop()`, with `pause()`/`resume()` for manual agent deconfliction.
- `_handle_change()`: evaluate rules → execute plan → enqueue delivery items → signal synthesis scheduler.

### Key Architectural Decisions

1. **One-shot ignore**: Self-trigger prevention entries auto-expire after the debounce window. This avoids stale entries accumulating and accidentally suppressing legitimate events.
2. **Phase separation**: Phase 0 (deterministic) has no concurrency limit. Phase 1+ (LLM) shares a single semaphore. This means a burst of file events can immediately refresh caches and move files while LLM work queues orderly.
3. **Lazy imports in handlers**: Rule handlers import agent modules at call time, not at registration time. This keeps engine startup fast and avoids circular dependency chains.
4. **Exception isolation**: A failing rule doesn't prevent other rules from evaluating. A failing action doesn't prevent other actions in the plan from executing (unless they depend on it).

---

## 4. Council's Watch Surfaces

Council has 5 watch surfaces producing events that the engine should react to. Each maps to existing agent work that currently runs on timers or manual invocation.

| Watch Surface | Path Pattern | Event Types | Current Trigger | Reactive Trigger |
|---|---|---|---|---|
| Health history | `profiles/health-history.jsonl` | modified | 15min timer | On append |
| RAG sources | `$RAG_SOURCES_DIR/**` (`~/documents/rag-sources/`) | created | Ingest watchdog | Engine action calling `ingest_file()` |
| SDLC events | `profiles/sdlc-events.jsonl` | modified | GitHub Actions | On append (notify + cache refresh) |
| Axiom files | `axioms/` | modified | CI gate only | On implication/precedent change |
| Profiles output | `profiles/*.json`, `profiles/*.jsonl` | created, modified | Collector timers | On upstream data change |

> **Note**: RAG sources originate outside the project tree (`~/documents/rag-sources/`, configured via `shared.config.RAG_SOURCES_DIR`). The engine must add `RAG_SOURCES_DIR` to its watch list explicitly, in addition to the project-relative paths.

**Removed from earlier draft**: `profiles/facts/` (facts live in Qdrant, not filesystem), `profiles/dev-story/` (SQLite database, not filesystem-watchable), `cockpit/data/` (Python modules with collector logic, not JSON output).

### Path-to-Document-Type Mapping

The engine extracts `doc_type` from YAML frontmatter when present. For files without frontmatter (JSONL, raw JSON), `doc_type` is inferred from the file path:

```
profiles/health-history.jsonl    → doc_type: health-event
profiles/sdlc-events.jsonl       → doc_type: sdlc-event
profiles/drift-report.json       → doc_type: drift-report
profiles/scout-report.json       → doc_type: scout-report
profiles/operator-profile.json   → doc_type: operator-profile
axioms/implications/*.yaml       → doc_type: axiom-implication
axioms/precedents/*.yaml         → doc_type: axiom-precedent
```

This mapping leverages `shared/frontmatter.py` for any markdown files and path-pattern matching for everything else. The ingest agent's `source_service` detection (`agents/ingest.py`) already recognizes 10 path patterns in `rag-sources/`; the engine reuses this logic for RAG source classification.

---

## 5. Event Model

```python
@dataclass
class ChangeEvent:
    path: Path
    event_type: str          # created | modified | deleted | moved
    doc_type: str | None     # from frontmatter or path inference
    frontmatter: dict | None # full YAML frontmatter if markdown
    timestamp: datetime

    @property
    def subdirectory(self) -> str:
        """First path component relative to data_dir (e.g., 'profiles', 'axioms')."""
        ...

    @property
    def source_service(self) -> str | None:
        """For rag-sources, the detected service (gdrive, gmail, etc.)."""
        ...
```

Events are created by the watcher after debounce. Frontmatter parsing uses `shared/frontmatter.py` (which needs porting from officium's canonical implementation — council currently has only the simpler `vault_utils.py` version that returns dict without body text).

---

## 6. Rules by Domain

Rules are organized into 3 groups across 3 execution phases. Each rule specifies a trigger filter, action producer, and phase assignment.

### Infrastructure Rules (Phase 0 — Deterministic)

| Rule | Trigger | Actions | Rationale |
|---|---|---|---|
| `config-changed` | `axioms/registry.yaml` modified | Reload axiom registry in-process | Avoid stale axiom data after edits |
| `collector-refresh` | Any watched `profiles/` path modified | Refresh relevant cockpit cache tier | Ensures API serves fresh data |
| `sdlc-event-logged` | `profiles/sdlc-events.jsonl` modified | Send notification + `cache.refresh_slow()` | No LLM needed — complements GitHub Actions (which drives the pipeline stages), engine handles local notification and cache refresh |

`collector-refresh` maps file changes to cache tiers:

| File Pattern | Cache Action |
|---|---|
| `profiles/health-history.jsonl` | `cache.refresh_fast()` |
| `profiles/drift-report.json` | `cache.refresh_slow()` |
| `profiles/scout-report.json` | `cache.refresh_slow()` |
| `profiles/operator-profile.json` | `cache.refresh_slow()` |

### Sync Rules (Phase 1 — Local GPU)

| Rule | Trigger | Actions | Rationale |
|---|---|---|---|
| `rag-source-landed` | `$RAG_SOURCES_DIR/**` created | Call `ingest_file(path)` directly | Processes file on arrival via `agents/ingest.py:483` |

### Knowledge Rules (Phase 2 — Cloud LLM)

| Rule | Trigger | Actions | Rationale |
|---|---|---|---|
| `knowledge-maintenance` | Multiple `profiles/` changes within quiet window | Run `agents/knowledge_maint.py` | Runs the existing maintenance agent after burst of changes settles |

### Ingest Watchdog Coexistence

The ingest agent has its own standalone watchdog (`agents/ingest.py:638-663`) using watchdog's `Observer` to watch `RAG_SOURCES_DIR`. When the reactive engine is active, the ingest watchdog should be disabled to avoid duplicate processing. The engine calls `ingest_file(path)` directly — same function the watchdog's `IngestHandler` calls internally.

Implementation approach: the ingest agent's `watch()` function is only invoked from `__main__`. When running under the engine, `ingest_file()` is imported and called directly; `watch()` is never started. No code changes needed — the engine simply doesn't call `watch()`.

### Deferred Rules

These rules cannot be implemented as filesystem watches and are deferred until their storage backends support change notifications:

| Rule | Why Deferred | Storage |
|---|---|---|
| `profile-fact-updated` | Facts live in Qdrant (vector DB), not on the filesystem | Qdrant collection `profile-facts` |
| `dev-story-artifact` | Dev story uses SQLite database, not filesystem artifacts | SQLite via `agents/dev_story/` |

When Qdrant or SQLite change hooks become available (or if a touch-file protocol is adopted), these rules can be promoted to active.

### Loop Prevention

Two active rules require explicit loop prevention:

- `rag-source-landed` must ignore files moved to `processed/` by the ingest agent.
- `knowledge-maintenance` must ignore its own synthesis output files.

Each handler calls `ignore_fn(output_path)` before writing, following officium's pattern. The watcher's one-shot ignore set handles the rest.

---

## 7. Three-Phase Execution

```
Phase 0: Deterministic
├── Unlimited concurrency
├── Zero cost (no LLM calls)
├── File moves, cache invalidation, collector refresh, notifications
└── Actions: gather() all simultaneously

Phase 1: Local GPU (Ollama via LiteLLM)
├── Semaphore = 1 (single RTX 3090)
├── Model: qwen3.5:27b (reasoning/coding) or qwen3:8b (fast)
├── SDLC next-stage, dev story synthesis, RAG embedding
└── Actions: acquire semaphore → execute → release

Phase 2: Cloud LLM (Anthropic/Gemini via LiteLLM)
├── Semaphore = 2
├── Model: claude-sonnet (balanced) or gemini-flash (fast)
├── Knowledge synthesis, complex classification
└── Actions: acquire semaphore → execute → release
```

### Why Three Phases Instead of Two

Officium uses two phases: deterministic (phase 0) and LLM (phase 1+, semaphore 2). Council needs three because local GPU and cloud API are separate bottlenecks:

- The RTX 3090 can run one inference at a time. Queuing two Ollama requests doesn't help — the second blocks on GPU memory.
- Cloud APIs can handle concurrent requests. Two simultaneous Claude calls are fine.
- Sharing a single semaphore between local and cloud would artificially limit cloud work when the GPU is busy, or let GPU work queue behind cloud work unnecessarily.

### Default Configuration

| Parameter | Default | Env Var | Rationale |
|---|---|---|---|
| `debounce_ms` | 500 | `ENGINE_DEBOUNCE_MS` | Larger files than officium (200ms) |
| `gpu_concurrency` | 1 | `ENGINE_GPU_CONCURRENCY` | Single RTX 3090 |
| `cloud_concurrency` | 2 | `ENGINE_CLOUD_CONCURRENCY` | Match officium |
| `delivery_interval_s` | 300 | `ENGINE_DELIVERY_INTERVAL_S` | Same 5min batch |
| `action_timeout_s` | 120 | `ENGINE_ACTION_TIMEOUT_S` | Longer than officium (60s) for embedding |
| `quiet_window_s` | 180 | `ENGINE_QUIET_WINDOW_S` | Same as officium |
| `cooldown_default_s` | 600 | `ENGINE_COOLDOWN_S` | Council extension |

**Dev mode**: When `get_cycle_mode() == "dev"`, `debounce_ms` doubles to 1000 and phase 2 rules are disabled (avoiding cloud LLM costs during development).

### Deduplication

Identical actions within the debounce window collapse. If three files land in `RAG_SOURCES_DIR` within 500ms, `evaluate_rules()` produces three `rag-source-landed` actions. Deduplication by action name keeps only one (the first). For per-file actions, the action name includes the file path to prevent inappropriate deduplication.

---

## 8. Self-Trigger Prevention

The engine writes files (moving RAG sources to `processed/`, writing synthesis outputs, refreshing collector caches). Without prevention, these writes trigger new events, which trigger new rules, which write more files — an infinite loop.

### Mechanism

Following officium's pattern (`watcher.py:186-199`):

1. Before writing a file, the handler calls `ignore_fn(path)`.
2. The watcher adds the path to an `_own_writes: set[Path]`.
3. When a filesystem event arrives for a path in `_own_writes`, the watcher skips it.
4. The entry auto-clears after the debounce window expires.

### Why One-Shot

The ignore entry is consumed on first use and expires with the debounce timer. This prevents stale entries from accumulating and accidentally suppressing legitimate external events. If the engine writes `/profiles/facts/openness.md` and the entry expires, a subsequent human edit to the same file will be detected normally.

### Additional Safeguards

- Path filtering: dotfiles and `processed/` subdirectories are always excluded.
- Rule-level guards: `rag-source-landed` checks `event_type != "moved"` to ignore ingest's move-to-processed operation.
- Cooldown per rule: optional per-rule minimum interval between firings (e.g., `knowledge-maintenance` no more than once per 10 minutes regardless of events). Note: cooldown per rule is a council extension not present in officium. Officium relies on the synthesis scheduler's quiet window for similar effect.

---

## 9. Systemd Timer Coexistence

Council currently runs 11 timers covering 10 agents. The reactive engine does not replace them — it fills the gap between timer ticks.

### Division of Responsibility

| Concern | Mechanism | Example |
|---|---|---|
| Scheduled work | Systemd timer | Health check every 15min, scout weekly |
| Reactive work | Engine rule | RAG source lands → immediate ingest |
| Both | Timer + rule | Profile update: timer every 6h for full sweep, rule on new fact for incremental |

### No Overlap Guarantee

- Timers don't watch files. They fire on schedule.
- The engine doesn't run on schedules. It fires on file events.
- For agents that have both a timer and a reactive rule (e.g., profile update), the agent itself is idempotent — running it twice with the same input produces the same output.

### Pause During Manual Work

When an operator runs an agent manually (`uv run python -m agents.health_monitor --history`), the engine pauses rule evaluation for that agent's watch surfaces. This prevents the engine from reacting to intermediate files the manual run produces. Officium implements this via `pause()`/`resume()` on the `ReactiveEngine` (`__init__.py:130-141`).

---

## 10. Voice Daemon Boundary

The voice daemon (`agents/hapax_voice/`) has its own reactive architecture:

- `Behavior[T]` for continuous state (microphone level, VAD state, model readiness)
- `Event[T]` for discrete occurrences (utterance detected, transcription complete)
- `VetoChain` for governance (capability health veto, compliance veto)
- `FallbackChain` for graceful degradation (cloud → local → error)

This is a real-time FRP pipeline operating at audio-frame granularity (~20ms). The reactive engine operates at file-event granularity (~seconds). They are architecturally separate.

### Interaction Points

The engine may react to voice state files written to disk:
- `profiles/voice-sessions/*.md` — completed voice session transcripts
- `profiles/rag-sources/ambient-audio/*.md` — ambient audio transcripts

The engine never:
- Drives the voice daemon's real-time pipeline
- Sends events into the FRP stream
- Manages voice daemon lifecycle (that's systemd's job)

---

## 11. Cockpit API Integration

Council's cockpit API (`cockpit/api/`) has 11 route groups serving ~30 endpoints. The engine adds 3 new endpoints under a new route group:

### New Endpoints

```
GET /engine/status
  → { running: bool, paused: bool, uptime_s: float, events_processed: int,
      rules_evaluated: int, actions_executed: int, errors: int }

GET /engine/rules
  → [ { name: str, description: str, phase: int, last_fired: datetime | null,
        fire_count: int, error_count: int } ]

GET /engine/history?limit=50
  → [ { timestamp: datetime, event_path: str, doc_type: str,
        rules_matched: [str], actions: [str], errors: [str] } ]
```

### Integration Pattern

The engine runs as a background task within the cockpit API process (FastAPI `lifespan` context manager), matching how officium's engine runs. This avoids a separate process and shares the event loop.

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = ReactiveEngine(data_dir=PROFILES_DIR)
    app.state.engine = engine
    await engine.start()
    yield
    await engine.stop()
```

Route handlers access `request.app.state.engine` for status queries.

---

## 12. Implementation Phases

### Phase A: Core Infrastructure

- `cockpit/engine/models.py` — `ChangeEvent`, `Action`, `ActionPlan`, `DeliveryItem`
- `cockpit/engine/watcher.py` — Watchdog-based watcher with debounce and self-trigger prevention
- `cockpit/engine/executor.py` — Three-phase executor with GPU and cloud semaphores
- `cockpit/engine/rules.py` — `Rule`, `RuleRegistry`, `evaluate_rules()`
- `cockpit/engine/__init__.py` — `ReactiveEngine` orchestrator

Port frontmatter.py from officium (canonical regex-based implementation returning `(dict, body)` tuple).

**Acceptance**: Engine starts, watches `profiles/`, debounces events, logs to console. No rules yet.

### Phase B: First Rules (Phase 0 Only)

- `cockpit/engine/reactive_rules.py` — Infrastructure domain rules
- Rules: `collector-refresh` (with explicit cache tier mapping), `config-changed`, `sdlc-event-logged`
- Self-trigger prevention verified with integration test

**Acceptance**: Appending to `health-history.jsonl` triggers `cache.refresh_fast()` within debounce window. Appending to `sdlc-events.jsonl` triggers notification + `cache.refresh_slow()`.

### Phase C: Sync Rules

- Rules: `rag-source-landed` (watching `$RAG_SOURCES_DIR/**`, calling `ingest_file()` directly)
- Ingest agent integration (phase 1, local GPU semaphore)
- Loop prevention for rag-source → processed move
- Ingest watchdog coexistence: engine calls `ingest_file()` directly; standalone `watch()` not started

**Acceptance**: Dropping a file in `RAG_SOURCES_DIR` triggers ingest without waiting for timer.

### Phase D: Knowledge Rules

- Rules: `knowledge-maintenance` (runs existing `agents/knowledge_maint.py`)
- Quiet window implementation (180s, following officium's `synthesis.py` pattern)
- Cloud LLM semaphore (phase 2)

**Acceptance**: Multiple profile changes within 3 minutes trigger one maintenance run, not many.

### Phase E: Cockpit Integration + Dashboard

- API endpoints: `/engine/status`, `/engine/rules`, `/engine/history`
- OpenTelemetry spans for rule evaluation and action execution
- council-web dashboard panel for engine status

**Acceptance**: Engine status visible in cockpit API and web dashboard.

---

## 13. Testing Strategy

All tests use `unittest.mock`, consistent with council's testing conventions. No infrastructure required.

### Unit Tests

- **Watcher**: Mock watchdog `Observer`. Emit synthetic filesystem events. Verify debounce (multiple events on same path → single callback). Verify self-trigger prevention (ignored paths produce no callback). Verify dotfile/processed filtering.
- **Rules**: Create test rules with known filters. Pass synthetic `ChangeEvent` instances. Verify correct rules fire, wrong rules don't, deduplication works.
- **Executor**: Create `ActionPlan` with actions across phases. Mock async handlers. Verify phase 0 runs before phase 1, phase 1 before phase 2. Verify semaphore bounds (only N actions concurrent in LLM phases). Verify dependency skipping on failure.
- **Models**: Verify `actions_by_phase()` grouping and priority sorting. Verify `ChangeEvent` property derivation.

### Integration Tests (Marked `integration`)

- **End-to-end**: Start engine with temp directory. Write a file. Verify rule fires and action executes within debounce + execution window.
- **Self-trigger loop**: Handler writes a file with `ignore_fn`. Verify no re-trigger.
- **Timer coexistence**: Simulate timer-triggered agent run concurrent with engine rule. Verify no interference.

### What Not to Test

- Watchdog's inotify integration (tested by watchdog library)
- LLM output quality (tested by agent-specific tests)
- Cockpit API endpoint routing (tested by existing API tests)

---

## 14. Risks and Mitigations

| Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|
| File event storms | GPU/API saturation, cost runaway | Medium | Debounce + deduplication + per-rule cooldowns |
| LLM cost runaway | Unexpected API spend | Low | Semaphore caps (1 local, 2 cloud), per-rule cooldowns, cycle mode awareness |
| Self-trigger loops | Infinite cascades, disk thrash | Medium | `_own_writes` set, path filtering, rule-level guards |
| Voice daemon interference | Audio pipeline disrupted | Low | Explicit boundary — engine never writes to voice state paths |
| Stale ignore entries | Legitimate events suppressed | Low | One-shot expiry after debounce window |
| Engine crash during action | Orphaned state, missed events | Low | Executor catches all exceptions per-action, engine restart picks up from current filesystem state |
| Race with manual agent runs | Duplicate work, conflicting writes | Medium | `pause()`/`resume()` API, agent idempotency |

### Cycle Mode Awareness

In `dev` mode (`shared.cycle_mode.get_cycle_mode() == "dev"`), the engine should:
- Increase debounce window (reduce noise during active development)
- Disable phase 2 rules (avoid cloud LLM costs during dev)
- Log more verbosely

In `prod` mode, all rules active with production debounce windows.

---

## Appendix: Officium → Council Translation

Officium's 12 rules map to council's domain as follows. This is not a direct port — council's watch surfaces and agent topology are different — but the architectural patterns transfer directly.

| Officium Rule | Officium Domain | Council Equivalent | Council Domain |
|---|---|---|---|
| `inbox_ingest` | Inbox documents | `rag-source-landed` | RAG source files |
| `meeting_cascade` | Meeting transcripts | `sdlc-event-logged` | SDLC pipeline events (phase 0, no LLM) |
| `person_changed` | People files | — (deferred) | Facts in Qdrant, not filesystem |
| `coaching_changed` | Coaching notes | — | No equivalent (single-user) |
| `feedback_changed` | Feedback files | — | No equivalent (single-user) |
| `decision_logged` | Decision records | — (deferred) | Dev story in SQLite, not filesystem |
| Cache refresh rules (6) | Various | `collector-refresh` | Cockpit collectors (with tier mapping) |
| Synthesis scheduler | Knowledge synthesis | `knowledge-maintenance` | Runs existing `knowledge_maint.py` |

The structural patterns — `ChangeEvent` → `evaluate_rules()` → `PhasedExecutor` → `DeliveryQueue` — transfer without modification. The `SynthesisScheduler` quiet-window pattern transfers to `knowledge-maintenance` with the same 180-second default.

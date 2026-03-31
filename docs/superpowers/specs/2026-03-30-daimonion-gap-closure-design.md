# Daimonion Voice Pipeline Gap Closure

**Date:** 2026-03-30
**Scope:** Full audit remediation — 155 source files, all severity levels
**Approach:** 4-stage gated implementation (P0 → P1 → Structural → Tests)

---

## Audit Summary

Full pipeline audit covered 155 source modules and 154 test files across 5 dimensions:
correctness, consistency, robustness, completion, coherence.

- **9 P0 critical bugs** (production blockers)
- **10 P1 high bugs** (reliability risks)
- **3 dead code items** to remove
- **3 structural gaps** (init tracking, error strategy, resource lifecycle)
- **3 stale tests** (OpenTelemetry import regression)
- **112/155 modules untested** (72% coverage gap)

Architecture is sound. Backend protocol adherence is 98%. Consent threading, behavior
watermarking, and Composition Ladder compliance are all strong. The gaps are in error
handling uniformity, long-running robustness, and test coverage.

---

## Stage 1: P0 Critical Fixes

Nine surgical fixes. Each is isolated — no cross-dependencies.

### 1.1 contact_mic.py:378 — Undefined variable `device_idx`

**Bug:** `log.info("Contact mic capturing from device %d", device_idx)` references a
variable that was never assigned.

**Fix:** Remove the log statement or replace with device info from PyAudio:
```python
dev_info = self._pa.get_default_input_device_info()
log.info("Contact mic capturing from device %d (%s)", dev_info["index"], dev_info["name"])
```

### 1.2 contact_mic.py:474 — Silent capture thread death

**Bug:** `_capture_loop()` catches Exception, logs at DEBUG, and exits. `_available`
stays True. Perception believes the mic is still capturing.

**Fix:**
```python
except Exception:
    log.warning("Contact mic capture failed — marking unavailable", exc_info=True)
    self._available = False
```

### 1.3 echo_canceller.py:141 — Race condition on `_latency_buf`

**Bug:** `_latency_buf` is accessed from `feed_reference()` (TTS thread) and `process()`
(audio loop thread). Only `_ref_buf` is guarded by `_ref_lock`. The latency buffer
reads/writes are unsynchronized.

**Fix:** Extend `_ref_lock` scope to cover all shared state:
```python
with self._ref_lock:
    self._ref_buf.append(resampled)
    self._latency_buf.append(resampled)
```

And in `process()`:
```python
with self._ref_lock:
    if self._ref_buf:
        ref_frame = self._ref_buf.popleft()
    latency_frame = self._latency_buf.popleft() if self._latency_buf else None
```

### 1.4 echo_canceller.py:73 — Memory leak on speexdsp state

**Bug:** `speex_echo_state_init()` allocates native memory. No `__del__` or context
manager ensures cleanup if daemon crashes or AEC is abandoned.

**Fix:** Add `__del__` and context manager protocol:
```python
def __del__(self) -> None:
    self.destroy()

def __enter__(self):
    return self

def __exit__(self, *exc):
    self.destroy()
```

### 1.5 multi_mic.py:285 — Process handle accumulation

**Bug:** Terminated subprocess handles are appended to `_processes` but only removed in
the `finally` block on exception. On normal loop exit, handles persist. Over days,
`_processes` grows unbounded.

**Fix:** Add cleanup on normal loop iteration:
```python
# After proc.wait() or proc.poll() shows termination:
if proc.poll() is not None:
    with self._lock:
        if proc in self._processes:
            self._processes.remove(proc)
```

### 1.6 phone_messages.py:42 — Shell injection vector

**Bug:** `_PHONE_MAC` is concatenated into a Python code string passed to subprocess.
If the value ever contains special characters, this is exploitable.

**Fix:** Pass MAC as a command-line argument instead of embedding in code:
```python
subprocess.run(
    [sys.executable, "-c", SCRIPT, _PHONE_MAC],
    ...
)
```
Where SCRIPT reads `sys.argv[1]` for the MAC address.

### 1.7 phone_media.py:48-83 — Busctl parsing stub

**Bug:** Code acknowledges busctl dict parsing is complex, then does nothing. Title and
artist remain empty strings forever.

**Fix:** Use `--json=short` flag and parse with `json.loads()`:
```python
result = subprocess.run(
    ["busctl", "--user", "--json=short", "get-property", ...],
    capture_output=True, text=True, timeout=3,
)
if result.returncode == 0:
    data = json.loads(result.stdout)
    title = data.get("data", "")
```

### 1.8 governor.py:129 — Missing `_check_compliance` method

**Bug:** The axiom compliance veto references `self._check_compliance` which is not
implemented. Will raise `AttributeError` on first governance evaluation.

**Fix:** Check if axiom infrastructure exists in the codebase. If available, wire it.
If not, implement as always-allow with logged TODO:
```python
def _check_compliance(self, ctx: FusedContext) -> bool:
    """Axiom compliance check — placeholder until wired to shared/axiom_*.py."""
    return True
```

### 1.9 run_inner.py:181 — Shutdown ordering

**Bug:** Stops pipeline before audio input. If audio loop holds a pipeline reference,
stopping pipeline first can race.

**Fix:** Reverse the shutdown order:
1. Stop audio input (breaks the frame source)
2. Stop pipeline (drains remaining frames)
3. Stop hotkey server
4. Cancel background tasks

---

## Stage 2: P1 Fixes + Dead Code Removal

### 2.1 conversation_buffer.py:153 — Undefined `_speaking_started_at`

**Fix:** Initialize `self._speaking_started_at: float | None = None` in `__init__`.
Replace `getattr` fallback with explicit None check.

### 2.2 audio_executor.py:55 — Stream resource leak

**Fix:** Wrap playback in try/finally:
```python
stream = self._pa.open(...)
try:
    stream.write(pcm_data)
finally:
    stream.stop_stream()
    stream.close()
```

### 2.3 tts.py:32 — Float32 quantization

**Fix:** Change `audio * 32767` to `audio * 32768`.

### 2.4 pipecat_tts.py:57 — No synthesis timeout

**Fix:**
```python
audio = await asyncio.wait_for(
    asyncio.to_thread(self._tts.synthesize, text),
    timeout=30.0,
)
```

### 2.5 pipeline_start.py:48 — Stale experiment flags

**Fix:** Reset at session start before reading config:
```python
daemon._experiment_flags = {}
if experiment_config_path.exists():
    daemon._experiment_flags = json.loads(experiment_config_path.read_text())
```

### 2.6 presence_engine.py:259 — Likelihood ratio overflow

**Fix:** Move to log-domain computation:
```python
log_odds = math.log(self._prior / (1.0 - self._prior))
for signal_name, observed in signals.items():
    if observed is None:
        continue
    tp, fp = self._signal_weights[signal_name]
    lr = tp / max(fp, 1e-12) if observed else (1.0 - tp) / max(1.0 - fp, 1e-12)
    log_odds += math.log(max(lr, 1e-12))
posterior = 1.0 / (1.0 + math.exp(-log_odds))
```

### 2.7 perception_loop.py:37 — Off-by-one on voice session

**Fix:** Move `set_voice_session_active()` before `tick()`:
```python
daemon.perception.set_voice_session_active(daemon.session.is_active)
state = daemon.perception.tick()
```
(Verify this is not already the order — the audit says tick sees previous state.)

### 2.8 consent_state.py:117 — Duplicate notifications on zero debounce

**Fix:** Set notification flag when debounce is skipped:
```python
if self.debounce_s <= 0:
    self._phase = ConsentPhase.CONSENT_PENDING
    self._notification_sent = True
    self._emit("consent_pending", face_count=face_count)
```

### 2.9 tool_definitions.py — Schema-handler validation

**Fix:** At registry build time, assert every tool in `_META` has a corresponding handler:
```python
for name in _META:
    assert name in handler_map, f"Tool '{name}' defined in _META but has no handler"
```

### 2.10 devices.py:238 — BLE scan disabled without fallback

**Fix:** Explicitly set behavior to disabled state:
```python
# BLE scanning disabled — bleak destabilizes dbus-broker (see comment above)
behaviors["bluetooth_nearby"] = Behavior(False, note="BLE scan disabled")
```

### 2.11-2.13 Dead Code Removal

- **Delete** `init_workspace.py` — never called, work done inline in `daemon.py`
- **Remove** `_repair_threshold()` from `grounding_ledger.py`
- **Remove** `format_tick_log()` from `presence_diagnostics.py`

---

## Stage 3: Structural Improvements

### 3A. Init Phase Tracking

New enum and tracking in `daemon.py`:

```python
class InitPhase(enum.Enum):
    CORE = "core"
    PERCEPTION = "perception"
    STATE = "state"
    VOICE = "voice"
    ACTUATION = "actuation"
```

Each `_init_*` method wraps in try/except, appends to `self._init_completed: set[InitPhase]`
on success. Failure logs at ERROR and sets `self._init_failed: dict[InitPhase, str]`.

`is_ready() -> bool` returns True only if all phases completed. Pipeline start gates
on `is_ready()`. Backend registration count logged at end of perception init.

### 3B. Degradation Registry

New module: `agents/hapax_daimonion/error_strategy.py`

```python
@dataclass(frozen=True)
class DegradationEvent:
    subsystem: str       # "backends", "salience", "audio"
    component: str       # "PipeWireBackend", "echo_canceller"
    severity: str        # "info", "warning", "error"
    message: str
    timestamp: float     # time.monotonic()

class DegradationRegistry:
    _events: list[DegradationEvent]

    def record(self, subsystem: str, component: str, severity: str, message: str) -> None: ...
    def active(self) -> list[DegradationEvent]: ...
    def count_by_severity(self) -> dict[str, int]: ...
    def summary(self) -> str: ...
```

`log_degradation(registry, subsystem, component, message, severity="warning")` helper
replaces all `log.info("skipping")` patterns. The registry is attached to daemon and
queryable for health checks.

Retrofit all 27 init_backends.py catches + 7 silent-failure backends to use this.

### 3C. Resource Lifecycle Management

New module: `agents/hapax_daimonion/resource_lifecycle.py`

```python
class ManagedResource(Protocol):
    def stop(self) -> None: ...
    def is_alive(self) -> bool: ...

class ResourceRegistry:
    def register(self, name: str, resource: ManagedResource, phase: InitPhase) -> None: ...
    def stop_all(self, timeout: float = 5.0) -> list[str]: ...  # returns failed names
```

Daemon shutdown calls `registry.stop_all()` in reverse-phase order. Covers:
- `_frame_executor` (ThreadPoolExecutor — wrap in ManagedResource adapter)
- `_stt_executor` (ThreadPoolExecutor)
- `echo_canceller` (speexdsp state)
- `multi_mic` processes
- `audio_input` stream
- All backend `stop()` methods

### 3D. Fix Stale Tracing Tests

Update imports in 3 test files from deprecated OpenTelemetry path:
```python
# Old
from opentelemetry.sdk.trace.export.in_memory import InMemorySpanExporter
# New
from opentelemetry.sdk.trace.export import InMemorySpanExporter
```

---

## Stage 4: Test Coverage

### 4A. Backend Tests (22 files)

Template-driven. Each backend test file verifies:

1. **Protocol compliance:** `name`, `provides`, `tier`, `available()`, `contribute()`,
   `start()`, `stop()` all exist and return correct types
2. **Graceful degradation:** When dependency is unavailable, `available()` returns False
   and `contribute()` is a no-op
3. **Behavior correctness:** Values are correct types, within expected ranges
4. **Error handling:** Exceptions don't propagate, logged appropriately

Backends that spawn subprocesses (contact_mic, phone_*, devices, stream_health) get
additional tests for subprocess failure and timeout handling.

### 4B. Salience Tests (5 files)

- `test_salience_router.py` — Tier selection for known activation levels, hysteresis
  (can only drop 1 tier per turn), cold-start routing, consent phase overrides
- `test_concern_graph.py` — Refresh with valid/empty anchors, overlap scoring, novelty
  for zero vectors, deduplication
- `test_embedder.py` — Available/unavailable states, embed returns (256,) float32,
  embed_batch empty input
- `test_utterance_features.py` — Dialog act classification, phatic detection with
  punctuation edge cases, overlap calculation
- `test_salience_diagnostics.py` — History tracking, stats with missing keys

### 4C. Perception + Pipeline Tests (5 files)

- `test_perception_engine.py` — Tick cycle, behavior aggregation, interruptibility
  score boundaries
- `test_perception_loop.py` — Voice session flag ordering (the off-by-one fix),
  consent tick with missing IR backend
- `test_arbiter.py` — Claim/release ordering, priority FIFO, hold expiry GC,
  same-chain priority rejection
- `test_conversation_buffer_extended.py` — Cooldown scaling at long TTS durations,
  max_duration enforcement
- `test_init_phase_tracking.py` — All phases complete → is_ready True, partial
  failure → is_ready False with correct failed dict

### 4D. Structural Tests (3 files)

- `test_error_strategy.py` — DegradationRegistry record/query, severity counts,
  summary output
- `test_resource_lifecycle.py` — Register/stop_all ordering, timeout on hung resource,
  failed names returned
- `test_pipeline_lifecycle_extended.py` — Shutdown ordering (audio before pipeline),
  vision pause tracking, resume failure handling

---

## Implementation Constraints

- All fixes must pass existing test suite (`uv run pytest tests/hapax_daimonion/ -q`)
- New code follows project conventions: ruff, pyright, type hints, 100-char lines
- New modules get `__all__` exports
- No new dependencies unless absolutely required
- Each stage is a separate commit (or small group of commits)
- Stage N+1 does not start until Stage N passes tests

---

## Success Criteria

- All 9 P0 bugs fixed and verified
- All 10 P1 bugs fixed and verified
- 3 dead code items removed
- Init phase tracking operational with `is_ready()` gate
- DegradationRegistry replacing all silent failure patterns
- ResourceRegistry managing all long-lived resources
- 3 stale tracing tests fixed
- 35 new test files covering backends, salience, perception, pipeline, structural
- Full test suite green

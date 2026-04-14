# Phase 1 — Task supervisor design (unblocks BETA-FINDING-L)

**Queue item:** 026
**Phase:** 1 of 6
**Depends on:** Queue 025 Phase 2 (BETA-FINDING-L)
**Date:** 2026-04-13 CDT
**Register:** scientific, neutral (per `feedback_scientific_register.md`)
**Purpose:** design pass so alpha's next session can implement the fix without re-deriving the architecture.

## Headline

**Recommendation: Pattern 3 (supervisor loop) with per-task
restart policy.** Rationale, in one sentence: the daimonion's 10
background tasks have **mixed criticality** — some are voice-
critical (CPAL runner → crash means voice is dead, should
`SystemExit(1)` and let systemd restart), some are independent
(workspace monitor → crash means screen capture is dead, CPAL
should keep ticking). `asyncio.TaskGroup` is all-or-nothing
(first child exception cancels siblings) which is wrong for
independent subsystems. A supervisor loop with per-task policy
gives the right semantics and costs ~50 lines.

A copy-pasteable sketch is in § The recommendation below.

## The three candidate patterns

### Pattern 1 — fire-and-forget (current daimonion behavior, broken)

```python
daemon._background_tasks.append(asyncio.create_task(task_a()))
daemon._background_tasks.append(asyncio.create_task(task_b()))
# Main loop:
while daemon._running:
    await asyncio.sleep(1)
# Only at shutdown:
await asyncio.gather(*daemon._background_tasks, return_exceptions=True)
```

**Semantics:** exceptions are held in the Task object and only
observed when gather runs. In the daimonion, gather is only in
the shutdown `finally` — so crashes during normal operation are
invisible.

**Verdict:** the baseline bug. Must be replaced.

### Pattern 2 — `asyncio.TaskGroup` (structured concurrency)

```python
async with asyncio.TaskGroup() as tg:
    tg.create_task(task_a())
    tg.create_task(task_b())
    # Main loop lives inside the group
    while daemon._running:
        await asyncio.sleep(1)
```

**Semantics:** available in Python 3.11+ (daimonion runs 3.12,
confirmed). Available under uvloop (verified experimentally
below). On first child exception:

- The exception is held
- Every other child task is cancelled
- At context exit, the exception is raised as an `ExceptionGroup`

The pattern is "structured concurrency": every task has a
clear lifetime tied to the enclosing `async with` block, and
exceptions propagate to the parent.

**Verdict:** structurally elegant but the "cancel all siblings
on any crash" semantics are wrong for the daimonion. A bug in
`workspace_monitor.run()` would cancel CPAL. A bug in
`ambient_refresh_loop` would cancel the audio loop. The
daimonion's 10 tasks are intentionally independent at the
subsystem level; TaskGroup treats them as one unit.

### Pattern 3 — Supervisor loop (explicit per-task check)

```python
tasks: dict[str, asyncio.Task] = {
    "cpal_runner": asyncio.create_task(daemon._cpal_runner.run(), name="cpal_runner"),
    "workspace_monitor": asyncio.create_task(daemon.workspace_monitor.run(), name="workspace_monitor"),
    ...
}
# In the main loop, every tick:
for name, t in list(tasks.items()):
    if t.done() and not t.cancelled():
        exc = t.exception()
        if exc is not None:
            handle_task_crash(name, exc)  # policy varies per task
```

**Semantics:** explicit. The main loop observes crashes at most
one tick late. The `handle_task_crash` function can be
per-task:

- `cpal_runner`: `raise SystemExit(1)` → systemd restarts the daemon
- `workspace_monitor`: `log.exception(...)` + recreate the task
- `ambient_refresh_loop`: `log.warning(...)` + increment counter + recreate

**Verdict:** verbose but correct. Every task's failure mode is
explicit. The operator can tune policy per-subsystem.

## Failure-semantics experiment

Script: `docs/research/2026-04-13/round5-unblock-and-gaps/data/test-supervisor-patterns.py`

Each test: `task_a` runs a 5-tick loop at 200 ms cadence.
`task_b` raises after 500 ms. Main loop runs 6 ticks.

```bash
$ uv run python data/test-supervisor-patterns.py
```

### Pattern 1 output

```text
=== Pattern 1: fire-and-forget create_task ===
main_loop tick 0
p1_a tick 0
main_loop tick 1
p1_a tick 1
main_loop tick 2
p1_a tick 2
main_loop tick 3
p1_a tick 3
main_loop tick 4
p1_a tick 4
main_loop tick 5
gather results at shutdown: ['NoneType', 'RuntimeError']
```

**`task_b`'s exception is invisible until shutdown.** Main loop
completed 6 ticks, `task_a` completed 5 ticks, and only at the
shutdown `gather` did the RuntimeError surface. **This is exactly
the BETA-FINDING-L observed behavior.**

### Pattern 2 (TaskGroup) output

```text
=== Pattern 2: TaskGroup ===
p2_a tick 0
p2_a tick 1
p2_a tick 2
ERROR TaskGroup caught exception group: (RuntimeError('task_b exploded'),)
```

**task_a gets cancelled at tick 2 (3 ticks total, not 5).** The
moment `task_b` raises at 500 ms, TaskGroup propagates the
cancellation to `task_a`. The exception is surfaced as an
`ExceptionGroup` at context exit.

**Confirmed: uvloop supports TaskGroup.** The script ran with
`uvloop.install()` + `asyncio.run(main())` and TaskGroup worked
correctly. No uvloop-specific caveat.

### Pattern 3 (supervisor loop) output

```text
=== Pattern 3: Supervisor loop ===
supervisor tick 0, live tasks: ['a', 'b']
p3_a tick 0
supervisor tick 1, live tasks: ['a', 'b']
p3_a tick 1
supervisor tick 2, live tasks: ['a', 'b']
p3_a tick 2
ERROR task b crashed: RuntimeError: task_b exploded
ERROR supervisor observed crash; would raise SystemExit in real daemon
```

**task_a ran for 3 ticks (not auto-cancelled).** The supervisor
observed `task_b`'s crash on the next tick after it completed,
logged it explicitly, and then made the policy decision
(raise SystemExit). task_a was NOT implicitly cancelled —
only the explicit supervisor action would stop it.

## uvloop compatibility

Claim: uvloop does not change TaskGroup semantics vs stock
asyncio for our purposes.

**Evidence:** Pattern 2 experiment uses `uvloop.install()`
before `asyncio.run(main())` and TaskGroup works correctly —
exception group propagation, automatic sibling cancellation,
and context exit all behave per asyncio docs. uvloop 0.22.1
on Python 3.12.13 confirmed.

No uvloop-specific caveat for any pattern.

## Per-task supervisory requirement survey

Walking the 10 `create_task` callsites in
`agents/hapax_daimonion/run_inner.py:135-180`:

| # | task | criticality | crash policy | rationale |
|---|---|---|---|---|
| 1 | `proactive_delivery_loop` | Medium | log + recreate | proactive delivery is nice-to-have; crash means pending notifications stop dispatching but voice still works. Recreate with backoff. |
| 2 | `subscribe_ntfy` | Medium | log + recreate | ntfy is external; network hiccups should retry. Recreate with exponential backoff. |
| 3 | `workspace_monitor.run` | Medium | log + recreate | screen capture + perception; crash degrades perception but voice still works. Recreate. |
| 4 | `audio_loop` | **Critical** | SystemExit | audio input is the VAD + speech source. Crash means voice is deaf. SystemExit → systemd restart. |
| 5 | `perception_loop` | Medium | log + recreate | perception degradation is survivable; gain controller falls back to simpler signals. |
| 6 | `ambient_refresh_loop` | Low | log + continue | ambient context refresh is decorative. Crash = stale ambient label. Non-critical. |
| 7 | `daemon._cpal_runner.run` | **Critical** | SystemExit | CPAL IS the cognitive loop. Crash = voice pipeline dead. This is the queue 024 "alive but silent" root cause. Must SystemExit. |
| 8 | `_cpal_impingement_loop` | **Critical** | SystemExit | impingement delivery is the cognitive input path. Crash = CPAL starves for stimuli. Must SystemExit. |
| 9 | `impingement_consumer_loop` | High | log + recreate | affordance dispatch + Thompson learning; crash is survivable short-term, degrades cross-modal coordination. Recreate with monitoring. |
| 10 | `actuation_loop` | Medium | log + recreate | MIDI/OBS actuation; crash means scene commands stop. Recreate. |

**3 critical tasks** (audio_loop, cpal_runner, cpal_impingement_loop)
warrant fail-hard on crash. **7 non-critical tasks** warrant
log-and-recreate or log-and-continue.

TaskGroup (Pattern 2) treats all 10 as one unit. A crash in
task 6 (ambient_refresh_loop — least critical) would cancel
tasks 4, 7, and 8 (all critical). Wrong semantics.

Supervisor loop (Pattern 3) lets each task have its own policy.
Correct semantics.

## The recommendation

**Ship Pattern 3 (supervisor loop) with a per-task policy
dictionary.** Sketch below.

### Code sketch (drop-in for `run_inner.py:135-180`)

```python
# New module-level constants, near top of run_inner.py
CRITICAL_TASKS = frozenset({"audio_loop", "cpal_runner", "cpal_impingement_loop"})
RECREATE_TASKS = frozenset({
    "proactive_delivery_loop",
    "ntfy_subscribe",
    "workspace_monitor",
    "perception_loop",
    "impingement_consumer_loop",
    "actuation_loop",
})
LOG_AND_CONTINUE_TASKS = frozenset({"ambient_refresh_loop"})


def _make_task(
    daemon: VoiceDaemon,
    name: str,
    coro_factory: Callable[[], Awaitable[None]],
) -> asyncio.Task:
    """Wrap a coroutine factory into a named task stored by name."""
    task = asyncio.create_task(coro_factory(), name=name)
    daemon._background_tasks_by_name[name] = (task, coro_factory)
    return task


# In run_inner(daemon), replace the create_task calls:

daemon._background_tasks_by_name: dict[
    str, tuple[asyncio.Task, Callable[[], Awaitable[None]]]
] = {}

_make_task(daemon, "proactive_delivery_loop",
           lambda: proactive_delivery_loop(daemon))
_make_task(daemon, "ntfy_subscribe",
           lambda: subscribe_ntfy(
               _NTFY_BASE_URL, _NTFY_TOPICS,
               lambda n: ntfy_callback(daemon, n)
           ))
_make_task(daemon, "workspace_monitor", daemon.workspace_monitor.run)
if daemon._audio_input.is_active:
    _make_task(daemon, "audio_loop", lambda: audio_loop(daemon))
_make_task(daemon, "perception_loop", lambda: perception_loop(daemon))
_make_task(daemon, "ambient_refresh_loop", lambda: ambient_refresh_loop(daemon))
_make_task(daemon, "cpal_runner", daemon._cpal_runner.run)
_make_task(daemon, "cpal_impingement_loop", _cpal_impingement_loop)
_make_task(daemon, "impingement_consumer_loop",
           lambda: impingement_consumer_loop(daemon))
if daemon.cfg.mc_enabled or daemon.cfg.obs_enabled:
    _make_task(daemon, "actuation_loop", lambda: actuation_loop(daemon))

# In the main loop, add supervisor check as the FIRST action of every iteration:

while daemon._running:
    _supervise_background_tasks(daemon)   # ← new line, first thing every tick
    daemon.notifications.prune_expired()
    # ... (wav sweep, workspace analysis, rest of the main loop)
    await asyncio.sleep(1)
```

### The supervisor function

```python
# New function at module level:

def _supervise_background_tasks(daemon: VoiceDaemon) -> None:
    """Walk the background task map; observe crashes; apply per-task policy.

    Called every tick of the main control loop.

    Policy:
      CRITICAL_TASKS (audio, CPAL, impingement): fail-hard → SystemExit(1)
        so systemd restarts the daemon. These tasks are the cognitive
        loop spine; silent death yields the "alive but silent" failure
        mode from queue 024 Phase 4.
      RECREATE_TASKS: log the exception and recreate with exponential
        backoff. Bounded retry count (10) to prevent infinite spinning
        on a permanent bug.
      LOG_AND_CONTINUE_TASKS: log the exception and remove from the
        task map. These are strictly decorative subsystems.
    """
    for name, (task, coro_factory) in list(daemon._background_tasks_by_name.items()):
        if not task.done():
            continue
        if task.cancelled():
            # Shutdown path — don't re-raise or recreate
            continue

        exc = task.exception()
        if exc is None:
            # Task completed normally. Only the never-ending coroutines
            # end up here if they return cleanly; recreate or drop.
            if name in RECREATE_TASKS or name in CRITICAL_TASKS:
                log.warning(
                    "background task %s returned normally; recreating", name
                )
                daemon._background_tasks_by_name[name] = (
                    asyncio.create_task(coro_factory(), name=name),
                    coro_factory,
                )
            else:
                del daemon._background_tasks_by_name[name]
            continue

        # Task crashed with an exception.
        log.exception(
            "background task %s crashed", name, exc_info=exc
        )

        if name in CRITICAL_TASKS:
            log.critical(
                "critical task %s crashed — daemon entering fail-closed state",
                name,
            )
            # Emit a structured event before exiting so Langfuse captures it
            daemon.event_log.emit(
                "background_task_crash",
                task_name=name,
                exception_type=type(exc).__name__,
                exception_message=str(exc),
                policy="systemexit",
            )
            raise SystemExit(1)

        if name in RECREATE_TASKS:
            # Exponential backoff via a retry count attribute
            retries = getattr(task, "_retry_count", 0) + 1
            if retries > 10:
                log.error(
                    "background task %s exceeded retry budget (10); escalating to SystemExit",
                    name,
                )
                daemon.event_log.emit(
                    "background_task_crash",
                    task_name=name,
                    exception_type=type(exc).__name__,
                    policy="retry_exhausted_systemexit",
                )
                raise SystemExit(1)
            # Recreate after a delay proportional to retry count
            delay = min(30.0, 2 ** (retries - 1))
            log.info(
                "recreating %s after %.1fs (retry %d/10)",
                name, delay, retries,
            )

            async def _relaunch_with_delay(
                n: str = name,
                factory: Callable[[], Awaitable[None]] = coro_factory,
                d: float = delay,
                r: int = retries,
            ) -> None:
                await asyncio.sleep(d)
                inner = asyncio.create_task(factory(), name=n)
                inner._retry_count = r  # type: ignore[attr-defined]
                daemon._background_tasks_by_name[n] = (inner, factory)

            # The relaunch is itself a task; fire-and-forget is fine here
            # since the outer supervisor will pick up its crash on the next tick.
            asyncio.create_task(_relaunch_with_delay(), name=f"_relaunch_{name}")
            # Remove the dead entry for now; the relaunch task will repopulate it
            del daemon._background_tasks_by_name[name]
            continue

        if name in LOG_AND_CONTINUE_TASKS:
            log.warning("non-critical task %s dropped after crash", name)
            daemon.event_log.emit(
                "background_task_crash",
                task_name=name,
                exception_type=type(exc).__name__,
                policy="drop",
            )
            del daemon._background_tasks_by_name[name]
            continue

        # Unknown task name — default to SystemExit to be safe
        log.critical(
            "unknown background task %s crashed — defaulting to SystemExit", name
        )
        raise SystemExit(1)
```

### Shutdown path compatibility

The existing shutdown path at `run_inner.py:226-228` uses
`daemon._background_tasks` as a list. The new code uses a dict.
Update the shutdown path:

```python
finally:
    # ... existing cleanup ...
    # Cancel all background tasks
    for name, (task, _factory) in daemon._background_tasks_by_name.items():
        task.cancel()
    await asyncio.gather(
        *(t for t, _ in daemon._background_tasks_by_name.values()),
        return_exceptions=True,
    )
    daemon._background_tasks_by_name.clear()
    # ... rest of cleanup ...
```

### Tests

Alpha should add three test cases in
`tests/hapax_daimonion/test_task_supervisor.py`:

```python
async def test_critical_task_crash_triggers_systemexit():
    # Construct a mock daemon with CRITICAL_TASKS containing "crasher"
    # Create a task that raises on first await
    # Call _supervise_background_tasks
    # Assert SystemExit(1) raised
    ...

async def test_recreate_task_exponential_backoff():
    # Construct a mock daemon with RECREATE_TASKS containing "crasher"
    # Count how many times the factory is called after crashes
    # Assert backoff: first retry ~0s, second ~2s, third ~4s, ..., 10th escalates to SystemExit
    ...

async def test_log_and_continue_task_drops_on_crash():
    # Construct a mock daemon with LOG_AND_CONTINUE_TASKS containing "crasher"
    # Crash once
    # Assert the task is removed from the dict, no SystemExit, no recreate
    ...
```

## Observability additions (cheap paired wins)

While touching this code, add:

1. **Prometheus counters** (when the compositor scrape lands via
   queue 024 Phase 2's fix):
   - `hapax_background_task_crashes_total{task_name, policy}`
   - `hapax_background_task_recreations_total{task_name}`
2. **`event_log.emit("background_task_crash", ...)`** — already
   included in the sketch above; gives Langfuse a structured
   event for every crash.
3. **Log line shape consistency** — every crash path uses
   `log.exception` with `exc_info` so the full traceback lands
   in the journal.

## Rejected alternatives

### Pattern 2a — TaskGroup with try/except in each task

We could combine TaskGroup with per-task try/except that
prevents exceptions from propagating. But this just re-implements
the fire-and-forget pattern inside TaskGroup — a task that
suppresses its own exceptions defeats TaskGroup's whole point.
Not useful.

### Pattern 4 — asyncio.gather in a background observer task

```python
async def _observer():
    results = await asyncio.gather(*tasks, return_exceptions=True)
    ...
```

Same problem as the supervisor loop but less explicit per-task
handling. Can use `asyncio.wait(..., return_when=FIRST_EXCEPTION)`
instead but then re-entering the wait on recreate is awkward.
Supervisor loop is simpler.

### Pattern 5 — systemd `Restart=on-failure`

systemd already restarts the daimonion on failure. Could just
let the whole daemon crash whenever any task crashes. But:

- The daimonion takes ~60 s to load all models on startup
- CPAL signal cache presynthesis adds another 20 s
- Bridge phrase presynthesis adds 65 s
- Total cold-start cost: ~2–3 minutes during which the operator
  has no voice

Selective recreate (Pattern 3 with RECREATE_TASKS policy) avoids
the cold-start cost for non-critical subsystems while still
fail-hard-ing on critical crashes. Better than global restart.

## Effort + risk assessment

- **Code change**: ~80 lines in `run_inner.py`, ~60 lines in a
  new `tests/hapax_daimonion/test_task_supervisor.py`
- **Review risk**: low — the change is local, the existing
  shutdown path is preserved, and the supervisor function is
  pure except for calling the SystemExit escape.
- **Runtime risk**: medium during the first deployment — if the
  supervisor has a bug, the daemon might fail-hard on the wrong
  task. Mitigation: ship with RECREATE_TASKS for EVERY task on
  day 1, promote to CRITICAL_TASKS after a 24-hour observation
  window.
- **Rollback**: trivial. Revert the commit. The original code
  is unchanged in structure (just adding supervision, not
  replacing task creation logic).

## Backlog additions (for round-5 retirement handoff)

133. **`fix(daimonion): implement Pattern 3 task supervisor in run_inner.py`** [Phase 1 recommendation] — closes BETA-FINDING-L. Alpha can paste the sketch in Phase 1 doc's § The recommendation section directly, add the three test cases, and ship. Estimated effort: 2–3 hours including tests + review.
134. **`feat(daimonion): hapax_background_task_crashes_total{task_name,policy} counter`** [Phase 1 observability pair] — depends on queue 024 FINDING-H scrape fix landing first.
135. **`research(daimonion): 24-hour observation window with all tasks in RECREATE_TASKS`** [Phase 1 risk mitigation] — ship with soft policy day 1, promote to CRITICAL on day 2 after data shows no false-positive crashes.
136. **`fix(daimonion): event_log.emit('background_task_crash', ...) structured event`** [Phase 1 observability pair] — Langfuse structured events for every crash regardless of policy.

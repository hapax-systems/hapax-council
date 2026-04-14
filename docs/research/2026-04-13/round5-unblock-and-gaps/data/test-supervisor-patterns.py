"""Failure-semantics experiment for the 3 supervisor patterns.

Each test: task_a runs forever (prints tick count), task_b raises after 1s.
We want to see:
  - Does task_a continue or stop?
  - Is the exception observable in the control loop?
  - Is it logged?

Run with: uv run python /tmp/test-supervisor-patterns.py
"""

import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("test")


async def task_a(name: str) -> None:
    """Long-running task that just ticks."""
    for i in range(5):
        log.info("%s tick %d", name, i)
        await asyncio.sleep(0.2)


async def task_b() -> None:
    """Task that raises after ~0.5s."""
    await asyncio.sleep(0.5)
    raise RuntimeError("task_b exploded")


# ── Pattern 1: fire-and-forget (current daimonion behavior) ──
async def pattern_1_fire_and_forget():
    log.info("=== Pattern 1: fire-and-forget create_task ===")
    tasks = []
    tasks.append(asyncio.create_task(task_a("p1_a")))
    tasks.append(asyncio.create_task(task_b()))
    # Main loop continues without supervision
    for i in range(6):
        log.info("main_loop tick %d", i)
        await asyncio.sleep(0.2)
    # At shutdown, gather
    for t in tasks:
        t.cancel()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    log.info("gather results at shutdown: %s", [type(r).__name__ for r in results])


# ── Pattern 2: TaskGroup ──
async def pattern_2_taskgroup():
    log.info("=== Pattern 2: TaskGroup ===")
    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(task_a("p2_a"))
            tg.create_task(task_b())
            # Main loop runs as an async context task inside the group
            # (for clarity we just sleep)
            await asyncio.sleep(2.0)
    except* RuntimeError as eg:
        log.error("TaskGroup caught exception group: %s", eg.exceptions)


# ── Pattern 3: Supervisor loop ──
async def pattern_3_supervisor():
    log.info("=== Pattern 3: Supervisor loop ===")
    tasks = {}
    tasks["a"] = asyncio.create_task(task_a("p3_a"), name="task_a")
    tasks["b"] = asyncio.create_task(task_b(), name="task_b")
    crashed = False
    for i in range(15):
        # Check every tick
        for name, t in list(tasks.items()):
            if t.done() and not t.cancelled():
                exc = t.exception()
                if exc is not None:
                    log.error("task %s crashed: %s: %s", name, type(exc).__name__, exc)
                    tasks.pop(name)
                    crashed = True
        if crashed:
            log.error("supervisor observed crash; would raise SystemExit in real daemon")
            break
        log.info("supervisor tick %d, live tasks: %s", i, list(tasks.keys()))
        await asyncio.sleep(0.2)
    for t in tasks.values():
        t.cancel()
    await asyncio.gather(*tasks.values(), return_exceptions=True)


async def main():
    await pattern_1_fire_and_forget()
    print()
    await pattern_2_taskgroup()
    print()
    await pattern_3_supervisor()


if __name__ == "__main__":
    import uvloop

    uvloop.install()
    asyncio.run(main())

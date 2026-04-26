"""Type-C conditional-refusal watcher (cc-task close-event hook).

Event-driven re-evaluation: when a non-REFUSED cc-task closes, walk all
type-C REFUSED tasks whose ``depends_on_slug`` includes the closed slug
and re-probe via the underlying type (structural / constitutional). The
dependency closing is a *trigger* — whether the refusal lifts depends on
the underlying probe's verdict.

Two integration points:

1. **cc-task close hook** — `cc-close <slug>` invokes
   ``on_cc_task_closed(slug)`` synchronously via import.
2. **inotify fallback** — watchdog Observer on the active/ vault dir
   catches `MOVED_FROM` events when a task is `git mv`-d to closed/
   manually.

Both paths converge on ``on_cc_task_closed``.

No periodic poll — cc-task closes are sparse (≤10/day). Always-on
inotify daemon is cheap.

Spec: ``docs/research/2026-04-25-refused-lifecycle-pipeline.md`` §2.C.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from agents.refused_lifecycle import constitutional_watcher, runner, structural_watcher
from agents.refused_lifecycle.evaluator import decide_transition
from agents.refused_lifecycle.metrics import probes_total
from agents.refused_lifecycle.state import ProbeResult, RefusalTask

log = logging.getLogger(__name__)


def matches_dependency(task: RefusalTask, closed_slug: str) -> bool:
    """Return True if ``closed_slug`` appears in ``task``'s depends_on_slug."""
    raw = (task.evaluation_probe or {}).get("depends_on_slug")
    if raw is None:
        return False
    if isinstance(raw, str):
        return raw == closed_slug
    if isinstance(raw, list):
        return closed_slug in raw
    return False


def find_dependent_tasks(active_dir: Path, closed_slug: str) -> list[RefusalTask]:
    """Walk ``active_dir`` for type-C refusals whose dependency matches."""
    matches: list[RefusalTask] = []
    for task in runner.iter_refused_tasks(active_dir):
        if "conditional" not in task.evaluation_trigger:
            continue
        if matches_dependency(task, closed_slug):
            matches.append(task)
    return matches


async def probe_conditional(task: RefusalTask, *, just_closed: str) -> ProbeResult:
    """Delegate to the underlying probe based on what's configured.

    Pure type-C with no underlying probe is conservatively re-affirmed —
    the dependency closing is recorded as the snippet but the substrate
    does not auto-accept without a probe demonstrating the refusal-
    condition has actually lifted.
    """
    probes_total.labels(trigger="conditional", slug=task.slug).inc()

    probe = task.evaluation_probe or {}
    if probe.get("url"):
        return await structural_watcher.probe_url(task)
    if probe.get("conditional_path"):
        target = Path(probe["conditional_path"]).expanduser()
        return constitutional_watcher.probe_constitutional(task, {target})

    return ProbeResult(
        changed=False,
        snippet=f"dependency-shipped: {just_closed} (no underlying probe configured)",
    )


async def on_cc_task_closed_async(
    closed_slug: str,
    *,
    active_dir: Path | None = None,
) -> int:
    """Async hook — re-evaluate all type-C tasks depending on closed_slug.

    Returns the number of transitions emitted.
    """
    target_dir = active_dir or runner.DEFAULT_ACTIVE_DIR
    matches = find_dependent_tasks(target_dir, closed_slug)
    now = datetime.now(UTC)
    count = 0
    for task in matches:
        result = await probe_conditional(task, just_closed=closed_slug)
        event = decide_transition(task, [result])
        runner.apply_transition(Path(task.path), task, event, now)
        count += 1
    return count


def on_cc_task_closed(closed_slug: str, *, active_dir: Path | None = None) -> int:
    """Sync wrapper for cc-task tool integration.

    The cc-close CLI invokes this synchronously; we run a fresh asyncio
    loop because cc-tools doesn't carry one. Returns transition count.
    """
    return asyncio.run(on_cc_task_closed_async(closed_slug, active_dir=active_dir))


class _CcCloseHandler(FileSystemEventHandler):
    """Watchdog handler for fallback inotify-based detection of cc-close.

    A `MOVED_FROM` event on the active/ dir indicates a task moved to
    closed/. We extract the slug from the original filename and dispatch
    via ``on_cc_task_closed``.
    """

    def __init__(self, active_dir: Path) -> None:
        self.active_dir = active_dir

    def on_moved(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        # `MOVED_FROM` (file moved out of active/) — slug is the stem of src_path
        src = Path(event.src_path)
        if src.parent.resolve() != self.active_dir.resolve():
            return
        if src.suffix != ".md":
            return
        slug = src.stem
        try:
            on_cc_task_closed(slug, active_dir=self.active_dir)
        except Exception:
            log.exception("conditional-watcher: hook failed for %s", slug)


def main(argv: list[str] | None = None) -> int:
    """Always-on inotify daemon."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--active-dir", type=Path, default=runner.DEFAULT_ACTIVE_DIR)
    parser.add_argument(
        "--once-for-slug",
        help="Run the hook for one slug and exit (testing aid)",
    )
    args = parser.parse_args(argv)

    if args.once_for_slug:
        count = on_cc_task_closed(args.once_for_slug, active_dir=args.active_dir)
        print(f"conditional-watcher: re-evaluated {count} type-C tasks")
        return 0

    handler = _CcCloseHandler(args.active_dir)
    observer = Observer()
    observer.schedule(handler, str(args.active_dir), recursive=False)
    observer.start()
    log.info("conditional-watcher started; watching %s", args.active_dir)

    try:
        while True:
            time.sleep(60)
    finally:
        observer.stop()
        observer.join(timeout=5)
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "find_dependent_tasks",
    "main",
    "matches_dependency",
    "on_cc_task_closed",
    "on_cc_task_closed_async",
    "probe_conditional",
]

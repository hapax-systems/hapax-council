"""Async demo generation job manager.

Provides single-concurrent demo execution with progress tracking,
SSE streaming, and persistent job state in profiles/jobs/.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

log = logging.getLogger(__name__)

JOBS_DIR = Path(__file__).resolve().parents[2] / "profiles" / "jobs"


@dataclass
class DemoJob:
    """State of a single demo generation job."""

    id: str
    status: Literal["queued", "running", "complete", "failed", "cancelled"] = "queued"
    request: str = ""
    format: str = "slides"
    created_at: str = ""
    started_at: str | None = None
    completed_at: str | None = None
    phase: str | None = None
    progress_pct: int = 0
    result_path: str | None = None
    error: str | None = None
    # Phase tracking for progress estimation
    _phases_seen: int = field(default=0, repr=False)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("_phases_seen", None)
        return d


# Rough phase count for progress estimation (varies by format)
_ESTIMATED_PHASES = {
    "slides": 14,
    "video": 20,
    "markdown-only": 8,
}


class DemoJobManager:
    """Manages async demo generation with single-concurrent execution."""

    def __init__(self, jobs_dir: Path = JOBS_DIR) -> None:
        self._jobs_dir = jobs_dir
        self._jobs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._current_task: asyncio.Task | None = None
        self._current_job_id: str | None = None
        self._cancel_event: asyncio.Event | None = None
        # Per-job queues for SSE streaming (job_id -> Queue)
        self._queues: dict[str, asyncio.Queue[dict | None]] = {}

    def submit(self, request: str, format: str = "slides") -> DemoJob:
        """Create a new demo job and start it in the background.

        Returns immediately with the queued job. Raises if another
        job is already running.
        """
        if self._current_task is not None and not self._current_task.done():
            raise RuntimeError(
                f"Demo generation already in progress (job {self._current_job_id}). "
                "Cancel it first or wait for completion."
            )

        job = DemoJob(
            id=str(uuid.uuid4()),
            request=request,
            format=format,
            created_at=datetime.now(UTC).isoformat(),
        )
        self._save(job)

        self._cancel_event = asyncio.Event()
        self._current_job_id = job.id
        self._queues[job.id] = asyncio.Queue()
        self._current_task = asyncio.create_task(self._run_demo(job))
        self._current_task.add_done_callback(lambda _: self._cleanup(job.id))

        log.info("Demo job %s submitted: %s (format=%s)", job.id, request[:60], format)
        return job

    async def cancel(self, job_id: str) -> bool:
        """Cancel a running job. Returns True if cancelled, False if not found/not running."""
        if self._current_job_id != job_id or self._current_task is None:
            return False

        if self._current_task.done():
            return False

        log.info("Cancelling demo job %s", job_id)
        if self._cancel_event:
            self._cancel_event.set()
        self._current_task.cancel()

        try:
            await self._current_task
        except (asyncio.CancelledError, Exception):
            pass

        job = self.get(job_id)
        if job and job.status == "running":
            job.status = "cancelled"
            job.completed_at = datetime.now(UTC).isoformat()
            self._save(job)

        return True

    def get(self, job_id: str) -> DemoJob | None:
        """Read job state from disk."""
        path = self._jobs_dir / f"{job_id}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return DemoJob(**{k: v for k, v in data.items() if not k.startswith("_")})
        except (json.JSONDecodeError, TypeError) as e:
            log.warning("Failed to read job %s: %s", job_id, e)
            return None

    def list_jobs(self, limit: int = 20) -> list[dict]:
        """List recent jobs, newest first."""
        jobs = []
        for path in sorted(self._jobs_dir.glob("*.json"), reverse=True):
            try:
                data = json.loads(path.read_text())
                data.pop("_phases_seen", None)
                jobs.append(data)
            except (json.JSONDecodeError, TypeError):
                continue
            if len(jobs) >= limit:
                break
        return jobs

    async def stream(self, job_id: str) -> AsyncIterator[dict]:
        """Yield SSE events for a job. Completes when job finishes."""
        queue = self._queues.get(job_id)
        if queue is None:
            # Job not actively running — yield current state and stop
            job = self.get(job_id)
            if job:
                if job.status == "complete":
                    yield {"event": "done", "data": {"job_id": job_id, "path": job.result_path}}
                elif job.status == "failed":
                    yield {"event": "error", "data": {"job_id": job_id, "message": job.error}}
                elif job.status == "cancelled":
                    yield {"event": "cancelled", "data": {"job_id": job_id}}
            return

        while True:
            event = await queue.get()
            if event is None:
                break
            yield event

    async def _run_demo(self, job: DemoJob) -> None:
        """Execute generate_demo() with progress tracking."""
        from agents.demo import generate_demo

        job.status = "running"
        job.started_at = datetime.now(UTC).isoformat()
        self._save(job)

        queue = self._queues.get(job.id)
        total_phases = _ESTIMATED_PHASES.get(job.format, 14)

        def on_progress(msg: str) -> None:
            job.phase = msg
            job._phases_seen += 1
            job.progress_pct = min(95, int(job._phases_seen / total_phases * 100))
            self._save(job)
            if queue:
                queue.put_nowait(
                    {
                        "event": "progress",
                        "data": {"job_id": job.id, "phase": msg, "progress_pct": job.progress_pct},
                    }
                )

        try:
            demo_dir = await generate_demo(
                job.request,
                format=job.format,
                on_progress=on_progress,
            )
            job.status = "complete"
            job.progress_pct = 100
            job.result_path = str(demo_dir)
            job.completed_at = datetime.now(UTC).isoformat()
            self._save(job)
            if queue:
                queue.put_nowait(
                    {
                        "event": "done",
                        "data": {"job_id": job.id, "path": str(demo_dir)},
                    }
                )
            log.info("Demo job %s complete: %s", job.id, demo_dir)

        except asyncio.CancelledError:
            job.status = "cancelled"
            job.completed_at = datetime.now(UTC).isoformat()
            self._save(job)
            if queue:
                queue.put_nowait({"event": "cancelled", "data": {"job_id": job.id}})
            log.info("Demo job %s cancelled", job.id)

        except Exception as e:
            job.status = "failed"
            job.error = str(e)
            job.completed_at = datetime.now(UTC).isoformat()
            self._save(job)
            if queue:
                queue.put_nowait(
                    {
                        "event": "error",
                        "data": {"job_id": job.id, "message": str(e)},
                    }
                )
            log.error("Demo job %s failed: %s", job.id, e, exc_info=True)

    def _cleanup(self, job_id: str) -> None:
        """Clean up after a job completes."""
        queue = self._queues.pop(job_id, None)
        if queue:
            queue.put_nowait(None)  # Sentinel to end stream
        if self._current_job_id == job_id:
            self._current_task = None
            self._current_job_id = None
            self._cancel_event = None

    def _save(self, job: DemoJob) -> None:
        """Atomically persist job state to disk."""
        path = self._jobs_dir / f"{job.id}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(job.to_dict(), indent=2))
        tmp.replace(path)

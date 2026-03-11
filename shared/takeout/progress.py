"""progress.py — Resumable progress tracking for long-running ingestion.

A 50GB Takeout export can take hours. This tracker enables:
- Ctrl+C and resume without re-processing completed services
- Per-service status tracking
- Record counts and timing

State persisted as JSONL at ~/.cache/takeout-ingest/progress.jsonl
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from shared.config import TAKEOUT_STATE_DIR

log = logging.getLogger("takeout.progress")

PROGRESS_DIR = TAKEOUT_STATE_DIR
PROGRESS_FILE = PROGRESS_DIR / "progress.jsonl"


@dataclass
class ServiceProgress:
    """Progress state for a single service."""

    service: str
    status: str = "pending"  # pending, in_progress, completed, failed
    records_processed: int = 0
    records_skipped: int = 0
    started_at: float = 0.0
    completed_at: float = 0.0
    error: str = ""


class ProgressTracker:
    """JSONL-based resumable progress for long-running ingestion.

    Usage:
        tracker = ProgressTracker("takeout-2025-06-15.zip")
        if not tracker.is_completed("chrome"):
            tracker.start_service("chrome")
            # ... process chrome ...
            tracker.complete_service("chrome", records=150)
    """

    def __init__(self, run_id: str, progress_dir: Path = PROGRESS_DIR):
        self.run_id = run_id
        self.progress_dir = progress_dir
        self.progress_file = progress_dir / f"{run_id}.json"
        self._services: dict[str, ServiceProgress] = {}
        self._load()

    def _load(self) -> None:
        """Load progress state from disk."""
        if not self.progress_file.exists():
            return

        try:
            data = json.loads(self.progress_file.read_text())
            for svc_data in data.get("services", []):
                sp = ServiceProgress(
                    service=svc_data["service"],
                    status=svc_data.get("status", "pending"),
                    records_processed=svc_data.get("records_processed", 0),
                    records_skipped=svc_data.get("records_skipped", 0),
                    started_at=svc_data.get("started_at", 0),
                    completed_at=svc_data.get("completed_at", 0),
                    error=svc_data.get("error", ""),
                )
                self._services[sp.service] = sp
        except (json.JSONDecodeError, KeyError) as e:
            log.warning("Failed to load progress: %s", e)

    def _save(self) -> None:
        """Persist progress state to disk."""
        self.progress_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "run_id": self.run_id,
            "updated_at": datetime.now().isoformat(),
            "services": [
                {
                    "service": sp.service,
                    "status": sp.status,
                    "records_processed": sp.records_processed,
                    "records_skipped": sp.records_skipped,
                    "started_at": sp.started_at,
                    "completed_at": sp.completed_at,
                    "error": sp.error,
                }
                for sp in self._services.values()
            ],
        }
        import os as _os
        import tempfile

        tmp_fd, tmp_path = tempfile.mkstemp(dir=self.progress_dir, suffix=".tmp")
        try:
            _os.write(tmp_fd, json.dumps(data, indent=2).encode())
            _os.close(tmp_fd)
            _os.replace(tmp_path, self.progress_file)
        except BaseException:
            _os.close(tmp_fd)
            _os.unlink(tmp_path)
            raise

    def is_completed(self, service: str) -> bool:
        """Check if a service has been fully processed."""
        sp = self._services.get(service)
        return sp is not None and sp.status == "completed"

    def start_service(self, service: str) -> None:
        """Mark a service as in-progress."""
        self._services[service] = ServiceProgress(
            service=service,
            status="in_progress",
            started_at=time.time(),
        )
        self._save()
        log.info("Started: %s", service)

    def complete_service(
        self,
        service: str,
        records: int = 0,
        skipped: int = 0,
    ) -> None:
        """Mark a service as completed."""
        sp = self._services.get(service, ServiceProgress(service=service))
        sp.status = "completed"
        sp.records_processed = records
        sp.records_skipped = skipped
        sp.completed_at = time.time()
        self._services[service] = sp
        self._save()

        elapsed = sp.completed_at - sp.started_at if sp.started_at else 0
        log.info("Completed: %s — %d records in %.1fs", service, records, elapsed)

    def fail_service(self, service: str, error: str) -> None:
        """Mark a service as failed."""
        sp = self._services.get(service, ServiceProgress(service=service))
        sp.status = "failed"
        sp.error = error
        sp.completed_at = time.time()
        self._services[service] = sp
        self._save()
        log.error("Failed: %s — %s", service, error)

    def summary(self) -> dict:
        """Return a summary of all service statuses."""
        return {
            "run_id": self.run_id,
            "services": {
                sp.service: {
                    "status": sp.status,
                    "records": sp.records_processed,
                    "skipped": sp.records_skipped,
                }
                for sp in self._services.values()
            },
            "completed": sum(1 for sp in self._services.values() if sp.status == "completed"),
            "failed": sum(1 for sp in self._services.values() if sp.status == "failed"),
            "pending": sum(1 for sp in self._services.values() if sp.status == "pending"),
        }

    def get_incomplete_services(self, all_services: list[str]) -> list[str]:
        """Return services that haven't been completed yet."""
        return [s for s in all_services if not self.is_completed(s)]

"""Runtime SHM flow observation — correlates writers with readers."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from logos.event_bus import EventBus

log = logging.getLogger(__name__)

DEFAULT_SHM_ROOT = Path("/dev/shm")


class FlowObserver:
    """Observes SHM directories to discover actual data flows.

    Correlates file writers (by directory name convention ``hapax-{agent}``)
    with registered readers (from manifest ``pipeline_state.path``).
    """

    def __init__(
        self,
        shm_root: Path = DEFAULT_SHM_ROOT,
        decay_seconds: float = 60.0,
        event_bus: EventBus | None = None,
    ):
        self._shm_root = shm_root
        self._decay_seconds = decay_seconds
        self._writers: dict[str, dict[str, float]] = {}
        self._readers: dict[str, str] = {}
        self._observed: dict[tuple[str, str], float] = {}
        self._prev_mtimes: dict[str, float] = {}
        self._event_bus = event_bus

    def register_reader(self, agent_id: str, state_path: str) -> None:
        """Register an agent as a reader of a specific state file."""
        self._readers[agent_id] = state_path

    def scan(self) -> None:
        """Scan SHM directories for recent writes and correlate with readers."""
        now = time.time()

        for d in self._shm_root.iterdir():
            if not d.is_dir() or not d.name.startswith("hapax-"):
                continue
            writer_name = d.name
            for f in d.iterdir():
                if not f.is_file():
                    continue
                try:
                    mtime = f.stat().st_mtime
                except OSError:
                    continue
                self._writers.setdefault(writer_name, {})[f.name] = mtime

                # Emit shm.write event when mtime changes
                full_path = str(f)
                prev_mtime = self._prev_mtimes.get(full_path)
                if prev_mtime is not None and mtime != prev_mtime and self._event_bus is not None:
                    agent_name = writer_name.removeprefix("hapax-")
                    for reader_id, reader_path in self._readers.items():
                        if reader_path == full_path:
                            from logos.event_bus import FlowEvent

                            self._event_bus.emit(
                                FlowEvent(
                                    kind="shm.write",
                                    source=agent_name,
                                    target=reader_id,
                                    label=f"{f.name} updated",
                                )
                            )
                self._prev_mtimes[full_path] = mtime

                for reader_id, reader_path in self._readers.items():
                    if reader_path == full_path:
                        if now - mtime < 30:
                            self._observed[(writer_name, reader_id)] = now

        expired = [k for k, v in self._observed.items() if now - v > self._decay_seconds]
        for k in expired:
            del self._observed[k]

    def get_writers(self) -> dict[str, dict[str, float]]:
        """Return current writer map."""
        return dict(self._writers)

    def get_observed_edges(self) -> set[tuple[str, str]]:
        """Return set of (writer, reader) pairs currently observed."""
        return set(self._observed.keys())

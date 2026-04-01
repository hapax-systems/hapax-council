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

# Verified consumption map: producer_node_id → [consumer_node_ids]
# Derived from codebase audit — each entry is a proven code-level read
# of one agent's SHM state file by another agent's source code.
_VERIFIED_CONSUMERS: dict[str, list[str]] = {
    "stimmung_sync": ["hapax_daimonion", "reactive_engine", "studio_compositor"],
    "temporal_bands": ["hapax_daimonion", "studio_compositor"],
    "apperception": ["hapax_daimonion"],
    "studio_compositor": ["hapax_daimonion"],
    "dmn": ["hapax_daimonion", "studio_compositor"],
    "hapax_daimonion": ["studio_compositor"],
}


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
        self._event_bus = event_bus
        self._prev_mtimes: dict[str, float] = {}
        # Map SHM directory names to manifest node IDs.
        # Most populated dynamically via register_reader, but some agents
        # don't have SHM-based state paths (e.g., daimonion uses ~/.cache).
        self._writer_node_map: dict[str, str] = {
            "stimmung": "stimmung_sync",
            "temporal": "temporal_bands",
            "compositor": "studio_compositor",
            "daimonion": "hapax_daimonion",
            "dmn": "dmn",
        }

    def register_reader(self, agent_id: str, state_path: str) -> None:
        """Register an agent as a reader of a specific state file."""
        self._readers[agent_id] = state_path

    def scan(self) -> None:
        """Scan SHM directories for recent writes and correlate with readers."""
        now = time.time()

        for d in self._shm_root.iterdir():
            if not d.is_dir() or not d.name.startswith("hapax-"):
                continue
            writer_name = d.name.removeprefix("hapax-")
            for f in d.iterdir():
                if not f.is_file():
                    continue
                try:
                    mtime = f.stat().st_mtime
                except OSError:
                    continue
                self._writers.setdefault(writer_name, {})[f.name] = mtime

                # Resolve writer to node ID (SHM dir name -> manifest ID)
                source_node = self._writer_node_map.get(writer_name, writer_name)

                # Emit shm.write events when mtime changes
                full_path = str(f)
                prev = self._prev_mtimes.get(full_path)
                if prev is not None and mtime != prev and self._event_bus:
                    from logos.event_bus import FlowEvent

                    # Route only to verified consumers (code-level reads)
                    targets = _VERIFIED_CONSUMERS.get(source_node, [])
                    for target_id in targets:
                        self._event_bus.emit(
                            FlowEvent(
                                kind="shm.write",
                                source=source_node,
                                target=target_id,
                                label=f.name,
                            )
                        )
                self._prev_mtimes[full_path] = mtime

                for reader_id, reader_path in self._readers.items():
                    if reader_path == full_path:
                        if now - mtime < 30:
                            self._observed[(source_node, reader_id)] = now

        expired = [k for k, v in self._observed.items() if now - v > self._decay_seconds]
        for k in expired:
            del self._observed[k]

    def get_writers(self) -> dict[str, dict[str, float]]:
        """Return current writer map."""
        return dict(self._writers)

    def get_observed_edges(self) -> set[tuple[str, str]]:
        """Return set of (writer, reader) pairs currently observed."""
        return set(self._observed.keys())

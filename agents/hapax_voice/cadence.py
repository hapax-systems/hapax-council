"""CadenceGroup — multi-cadence dispatch for perception backends.

Different backends polled at different rates, each cadence emitting its own
tick Event. CadenceGroup writes to the shared engine.behaviors dict so fast-cadence
updates are immediately visible to the 2.5s tick's with_latest_from.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from agents.hapax_voice.perception import PerceptionBackend
from agents.hapax_voice.primitives import Behavior, Event

log = logging.getLogger(__name__)


@dataclass
class CadenceGroup:
    """A group of backends polled at a shared interval.

    Each poll cycle calls contribute() on all backends, then emits a tick event.
    The tick event enables combinator wiring: with_latest_from(group.tick_event, behaviors).
    """

    name: str
    interval_s: float
    backends: list[PerceptionBackend] = field(default_factory=list)
    tick_event: Event[float] = field(default_factory=lambda: Event[float]())

    def register(self, backend: PerceptionBackend) -> None:
        """Add a backend to this cadence group."""
        self.backends.append(backend)

    def poll(self, behaviors: dict[str, Behavior]) -> None:
        """Poll all backends, then emit tick event."""
        now = time.monotonic()
        for backend in self.backends:
            try:
                backend.contribute(behaviors)
            except Exception:
                log.exception("Backend %s contribute failed in cadence group %s", backend.name, self.name)
        self.tick_event.emit(now, now)

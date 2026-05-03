"""ControlSignal — per-component perceptual control error reporting.

Each S1 component in the cognitive mesh computes a ControlSignal on each tick:
- reference: what the component expects to perceive
- perception: what the component actually perceives
- error: abs(reference - perception)

Published to /dev/shm/hapax-{component}/health.json for mesh-wide aggregation.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ControlSignal:
    """A single control error measurement."""

    component: str
    reference: float
    perception: float

    @property
    def error(self) -> float:
        return abs(self.reference - self.perception)

    def to_dict(self) -> dict:
        return {
            "component": self.component,
            "reference": self.reference,
            "perception": self.perception,
            "error": self.error,
            "timestamp": time.time(),
        }


def publish_health(signal: ControlSignal, *, path: Path | None = None) -> None:
    """Write component health to /dev/shm atomically."""
    if path is None:
        path = Path(f"/dev/shm/hapax-{signal.component}/health.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{time.monotonic_ns()}.tmp")
    tmp.write_text(json.dumps(signal.to_dict()), encoding="utf-8")
    tmp.replace(path)

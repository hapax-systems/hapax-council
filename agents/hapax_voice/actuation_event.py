"""ActuationEvent — immutable record of a completed actuation.

Emitted by ExecutorRegistry on successful dispatch. Feeds back into
the perception layer via Behaviors, closing the perception→actuation→feedback loop.
"""

from __future__ import annotations

import types
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ActuationEvent:
    """Record of a completed actuation with latency tracking.

    Frozen dataclass — immutable like Command, Schedule, and Stamped.
    """

    action: str
    chain: str = ""
    wall_time: float = 0.0
    target_time: float = 0.0
    latency_ms: float = 0.0
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "params", types.MappingProxyType(self.params))

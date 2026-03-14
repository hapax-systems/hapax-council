"""ActuationEvent — immutable record of a completed actuation.

Emitted by ExecutorRegistry on successful dispatch. Feeds back into
the perception layer via Behaviors, closing the perception→actuation→feedback loop.

Consent threading (DD-22 L8): consent_label propagated from the Command
that triggered the actuation. Closes the IFC loop: perception → FusedContext
→ Command → ActuationEvent → feedback Behaviors → back to perception.
"""

from __future__ import annotations

import types
from dataclasses import dataclass, field
from typing import Any

from shared.consent_label import ConsentLabel


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
    consent_label: ConsentLabel | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "params", types.MappingProxyType(self.params))

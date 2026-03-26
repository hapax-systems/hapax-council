"""Affordance-as-retrieval — relational capability selection models.

Capabilities are described in function-free natural language, embedded,
and indexed in Qdrant. Selection uses ACT-R activation (recency + frequency),
Thompson Sampling (exploration-exploitation), and biased competition
(mutual suppression). Associations are learned through outcome feedback.

See: docs/superpowers/specs/2026-03-25-affordance-retrieval-architecture.md
"""

from __future__ import annotations

import math
import random
import time
from typing import Any

from pydantic import BaseModel, Field


class OperationalProperties(BaseModel, frozen=True):
    """Hard constraints for filtering, not semantic matching."""

    requires_gpu: bool = False
    requires_network: bool = False
    latency_class: str = "fast"  # fast (<1s), moderate (1-30s), slow (>30s)
    persistence: str = "none"  # none, session, permanent
    consent_required: bool = False
    priority_floor: bool = False


class CapabilityRecord(BaseModel, frozen=True):
    """A capability indexed in the affordance landscape."""

    name: str
    description: str  # function-free property description
    daemon: str  # which daemon owns this capability
    operational: OperationalProperties = Field(default_factory=OperationalProperties)


class ActivationState(BaseModel):
    """Mutable ACT-R activation + Thompson Sampling state per capability.

    ACT-R base-level uses Petrov (2006) k=1 approximation:
    B_i = ln( t_1^{-d} + 2(n-1) / (sqrt(t_n) + sqrt(t_1)) )

    Thompson Sampling uses discounted Beta distribution (gamma=0.99).
    """

    use_count: int = 0
    last_use_ts: float = 0.0
    first_use_ts: float = 0.0
    ts_alpha: float = 1.0
    ts_beta: float = 1.0

    def base_level(self, now: float, decay: float = 0.5) -> float:
        """Petrov k=1 approximation of ACT-R base-level activation."""
        if self.use_count == 0:
            return -10.0
        t1 = max(0.001, now - self.last_use_ts)
        if self.use_count == 1:
            return math.log(t1 ** (-decay))
        tn = max(0.001, now - self.first_use_ts)
        recent = t1 ** (-decay)
        old_approx = 2 * (self.use_count - 1) / (tn**0.5 + t1**0.5)
        return math.log(recent + old_approx)

    def thompson_sample(self) -> float:
        """Sample from discounted Beta posterior."""
        return random.betavariate(max(0.01, self.ts_alpha), max(0.01, self.ts_beta))

    def record_success(self, gamma: float = 0.99) -> None:
        """Record successful activation. Discount then increment."""
        now = time.time()
        self.ts_alpha = self.ts_alpha * gamma + 1.0
        self.ts_beta *= gamma
        self.use_count += 1
        if self.first_use_ts == 0.0:
            self.first_use_ts = now
        self.last_use_ts = now

    def record_failure(self, gamma: float = 0.99) -> None:
        """Record failed activation (e.g., operator dismissal)."""
        self.ts_alpha *= gamma
        self.ts_beta = self.ts_beta * gamma + 1.0


class SelectionCandidate(BaseModel):
    """A capability retrieved and scored for selection."""

    capability_name: str
    similarity: float = 0.0
    base_level: float = 0.0
    context_boost: float = 0.0
    thompson_score: float = 0.0
    cost_weight: float = 1.0
    combined: float = 0.0
    suppressed: bool = False
    payload: dict[str, Any] = Field(default_factory=dict)

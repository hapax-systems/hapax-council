"""Affordance-as-retrieval — relational capability selection models."""

from __future__ import annotations

import math
import random
import time
from typing import Any

from pydantic import BaseModel, Field


class OperationalProperties(BaseModel, frozen=True):
    requires_gpu: bool = False
    requires_network: bool = False
    latency_class: str = "fast"
    persistence: str = "none"
    medium: str | None = None
    consent_required: bool = False
    priority_floor: bool = False


class CapabilityRecord(BaseModel, frozen=True):
    name: str
    description: str
    daemon: str
    operational: OperationalProperties = Field(default_factory=OperationalProperties)


class ActivationState(BaseModel):
    use_count: int = 0
    last_use_ts: float = 0.0
    first_use_ts: float = 0.0
    ts_alpha: float = 2.0
    ts_beta: float = 1.0

    # Cap alpha/beta to prevent Thompson saturation. Without a cap, the
    # geometric decay formula (alpha * 0.99 + 1.0) converges to 100.0,
    # producing Beta(100, ~0) which samples ~1.0 deterministically. With
    # a cap of 10, Beta(10, 1) samples ~0.9 with variance ~0.008 — still
    # exploitative but occasionally dips low enough for newcomers at
    # Beta(2, 1) = 0.67 to win a competition.
    _TS_CAP: float = 10.0

    def base_level(self, now: float, decay: float = 0.5) -> float:
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
        return random.betavariate(max(0.01, self.ts_alpha), max(0.01, self.ts_beta))

    # Floor for the opposing parameter. Without a floor, beta decays to 0.01
    # under sustained success, making Beta(10, 0.01) ≈ 1.0 deterministic.
    # Floor of 1.0 means Beta(10, 1) samples ~0.91 with variance ~0.007 —
    # still exploitative but with enough variance for newcomers to occasionally win.
    _TS_FLOOR: float = 1.0

    def record_success(self, gamma: float = 0.99) -> None:
        now = time.time()
        self.ts_alpha = min(self._TS_CAP, self.ts_alpha * gamma + 1.0)
        self.ts_beta = max(self._TS_FLOOR, self.ts_beta * gamma)
        self.use_count += 1
        if self.first_use_ts == 0.0:
            self.first_use_ts = now
        self.last_use_ts = now

    def record_failure(self, gamma: float = 0.99) -> None:
        self.ts_alpha = max(self._TS_FLOOR, self.ts_alpha * gamma)
        self.ts_beta = min(self._TS_CAP, self.ts_beta * gamma + 1.0)
        self.use_count += 1

    def to_summary(self) -> dict[str, float]:
        """Summary for cross-daemon visibility via Qdrant payload."""
        total = self.ts_alpha + self.ts_beta
        return {
            "use_count": self.use_count,
            "last_use_ts": self.last_use_ts,
            "ts_alpha": self.ts_alpha,
            "ts_beta": self.ts_beta,
            "success_rate": self.ts_alpha / total if total > 0 else 0.5,
        }


class SelectionCandidate(BaseModel):
    capability_name: str
    similarity: float = 0.0
    base_level: float = 0.0
    context_boost: float = 0.0
    thompson_score: float = 0.0
    cost_weight: float = 1.0
    combined: float = 0.0
    suppressed: bool = False
    payload: dict[str, Any] = Field(default_factory=dict)

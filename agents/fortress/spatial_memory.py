"""Spatial memory with ACT-R base-level activation decay."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum

from agents.fortress.config import PerceptionConfig


class EntityMobility(StrEnum):
    STATIC = "static"  # walls, rooms — decay slowly
    SLOW = "slow"  # stockpile levels — moderate decay
    FAST = "fast"  # creatures, jobs — decay quickly


class MemoryState(StrEnum):
    IMPRESSION = "impression"  # vivid, recently observed
    RETENTION = "retention"  # fading but available
    FORGOTTEN = "forgotten"  # pruned, fog of war


TICKS_PER_DAY = 1200  # normalization constant


@dataclass
class SpatialMemory:
    """Memory of a single observed patch."""

    patch_id: str
    last_observation: str  # NL description from last query
    observation_ticks: list[int] = field(default_factory=list)
    entity_mobility: EntityMobility = EntityMobility.STATIC
    semantic_summary: str | None = None

    def activation(self, current_tick: int, d: float = 0.5) -> float:
        """ACT-R base-level activation: ln(sum (delta_t / TICKS_PER_DAY)^(-d))."""
        if not self.observation_ticks:
            return float("-inf")
        total = 0.0
        for t in self.observation_ticks:
            delta = max(1, current_tick - t) / TICKS_PER_DAY
            total += delta ** (-d)
        return math.log(max(total, 1e-10))

    def confidence(self, current_tick: int, d: float = 0.5) -> float:
        """Belief confidence [0, 1] adjusted for entity mobility."""
        act = self.activation(current_tick, d)
        mobility_factor = {
            EntityMobility.STATIC: 1.0,
            EntityMobility.SLOW: 1.5,
            EntityMobility.FAST: 3.0,
        }[self.entity_mobility]
        # Sigmoid mapping: activation -> confidence, penalized by mobility
        adjusted = act / mobility_factor
        return 1.0 / (1.0 + math.exp(-adjusted - 1.0))


def memory_state(activation: float, config: PerceptionConfig) -> MemoryState:
    if activation > 0:
        return MemoryState.IMPRESSION
    if activation > config.forget_threshold:
        return MemoryState.RETENTION
    return MemoryState.FORGOTTEN


class SpatialMemoryStore:
    """Manages spatial memories for all observed patches."""

    def __init__(self, config: PerceptionConfig | None = None) -> None:
        self._config = config or PerceptionConfig()
        self._memories: dict[str, SpatialMemory] = {}

    def observe(
        self,
        patch_id: str,
        description: str,
        tick: int,
        mobility: EntityMobility = EntityMobility.STATIC,
    ) -> None:
        if patch_id in self._memories:
            mem = self._memories[patch_id]
            mem.last_observation = description
            mem.observation_ticks.append(tick)
            self._trim_history(mem)
        else:
            self._memories[patch_id] = SpatialMemory(
                patch_id=patch_id,
                last_observation=description,
                observation_ticks=[tick],
                entity_mobility=mobility,
            )

    def recall(self, patch_id: str, current_tick: int) -> tuple[MemoryState, str | None]:
        mem = self._memories.get(patch_id)
        if mem is None:
            return MemoryState.FORGOTTEN, None
        act = mem.activation(current_tick, self._config.decay_exponent)
        state = memory_state(act, self._config)
        if state == MemoryState.FORGOTTEN:
            return state, None
        if state == MemoryState.RETENTION and mem.semantic_summary:
            return state, mem.semantic_summary
        return state, mem.last_observation

    def consolidate(self, current_tick: int) -> int:
        """Consolidate fading memories. Returns count of consolidated."""
        count = 0
        for mem in self._memories.values():
            act = mem.activation(current_tick, self._config.decay_exponent)
            if act < self._config.consolidation_threshold and mem.semantic_summary is None:
                # Simple consolidation: truncate description
                if len(mem.last_observation) > 50:
                    mem.semantic_summary = mem.last_observation[:80] + "..."
                    count += 1
        return count

    def prune(self, current_tick: int) -> int:
        """Remove forgotten memories. Returns count pruned."""
        to_remove = []
        for pid, mem in self._memories.items():
            act = mem.activation(current_tick, self._config.decay_exponent)
            if act < self._config.forget_threshold:
                to_remove.append(pid)
        for pid in to_remove:
            del self._memories[pid]
        return len(to_remove)

    def active_memories(self, current_tick: int) -> list[SpatialMemory]:
        result = []
        for mem in self._memories.values():
            act = mem.activation(current_tick, self._config.decay_exponent)
            if memory_state(act, self._config) != MemoryState.FORGOTTEN:
                result.append(mem)
        return sorted(result, key=lambda m: m.activation(current_tick), reverse=True)

    def __len__(self) -> int:
        return len(self._memories)

    def _trim_history(self, mem: SpatialMemory) -> None:
        if len(mem.observation_ticks) > self._config.max_observation_history:
            mem.observation_ticks = mem.observation_ticks[-self._config.max_observation_history :]

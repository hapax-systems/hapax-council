"""Fortress metrics and survival tracking.

Tracks survival time, per-chain governance effectiveness,
and session records. See docs/superpowers/specs/2026-03-23-fortress-metrics-and-survival.md.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field

from agents._config import PROFILES_DIR
from agents.fortress.schema import FastFortressState

log = logging.getLogger(__name__)

SESSIONS_PATH = PROFILES_DIR / "fortress-sessions.jsonl"


@dataclass
class ChainMetrics:
    """Per-chain governance counters."""

    commands_issued: int = 0
    commands_vetoed: int = 0
    llm_calls: int = 0


@dataclass
class FortressSessionTracker:
    """Tracks a single fortress session's metrics."""

    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    fortress_name: str = ""
    start_time: float = 0.0
    start_tick: int = 0
    end_tick: int = 0
    peak_population: int = 0
    final_population: int = 0
    cause_of_death: str = ""
    chain_metrics: dict[str, ChainMetrics] = field(default_factory=dict)
    total_commands: int = 0
    events_summary: dict[str, int] = field(default_factory=dict)

    def start(self, state: FastFortressState) -> None:
        self.fortress_name = state.fortress_name
        self.start_time = time.time()
        self.start_tick = state.game_tick
        self.peak_population = state.population
        for chain in (
            "fortress_planner",
            "military_commander",
            "resource_manager",
            "crisis_responder",
            "storyteller",
            "advisor",
        ):
            self.chain_metrics[chain] = ChainMetrics()

    def update(self, state: FastFortressState) -> None:
        self.end_tick = state.game_tick
        self.final_population = state.population
        if state.population > self.peak_population:
            self.peak_population = state.population

    def record_command(self, chain: str, vetoed: bool = False) -> None:
        if chain not in self.chain_metrics:
            self.chain_metrics[chain] = ChainMetrics()
        if vetoed:
            self.chain_metrics[chain].commands_vetoed += 1
        else:
            self.chain_metrics[chain].commands_issued += 1
            self.total_commands += 1

    def record_event(self, event_type: str) -> None:
        self.events_summary[event_type] = self.events_summary.get(event_type, 0) + 1

    @property
    def survival_ticks(self) -> int:
        return self.end_tick - self.start_tick

    @property
    def survival_days(self) -> int:
        return self.survival_ticks // 1200

    @property
    def survival_years(self) -> float:
        return self.survival_ticks / 403200

    def is_fortress_dead(self, state: FastFortressState) -> bool:
        """Check if fortress is in an unrecoverable state."""
        if state.population == 0:
            return True
        return state.food_count == 0 and state.drink_count == 0

    def finalize(self, cause: str = "unknown") -> dict:
        self.cause_of_death = cause
        record = {
            "session_id": self.session_id,
            "fortress_name": self.fortress_name,
            "start_time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.start_time)),
            "end_time": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "start_tick": self.start_tick,
            "end_tick": self.end_tick,
            "survival_days": self.survival_days,
            "survival_years": round(self.survival_years, 2),
            "peak_population": self.peak_population,
            "final_population": self.final_population,
            "cause_of_death": cause,
            "total_commands": self.total_commands,
            "chain_metrics": {
                k: {"issued": v.commands_issued, "vetoed": v.commands_vetoed}
                for k, v in self.chain_metrics.items()
            },
            "events_summary": self.events_summary,
        }
        SESSIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        # jsonl-rotation: exempt(registry candidate — consumer shrink-audit pending, see audit-w0 follow-up)
        with SESSIONS_PATH.open("a") as f:
            f.write(json.dumps(record) + "\n")
        log.info(
            "Session %s finalized: %d days, cause=%s",
            self.session_id,
            self.survival_days,
            cause,
        )
        return record

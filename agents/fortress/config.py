"""Fortress configuration — bridge paths, poll intervals, governance defaults."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class BridgeConfig:
    """DFHack bridge file paths and polling intervals."""

    state_dir: Path = field(default_factory=lambda: Path("/dev/shm/hapax-df"))
    state_file: str = "state.json"
    commands_file: str = "commands.json"
    results_file: str = "results.json"
    staleness_threshold_s: float = 30.0

    @property
    def state_path(self) -> Path:
        return self.state_dir / self.state_file

    @property
    def commands_path(self) -> Path:
        return self.state_dir / self.commands_file

    @property
    def results_path(self) -> Path:
        return self.state_dir / self.results_file


@dataclass(frozen=True)
class SuppressionConfig:
    """Default suppression field timing parameters."""

    crisis_attack_s: float = 0.1
    crisis_release_s: float = 5.0
    military_attack_s: float = 0.5
    military_release_s: float = 3.0
    resource_attack_s: float = 1.0
    resource_release_s: float = 2.0
    planner_attack_s: float = 0.3
    planner_release_s: float = 0.5
    creativity_attack_s: float = 0.5
    creativity_release_s: float = 10.0
    creativity_floor: float = 0.05
    creativity_ceiling: float = 0.90
    suppression_floor: float = 0.0
    suppression_ceiling: float = 0.95


@dataclass(frozen=True)
class PerceptionConfig:
    """ACT-R spatial memory and attention budget parameters."""

    decay_exponent: float = 0.5
    consolidation_threshold: float = -1.0
    forget_threshold: float = -3.0
    max_observation_history: int = 20
    budget_base: int = 5
    budget_scale: float = 1.8
    budget_cap: int = 30


@dataclass(frozen=True)
class CreativityConfig:
    """Creativity activation parameters."""

    bell_center: float = 0.4
    bell_width: float = 0.2
    base_epsilon: float = 0.30
    maslow_food_per_capita: int = 5
    maslow_drink_per_capita: int = 3
    maslow_idle_ratio: float = 0.3
    maslow_stress_threshold: int = 100_000
    neuroception_threshold: float = 0.7
    stress_normalizer: int = 200_000


@dataclass(frozen=True)
class FortressConfig:
    """Top-level fortress agent configuration."""

    bridge: BridgeConfig = field(default_factory=BridgeConfig)
    suppression: SuppressionConfig = field(default_factory=SuppressionConfig)
    perception: PerceptionConfig = field(default_factory=PerceptionConfig)
    creativity: CreativityConfig = field(default_factory=CreativityConfig)
    min_population_for_military: int = 10
    food_critical_threshold: int = 10  # per capita
    drink_critical_threshold: int = 5  # per capita
    recovery_cooldown_ticks: int = 2400  # 2 days

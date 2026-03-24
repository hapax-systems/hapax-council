"""Creativity metrics — policy entropy, novelty, narrative density."""

from __future__ import annotations

import math
from dataclasses import dataclass, field


def policy_entropy(action_counts: dict[str, int]) -> float:
    """Shannon entropy of action distribution. Higher = more diverse."""
    total = sum(action_counts.values())
    if total == 0:
        return 0.0
    entropy = 0.0
    for count in action_counts.values():
        if count > 0:
            p = count / total
            entropy -= p * math.log2(p)
    return entropy


def novelty_score(current_action: str, prior_actions: list[str]) -> float:
    """Novelty based on action frequency. 1.0 = never seen, 0.0 = always seen."""
    if not prior_actions:
        return 1.0
    frequency = prior_actions.count(current_action)
    return 1.0 - (frequency / len(prior_actions))


def narrative_density(episode_count: int, game_years: float) -> float:
    """Episodes per game year. Higher = richer narrative."""
    if game_years <= 0:
        return 0.0
    return episode_count / game_years


def semantic_injection_rate(decisions_with_ref: int, total_decisions: int) -> float:
    """Fraction of decisions referencing external knowledge."""
    if total_decisions == 0:
        return 0.0
    return decisions_with_ref / total_decisions


@dataclass
class CreativityMetrics:
    """Tracks creativity metrics for a fortress session."""

    action_counts: dict[str, int] = field(default_factory=dict)
    prior_actions: list[str] = field(default_factory=list)
    episode_count: int = 0
    game_ticks: int = 0
    semantic_refs: int = 0
    total_decisions: int = 0

    def record_action(self, action: str, has_semantic_ref: bool = False) -> None:
        self.action_counts[action] = self.action_counts.get(action, 0) + 1
        self.prior_actions.append(action)
        self.total_decisions += 1
        if has_semantic_ref:
            self.semantic_refs += 1

    def record_episode(self) -> None:
        self.episode_count += 1

    def update_ticks(self, ticks: int) -> None:
        self.game_ticks = ticks

    def compute_score(
        self,
        weights: tuple[float, ...] | None = None,
    ) -> float:
        """Weighted composite creativity score."""
        w = weights or (0.25, 0.25, 0.25, 0.25)
        game_years = max(0.01, self.game_ticks / 403_200)

        pe = policy_entropy(self.action_counts)
        ns = novelty_score(
            self.prior_actions[-1] if self.prior_actions else "",
            self.prior_actions[:-1] if len(self.prior_actions) > 1 else [],
        )
        nd = narrative_density(self.episode_count, game_years)
        sir = semantic_injection_rate(self.semantic_refs, self.total_decisions)

        # Normalize each to [0, 1] range approximately
        pe_norm = min(1.0, pe / 3.0)  # max entropy ~3 bits for 8 actions
        nd_norm = min(1.0, nd / 20.0)  # 20 episodes/year is very high

        return w[0] * pe_norm + w[1] * ns + w[2] * nd_norm + w[3] * sir

    def to_dict(self) -> dict:
        game_years = max(0.01, self.game_ticks / 403_200)
        return {
            "policy_entropy": round(policy_entropy(self.action_counts), 3),
            "latest_novelty": round(
                novelty_score(
                    self.prior_actions[-1] if self.prior_actions else "",
                    self.prior_actions[:-1] if len(self.prior_actions) > 1 else [],
                ),
                3,
            ),
            "narrative_density": round(narrative_density(self.episode_count, game_years), 3),
            "semantic_injection_rate": round(
                semantic_injection_rate(self.semantic_refs, self.total_decisions), 3
            ),
            "composite_score": round(self.compute_score(), 3),
            "total_decisions": self.total_decisions,
            "episode_count": self.episode_count,
        }

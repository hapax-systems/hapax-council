"""Fortress suppression topology — graduated inter-chain modulation.

Four suppression fields implementing Brooks' subsumption with graduated
inhibition. See docs/superpowers/specs/2026-03-23-fortress-suppression-topology.md.

Reuses SuppressionField from agents.hapax_daimonion.suppression without modification.
"""

from __future__ import annotations

from agents.fortress.config import SuppressionConfig
from agents.hapax_daimonion.suppression import SuppressionField


def create_fortress_suppression_fields(
    config: SuppressionConfig | None = None,
) -> dict[str, SuppressionField]:
    """Create the 5 fortress suppression fields with configured timing."""
    cfg = config or SuppressionConfig()
    return {
        "crisis_suppression": SuppressionField(
            attack_s=cfg.crisis_attack_s,
            release_s=cfg.crisis_release_s,
        ),
        "military_alert": SuppressionField(
            attack_s=cfg.military_attack_s,
            release_s=cfg.military_release_s,
        ),
        "resource_pressure": SuppressionField(
            attack_s=cfg.resource_attack_s,
            release_s=cfg.resource_release_s,
        ),
        "planner_activity": SuppressionField(
            attack_s=cfg.planner_attack_s,
            release_s=cfg.planner_release_s,
        ),
        "creativity_suppression": SuppressionField(
            attack_s=cfg.creativity_attack_s,
            release_s=cfg.creativity_release_s,
        ),
    }

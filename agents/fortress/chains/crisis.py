"""Crisis Responder governance chain.

Decides emergency response level: lockdown, targeted response, heightened alert.
Works with FastFortressState (food_count/drink_count/active_threats/stress).
"""

from __future__ import annotations

from agents.fortress.config import FortressConfig
from agents.fortress.schema import FastFortressState
from agents.hapax_daimonion.governance import (
    Candidate,
    FallbackChain,
    Selected,
    Veto,
    VetoChain,
    VetoResult,
)


class CrisisResponderChain:
    """Governance chain for emergency response decisions."""

    CHAIN_NAME = "crisis_responder"

    def __init__(self, config: FortressConfig | None = None) -> None:
        self._config = config or FortressConfig()
        self._last_activation_tick: int = -self._config.recovery_cooldown_ticks

        self._veto_chain: VetoChain[FastFortressState] = VetoChain(
            [
                Veto(
                    "not_in_cooldown",
                    self._not_in_cooldown,
                    description="Crisis response cooldown period",
                ),
            ]
        )
        self._fallback: FallbackChain[FastFortressState, str] = FallbackChain(
            candidates=[
                Candidate("immediate_lockdown", self._famine_and_siege, "immediate_lockdown"),
                Candidate("targeted_response", self._has_threats, "targeted_response"),
                Candidate("heightened_alert", self._extreme_stress, "heightened_alert"),
            ],
            default="no_action",
        )

    def _not_in_cooldown(self, state: FastFortressState) -> bool:
        return state.game_tick - self._last_activation_tick >= self._config.recovery_cooldown_ticks

    @staticmethod
    def _famine_and_siege(state: FastFortressState) -> bool:
        return state.active_threats > 30 and state.food_count < state.population * 5

    @staticmethod
    def _has_threats(state: FastFortressState) -> bool:
        return state.active_threats > 0

    @staticmethod
    def _extreme_stress(state: FastFortressState) -> bool:
        return state.most_stressed_value > 100000

    def evaluate(self, state: FastFortressState) -> tuple[VetoResult, Selected[str]]:
        """Evaluate crisis level. Records activation tick for cooldown."""
        veto_result = self._veto_chain.evaluate(state)
        if not veto_result.allowed:
            return veto_result, Selected(action="no_action", selected_by="vetoed")
        selection = self._fallback.select(state)
        if selection.action != "no_action":
            self._last_activation_tick = state.game_tick
        return veto_result, selection

"""FortressGovernor — central orchestrator wiring all governance chains.

Evaluation loop: read state -> check suppression -> evaluate chains ->
wrap in ResourceClaim -> arbitrate -> collect commands for dispatch.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from agents.fortress.chains.advisor import AdvisorChain
from agents.fortress.chains.creativity import CreativityChain
from agents.fortress.chains.crisis import CrisisResponderChain
from agents.fortress.chains.military import MilitaryCommanderChain
from agents.fortress.chains.planner import FortressPlannerChain
from agents.fortress.chains.resource import ResourceManagerChain
from agents.fortress.chains.storyteller import StorytellerChain
from agents.fortress.commands import FortressCommand
from agents.fortress.config import FortressConfig
from agents.fortress.schema import FastFortressState, FullFortressState
from agents.fortress.suppression import create_fortress_suppression_fields
from agents.hapax_voice.suppression import SuppressionField

log = logging.getLogger(__name__)


class FortressGovernor:
    """Wires 7 chains + 5 suppression fields into a coherent governance loop."""

    def __init__(self, config: FortressConfig | None = None) -> None:
        self._config = config or FortressConfig()

        # Chains
        self._planner = FortressPlannerChain()
        self._military = MilitaryCommanderChain()
        self._resource = ResourceManagerChain()
        self._storyteller = StorytellerChain()
        self._advisor = AdvisorChain()
        self._crisis = CrisisResponderChain(config=self._config)
        self._creativity = CreativityChain()

        # Cached full state for chains that need it
        self._last_full_state: FullFortressState | None = None

        # Suppression fields
        self._fields = create_fortress_suppression_fields(self._config.suppression)

        # Track last evaluation time for suppression ticking
        self._last_tick_time: float = 0.0

    @property
    def suppression_fields(self) -> dict[str, SuppressionField]:
        return dict(self._fields)

    def tick_suppression(self, now: float | None = None) -> dict[str, float]:
        """Advance all suppression fields and return current levels."""
        t = now or time.monotonic()
        self._last_tick_time = t
        return {name: field.tick(t) for name, field in self._fields.items()}

    def governor_state(self) -> dict[str, Any]:
        """Return serializable snapshot of governance state."""
        return {
            "suppression": {name: field.value for name, field in self._fields.items()},
        }

    def evaluate(
        self,
        state: FastFortressState | FullFortressState,
    ) -> list[FortressCommand]:
        """Run one governance evaluation cycle.

        Caches last FullFortressState so planner/military chains can
        evaluate even when the bridge sends FastFortressState.
        """
        now = time.monotonic()

        # Cache full state for chains that need it
        if isinstance(state, FullFortressState):
            self._last_full_state = state
        full = getattr(self, "_last_full_state", None)
        levels = self.tick_suppression(now)
        commands: list[FortressCommand] = []

        # --- Crisis first (L4, top of subsumption) ---
        # Crisis works on FastFortressState (food/drink/threats/stress)
        crisis_veto, crisis_action = self._crisis.evaluate(state)
        if crisis_action.action != "no_action":
            self._fields["crisis_suppression"].set_target(1.0, now)
            commands.append(
                FortressCommand(
                    id="",
                    action="military",
                    chain="crisis_responder",
                    params={"operation": crisis_action.action},
                )
            )
        else:
            self._fields["crisis_suppression"].set_target(0.0, now)

        # --- Military (L2) — suppressed by resource_pressure (uses cached full state) ---
        if full is not None:
            resource_supp = levels.get("resource_pressure", 0.0)
            if resource_supp < self._config.suppression.suppression_ceiling:
                mil_veto, mil_action = self._military.evaluate(full)
                if mil_action.action != "no_action" and mil_veto.allowed:
                    self._fields["military_alert"].set_target(
                        0.5 if mil_action.action == "defensive_position" else 1.0, now
                    )
                    commands.append(
                        FortressCommand(
                            id="",
                            action="military",
                            chain="military_commander",
                            params={"operation": mil_action.action},
                        )
                    )
                else:
                    self._fields["military_alert"].set_target(0.0, now)

        # --- Resource manager (L0) — works on FastFortressState ---
        crisis_supp = levels.get("crisis_suppression", 0.0)
        planner_supp = levels.get("planner_activity", 0.0)
        combined_supp = max(crisis_supp, planner_supp)
        if combined_supp < self._config.suppression.suppression_ceiling:
            res_veto, res_action = self._resource.evaluate(state)
            if res_action.action != "no_action" and res_veto.allowed:
                if state.food_count < state.population * self._config.food_critical_threshold:
                    self._fields["resource_pressure"].set_target(0.8, now)
                else:
                    self._fields["resource_pressure"].set_target(0.0, now)
                commands.append(
                    FortressCommand(
                        id="",
                        action="order",
                        chain="resource_manager",
                        params={"operation": res_action.action},
                    )
                )

        # --- Planner (L1) — suppressed by crisis, military (uses cached full state) ---
        if full is not None:
            crisis_supp = levels.get("crisis_suppression", 0.0)
            military_supp = levels.get("military_alert", 0.0)
            combined_supp = max(crisis_supp, military_supp)
            if combined_supp < self._config.suppression.suppression_ceiling:
                plan_veto, plan_action = self._planner.evaluate(full)
                if plan_action.action != "no_action" and plan_veto.allowed:
                    self._fields["planner_activity"].set_target(0.5, now)
                    commands.append(
                        FortressCommand(
                            id="",
                            action="dig",
                            chain="fortress_planner",
                            params={"operation": plan_action.action},
                        )
                    )
                else:
                    self._fields["planner_activity"].set_target(0.0, now)

        # --- Storyteller (L3, never suppresses others) ---
        story_veto, story_action = self._storyteller.evaluate(state)
        # Storyteller produces narrative, not game commands — handled separately

        # --- Creativity (L3.5) — gated by safety + suppression (uses cached full state) ---
        if full is not None:
            max_lower = max(
                levels.get("crisis_suppression", 0.0),
                levels.get("military_alert", 0.0),
                levels.get("resource_pressure", 0.0),
            )
            self._fields["creativity_suppression"].set_target(max_lower, now)

            creativity_supp = levels.get("creativity_suppression", 0.0)
            if creativity_supp < self._config.suppression.creativity_ceiling:
                creat_veto, creat_action = self._creativity.evaluate(full)
                if creat_action.action != "no_action" and creat_veto.allowed:
                    commands.append(
                        FortressCommand(
                            id="",
                            action="creativity",
                            chain="creativity",
                            params={"operation": creat_action.action},
                        )
                    )

        return commands

"""cockpit/engine/executor.py — Three-phase action executor with semaphore bounds."""

from __future__ import annotations

import asyncio
import logging
import time

from cockpit.engine.models import Action, ActionPlan

_log = logging.getLogger(__name__)


class PhasedExecutor:
    """Executes actions phase-by-phase with concurrency control.

    Phase 0: Unlimited concurrency (deterministic work).
    Phase 1: GPU semaphore (local LLM inference).
    Phase 2: Cloud semaphore (cloud LLM APIs).
    """

    def __init__(
        self,
        gpu_concurrency: int = 1,
        cloud_concurrency: int = 2,
        action_timeout_s: float = 120,
    ) -> None:
        self._gpu_sem = asyncio.Semaphore(gpu_concurrency)
        self._cloud_sem = asyncio.Semaphore(cloud_concurrency)
        self._action_timeout_s = action_timeout_s

    def _semaphore_for_phase(self, phase: int) -> asyncio.Semaphore | None:
        if phase == 1:
            return self._gpu_sem
        if phase == 2:
            return self._cloud_sem
        return None

    async def _run_action(
        self, action: Action, plan: ActionPlan, sem: asyncio.Semaphore | None
    ) -> None:
        # Check dependencies
        for dep in action.depends_on:
            if dep in plan.errors or dep in plan.skipped:
                plan.skipped.add(action.name)
                _log.debug("Skipping %s: dependency %s failed/skipped", action.name, dep)
                return

        from shared.telemetry import hapax_span

        with hapax_span(
            "engine",
            f"action.{action.name}",
            metadata={"phase": action.phase, "priority": action.priority},
        ) as _action_span:
            try:
                _t_wait = time.monotonic()
                if sem is not None:
                    async with sem:
                        _t_run = time.monotonic()
                        if _action_span is not None:
                            try:
                                _action_span.update(
                                    metadata={
                                        "semaphore_wait_ms": round((_t_run - _t_wait) * 1000),
                                    }
                                )
                            except Exception:
                                pass
                        result = await asyncio.wait_for(
                            action.handler(**action.args), timeout=self._action_timeout_s
                        )
                else:
                    result = await asyncio.wait_for(
                        action.handler(**action.args), timeout=self._action_timeout_s
                    )
                plan.results[action.name] = result
            except TimeoutError:
                msg = f"Timed out after {self._action_timeout_s}s"
                plan.errors[action.name] = msg
                _log.warning("Action %s: %s", action.name, msg)
            except Exception as exc:
                plan.errors[action.name] = str(exc)
                _log.exception("Action %s failed", action.name)

    async def execute(self, plan: ActionPlan) -> ActionPlan:
        """Execute all actions in the plan, phase by phase."""
        phases = plan.actions_by_phase()

        for phase_num in sorted(phases.keys()):
            actions = phases[phase_num]
            sem = self._semaphore_for_phase(phase_num)

            tasks = [self._run_action(action, plan, sem) for action in actions]
            await asyncio.gather(*tasks)

        return plan

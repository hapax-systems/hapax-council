"""Universal axiom enforcement wrapper for pydantic-ai agents.

Intercepts agent output and runs axiom pattern checks before returning.
Raises AxiomViolationError on T0 violations when blocking is enabled.
"""

from __future__ import annotations

import logging
from typing import Any, TypeVar

from shared.axiom_enforcer import enforce_output

logger = logging.getLogger(__name__)

R = TypeVar("R")


class AxiomViolationError(Exception):
    """Raised when agent output violates a T0 axiom pattern."""

    def __init__(self, agent_id: str, violations: list[Any]) -> None:
        self.agent_id = agent_id
        self.violations = violations
        ids = ", ".join(v.pattern_id for v in violations)
        super().__init__(f"Agent {agent_id} output blocked by axiom enforcement: {ids}")


def _extract_text(output: Any) -> str:
    """Extract checkable text from agent output."""
    if isinstance(output, str):
        return output
    if hasattr(output, "model_dump_json"):
        return output.model_dump_json()
    return str(output)


async def run_enforced(
    agent: Any,
    prompt: str,
    *,
    agent_id: str,
    deps: Any | None = None,
    output_path: str = "",
) -> Any:
    """Run a pydantic-ai agent with mandatory axiom enforcement on output."""
    if deps is not None:
        result = await agent.run(prompt, deps=deps)
    else:
        result = await agent.run(prompt)

    text = _extract_text(result.output)
    enforcement = enforce_output(text, agent_id, output_path)

    if not enforcement.allowed:
        logger.warning(
            "Axiom enforcement blocked output from %s: %s",
            agent_id,
            [v.pattern_id for v in enforcement.violations],
        )
        raise AxiomViolationError(agent_id, enforcement.violations)

    if enforcement.violations:
        logger.info(
            "Axiom enforcement advisory for %s: %s",
            agent_id,
            [v.pattern_id for v in enforcement.violations],
        )

    return result.output

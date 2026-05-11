"""Governor wrapper: per-agent governance validation.

Each agent gets a governance wrapper that validates inputs against consent
contracts before processing and validates outputs against axiom enforcement
before persistence. The wrapper is a pure validation layer — it does not
modify data, only allows or denies flow.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agentgov.consent_label import ConsentLabel
from agentgov.labeled import Labeled


@dataclass(frozen=True)
class GovernorDenial:
    """Outcome when a governor denies a data flow."""

    agent_id: str
    direction: str
    reason: str
    axiom_ids: tuple[str, ...] = ()
    data_category: str = ""


@dataclass(frozen=True)
class GovernorResult:
    """Outcome of a governor check."""

    allowed: bool
    denial: GovernorDenial | None = None


@dataclass(frozen=True)
class GovernorPolicy:
    """A single governance policy for an agent.

    Policies are evaluated in order. First denial wins.
    """

    name: str
    check: Callable[[str, Labeled[Any]], bool]
    axiom_id: str = ""
    description: str = ""


class GovernorWrapper:
    """Per-agent governance wrapper.

    Validates labeled data at agent boundaries:
    - Input: checks consent labels before agent processes data
    - Output: checks axiom compliance before data is persisted

    The wrapper is a pure filter — it does not transform data.
    """

    __slots__ = ("_agent_id", "_input_policies", "_output_policies", "_audit_log")

    def __init__(self, agent_id: str) -> None:
        self._agent_id = agent_id
        self._input_policies: list[GovernorPolicy] = []
        self._output_policies: list[GovernorPolicy] = []
        self._audit_log: list[GovernorResult] = []

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def audit_log(self) -> list[GovernorResult]:
        return list(self._audit_log)

    def add_input_policy(self, policy: GovernorPolicy) -> None:
        self._input_policies.append(policy)

    def add_output_policy(self, policy: GovernorPolicy) -> None:
        self._output_policies.append(policy)

    def check_input(self, data: Labeled[Any]) -> GovernorResult:
        return self._evaluate("input", self._input_policies, data)

    def check_output(self, data: Labeled[Any]) -> GovernorResult:
        return self._evaluate("output", self._output_policies, data)

    def _evaluate(
        self, direction: str, policies: list[GovernorPolicy], data: Labeled[Any]
    ) -> GovernorResult:
        denials: list[str] = []
        axiom_ids: list[str] = []
        for policy in policies:
            if not policy.check(self._agent_id, data):
                denials.append(policy.name)
                if policy.axiom_id:
                    axiom_ids.append(policy.axiom_id)

        if denials:
            result = GovernorResult(
                allowed=False,
                denial=GovernorDenial(
                    agent_id=self._agent_id,
                    direction=direction,
                    reason=f"Denied by: {', '.join(denials)}",
                    axiom_ids=tuple(axiom_ids),
                ),
            )
        else:
            result = GovernorResult(allowed=True)

        self._audit_log.append(result)
        return result


def consent_input_policy(required_label: ConsentLabel) -> GovernorPolicy:
    """Create a policy that validates input consent labels."""

    def _check(agent_id: str, data: Labeled[Any]) -> bool:
        return data.label.can_flow_to(required_label)

    return GovernorPolicy(
        name="consent_input",
        check=_check,
        axiom_id="interpersonal_transparency",
        description=f"Input must flow to {required_label}",
    )


def consent_output_policy(max_label: ConsentLabel) -> GovernorPolicy:
    """Create a policy that validates output consent labels."""

    def _check(agent_id: str, data: Labeled[Any]) -> bool:
        return data.label.can_flow_to(max_label)

    return GovernorPolicy(
        name="consent_output",
        check=_check,
        axiom_id="interpersonal_transparency",
        description=f"Output must flow to {max_label}",
    )

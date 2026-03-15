"""Governor wrapper: per-agent governance validation (§8.3, AMELI pattern).

Each agent gets a governance wrapper that validates inputs against consent
contracts before processing and validates outputs against axiom enforcement
before persistence. The wrapper mediates all interactions, following AMELI's
regimentation-via-proxy approach.

The GovernorWrapper is a pure validation layer — it does not modify data,
only allows or denies flow. Denial produces a GovernorDenial with audit
trail. The filesystem-as-bus architecture makes this feasible: governors
intercept at read/write boundaries.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from shared.governance.consent_label import ConsentLabel
from shared.governance.labeled import Labeled


@dataclass(frozen=True)
class GovernorDenial:
    """Outcome when a governor denies a data flow."""

    agent_id: str
    direction: str  # "input" | "output"
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

    Policies are evaluated in order. First denial wins (deny-wins,
    consistent with VetoChain semantics).
    """

    name: str
    check: Callable[[str, Labeled[Any]], bool]
    axiom_id: str = ""
    description: str = ""


class GovernorWrapper:
    """Per-agent governance wrapper (§8.3 AMELI pattern).

    Validates labeled data at agent boundaries:
    - Input: checks consent labels before agent processes data
    - Output: checks axiom compliance before data is persisted

    The wrapper is a pure filter — it does not transform data.
    All decisions are logged to the audit trail.
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
        """Add a policy for validating inputs to this agent."""
        self._input_policies.append(policy)

    def add_output_policy(self, policy: GovernorPolicy) -> None:
        """Add a policy for validating outputs from this agent."""
        self._output_policies.append(policy)

    def check_input(self, data: Labeled[Any]) -> GovernorResult:
        """Validate labeled data before agent processing."""
        return self._evaluate("input", self._input_policies, data)

    def check_output(self, data: Labeled[Any]) -> GovernorResult:
        """Validate labeled data before persistence."""
        return self._evaluate("output", self._output_policies, data)

    def _evaluate(
        self, direction: str, policies: list[GovernorPolicy], data: Labeled[Any]
    ) -> GovernorResult:
        """Evaluate all policies. First denial wins."""
        for policy in policies:
            if not policy.check(self._agent_id, data):
                result = GovernorResult(
                    allowed=False,
                    denial=GovernorDenial(
                        agent_id=self._agent_id,
                        direction=direction,
                        reason=f"Policy '{policy.name}' denied",
                        axiom_ids=(policy.axiom_id,) if policy.axiom_id else (),
                    ),
                )
                self._audit_log.append(result)
                return result

        result = GovernorResult(allowed=True)
        self._audit_log.append(result)
        return result


def consent_input_policy(required_label: ConsentLabel) -> GovernorPolicy:
    """Create a policy that validates input consent labels.

    Data must have a consent label that can flow to the required label.
    Unlabeled data (label = bottom) is treated as public and always flows.
    """

    def _check(agent_id: str, data: Labeled[Any]) -> bool:
        return data.label.can_flow_to(required_label)

    return GovernorPolicy(
        name="consent_input",
        check=_check,
        axiom_id="interpersonal_transparency",
        description=f"Input must flow to {required_label}",
    )


def consent_output_policy(max_label: ConsentLabel) -> GovernorPolicy:
    """Create a policy that validates output consent labels.

    Output data's label must be able to flow to max_label (i.e., output
    must not be more restrictive than the agent is permitted to produce).
    """

    def _check(agent_id: str, data: Labeled[Any]) -> bool:
        return data.label.can_flow_to(max_label)

    return GovernorPolicy(
        name="consent_output",
        check=_check,
        axiom_id="interpersonal_transparency",
        description=f"Output must flow to {max_label}",
    )

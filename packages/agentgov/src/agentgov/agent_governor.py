"""Agent governor factory: builds GovernorWrapper from axiom bindings.

Translates declarative axiom bindings in agent manifests into runtime
governance policies. Each agent gets a GovernorWrapper configured with
input/output policies derived from its axiom relationships.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from agentgov.consent_label import ConsentLabel
from agentgov.governor import (
    GovernorPolicy,
    GovernorWrapper,
    consent_input_policy,
    consent_output_policy,
)
from agentgov.labeled import Labeled

_log = logging.getLogger(__name__)

PolicyBuilder = Callable[[str], tuple[list[GovernorPolicy], list[GovernorPolicy]]]


def interpersonal_transparency_policies(
    role: str,
) -> tuple[list[GovernorPolicy], list[GovernorPolicy]]:
    """Build policies for the interpersonal_transparency axiom."""
    input_policies: list[GovernorPolicy] = []
    output_policies: list[GovernorPolicy] = []

    if role in ("subject", "enforcer"):
        input_policies.append(consent_input_policy(ConsentLabel.bottom()))
        output_policies.append(consent_output_policy(ConsentLabel.bottom()))

    return input_policies, output_policies


def corporate_boundary_policies(
    role: str,
) -> tuple[list[GovernorPolicy], list[GovernorPolicy]]:
    """Build policies for the corporate_boundary axiom."""
    input_policies: list[GovernorPolicy] = []
    output_policies: list[GovernorPolicy] = []

    if role in ("subject", "enforcer"):

        def _no_work_data(_agent_id: str, data: Labeled[Any]) -> bool:
            if not (hasattr(data, "metadata") and isinstance(data.metadata, dict)):
                _log.warning("corporate_boundary: denying data with no metadata dict (fail-closed)")
                return False
            category = data.metadata.get("data_category")
            if category is None:
                _log.warning(
                    "corporate_boundary: denying data with no data_category key (fail-closed)"
                )
                return False
            return category != "work"

        output_policies.append(
            GovernorPolicy(
                name="corporate_boundary_output",
                check=_no_work_data,
                axiom_id="corporate_boundary",
                description="Block work data from persisting to home system",
            )
        )

    return input_policies, output_policies


DEFAULT_AXIOM_BUILDERS: dict[str, PolicyBuilder] = {
    "interpersonal_transparency": interpersonal_transparency_policies,
    "corporate_boundary": corporate_boundary_policies,
}


def create_agent_governor(
    agent_id: str,
    axiom_bindings: list[dict[str, Any]] | None = None,
    *,
    axiom_builders: dict[str, PolicyBuilder] | None = None,
    binding_loader: Callable[[str], list[Any]] | None = None,
) -> GovernorWrapper:
    """Build a GovernorWrapper from agent manifest axiom bindings.

    Args:
        agent_id: Agent identifier.
        axiom_bindings: List of binding dicts with keys 'axiom_id', 'role'.
        axiom_builders: Custom axiom-to-policy mapping. Defaults to
            built-in interpersonal_transparency and corporate_boundary.
        binding_loader: Optional callable to load bindings from an
            external registry when axiom_bindings is None.
    """
    gov = GovernorWrapper(agent_id)
    builders = axiom_builders or DEFAULT_AXIOM_BUILDERS

    bindings = axiom_bindings
    if bindings is None and binding_loader is not None:
        bindings = binding_loader(agent_id)
    if bindings is None:
        bindings = []

    for binding in bindings:
        axiom_id = binding.get("axiom_id", "") if isinstance(binding, dict) else binding.axiom_id
        role = binding.get("role", "subject") if isinstance(binding, dict) else binding.role

        builder = builders.get(axiom_id)
        if builder is None:
            continue

        input_policies, output_policies = builder(role)
        for p in input_policies:
            gov.add_input_policy(p)
        for p in output_policies:
            gov.add_output_policy(p)

        _log.debug(
            "Governor %s: added %d input + %d output policies for %s",
            agent_id,
            len(input_policies),
            len(output_policies),
            axiom_id,
        )

    return gov

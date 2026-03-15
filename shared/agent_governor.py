"""Agent governor factory: builds GovernorWrapper from manifest axiom bindings.

Translates declarative axiom bindings in agent manifests into runtime
governance policies. Each agent gets a GovernorWrapper configured with
input/output policies derived from its axiom relationships.

The factory pattern ensures consistent policy construction across all agents
and centralizes the mapping from axiom IDs to concrete validation policies.

See §8.3 (AMELI pattern) and DD-8 (consent governance).
"""

from __future__ import annotations

import logging
from typing import Any

from shared.consent_label import ConsentLabel
from shared.governor import (
    GovernorPolicy,
    GovernorWrapper,
    consent_input_policy,
    consent_output_policy,
)
from shared.labeled import Labeled

_log = logging.getLogger(__name__)

# ── Axiom-specific policy builders ──────────────────────────────────


def _interpersonal_transparency_policies(
    role: str,
) -> tuple[list[GovernorPolicy], list[GovernorPolicy]]:
    """Build policies for the interpersonal_transparency axiom.

    Agents bound to this axiom must validate consent labels on data
    about non-operator persons. The policy requires that input data's
    consent label can flow to the agent's processing context (bottom =
    public data, always allowed).

    Returns (input_policies, output_policies).
    """
    input_policies: list[GovernorPolicy] = []
    output_policies: list[GovernorPolicy] = []

    if role in ("subject", "enforcer"):
        # Input: data must have valid consent for this agent to process
        input_policies.append(
            consent_input_policy(ConsentLabel.bottom())
        )
        # Output: agent must not produce data with labels it doesn't hold
        output_policies.append(
            consent_output_policy(ConsentLabel.bottom())
        )

    return input_policies, output_policies


def _corporate_boundary_policies(
    role: str,
) -> tuple[list[GovernorPolicy], list[GovernorPolicy]]:
    """Build policies for the corporate_boundary axiom.

    Agents must not write work data to the home system. This is a
    structural constraint enforced by the data category check.
    """
    input_policies: list[GovernorPolicy] = []
    output_policies: list[GovernorPolicy] = []

    if role in ("subject", "enforcer"):

        def _no_work_data(_agent_id: str, data: Labeled[Any]) -> bool:
            """Deny data categorized as work/employer data."""
            if hasattr(data, "metadata") and isinstance(data.metadata, dict):
                return data.metadata.get("data_category") != "work"
            return True  # No metadata = no category = allowed

        output_policies.append(
            GovernorPolicy(
                name="corporate_boundary_output",
                check=_no_work_data,
                axiom_id="corporate_boundary",
                description="Block work data from persisting to home system",
            )
        )

    return input_policies, output_policies


# Registry of axiom ID → policy builder
_AXIOM_POLICY_BUILDERS: dict[
    str,
    type[
        tuple[list[GovernorPolicy], list[GovernorPolicy]]
    ],
] = {}

_AXIOM_BUILDERS = {
    "interpersonal_transparency": _interpersonal_transparency_policies,
    "corporate_boundary": _corporate_boundary_policies,
}


# ── Factory ─────────────────────────────────────────────────────────


def create_agent_governor(
    agent_id: str,
    axiom_bindings: list[dict[str, Any]] | None = None,
) -> GovernorWrapper:
    """Build a GovernorWrapper from agent manifest axiom bindings.

    If axiom_bindings is not provided, attempts to load the agent's
    manifest from the registry. Falls back to an empty (permissive)
    governor if the manifest is not found.

    Args:
        agent_id: Agent identifier (e.g., "audio_processor").
        axiom_bindings: Optional list of binding dicts with keys
            'axiom_id', 'role', 'implications'. If None, loaded from manifest.

    Returns:
        A configured GovernorWrapper.
    """
    gov = GovernorWrapper(agent_id)

    bindings = axiom_bindings
    if bindings is None:
        bindings = _load_bindings_from_manifest(agent_id)

    for binding in bindings:
        axiom_id = binding.get("axiom_id", "") if isinstance(binding, dict) else binding.axiom_id
        role = binding.get("role", "subject") if isinstance(binding, dict) else binding.role

        builder = _AXIOM_BUILDERS.get(axiom_id)
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


def _load_bindings_from_manifest(agent_id: str) -> list[Any]:
    """Load axiom bindings from agent manifest via registry."""
    try:
        from shared.agent_registry import AgentRegistry

        registry = AgentRegistry()
        registry.load()
        manifest = registry.get(agent_id)
        if manifest is None:
            _log.debug("No manifest found for %s, using empty governor", agent_id)
            return []
        return manifest.axiom_bindings
    except Exception:
        _log.debug("Could not load manifest for %s", agent_id, exc_info=True)
        return []

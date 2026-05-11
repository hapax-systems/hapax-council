"""Agent governor factory — extends agentgov with hapax agent registry integration."""

from __future__ import annotations

import logging
from typing import Any

from agentgov.agent_governor import (
    DEFAULT_AXIOM_BUILDERS,
    PolicyBuilder,
    corporate_boundary_policies,
    interpersonal_transparency_policies,
)
from agentgov.agent_governor import (
    create_agent_governor as _base_create,
)
from agentgov.governor import GovernorPolicy, GovernorWrapper

_log = logging.getLogger(__name__)


def _load_bindings_from_manifest(agent_id: str) -> list[Any]:
    """Load axiom bindings from agent manifest via hapax registry."""
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


def create_agent_governor(
    agent_id: str,
    axiom_bindings: list[dict[str, Any]] | None = None,
) -> GovernorWrapper:
    """Build a GovernorWrapper, loading from hapax agent registry if needed."""
    return _base_create(
        agent_id,
        axiom_bindings,
        binding_loader=_load_bindings_from_manifest,
    )


__all__ = [
    "DEFAULT_AXIOM_BUILDERS",
    "GovernorPolicy",
    "GovernorWrapper",
    "PolicyBuilder",
    "corporate_boundary_policies",
    "create_agent_governor",
    "interpersonal_transparency_policies",
]

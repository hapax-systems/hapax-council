"""Parity tests: vendored governance modules must export the same types as agentgov."""

from __future__ import annotations

import agentgov

VENDORED_CORE_TYPES = {
    "Veto",
    "VetoChain",
    "VetoResult",
    "GatedResult",
    "FallbackChain",
    "Candidate",
    "Selected",
    "ConsentLabel",
    "Labeled",
    "Principal",
    "PrincipalKind",
}

FULL_PACKAGE_TYPES = VENDORED_CORE_TYPES | {
    "Says",
    "ProvenanceExpr",
}


def _exported_names(module) -> set[str]:
    if hasattr(module, "__all__"):
        return set(module.__all__)
    return {n for n in dir(module) if not n.startswith("_")}


def test_agents_governance_has_core_types():
    from agents import _governance

    vendored = _exported_names(_governance)
    missing = VENDORED_CORE_TYPES - vendored
    assert not missing, f"agents._governance missing core types: {missing}"


def test_logos_governance_has_core_types():
    from logos import _governance

    vendored = _exported_names(_governance)
    missing = VENDORED_CORE_TYPES - vendored
    assert not missing, f"logos._governance missing core types: {missing}"


def test_shared_governance_reexports_core():
    from shared import governance

    facade = _exported_names(governance)
    missing = VENDORED_CORE_TYPES - facade
    assert not missing, f"shared.governance missing core types: {missing}"


def test_agentgov_package_has_full_surface():
    exported = _exported_names(agentgov)
    missing = FULL_PACKAGE_TYPES - exported
    assert not missing, f"agentgov package missing: {missing}"

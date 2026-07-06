"""CapabilityExecutionInvariant session attestation helpers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from shared.execution_observer import (
    EXPLICIT_SELF_ENFORCED,
    IMPLICIT_INHERITANCE,
    UNSUPPORTED_EXECUTION_OBSERVER,
    ExecutionInvariantVerdict,
    GbaiCase,
    ObservedExecution,
    SelfEnforcementGuard,
    capability_class_for_model,
    check_execution_invariant,
    observe_claude_transcript,
    observe_codex_rollout,
)
from shared.platform_capability_registry import (
    PlatformCapabilityRegistry,
    normalize_route_id,
)

_OBSERVERS: Final[dict[str, Callable[[str | Path], ObservedExecution]]] = {
    "claude": observe_claude_transcript,
    "codex": observe_codex_rollout,
}


@dataclass(frozen=True)
class LoadBearingGovernanceAllowlist:
    """Versioned, curated LBG surface allowlist.

    This is intentionally hand-maintained code data, not a runtime purpose
    inference over arbitrary filenames.
    """

    version: int
    surfaces: frozenset[str]


LBG_ALLOWLIST_VERSION: Final[int] = 1
_LBG_ALLOWLIST: Final[LoadBearingGovernanceAllowlist] = LoadBearingGovernanceAllowlist(
    version=LBG_ALLOWLIST_VERSION,
    surfaces=frozenset(
        {
            "shared/execution_observer.py",
            "shared/execution_attestation.py",
            "tests/shared/test_execution_observer.py",
            "tests/shared/test_execution_attestation.py",
        }
    ),
)

GATE2_LOCAL_INTERCEPTOR: Final[str] = "synchronous_per_turn_interceptor"
_FORBIDDEN_GATE2_LOCALITY: Final[frozenset[str]] = frozenset(
    {
        "harness_round_trip",
        "external_harness_round_trip",
        "async_harness_round_trip",
        "remote_harness_round_trip",
    }
)


def load_lbg_allowlist(version: int | None = None) -> LoadBearingGovernanceAllowlist:
    """Return the curated LBG allowlist for ``version``."""

    requested = LBG_ALLOWLIST_VERSION if version is None else version
    if requested != LBG_ALLOWLIST_VERSION:
        raise ValueError(
            f"unsupported LBG allowlist version {requested}; available={LBG_ALLOWLIST_VERSION}"
        )
    return _LBG_ALLOWLIST


def is_load_bearing_governance_surface(
    surface_ref: str, *, allowlist: LoadBearingGovernanceAllowlist | None = None
) -> bool:
    """True only when ``surface_ref`` is in the curated versioned allowlist."""

    active = load_lbg_allowlist() if allowlist is None else allowlist
    normalized = surface_ref.strip().removeprefix("./")
    return normalized in active.surfaces


def assert_gate2_locality(interceptor_binding: str) -> str:
    """Gate 2 must remain the local synchronous per-turn interceptor."""

    normalized = interceptor_binding.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in _FORBIDDEN_GATE2_LOCALITY or normalized != GATE2_LOCAL_INTERCEPTOR:
        raise ValueError(
            "Gate 2 locality violation: the synchronous per-turn TOCTOU interceptor "
            "must not be externalized to a harness round trip."
        )
    return GATE2_LOCAL_INTERCEPTOR


def sanctioned_models_for_route(
    route_id: str, registry: PlatformCapabilityRegistry
) -> frozenset[str]:
    """Return concrete model ids sanctioned by a route descriptor and variants."""

    route = registry.route_map().get(normalize_route_id(route_id))
    if route is None:
        return frozenset()
    models = {str(route.execution_descriptor.model_id)}
    for variant in route.descriptor_variants:
        override = variant.knobs_override.get("model_id") if variant.knobs_override else None
        if override:
            models.add(str(override))
    return frozenset(models)


def sanctioned_capability_classes_for_route(
    route_id: str, registry: PlatformCapabilityRegistry
) -> frozenset[str]:
    """Return sanctioned capability classes for a route."""

    return frozenset(
        capability_class_for_model(model)
        for model in sanctioned_models_for_route(route_id, registry)
    )


def attest_transcript(
    transcript_path: str | Path,
    sanctioned: frozenset[str] | set[str] | tuple[str, ...],
    *,
    carrier: str = "claude",
    gbai_case: GbaiCase = IMPLICIT_INHERITANCE,
    self_enforcement_guard: SelfEnforcementGuard | None = None,
) -> ExecutionInvariantVerdict:
    """Observe a transcript and evaluate it against sanctioned execution."""

    observer = _OBSERVERS.get(carrier)
    if observer is None:
        return ExecutionInvariantVerdict(
            status=UNSUPPORTED_EXECUTION_OBSERVER,
            sanctioned_models=frozenset(sanctioned),
            gbai_case=gbai_case,
            failure_reasons=("unsupported_carrier",),
        )
    observed = observer(transcript_path)
    return check_execution_invariant(
        observed,
        sanctioned,
        gbai_case=gbai_case,
        self_enforcement_guard=self_enforcement_guard,
    )


__all__ = [
    "EXPLICIT_SELF_ENFORCED",
    "GATE2_LOCAL_INTERCEPTOR",
    "IMPLICIT_INHERITANCE",
    "LBG_ALLOWLIST_VERSION",
    "LoadBearingGovernanceAllowlist",
    "assert_gate2_locality",
    "attest_transcript",
    "is_load_bearing_governance_surface",
    "load_lbg_allowlist",
    "sanctioned_capability_classes_for_route",
    "sanctioned_models_for_route",
]

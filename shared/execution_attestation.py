"""CapabilityExecutionInvariant — session attestation (close-gate core).

Composes the observer + the invariant verdict into a one-call attestation of a session's
execution against what its dispatch route SANCTIONED. This is the core the cc-close
execution-attestation gate and the Yard Crow recomposition consume: resolve the sanctioned
model set from the route, observe the session transcript, and return the verdict. Only an
``execution_invariant_satisfied`` verdict is admissible for authoritative close.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from shared.execution_observer import (
    UNSUPPORTED_EXECUTION_OBSERVER,
    ExecutionInvariantVerdict,
    ObservedExecution,
    check_execution_invariant,
    observe_claude_transcript,
    observe_codex_rollout,
)
from shared.platform_capability_registry import (
    PlatformCapabilityRegistry,
    normalize_route_id,
)

#: carrier -> transcript observer. Carriers with no client-side transcript observer (a
#: gateway/provider-attested source is required instead) are absent → UNSUPPORTED.
_OBSERVERS: dict[str, Callable[[str | Path], ObservedExecution]] = {
    "claude": observe_claude_transcript,
    "codex": observe_codex_rollout,
}


def sanctioned_models_for_route(
    route_id: str, registry: PlatformCapabilityRegistry
) -> frozenset[str]:
    """The model identities a route SANCTIONS: its descriptor model plus any model overridden
    by a descriptor variant. An unknown route sanctions nothing (fail-closed: every observed
    model is then drift)."""
    route = registry.route_map().get(normalize_route_id(route_id))
    if route is None:
        return frozenset()
    models = {str(route.execution_descriptor.model_id)}
    for variant in route.descriptor_variants:
        if variant.blocked_reasons:
            continue
        override = variant.knobs_override.get("model_id") if variant.knobs_override else None
        if override:
            models.add(str(override))
    return frozenset(models)


def attest_transcript(
    transcript_path: str | Path,
    sanctioned: frozenset[str] | set[str] | tuple[str, ...],
    *,
    carrier: str = "claude",
) -> ExecutionInvariantVerdict:
    """Observe a session transcript for ``carrier`` and evaluate ``observed ⊆ sanctioned``.

    An unknown/unobservable carrier yields ``unsupported_execution_observer`` (fail-closed:
    not admissible) rather than a false pass — attestation must come from a real observer."""
    observer = _OBSERVERS.get(carrier)
    if observer is None:
        return ExecutionInvariantVerdict(
            status=UNSUPPORTED_EXECUTION_OBSERVER,
            sanctioned_models=frozenset(sanctioned),
        )
    observed = observer(transcript_path)
    return check_execution_invariant(observed, sanctioned)

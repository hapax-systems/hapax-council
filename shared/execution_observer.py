"""CapabilityExecutionInvariant observer and verdict primitives.

The lane transcript is useful drift evidence, but it is not a provider-side
receipt. Clean CEI satisfaction therefore prefers endpoint-attested provenance
such as a LiteLLM usage row or an OTel ``gen_ai.response.model`` span, and falls
closed when only lane-writable ``message.model`` evidence is present.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

IMPLICIT_INHERITANCE = "implicit_inheritance"
EXPLICIT_SELF_ENFORCED = "explicit_self_enforced"
GbaiCase = Literal["implicit_inheritance", "explicit_self_enforced"]

ENDPOINT_ATTESTATION_SOURCES: Final[frozenset[str]] = frozenset(
    {
        "litellm_usage",
        "otel_gen_ai",
        "provider_gateway_usage",
        "usage_api",
    }
)
LANE_WRITABLE_ATTESTATION_SOURCES: Final[frozenset[str]] = frozenset(
    {
        "lane",
        "transcript",
        "message.model",
        "codex_rollout",
        "claude_transcript",
    }
)

UNKNOWN_CAPABILITY_CLASS: Final[str] = "unknown"
MODEL_CAPABILITY_CLASS: Final[dict[str, str]] = {
    "claude-opus-4-8": "frontier_authoritative",
    "claude-sonnet-4-6": "frontier_authoritative",
    "claude-sonnet-5": "frontier_authoritative",
    "claude-haiku-4-5": "frontier_support",
    "claude-fable-5": "frontier_authoritative",
    "gpt-5.5": "frontier_authoritative",
    "gpt-5.3-codex-spark": "frontier_support",
    "gemini-3.1-pro-preview": "frontier_authoritative",
    "mistral-medium-3.5": "frontier_support",
    "z_ai-glm-5": "frontier_review",
    "command-r-08-2024": "local_grounding",
    "qwen3.5-9b": "local_support",
}


@dataclass(frozen=True)
class FallbackEvent:
    """A silent model remap observed in a client transcript."""

    from_model: str
    to_model: str
    trigger: str | None = None
    request_id: str | None = None


@dataclass(frozen=True)
class EndpointAttestation:
    """Provider/gateway-side model receipt."""

    model: str
    source: str
    receipt_ref: str


@dataclass(frozen=True)
class SelfEnforcementGuard:
    """Explicit self-enforcement guard metadata for the GBAI case split."""

    guard_id: str
    lane_rewritable: bool
    receipt_ref: str | None = None


@dataclass(frozen=True)
class ObservedExecution:
    """The observed execution set for a session.

    ``models`` is lane-observed evidence. ``endpoint_models`` is stronger
    receipt-backed evidence and is used preferentially by the invariant check.
    """

    models: frozenset[str] = frozenset()
    endpoint_models: frozenset[str] = frozenset()
    endpoint_attestations: tuple[EndpointAttestation, ...] = ()
    fallback_events: tuple[FallbackEvent, ...] = ()
    turn_count: int = 0
    source_path: str = ""
    malformed_lines: int = 0

    @property
    def endpoint_attested(self) -> bool:
        return bool(self.endpoint_attestations)

    @property
    def effective_models(self) -> frozenset[str]:
        if self.endpoint_attested and self.endpoint_models:
            return self.endpoint_models
        return self.models

    @property
    def drifted(self) -> bool:
        return len(self.models) > 1 or bool(self.fallback_events)


def capability_class_for_model(model: str) -> str:
    """Map a concrete model id to the governed capability class used for CEI equality."""

    normalized = model.strip().lower()
    return MODEL_CAPABILITY_CLASS.get(normalized, UNKNOWN_CAPABILITY_CLASS)


def _string(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _model_of_assistant_turn(record: dict) -> str | None:
    if record.get("type") != "assistant":
        return None
    message = record.get("message")
    if isinstance(message, dict):
        model = _string(message.get("model"))
        if model and not model.startswith("<"):
            return model
    return None


def _model_of_codex_turn(record: dict) -> str | None:
    if record.get("type") != "turn_context":
        return None
    payload = record.get("payload")
    if isinstance(payload, dict):
        model = _string(payload.get("model"))
        if model and not model.startswith("<"):
            return model
    return None


def _fallback_of_record(record: dict) -> FallbackEvent | None:
    if record.get("type") != "system" or record.get("subtype") != "model_refusal_fallback":
        return None
    from_model = _string(record.get("originalModel")) or _string(record.get("from_model"))
    to_model = _string(record.get("fallbackModel")) or _string(record.get("to_model"))
    if from_model is None or to_model is None:
        return None
    return FallbackEvent(
        from_model=from_model,
        to_model=to_model,
        trigger=_string(record.get("trigger")),
        request_id=_string(record.get("requestId")),
    )


def _endpoint_attestation_of_record(record: dict) -> EndpointAttestation | None:
    attributes = record.get("attributes")
    if not isinstance(attributes, dict):
        attributes = {}

    source = (
        _string(record.get("source"))
        or _string(record.get("attestation_source"))
        or _string(record.get("provenance"))
    )
    if source is None and _string(attributes.get("gen_ai.response.model")):
        source = "otel_gen_ai"
    if source is None:
        return None
    source = source.strip().lower()
    if source in LANE_WRITABLE_ATTESTATION_SOURCES or source not in ENDPOINT_ATTESTATION_SOURCES:
        return None

    model = (
        _string(record.get("model"))
        or _string(record.get("response_model"))
        or _string(attributes.get("gen_ai.response.model"))
        or _string(attributes.get("litellm.response.model"))
    )
    receipt_ref = (
        _string(record.get("receipt_id"))
        or _string(record.get("usage_row_id"))
        or _string(record.get("span_id"))
        or _string(attributes.get("usage_row_id"))
        or _string(attributes.get("span_id"))
        or _string(attributes.get("trace_id"))
    )
    if model is None or receipt_ref is None:
        return None
    return EndpointAttestation(model=model, source=source, receipt_ref=receipt_ref)


def _observe_jsonl(path: str | Path, *, codex: bool) -> ObservedExecution:
    p = Path(path)
    models: set[str] = set()
    endpoint_models: set[str] = set()
    attestations: list[EndpointAttestation] = []
    fallbacks: list[FallbackEvent] = []
    turns = 0
    malformed = 0

    if not p.is_file():
        return ObservedExecution(source_path=str(p))

    with p.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except (TypeError, ValueError):
                malformed += 1
                continue
            if not isinstance(record, dict):
                continue

            model = _model_of_codex_turn(record) if codex else _model_of_assistant_turn(record)
            if model is not None:
                models.add(model)
                turns += 1

            fallback = _fallback_of_record(record)
            if fallback is not None:
                fallbacks.append(fallback)
                models.add(fallback.from_model)
                models.add(fallback.to_model)

            endpoint_attestation = _endpoint_attestation_of_record(record)
            if endpoint_attestation is not None:
                attestations.append(endpoint_attestation)
                endpoint_models.add(endpoint_attestation.model)

    return ObservedExecution(
        models=frozenset(models),
        endpoint_models=frozenset(endpoint_models),
        endpoint_attestations=tuple(attestations),
        fallback_events=tuple(fallbacks),
        turn_count=turns,
        source_path=str(p),
        malformed_lines=malformed,
    )


def observe_claude_transcript(path: str | Path) -> ObservedExecution:
    """Parse a Claude Code transcript JSONL into observed execution evidence."""

    return _observe_jsonl(path, codex=False)


def observe_codex_rollout(path: str | Path) -> ObservedExecution:
    """Parse a Codex rollout JSONL into observed execution evidence."""

    return _observe_jsonl(path, codex=True)


EXECUTION_INVARIANT_SATISFIED: Final[str] = "execution_invariant_satisfied"
EXECUTION_OBSERVATION_MISSING: Final[str] = "execution_observation_missing"
EXECUTION_DRIFT_OBSERVED: Final[str] = "execution_drift_observed"
UNSANCTIONED_FALLBACK_OBSERVED: Final[str] = "unsanctioned_fallback_observed"
UNSUPPORTED_EXECUTION_OBSERVER: Final[str] = "unsupported_execution_observer"


@dataclass(frozen=True)
class ExecutionInvariantVerdict:
    """The verdict of the CEI check. Only SATISFIED is admissible."""

    status: str
    observed_models: frozenset[str] = frozenset()
    sanctioned_models: frozenset[str] = frozenset()
    observed_capability_classes: frozenset[str] = frozenset()
    sanctioned_capability_classes: frozenset[str] = frozenset()
    unsanctioned_models: frozenset[str] = frozenset()
    unsanctioned_capability_classes: frozenset[str] = frozenset()
    unsanctioned_fallbacks: tuple[FallbackEvent, ...] = ()
    endpoint_attested: bool = False
    gbai_case: GbaiCase = IMPLICIT_INHERITANCE
    failure_reasons: tuple[str, ...] = ()

    @property
    def admissible(self) -> bool:
        return self.status == EXECUTION_INVARIANT_SATISFIED


def _classes_for(models: frozenset[str]) -> frozenset[str]:
    return frozenset(capability_class_for_model(model) for model in models)


def _known_classes_for(models: frozenset[str]) -> frozenset[str]:
    return frozenset(cls for cls in _classes_for(models) if cls != UNKNOWN_CAPABILITY_CLASS)


def check_execution_invariant(
    observed: ObservedExecution,
    sanctioned: frozenset[str] | set[str] | tuple[str, ...],
    *,
    gbai_case: GbaiCase = IMPLICIT_INHERITANCE,
    self_enforcement_guard: SelfEnforcementGuard | None = None,
) -> ExecutionInvariantVerdict:
    """Evaluate CEI with endpoint-preferred provenance and GBAI case split.

    IMPLICIT_INHERITANCE requires endpoint-attested model evidence. EXPLICIT_SELF_ENFORCED
    requires a non-lane-rewritable guard. Equality is by capability class, not raw model
    string, and UNKNOWN classes fail closed.
    """

    sanctioned_models = frozenset(sanctioned)
    observed_models = observed.effective_models
    observed_classes = _classes_for(observed_models)
    sanctioned_classes = _known_classes_for(sanctioned_models)
    failure_reasons: list[str] = []

    if gbai_case not in {IMPLICIT_INHERITANCE, EXPLICIT_SELF_ENFORCED}:
        return ExecutionInvariantVerdict(
            status=UNSUPPORTED_EXECUTION_OBSERVER,
            observed_models=observed_models,
            sanctioned_models=sanctioned_models,
            observed_capability_classes=observed_classes,
            sanctioned_capability_classes=sanctioned_classes,
            endpoint_attested=observed.endpoint_attested,
            failure_reasons=("unsupported_gbai_case",),
        )

    if not observed_models and observed.turn_count == 0:
        failure_reasons.append("execution_observation_missing")
    elif gbai_case == IMPLICIT_INHERITANCE and not observed.endpoint_attested:
        failure_reasons.append("endpoint_attestation_missing")
    elif gbai_case == EXPLICIT_SELF_ENFORCED:
        if self_enforcement_guard is None:
            failure_reasons.append("self_enforcement_guard_missing")
        elif self_enforcement_guard.lane_rewritable:
            failure_reasons.append("self_enforcement_guard_lane_rewritable")

    unknown_observed_models = frozenset(
        model
        for model in observed_models
        if capability_class_for_model(model) == UNKNOWN_CAPABILITY_CLASS
    )
    unknown_sanctioned_models = frozenset(
        model
        for model in sanctioned_models
        if capability_class_for_model(model) == UNKNOWN_CAPABILITY_CLASS
    )
    if unknown_observed_models:
        failure_reasons.append("unknown_observed_capability_class")
    if unknown_sanctioned_models:
        failure_reasons.append("unknown_sanctioned_capability_class")

    unsanctioned_models = frozenset(
        model
        for model in observed_models
        if capability_class_for_model(model) not in sanctioned_classes
        or capability_class_for_model(model) == UNKNOWN_CAPABILITY_CLASS
    )
    unsanctioned_classes = frozenset(
        capability_class_for_model(model) for model in unsanctioned_models
    )
    unsanctioned_fallbacks = tuple(
        event
        for event in observed.fallback_events
        if capability_class_for_model(event.from_model) not in sanctioned_classes
        or capability_class_for_model(event.to_model) not in sanctioned_classes
        or UNKNOWN_CAPABILITY_CLASS
        in {
            capability_class_for_model(event.from_model),
            capability_class_for_model(event.to_model),
        }
    )

    if any(
        reason in failure_reasons
        for reason in (
            "execution_observation_missing",
            "endpoint_attestation_missing",
            "self_enforcement_guard_missing",
        )
    ):
        status = EXECUTION_OBSERVATION_MISSING
    elif unsanctioned_fallbacks:
        status = UNSANCTIONED_FALLBACK_OBSERVED
    elif failure_reasons or unsanctioned_models:
        status = EXECUTION_DRIFT_OBSERVED
    else:
        status = EXECUTION_INVARIANT_SATISFIED

    return ExecutionInvariantVerdict(
        status=status,
        observed_models=observed_models,
        sanctioned_models=sanctioned_models,
        observed_capability_classes=observed_classes,
        sanctioned_capability_classes=sanctioned_classes,
        unsanctioned_models=unsanctioned_models,
        unsanctioned_capability_classes=unsanctioned_classes,
        unsanctioned_fallbacks=unsanctioned_fallbacks,
        endpoint_attested=observed.endpoint_attested,
        gbai_case=gbai_case,
        failure_reasons=tuple(dict.fromkeys(failure_reasons)),
    )

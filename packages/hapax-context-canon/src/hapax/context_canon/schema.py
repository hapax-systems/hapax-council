"""Pure schema generation for the cross-repository carrier roots."""

from pydantic import TypeAdapter

from .contract import (
    CapabilityBehaviorObservation,
    ContextExposure,
    ContextFrame,
    ContextSelection,
    LifecycleDefinition,
    MeasurementApplicationReceipt,
    ObservabilityInvalidationResult,
    canonical_json_bytes,
)
from .projection import ContextBundleCompatibilityProjection, ProjectionEnvelope


def carrier_json_schema_bytes() -> bytes:
    """Return canonical JSON Schema bytes for the independently consumable roots."""

    contract = TypeAdapter(
        LifecycleDefinition
        | ContextFrame
        | ContextSelection
        | ContextExposure
        | CapabilityBehaviorObservation
        | MeasurementApplicationReceipt
        | ObservabilityInvalidationResult
        | ProjectionEnvelope
        | ContextBundleCompatibilityProjection
    )
    return canonical_json_bytes(contract.json_schema(by_alias=True)) + b"\n"

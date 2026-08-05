"""DemandShapeRef — content address of a demand act (forest finding F / Edge A §2).

Pure identity only: no dispatcher, no route selection, no registry mutation.

DemandShapeRef = stable_payload_hash({
  schema, basis, requirement_vector (8 dims int 0..5), constraint
})

Spec SSOT: vault 30-areas/hapax/capability-onboarding-process-edge-a-2026-08-04.md §2.
ADOPT C1: do not invent a second demand vocabulary — the vector is REQUIREMENT_VECTOR_DIMENSIONS.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from shared.route_metadata_schema import stable_payload_hash
from shared.sdlc_router import REQUIREMENT_VECTOR_DIMENSIONS

SCHEMA_V0: Final[str] = "hapax.demand_shape_ref.v0"
DEFAULT_BASIS: Final[str] = "capacity-dimensional-v1"

_CONSTRAINT_KEYS: Final[tuple[str, ...]] = (
    "mutation_surface",
    "authority_level",
    "routing_class",
)

_NEXT_VECTOR: Final[str] = (
    "next action: provide requirement_vector as a mapping with all eight dimensions: "
    + ", ".join(REQUIREMENT_VECTOR_DIMENSIONS)
)
_NEXT_SCORE: Final[str] = (
    "next action: set each requirement_vector score to a strict integer from 0 through 5"
)
_NEXT_CONSTRAINT: Final[str] = (
    "next action: provide constraint with keys mutation_surface, authority_level, routing_class"
)


def build_demand_shape_ref_payload(
    *,
    requirement_vector: Mapping[str, object],
    constraint: Mapping[str, object],
    basis: str = DEFAULT_BASIS,
    schema: str = SCHEMA_V0,
) -> dict[str, Any]:
    """Validate and build the canonical payload dict for DemandShapeRef hashing.

    Fail-closed on missing dimensions, non-int scores, unknown keys, or incomplete constraint.
    """
    if not isinstance(basis, str) or not basis.strip():
        raise ValueError(
            f"basis must be a non-empty string; next action: set basis (default {DEFAULT_BASIS!r})"
        )
    if schema != SCHEMA_V0:
        raise ValueError(
            f"unsupported demand_shape_ref schema {schema!r}; next action: use {SCHEMA_V0!r}"
        )
    if not isinstance(requirement_vector, Mapping):
        raise ValueError(f"requirement_vector must be a mapping; {_NEXT_VECTOR}")
    if not isinstance(constraint, Mapping):
        raise ValueError(f"constraint must be a mapping; {_NEXT_CONSTRAINT}")

    missing = tuple(d for d in REQUIREMENT_VECTOR_DIMENSIONS if d not in requirement_vector)
    if missing:
        raise ValueError(
            "requirement_vector missing dimensions: " + ", ".join(missing) + f"; {_NEXT_VECTOR}"
        )
    unknown = tuple(k for k in requirement_vector if k not in REQUIREMENT_VECTOR_DIMENSIONS)
    if unknown:
        raise ValueError(
            "unknown requirement_vector dimension(s): "
            + ", ".join(sorted(str(k) for k in unknown))
            + f"; {_NEXT_VECTOR}"
        )

    normalized_vector: dict[str, int] = {}
    for dim in REQUIREMENT_VECTOR_DIMENSIONS:
        score = requirement_vector[dim]
        if isinstance(score, bool) or not isinstance(score, int):
            raise ValueError(
                f"requirement_vector[{dim!r}] must be a strict integer 0..5; {_NEXT_SCORE}"
            )
        if score < 0 or score > 5:
            raise ValueError(f"requirement_vector[{dim!r}]={score!r} out of range; {_NEXT_SCORE}")
        normalized_vector[dim] = score

    missing_c = tuple(k for k in _CONSTRAINT_KEYS if k not in constraint)
    if missing_c:
        raise ValueError(
            "constraint missing keys: " + ", ".join(missing_c) + f"; {_NEXT_CONSTRAINT}"
        )
    unknown_c = tuple(k for k in constraint if k not in _CONSTRAINT_KEYS)
    if unknown_c:
        raise ValueError(
            "unknown constraint key(s): "
            + ", ".join(sorted(str(k) for k in unknown_c))
            + f"; {_NEXT_CONSTRAINT}"
        )
    normalized_constraint: dict[str, str] = {}
    for key in _CONSTRAINT_KEYS:
        value = constraint[key]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"constraint[{key!r}] must be a non-empty string; {_NEXT_CONSTRAINT}")
        normalized_constraint[key] = value

    return {
        "schema": schema,
        "basis": basis,
        "requirement_vector": normalized_vector,
        "constraint": normalized_constraint,
    }


def demand_shape_ref(payload: Mapping[str, Any]) -> str:
    """Return DemandShapeRef as ``sha256:<hex>`` for a validated payload mapping.

    Callers that build via :func:`build_demand_shape_ref_payload` get a validated payload.
    Raw mappings are re-validated so a hand-built dict cannot skip fail-closed rules.
    """
    if not isinstance(payload, Mapping):
        raise ValueError("payload must be a mapping")
    validated = build_demand_shape_ref_payload(
        requirement_vector=payload.get("requirement_vector", {}),  # type: ignore[arg-type]
        constraint=payload.get("constraint", {}),  # type: ignore[arg-type]
        basis=str(payload["basis"]) if "basis" in payload else DEFAULT_BASIS,
        schema=str(payload["schema"]) if "schema" in payload else SCHEMA_V0,
    )
    return stable_payload_hash(validated)


def demand_shape_ref_from_parts(
    *,
    requirement_vector: Mapping[str, object],
    constraint: Mapping[str, object],
    basis: str = DEFAULT_BASIS,
) -> str:
    """Convenience: validate parts and return DemandShapeRef digest."""
    payload = build_demand_shape_ref_payload(
        requirement_vector=requirement_vector,
        constraint=constraint,
        basis=basis,
    )
    return stable_payload_hash(payload)

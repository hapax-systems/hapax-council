"""World-language Layer-1/2 type system — the single adapted-language currency.

Pure types: no I/O, no generation (the materializer in
``shared/materialize_world_language.py`` generates these from the deployed SSOTs;
the affordance pipeline binds them at use-time). Afferent (perception), efferent
(drive), and stigmergic (coordination) signals are the SAME kind of thing here — a
``WorldLanguageNode``.

Layer-1 is the Lakoff/Johnson image-schema type system; Layer-2 is the SOSA (2023
Execution-superclass edition) / WoT-TD 1.1 node type. ``PhysicalDirection`` and
``Direction`` are imported from ``shared.direction`` (never re-defined).

See REQ-20260607-world-language-types + super-spec §2.1/§2.2.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

from shared.direction import Direction, PhysicalDirection

__all__ = [
    "ImageSchema",
    "ImageSchemaNode",
    "TdKind",
    "SosaClass",
    "FeatureOfInterest",
    "QUDT_UNITS",
    "DataSchema",
    "Form",
    "GeneratedFromRecord",
    "WorldLanguageNode",
    "SOSA_FOR_PHYSICAL_DIRECTION",
]


class ImageSchema(StrEnum):
    """Lakoff/Johnson image-schema primitives — the Layer-1 type system (exactly 7)."""

    SCALE = "scale"  # static magnitude range
    CYCLE = "cycle"  # update_hz multi-rate tier
    CONTAINER = "container"  # groups a FeatureOfInterest / SignalFamily
    FORCE = "force"  # directed precision-weighted gradient driving an efferent coupling
    PATH = "path"  # affordance traversal / Thompson posterior walk
    LINK = "link"  # sheaf restriction edge
    SUPPORT = "support"  # H¹ composability witness


class TdKind(StrEnum):
    """WoT Thing-Description interaction affordance kind."""

    PROPERTY = "property"
    ACTION = "action"
    EVENT = "event"


class SosaClass(StrEnum):
    """SOSA (2023 Execution-superclass edition) observation/actuation/sampling class."""

    OBSERVATION = "Observation"  # afferent — sensing into context
    ACTUATION = "Actuation"  # efferent — driving a prosthetic
    SAMPLING = "Sampling"  # stigmergic — a trace is a sosa:Sample


class FeatureOfInterest(StrEnum):
    """Whose/what state the node concerns (consent-relevant for afferent nodes)."""

    OPERATOR = "operator"
    ROOM = "room"
    IDENTIFIABLE_PERSON = "identifiable_person"


# afferent ↔ Observation, efferent ↔ Actuation, stigmergic ↔ Sampling (SOSA pinning).
SOSA_FOR_PHYSICAL_DIRECTION: dict[PhysicalDirection, SosaClass] = {
    PhysicalDirection.AFFERENT: SosaClass.OBSERVATION,
    PhysicalDirection.EFFERENT: SosaClass.ACTUATION,
    PhysicalDirection.STIGMERGIC: SosaClass.SAMPLING,
}

# Thin QUDT IRI subset — referenced, never vendored.
QUDT_UNITS: dict[str, str] = {
    "decibel": "http://qudt.org/vocab/unit/DeciB",
    "dbfs": "http://qudt.org/vocab/unit/DeciB_FS",
    "hertz": "http://qudt.org/vocab/unit/HZ",
    "normalized": "http://qudt.org/vocab/unit/UNITLESS",
    "midi": "http://qudt.org/vocab/unit/UNITLESS",
    "bpm": "http://qudt.org/vocab/unit/PER-MIN",
}


class DataSchema(BaseModel, frozen=True):
    """WoT-TD DataSchema for a node's value (unit is a QUDT IRI)."""

    type: str  # number | integer | string | boolean | ...
    unit: str | None = None  # QUDT IRI (see QUDT_UNITS)
    minimum: float | None = None
    maximum: float | None = None
    enum: tuple[str, ...] | None = None


class Form(BaseModel, frozen=True):
    """WoT-TD Form — a concrete operation binding (the efferent/observe terminus)."""

    op: str  # readproperty | invokeaction | subscribeevent | ...
    href: str
    content_type: str = "application/json"


class GeneratedFromRecord(BaseModel, frozen=True):
    """Provenance backpointer — the Ashby homomorphism witness, sheaf restriction
    map, and drift key. Carries a content_hash (unlike the deployed
    ``director_vocabulary.GeneratedFrom`` Literal, which cannot)."""

    ssot: str  # which source SSOT (e.g. "world_capability_surface", "hardm_signal_map")
    key: str  # the source row/entry key
    content_hash: str  # hash of the source content at materialization time


class ImageSchemaNode(BaseModel, frozen=True):
    """A Layer-1 image-schema relation. ``bounds`` is a RANGE, never a scalar value.

    SCALE-vs-FORCE operative test: a node is FORCE iff it drives an efferent
    coupling — a FORCE node with no ``efferent_terminus`` is a validation error.
    """

    image_schema: ImageSchema
    relatum_id: str
    relata: tuple[str, ...] = ()
    bounds: tuple[float, float] | None = None  # (min, max) range
    cadence_hz: float | None = None
    container_of: tuple[str, ...] = ()
    efferent_terminus: str | None = None  # the coupling a FORCE node drives

    @model_validator(mode="after")
    def _force_requires_efferent_terminus(self) -> Self:
        if self.image_schema is ImageSchema.FORCE and not self.efferent_terminus:
            raise ValueError("FORCE image-schema node requires an efferent_terminus")
        if self.bounds is not None and self.bounds[0] > self.bounds[1]:
            raise ValueError("bounds must be a (min, max) range with min <= max")
        return self


class WorldLanguageNode(BaseModel, frozen=True):
    """A Layer-2 SOSA/WoT-TD node — the common currency for every signal.

    ``physical_direction`` (transport polarity) and ``capability_direction`` (what
    the capability does) are orthogonal axes imported from ``shared.direction``.
    """

    model_config = ConfigDict(extra="forbid")

    node_id: str
    td_kind: TdKind
    sosa_class: SosaClass
    physical_direction: PhysicalDirection
    capability_direction: Direction
    image_schema: ImageSchema
    l1_relatum_id: str
    data_schema: DataSchema
    forms: tuple[Form, ...] = ()
    feature_of_interest: FeatureOfInterest = FeatureOfInterest.OPERATOR
    consent_process_ref: str | None = None
    safe: bool = True  # SOSA Actuation native metadata (= damping safety)
    idempotent: bool = True
    cadence_hz: float | None = None  # = slew ceiling
    authority_ceiling: str  # materialized (missing = build error); no default
    phenomenal_slot: str | None = None
    generated_from: GeneratedFromRecord  # every node has a non-null provenance

    @model_validator(mode="after")
    def _invariants(self) -> Self:
        # SOSA class must match the physical-transport polarity (the pinning).
        expected = SOSA_FOR_PHYSICAL_DIRECTION[self.physical_direction]
        if self.sosa_class is not expected:
            raise ValueError(
                f"sosa_class {self.sosa_class} != {expected} for "
                f"physical_direction {self.physical_direction}"
            )
        # FORCE node must drive an efferent coupling with an actuation terminus.
        if self.image_schema is ImageSchema.FORCE:
            if self.physical_direction is not PhysicalDirection.EFFERENT:
                raise ValueError("FORCE node must be efferent")
            if not self.forms:
                raise ValueError("FORCE node requires an efferent terminus (a Form)")
        return self

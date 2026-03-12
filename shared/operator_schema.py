"""Operator Schema: query interface and staleness model over the 11 profile dimensions.

Provides a typed query interface for agents to access operator profile data
with built-in staleness awareness. Trait dimensions use step-function decay
(confidence = 1.0 until a threshold, then drops to a floor). Behavioral
dimensions use linear decay (confidence decreases proportionally with age).

Usage:
    from shared.operator_schema import OperatorSchema, SchemaQuery

    schema = OperatorSchema()
    response = schema.query(SchemaQuery(dimensions=["energy_and_attention"]))
    for entry in response.entries:
        print(f"{entry.dimension}: confidence={entry.confidence:.2f}")
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Literal

from shared.dimensions import DIMENSIONS, DimensionDef, get_dimension

log = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Staleness model
# ------------------------------------------------------------------


@dataclass(frozen=True)
class StalenessConfig:
    """Per-kind staleness configuration."""

    # Trait dimensions: step function
    trait_fresh_threshold_days: float = 90.0  # confident for 90 days
    trait_floor: float = 0.5  # then drops to this

    # Behavioral dimensions: linear decay
    behavioral_half_life_hours: float = 24.0  # lose half confidence in 24h
    behavioral_floor: float = 0.1  # minimum confidence


class StalenessModel:
    """Computes confidence scores based on dimension kind and data age."""

    def __init__(self, config: StalenessConfig | None = None) -> None:
        self._config = config or StalenessConfig()

    def confidence(self, dimension: DimensionDef, age_seconds: float) -> float:
        """Compute confidence for a dimension given data age in seconds.

        Trait dimensions: step function (1.0 while fresh, floor when stale).
        Behavioral dimensions: linear decay toward floor.
        """
        if age_seconds < 0:
            return 1.0

        if dimension.kind == "trait":
            threshold_s = self._config.trait_fresh_threshold_days * 86400
            if age_seconds <= threshold_s:
                return 1.0
            return self._config.trait_floor

        # Behavioral: linear decay
        half_life_s = self._config.behavioral_half_life_hours * 3600
        if half_life_s <= 0:
            return self._config.behavioral_floor
        decay = age_seconds / half_life_s
        raw = max(0.0, 1.0 - 0.5 * decay)
        return max(self._config.behavioral_floor, raw)


# ------------------------------------------------------------------
# Query / Response types
# ------------------------------------------------------------------


@dataclass(frozen=True)
class SchemaQuery:
    """Query for operator schema data."""

    dimensions: list[str] = field(default_factory=list)  # empty = all
    kind_filter: Literal["trait", "behavioral", "all"] = "all"
    min_confidence: float = 0.0  # filter out entries below this


@dataclass(frozen=True)
class SchemaEntry:
    """Single dimension entry in a schema response."""

    dimension: str
    kind: Literal["trait", "behavioral"]
    confidence: float
    age_seconds: float
    stale: bool
    description: str


@dataclass(frozen=True)
class SchemaResponse:
    """Response to a schema query."""

    entries: tuple[SchemaEntry, ...]
    query_time: float
    total_dimensions: int


# ------------------------------------------------------------------
# Operator Schema
# ------------------------------------------------------------------


class OperatorSchema:
    """Query interface over the operator's 11 profile dimensions.

    Wraps the dimension registry with staleness-aware confidence scoring.
    Agents use this to understand what profile data is available and how
    fresh it is before making decisions.
    """

    def __init__(
        self,
        *,
        staleness_model: StalenessModel | None = None,
        dimension_timestamps: dict[str, float] | None = None,
    ) -> None:
        self._staleness = staleness_model or StalenessModel()
        # dimension_name → last_updated_timestamp (monotonic)
        self._timestamps: dict[str, float] = dimension_timestamps or {}
        self._access_log: list[tuple[float, str]] = []

    def update_timestamp(self, dimension: str, timestamp: float) -> None:
        """Record when a dimension was last updated."""
        self._timestamps[dimension] = timestamp

    def query(self, query: SchemaQuery) -> SchemaResponse:
        """Query the operator schema for dimension data with confidence scores."""
        now = time.monotonic()
        entries: list[SchemaEntry] = []

        target_dims: list[DimensionDef] = []
        if query.dimensions:
            for name in query.dimensions:
                dim = get_dimension(name)
                if dim is not None:
                    target_dims.append(dim)
        else:
            target_dims = list(DIMENSIONS)

        if query.kind_filter != "all":
            target_dims = [d for d in target_dims if d.kind == query.kind_filter]

        for dim in target_dims:
            last_updated = self._timestamps.get(dim.name, 0.0)
            age = now - last_updated if last_updated > 0 else float("inf")
            confidence = self._staleness.confidence(dim, age)

            if confidence < query.min_confidence:
                continue

            entries.append(
                SchemaEntry(
                    dimension=dim.name,
                    kind=dim.kind,
                    confidence=confidence,
                    age_seconds=age,
                    stale=confidence < 0.5,
                    description=dim.description,
                )
            )

        # Audit log
        dim_names = [e.dimension for e in entries]
        self._access_log.append((now, ",".join(dim_names)))
        if len(self._access_log) > 1000:
            self._access_log = self._access_log[-500:]

        return SchemaResponse(
            entries=tuple(entries),
            query_time=now,
            total_dimensions=len(DIMENSIONS),
        )

    @property
    def access_log(self) -> list[tuple[float, str]]:
        """Return a copy of the access audit log."""
        return list(self._access_log)

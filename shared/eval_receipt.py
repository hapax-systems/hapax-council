"""Canonical EvalReceiptV1 schema for evaluation evidence receipts."""

from __future__ import annotations

import enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, model_validator

__all__ = [
    "ContaminationStatus",
    "EvalReceiptV1",
    "FreshnessStatus",
]


class ContaminationStatus(enum.StrEnum):
    CLEAN = "clean"
    CONTAMINATED = "contaminated"
    UNKNOWN = "unknown"


class FreshnessStatus(enum.StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"


class EvalReceiptV1(BaseModel):
    schema_version: Literal["EvalReceiptV1"] = "EvalReceiptV1"

    run_id: str = Field(min_length=1)
    authority_case: str = Field(min_length=1)
    task_ref: str = Field(min_length=1)

    model_id_hash: str | None = None
    route_hash: str | None = None
    config_hash: str | None = None
    prompt_hash: str | None = None
    scorer_hash: str | None = None
    dataset_hash: str | None = None

    raw_artifact_refs: list[str] = Field(default_factory=list)
    replayable: bool = False

    normalized_score: Annotated[float, Field(ge=0.0, le=1.0)]

    contamination_status: ContaminationStatus
    freshness_status: FreshnessStatus

    resource_observations: dict[str, Any] = Field(default_factory=dict)

    claim_ceilings: Annotated[list[str], Field(min_length=1)]
    what_this_does_not_prove: Annotated[list[str], Field(min_length=1)]

    @model_validator(mode="after")
    def _replayable_requires_artifacts_and_hashes(self) -> EvalReceiptV1:
        if not self.replayable:
            return self
        if not self.raw_artifact_refs:
            raise ValueError("raw_artifact_refs must be non-empty when replayable=True")
        hash_fields = {
            "model_id_hash": self.model_id_hash,
            "route_hash": self.route_hash,
            "config_hash": self.config_hash,
            "prompt_hash": self.prompt_hash,
            "scorer_hash": self.scorer_hash,
            "dataset_hash": self.dataset_hash,
        }
        missing = [k for k, v in hash_fields.items() if v is None]
        if missing:
            raise ValueError(f"replayable=True requires all hash fields; missing: {missing}")
        return self

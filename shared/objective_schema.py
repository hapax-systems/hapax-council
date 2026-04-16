"""Objective schema (LRR Phase 8 item 1).

A research objective is a persistent, vault-native note (`~/Documents/Personal/
30-areas/hapax-objectives/obj-NNN.md`) that the director loop consults when
scoring candidate activities. The YAML frontmatter shape is validated here.

Objectives connect to the append-only research registry: each objective links
to zero or more `linked_claims` (IDs from the research registry) and
`linked_conditions` (condition IDs — e.g., the Qwen baseline vs OLMo-3 variants).

The body of the markdown file is free-form operator + Hapax notes; it is
outside this schema's scope.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ObjectiveStatus(StrEnum):
    active = "active"
    closed = "closed"
    deferred = "deferred"


class ObjectivePriority(StrEnum):
    high = "high"
    normal = "normal"
    low = "low"


class Objective(BaseModel):
    """A research objective that shapes director-loop activity selection.

    See LRR Phase 8 spec §3.1 for the design intent.
    """

    objective_id: str = Field(..., pattern=r"^obj-\d{3,4}$")
    title: str = Field(..., min_length=1, max_length=200)
    status: ObjectiveStatus
    priority: ObjectivePriority = ObjectivePriority.normal
    opened_at: datetime
    closed_at: datetime | None = None
    linked_claims: list[str] = Field(default_factory=list)
    linked_conditions: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(..., min_length=1)
    activities_that_advance: list[str] = Field(..., min_length=1)

    @field_validator("activities_that_advance")
    @classmethod
    def _normalize_activities(cls, v: list[str]) -> list[str]:
        known = {"react", "chat", "vinyl", "study", "observe", "silence"}
        unknown = [a for a in v if a not in known]
        if unknown:
            raise ValueError(
                f"activities_that_advance contains unknown activities: {unknown}. "
                f"Must be subset of {sorted(known)}."
            )
        return v

    @field_validator("closed_at")
    @classmethod
    def _closed_at_requires_closed_status(cls, v: datetime | None, info) -> datetime | None:
        if v is not None and info.data.get("status") != ObjectiveStatus.closed:
            raise ValueError("closed_at may only be set when status='closed'")
        return v


class ObjectiveFile(BaseModel):
    """Wrapper marking a parsed objective markdown file."""

    path: str
    objective: Objective
    body: str = ""


ObjectiveID = str
ActivityName = Literal["react", "chat", "vinyl", "study", "observe", "silence"]


def score_objective_advancement(
    activity: ActivityName,
    active_objectives: list[Objective],
) -> float:
    """Objective-advancement score per Phase 8 spec §3.3.

    Returns the fraction of currently active objectives that list `activity`
    in their `activities_that_advance`. Range: [0.0, 1.0].

    Used by the director loop as the 0.3-weighted term in:
        activity_score(a) = 0.7 * old_score + 0.3 * objective_advancement_score(a)
    """
    if not active_objectives:
        return 0.0
    advancing = sum(1 for obj in active_objectives if activity in obj.activities_that_advance)
    return advancing / len(active_objectives)

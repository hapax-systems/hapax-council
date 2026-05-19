"""CCTV Research Assessment mode — implementability triage.

For research-backed requests, evaluates each deliverable as
READY / NEEDS_DESIGN / THEORETICAL / BLOCKED. Only READY and
NEEDS_DESIGN items become cc-tasks. THEORETICAL items are excluded
from fulfillment checks.

Spec: docs/superpowers/specs/2026-05-18-cctv-intake-gate-design.md
"""

from __future__ import annotations

import logging
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

_log = logging.getLogger(__name__)


class ImplementabilityClass(StrEnum):
    READY = "ready"
    NEEDS_DESIGN = "needs_design"
    THEORETICAL = "theoretical"
    BLOCKED = "blocked"


READY_FLOOR = 4
NEEDS_DESIGN_FLOOR = 3
BLOCKED_INDICATOR = 2


class ImplementabilityAssessment(BaseModel):
    model_config = ConfigDict(frozen=True)

    section_ref: str
    deliverable_text: str
    impl_class: ImplementabilityClass
    scores: dict[str, int]
    existing_code: tuple[str, ...] = ()
    missing_pieces: tuple[str, ...] = ()
    blocked_by: tuple[str, ...] = ()


class ResearchImplementabilityMap(BaseModel):
    model_config = ConfigDict(frozen=True)

    research_doc: str
    assessments: tuple[ImplementabilityAssessment, ...]

    @property
    def coverage_ratio(self) -> float:
        if not self.assessments:
            return 0.0
        ready = sum(1 for a in self.assessments if a.impl_class == ImplementabilityClass.READY)
        return ready / len(self.assessments)

    @property
    def task_yield(self) -> int:
        return sum(
            1
            for a in self.assessments
            if a.impl_class in (ImplementabilityClass.READY, ImplementabilityClass.NEEDS_DESIGN)
        )

    @property
    def theoretical_remainder(self) -> int:
        return sum(1 for a in self.assessments if a.impl_class == ImplementabilityClass.THEORETICAL)

    @property
    def blocked_count(self) -> int:
        return sum(1 for a in self.assessments if a.impl_class == ImplementabilityClass.BLOCKED)


def classify_deliverable(
    scores: dict[str, int], has_missing_dep: bool = False
) -> ImplementabilityClass:
    values = list(scores.values())
    if not values:
        return ImplementabilityClass.THEORETICAL

    if has_missing_dep and any(v <= BLOCKED_INDICATOR for v in values):
        return ImplementabilityClass.BLOCKED

    if all(v >= READY_FLOOR for v in values):
        return ImplementabilityClass.READY

    if any(v <= BLOCKED_INDICATOR for v in values):
        return ImplementabilityClass.THEORETICAL

    if all(v >= NEEDS_DESIGN_FLOOR for v in values):
        return ImplementabilityClass.NEEDS_DESIGN

    return ImplementabilityClass.THEORETICAL


def build_assessment(
    section_ref: str,
    deliverable_text: str,
    scores: dict[str, int],
    existing_code: tuple[str, ...] = (),
    missing_pieces: tuple[str, ...] = (),
    blocked_by: tuple[str, ...] = (),
) -> ImplementabilityAssessment:
    has_missing_dep = len(blocked_by) > 0
    return ImplementabilityAssessment(
        section_ref=section_ref,
        deliverable_text=deliverable_text,
        impl_class=classify_deliverable(scores, has_missing_dep),
        scores=scores,
        existing_code=existing_code,
        missing_pieces=missing_pieces,
        blocked_by=blocked_by,
    )


def build_map(
    research_doc: str,
    assessments: list[ImplementabilityAssessment],
) -> ResearchImplementabilityMap:
    return ResearchImplementabilityMap(
        research_doc=research_doc,
        assessments=tuple(assessments),
    )

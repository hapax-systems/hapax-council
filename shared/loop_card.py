"""Control-loop admissibility cards.

Control-theory language is only operational when the loop boundary is explicit.
This module provides the small schema used by segment prep and documentation
checks to distinguish a real loop from a feedforward prior or marked analogy.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

LOOP_CARD_VERSION = 1


class LoopAdmissibility(StrEnum):
    """How much operational force the card is allowed to claim."""

    CLOSED_LOOP = "closed_loop"
    SUPERVISORY_GATE = "supervisory_gate"
    FEEDFORWARD_PLAN = "feedforward_plan"
    ANALOGY_ONLY = "analogy_only"


class ControlLoopCard(BaseModel):
    """One admissible use of control/systems-theory language.

    A prepared segment usually emits ``FEEDFORWARD_PLAN`` cards: it declares
    the reference/readback obligation for a later runtime loop. Runtime
    components may emit ``CLOSED_LOOP`` or ``SUPERVISORY_GATE`` cards when they
    actually own the sensor-actuator loop. ``ANALOGY_ONLY`` marks relation
    transfer without operational control authority.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    loop_card_version: Literal[1] = LOOP_CARD_VERSION
    loop_id: str = Field(min_length=1)
    admissibility: LoopAdmissibility
    plant_boundary: str = Field(min_length=1, max_length=500)
    controlled_variable: str = Field(min_length=1, max_length=240)
    reference_signal: str = Field(min_length=1, max_length=500)
    sensor_ref: str | None = Field(default=None, max_length=240)
    actuator_ref: str | None = Field(default=None, max_length=240)
    sample_period_s: float | None = Field(default=None, gt=0)
    latency_budget_s: float | None = Field(default=None, gt=0)
    readback_ref: str | None = Field(default=None, max_length=240)
    fallback_mode: str = Field(min_length=1, max_length=500)
    authority_boundary: str = Field(min_length=1, max_length=500)
    privacy_ceiling: str = Field(min_length=1, max_length=120)
    evidence_refs: tuple[str, ...] = ()
    disturbance_refs: tuple[str, ...] = ()
    failure_mode: str = Field(min_length=1, max_length=500)
    limits: tuple[str, ...] = ()

    @field_validator("evidence_refs", "disturbance_refs", "limits", mode="after")
    @classmethod
    def _tuple_items_non_empty(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for item in value:
            if not item.strip():
                raise ValueError("loop-card tuple fields must not contain empty strings")
        return value

    @model_validator(mode="after")
    def _admissibility_has_required_operational_surface(self) -> ControlLoopCard:
        if self.admissibility in {
            LoopAdmissibility.CLOSED_LOOP,
            LoopAdmissibility.SUPERVISORY_GATE,
        }:
            missing = [
                field
                for field, value in (
                    ("sensor_ref", self.sensor_ref),
                    ("actuator_ref", self.actuator_ref),
                    ("sample_period_s", self.sample_period_s),
                    ("latency_budget_s", self.latency_budget_s),
                    ("readback_ref", self.readback_ref),
                )
                if value in (None, "")
            ]
            if missing:
                raise ValueError(
                    "closed-loop/supervisory loop card missing operational fields: "
                    + ", ".join(missing)
                )
        elif self.admissibility == LoopAdmissibility.FEEDFORWARD_PLAN:
            if not self.readback_ref:
                raise ValueError("feedforward loop card must name the later readback_ref")
            boundary = self.authority_boundary.lower()
            if "prior" not in boundary and "readback" not in boundary:
                raise ValueError(
                    "feedforward loop card authority_boundary must mark prior/readback limits"
                )
        elif self.admissibility == LoopAdmissibility.ANALOGY_ONLY:
            if not self.limits:
                raise ValueError("analogy-only loop card must state limits")
            boundary = self.authority_boundary.lower()
            if "analogy" not in boundary and "metaphor" not in boundary:
                raise ValueError(
                    "analogy-only loop card authority_boundary must mark analogy/metaphor status"
                )
        if not self.evidence_refs and self.admissibility != LoopAdmissibility.ANALOGY_ONLY:
            raise ValueError("operational loop cards require evidence_refs")
        return self


def loop_card_sha256(card: ControlLoopCard | Mapping[str, Any]) -> str:
    """Return a stable hash for a loop card."""

    payload = card.model_dump(mode="json") if isinstance(card, ControlLoopCard) else dict(card)
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate_loop_cards(cards: Any) -> dict[str, Any]:
    """Validate a sequence of loop cards and return a non-throwing report."""

    if not isinstance(cards, Sequence) or isinstance(cards, (str, bytes)):
        return {"ok": False, "violations": [{"reason": "loop_cards_missing_or_not_sequence"}]}
    if not cards:
        return {"ok": False, "violations": [{"reason": "loop_cards_empty"}]}

    parsed: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, card in enumerate(cards):
        try:
            parsed_card = ControlLoopCard.model_validate(card)
        except Exception as exc:
            violations.append(
                {
                    "reason": "invalid_loop_card",
                    "index": index,
                    "error": str(exc),
                }
            )
            continue
        if parsed_card.loop_id in seen:
            violations.append(
                {
                    "reason": "duplicate_loop_id",
                    "index": index,
                    "loop_id": parsed_card.loop_id,
                }
            )
            continue
        seen.add(parsed_card.loop_id)
        parsed.append(parsed_card.model_dump(mode="json"))

    return {"ok": not violations, "violations": violations, "loop_cards": parsed}


__all__ = [
    "LOOP_CARD_VERSION",
    "ControlLoopCard",
    "LoopAdmissibility",
    "loop_card_sha256",
    "validate_loop_cards",
]

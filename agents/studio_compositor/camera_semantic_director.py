"""Camera semantic layout director.

Promotes camera layout from fixed tiles to director content-programming
moves with evidence, cooldowns, and WCS health refs. Consumes the
Bayesian camera salience bundle instead of raw priority labels.

The director does NOT control privacy/public aperture — that belongs
to WCS and egress gates. Camera renderability and public safety are
separate concerns.
"""

from __future__ import annotations

import logging
import time
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

log = logging.getLogger(__name__)

DEFAULT_MOVE_COOLDOWN_S = 8.0
DEFAULT_REPETITION_PENALTY = 0.7
MAX_MOVE_HISTORY = 50


class SemanticRole(StrEnum):
    OPERATOR_FACE = "operator-face"
    OPERATOR_HANDS = "operator-hands"
    ROOM_WIDE = "room-wide"
    OPERATOR_DESK_TOPDOWN = "operator-desk-topdown"
    OUTBOARD_GEAR = "outboard-gear"
    TURNTABLES = "turntables"
    UNSPECIFIED = "unspecified"


class MoveReason(StrEnum):
    SALIENCE_SHIFT = "salience_shift"
    PERSON_DETECTED = "person_detected"
    FOLLOW_MODE = "follow_mode"
    MANUAL_OVERRIDE = "manual_override"
    COOLDOWN_ROTATION = "cooldown_rotation"
    NOVELTY_PRESSURE = "novelty_pressure"
    PROGRAMME_CUE = "programme_cue"


class LayoutTarget(StrEnum):
    HERO = "hero"
    BALANCED = "balanced"
    SIERPINSKI = "sierpinski"
    PACKED = "packed"


class _DirectorModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CameraMove(_DirectorModel):
    camera_role: str = Field(min_length=1)
    semantic_role: SemanticRole
    reason: MoveReason
    layout_target: LayoutTarget
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    salience_score: float = Field(ge=0.0, le=1.0)
    timestamp: float
    cooldown_remaining_s: float = 0.0


class MoveRecord(_DirectorModel):
    move: CameraMove
    applied: bool
    rejected_reason: str | None = None


class CameraSalienceInput(_DirectorModel):
    camera_role: str = Field(min_length=1)
    semantic_role: SemanticRole = SemanticRole.UNSPECIFIED
    salience: float = Field(ge=0.0, le=1.0, default=0.5)
    person_detected: bool = False
    scene_label: str = ""
    wcs_public_safe: bool = False
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)


class CameraSemanticDirector:
    """Stateful director that produces camera layout moves."""

    def __init__(
        self,
        *,
        cooldown_s: float = DEFAULT_MOVE_COOLDOWN_S,
        repetition_penalty: float = DEFAULT_REPETITION_PENALTY,
    ) -> None:
        self._cooldown_s = cooldown_s
        self._repetition_penalty = repetition_penalty
        self._last_move_time: dict[str, float] = {}
        self._history: list[MoveRecord] = []
        self._current_hero: str | None = None
        self._manual_override: str | None = None

    @property
    def current_hero(self) -> str | None:
        return self._manual_override or self._current_hero

    @property
    def history(self) -> list[MoveRecord]:
        return list(self._history)

    def set_manual_override(self, camera_role: str | None) -> None:
        self._manual_override = camera_role

    def propose_move(
        self,
        candidates: list[CameraSalienceInput],
        *,
        layout_target: LayoutTarget = LayoutTarget.BALANCED,
    ) -> CameraMove | None:
        if not candidates:
            return None

        if self._manual_override:
            for c in candidates:
                if c.camera_role == self._manual_override:
                    return CameraMove(
                        camera_role=c.camera_role,
                        semantic_role=c.semantic_role,
                        reason=MoveReason.MANUAL_OVERRIDE,
                        layout_target=layout_target,
                        evidence_refs=c.evidence_refs,
                        salience_score=c.salience,
                        timestamp=time.monotonic(),
                    )

        now = time.monotonic()
        scored: list[tuple[float, CameraSalienceInput]] = []
        for c in candidates:
            score = c.salience
            last = self._last_move_time.get(c.camera_role, 0.0)
            elapsed = now - last
            if elapsed < self._cooldown_s:
                score *= self._repetition_penalty
            recent_count = sum(
                1 for r in self._history[-10:] if r.move.camera_role == c.camera_role
            )
            if recent_count > 3:
                score *= self._repetition_penalty
            scored.append((score, c))

        scored.sort(key=lambda x: x[0], reverse=True)
        best_score, best = scored[0]

        if best.camera_role == self._current_hero and best_score < 0.7:
            return None

        reason = MoveReason.SALIENCE_SHIFT
        if best.person_detected:
            reason = MoveReason.PERSON_DETECTED

        return CameraMove(
            camera_role=best.camera_role,
            semantic_role=best.semantic_role,
            reason=reason,
            layout_target=layout_target,
            evidence_refs=best.evidence_refs,
            salience_score=best_score,
            timestamp=now,
        )

    def apply_move(self, move: CameraMove) -> MoveRecord:
        self._current_hero = move.camera_role
        self._last_move_time[move.camera_role] = move.timestamp
        record = MoveRecord(move=move, applied=True)
        self._history.append(record)
        if len(self._history) > MAX_MOVE_HISTORY:
            self._history = self._history[-MAX_MOVE_HISTORY:]
        return record

    def reject_move(self, move: CameraMove, reason: str) -> MoveRecord:
        record = MoveRecord(move=move, applied=False, rejected_reason=reason)
        self._history.append(record)
        return record


def classify_cameras_from_config(
    cameras: list[dict[str, Any]],
) -> dict[str, SemanticRole]:
    result: dict[str, SemanticRole] = {}
    for cam in cameras:
        role = cam.get("role", "")
        raw_semantic = cam.get("semantic_role", "unspecified")
        try:
            semantic = SemanticRole(raw_semantic)
        except ValueError:
            semantic = SemanticRole.UNSPECIFIED
        result[role] = semantic
    return result


__all__ = [
    "CameraMove",
    "CameraSalienceInput",
    "CameraSemanticDirector",
    "LayoutTarget",
    "MoveReason",
    "MoveRecord",
    "SemanticRole",
    "classify_cameras_from_config",
]

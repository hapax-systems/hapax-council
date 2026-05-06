"""shared/ir_models.py — Pydantic models for Pi NoIR edge detection reports.

Shared between Pi edge daemon (producer) and council API (consumer).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class IrPerson(BaseModel):
    confidence: float = 0.0
    bbox: list[int] = Field(default_factory=list)
    head_pose: dict[str, float] = Field(default_factory=dict)
    gaze_zone: str = "unknown"
    posture: str = "unknown"
    ear_left: float = 0.0
    ear_right: float = 0.0


class IrHand(BaseModel):
    zone: str = "unknown"
    bbox: list[int] = Field(default_factory=list)
    activity: str = "idle"


class IrScreen(BaseModel):
    bbox: list[int] = Field(default_factory=list)
    area_pct: float = 0.0


class IrBiometrics(BaseModel):
    heart_rate_bpm: int = 0
    heart_rate_confidence: float = 0.0
    perclos: float = 0.0
    blink_rate: float = 0.0
    drowsiness_score: float = 0.0
    pupil_detected: bool = False
    face_detected: bool = False


class HandSemantics(BaseModel):
    """Rich-vocabulary hand-activity description from the VLM classifier.

    Produced by ``pi-edge/vlm_classifier.py`` (Phase 3 of cc-task
    ``ir-perception-replace-zones-with-vlm-classification``). Replaces
    the noisy fixed five-zone enum in :class:`IrHand` with open
    vocabulary; consumers that still need the coarse zone fall back to
    :attr:`IrHand.zone` until the Phase 4 migration retires it.
    """

    intent: str = ""
    surface: str = ""
    hand_position: str = ""
    confidence: float = 0.0


class IrDetectionReport(BaseModel):
    pi: str
    role: str
    cam_id: str = "primary"
    ts: str
    motion_delta: float = 0.0
    persons: list[IrPerson] = Field(default_factory=list)
    hands: list[IrHand] = Field(default_factory=list)
    screens: list[IrScreen] = Field(default_factory=list)
    ir_brightness: int = 0
    inference_ms: int = 0
    biometrics: IrBiometrics = Field(default_factory=IrBiometrics)
    # #143 — activity-gated cadence (cadence_controller).  Server-side fusion
    # uses ``cadence_state`` / ``cadence_interval_s`` to scale staleness cutoffs
    # relative to the cadence the Pi is currently running at.
    cadence_state: str = "IDLE"
    cadence_interval_s: float = 3.0
    # Phase 3 of `ir-perception-replace-zones-with-vlm-classification`
    # — frame-level rich-vocabulary classification produced by the
    # Pi-side VLM classifier. ``None`` when the runner's motion gate
    # / cache / failure paths declined to call the VLM this tick.
    hand_semantics: HandSemantics | None = None

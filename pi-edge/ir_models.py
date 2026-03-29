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


class IrDetectionReport(BaseModel):
    pi: str
    role: str
    ts: str
    motion_delta: float = 0.0
    persons: list[IrPerson] = Field(default_factory=list)
    hands: list[IrHand] = Field(default_factory=list)
    screens: list[IrScreen] = Field(default_factory=list)
    ir_brightness: int = 0
    inference_ms: int = 0
    biometrics: IrBiometrics = Field(default_factory=IrBiometrics)

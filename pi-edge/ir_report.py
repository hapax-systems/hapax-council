"""ir_report.py — Build IrDetectionReport from inference results."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
from ir_models import IrBiometrics, IrDetectionReport, IrHand, IrPerson, IrScreen


def build_report(
    hostname: str,
    role: str,
    motion_delta: float,
    persons: list[dict],
    hands: list[dict],
    screens: list[dict],
    grey: np.ndarray,
    inference_ms: int,
    biometrics_snapshot: dict,
) -> IrDetectionReport:
    """Build detection report from inference results."""
    return IrDetectionReport(
        pi=hostname,
        role=role,
        ts=datetime.now(UTC).isoformat(),
        motion_delta=round(motion_delta, 4),
        persons=[
            IrPerson(
                confidence=p.get("confidence", 0),
                bbox=p.get("bbox", []),
                head_pose=p.get("head_pose", {}),
                gaze_zone=p.get("gaze_zone", "unknown"),
                posture=p.get("posture", "unknown"),
                ear_left=p.get("ear_left", 0.0),
                ear_right=p.get("ear_right", 0.0),
            )
            for p in persons
        ],
        hands=[
            IrHand(
                zone=h.get("zone", ""),
                bbox=h.get("bbox", []),
                activity=h.get("activity", "idle"),
            )
            for h in hands
        ],
        screens=[IrScreen(bbox=s.get("bbox", []), area_pct=s.get("area_pct", 0)) for s in screens],
        ir_brightness=int(np.mean(grey)),
        inference_ms=inference_ms,
        biometrics=IrBiometrics(**biometrics_snapshot),
    )

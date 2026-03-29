"""tests/shared/test_ir_models.py"""

from shared.ir_models import (
    IrBiometrics,
    IrDetectionReport,
    IrHand,
    IrPerson,
    IrScreen,
)


def test_minimal_report():
    report = IrDetectionReport(
        pi="hapax-pi6",
        role="overhead",
        ts="2026-03-29T14:30:00-05:00",
        motion_delta=0.0,
    )
    assert report.pi == "hapax-pi6"
    assert report.persons == []
    assert report.hands == []
    assert report.screens == []
    assert report.biometrics is not None
    assert report.biometrics.heart_rate_bpm == 0


def test_full_report():
    report = IrDetectionReport(
        pi="hapax-pi1",
        role="desk",
        ts="2026-03-29T14:30:00-05:00",
        motion_delta=0.45,
        persons=[
            IrPerson(
                confidence=0.87,
                bbox=[120, 80, 400, 460],
                head_pose={"yaw": -5.2, "pitch": 12.1, "roll": 1.3},
                gaze_zone="at-screen",
                posture="upright",
                ear_left=0.31,
                ear_right=0.29,
            )
        ],
        hands=[IrHand(zone="mpc-pads", bbox=[200, 300, 350, 420], activity="tapping")],
        screens=[IrScreen(bbox=[0, 0, 300, 200], area_pct=0.12)],
        ir_brightness=142,
        inference_ms=280,
        biometrics=IrBiometrics(
            heart_rate_bpm=72,
            heart_rate_confidence=0.85,
            perclos=0.12,
            blink_rate=14.2,
            drowsiness_score=0.15,
            pupil_detected=False,
        ),
    )
    assert len(report.persons) == 1
    assert report.persons[0].gaze_zone == "at-screen"
    assert report.hands[0].activity == "tapping"
    assert report.biometrics.drowsiness_score == 0.15


def test_valid_roles():
    for role in ("desk", "room", "overhead"):
        report = IrDetectionReport(
            pi=f"hapax-pi{1}", role=role, ts="2026-03-29T00:00:00Z", motion_delta=0.0
        )
        assert report.role == role

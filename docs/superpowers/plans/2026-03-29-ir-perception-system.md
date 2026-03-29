# IR Perception System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy 3 Pi NoIR edge inference daemons that POST structured detections to council, where a new perception backend fuses IR signals into the existing perception engine.

**Architecture:** Pi-side daemon captures IR frames, runs YOLOv8n TFLite + face landmarks + NIR hand detection, POSTs JSON every 2-3s to Logos API. Council-side receiver writes state files. New `ir_presence` backend reads state files and contributes 13 signals. Presence engine gets a new IR signal weight.

**Tech Stack:** picamera2, tflite-runtime, face-detection-tflite, httpx, opencv-python-headless, FastAPI, Pydantic

**Spec:** `docs/superpowers/specs/2026-03-29-ir-perception-system-design.md`

---

## File Map

### Pi-side (deployed to each Pi at ~/hapax-edge/)

| File | Responsibility |
|------|---------------|
| `hapax_ir_edge.py` | Main daemon: capture loop, inference, POST |
| `ir_inference.py` | YOLOv8n TFLite wrapper + face landmark detection |
| `ir_hands.py` | NIR adaptive thresholding for hand detection |
| `ir_biometrics.py` | rPPG heart rate + PERCLOS drowsiness (30fps loop) |
| `ir_models.py` | Pydantic output models (shared with council) |
| `hapax-ir-edge.service` | systemd unit file |

### Council-side (in hapax-council repo)

| File | Responsibility |
|------|---------------|
| `shared/ir_models.py` | Pydantic models for IR detection reports (shared schema) |
| `logos/api/routes/pi.py` | FastAPI receiver: POST /api/pi/{role}/ir, GET /api/pi/status |
| `agents/hapax_voice/backends/ir_presence.py` | Perception backend: reads state files, contributes 13 signals |
| `agents/hapax_voice/ir_signals.py` | State file reader with caching (like watch_signals.py) |

### Modified files

| File | Change |
|------|--------|
| `logos/api/app.py` | Add `include_router(pi_router)` |
| `agents/hapax_voice/__main__.py` | Register `IrPresenceBackend` |
| `agents/hapax_voice/_perception_state_writer.py` | Add 8 IR fields to state dict |
| `agents/hapax_voice/perception.py` | Add `ir_drowsiness_score` to `compute_interruptibility()` |
| `agents/hapax_voice/presence_engine.py` | Add `ir_person_detected` signal weight |

---

## Task 1: Pydantic Models (shared schema)

**Files:**
- Create: `shared/ir_models.py`
- Test: `tests/shared/test_ir_models.py`

- [ ] **Step 1: Write test for IR detection models**

```python
"""tests/shared/test_ir_models.py"""
from shared.ir_models import (
    IrDetectionReport,
    IrPerson,
    IrHand,
    IrScreen,
    IrBiometrics,
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
        hands=[
            IrHand(zone="mpc-pads", bbox=[200, 300, 350, 420], activity="tapping")
        ],
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/shared/test_ir_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'shared.ir_models'`

- [ ] **Step 3: Implement models**

```python
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
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/shared/test_ir_models.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```
feat: add Pydantic models for IR detection reports
```

---

## Task 2: IR Signal Reader (state file cache)

**Files:**
- Create: `agents/hapax_voice/ir_signals.py`
- Test: `tests/hapax_voice/test_ir_signals.py`

- [ ] **Step 1: Write test for IR signal reader**

```python
"""tests/hapax_voice/test_ir_signals.py"""
import json
import os
import time
from pathlib import Path

from agents.hapax_voice.ir_signals import read_ir_signal, IR_STATE_DIR


def test_read_missing_file(tmp_path):
    result = read_ir_signal(tmp_path / "nonexistent.json")
    assert result is None


def test_read_valid_file(tmp_path):
    data = {"pi": "hapax-pi6", "role": "overhead", "motion_delta": 0.5}
    f = tmp_path / "overhead.json"
    f.write_text(json.dumps(data))
    result = read_ir_signal(f)
    assert result is not None
    assert result["role"] == "overhead"


def test_read_stale_file(tmp_path):
    data = {"pi": "hapax-pi6", "role": "overhead"}
    f = tmp_path / "overhead.json"
    f.write_text(json.dumps(data))
    old_time = time.time() - 20
    os.utime(f, (old_time, old_time))
    result = read_ir_signal(f, max_age_seconds=10)
    assert result is None


def test_read_corrupt_json(tmp_path):
    f = tmp_path / "bad.json"
    f.write_text("{not valid json")
    result = read_ir_signal(f)
    assert result is None


def test_default_state_dir():
    assert "pi-noir" in str(IR_STATE_DIR)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/hapax_voice/test_ir_signals.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement reader**

```python
"""agents/hapax_voice/ir_signals.py — Read Pi NoIR state files.

Follows the same pattern as watch_signals.py: read JSON state files
from ~/hapax-state/pi-noir/ with staleness checking.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from shared.config import HAPAX_HOME

log = logging.getLogger(__name__)

IR_STATE_DIR: Path = HAPAX_HOME / "hapax-state" / "pi-noir"
IR_ROLES: tuple[str, ...] = ("desk", "room", "overhead")


def read_ir_signal(
    path: Path, max_age_seconds: float = 15.0
) -> dict[str, Any] | None:
    """Read a Pi NoIR JSON state file, returning None if missing or stale."""
    if not path.exists():
        return None
    try:
        mtime = path.stat().st_mtime
        if time.time() - mtime > max_age_seconds:
            return None
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def read_all_ir_reports(
    state_dir: Path | None = None, max_age_seconds: float = 15.0
) -> dict[str, dict[str, Any]]:
    """Read all Pi NoIR state files, keyed by role.

    Returns only fresh, valid reports. Missing or stale files are omitted.
    """
    d = state_dir or IR_STATE_DIR
    reports: dict[str, dict[str, Any]] = {}
    for role in IR_ROLES:
        data = read_ir_signal(d / f"{role}.json", max_age_seconds=max_age_seconds)
        if data is not None:
            reports[role] = data
    return reports
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/hapax_voice/test_ir_signals.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```
feat: add IR signal reader for Pi NoIR state files
```

---

## Task 3: IR Presence Backend

**Files:**
- Create: `agents/hapax_voice/backends/ir_presence.py`
- Test: `tests/hapax_voice/test_ir_presence_backend.py`

- [ ] **Step 1: Write test for IR presence backend**

```python
"""tests/hapax_voice/test_ir_presence_backend.py"""
import json
from pathlib import Path

from agents.hapax_voice.backends.ir_presence import IrPresenceBackend
from agents.hapax_voice.perception import PerceptionTier
from agents.hapax_voice.primitives import Behavior


def _write_report(tmp_path: Path, role: str, **overrides):
    data = {
        "pi": f"hapax-pi-{role}",
        "role": role,
        "ts": "2026-03-29T14:30:00-05:00",
        "motion_delta": 0.0,
        "persons": [],
        "hands": [],
        "screens": [],
        "ir_brightness": 100,
        "inference_ms": 200,
        "biometrics": {
            "heart_rate_bpm": 0,
            "heart_rate_confidence": 0.0,
            "perclos": 0.0,
            "blink_rate": 0.0,
            "drowsiness_score": 0.0,
            "pupil_detected": False,
        },
    }
    data.update(overrides)
    (tmp_path / f"{role}.json").write_text(json.dumps(data))


def test_backend_protocol():
    backend = IrPresenceBackend()
    assert backend.name == "ir_presence"
    assert backend.tier == PerceptionTier.FAST
    assert backend.available()
    assert "ir_person_detected" in backend.provides
    assert "ir_drowsiness_score" in backend.provides
    assert len(backend.provides) == 13


def test_no_state_files(tmp_path):
    backend = IrPresenceBackend(state_dir=tmp_path)
    behaviors: dict[str, Behavior] = {}
    backend.contribute(behaviors)
    assert behaviors["ir_person_detected"].value is False
    assert behaviors["ir_motion_delta"].value == 0.0


def test_person_detected(tmp_path):
    _write_report(
        tmp_path,
        "desk",
        persons=[{"confidence": 0.9, "bbox": [0, 0, 100, 200], "gaze_zone": "at-screen",
                  "posture": "upright", "ear_left": 0.3, "ear_right": 0.3}],
        motion_delta=0.5,
    )
    backend = IrPresenceBackend(state_dir=tmp_path)
    behaviors: dict[str, Behavior] = {}
    backend.contribute(behaviors)
    assert behaviors["ir_person_detected"].value is True
    assert behaviors["ir_person_count"].value == 1
    assert behaviors["ir_gaze_zone"].value == "at-screen"
    assert behaviors["ir_posture"].value == "upright"
    assert behaviors["ir_motion_delta"].value == 0.5


def test_hand_activity_prefers_overhead(tmp_path):
    _write_report(tmp_path, "desk", hands=[{"zone": "keyboard", "activity": "typing"}])
    _write_report(tmp_path, "overhead", hands=[{"zone": "mpc-pads", "activity": "tapping"}])
    backend = IrPresenceBackend(state_dir=tmp_path)
    behaviors: dict[str, Behavior] = {}
    backend.contribute(behaviors)
    assert behaviors["ir_hand_activity"].value == "tapping"


def test_biometrics_from_desk(tmp_path):
    _write_report(
        tmp_path,
        "desk",
        persons=[{"confidence": 0.8}],
        biometrics={
            "heart_rate_bpm": 72,
            "heart_rate_confidence": 0.85,
            "perclos": 0.15,
            "blink_rate": 14.0,
            "drowsiness_score": 0.2,
            "pupil_detected": True,
        },
    )
    backend = IrPresenceBackend(state_dir=tmp_path)
    behaviors: dict[str, Behavior] = {}
    backend.contribute(behaviors)
    assert behaviors["ir_heart_rate_bpm"].value == 72
    assert behaviors["ir_drowsiness_score"].value == 0.2
    assert behaviors["ir_blink_rate"].value == 14.0


def test_screen_looking(tmp_path):
    _write_report(
        tmp_path,
        "desk",
        persons=[{"confidence": 0.8, "gaze_zone": "at-screen"}],
        screens=[{"bbox": [0, 0, 300, 200], "area_pct": 0.15}],
    )
    backend = IrPresenceBackend(state_dir=tmp_path)
    behaviors: dict[str, Behavior] = {}
    backend.contribute(behaviors)
    assert behaviors["ir_screen_looking"].value is True


def test_fusion_any_pi_presence(tmp_path):
    _write_report(tmp_path, "desk")  # no persons
    _write_report(tmp_path, "room", persons=[{"confidence": 0.6}])
    backend = IrPresenceBackend(state_dir=tmp_path)
    behaviors: dict[str, Behavior] = {}
    backend.contribute(behaviors)
    assert behaviors["ir_person_detected"].value is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/hapax_voice/test_ir_presence_backend.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement backend**

Create `agents/hapax_voice/backends/ir_presence.py` — FAST tier backend that reads Pi NoIR state files and contributes 13 signals. Fuses reports from up to 3 Pis with role-based priority: biometrics/gaze prefer desk Pi (face-on angle), hand activity prefers overhead Pi (best instrument view), presence uses any() across all Pis. Full implementation code is in the spec exploration context above — follow the `AttentionBackend` pattern with `Behavior[T]` instances, `contribute()` that reads via `read_all_ir_reports()`, and `provides` returning the 13 signal names.

Key implementation details:
- Person detection: `any()` across Pis
- Gaze/posture: prefer desk Pi with 0.1 confidence bonus, fall back by raw confidence
- Hand activity: prefer overhead Pi, fall back to first available
- Screen looking: gaze == "at-screen" AND screens detected in same report
- Biometrics: from best face report
- Staleness: `read_all_ir_reports` handles via `max_age_seconds=15`

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/hapax_voice/test_ir_presence_backend.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```
feat: add IR presence perception backend with multi-Pi fusion
```

---

## Task 4: Logos API Receiver

**Files:**
- Create: `logos/api/routes/pi.py`
- Modify: `logos/api/app.py:128-165`
- Test: `tests/logos/test_pi_routes.py`

- [ ] **Step 1: Write test for PI routes**

```python
"""tests/logos/test_pi_routes.py"""
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path):
    with patch("logos.api.routes.pi.IR_STATE_DIR", tmp_path):
        from logos.api.app import app
        yield TestClient(app)


def test_post_ir_detection(client, tmp_path):
    report = {
        "pi": "hapax-pi6",
        "role": "overhead",
        "ts": "2026-03-29T14:30:00-05:00",
        "motion_delta": 0.23,
        "persons": [{"confidence": 0.87, "bbox": [120, 80, 400, 460]}],
        "hands": [],
        "screens": [],
        "ir_brightness": 142,
        "inference_ms": 280,
        "biometrics": {"heart_rate_bpm": 72},
    }
    resp = client.post("/api/pi/overhead/ir", json=report)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    state_file = tmp_path / "overhead.json"
    assert state_file.exists()
    data = json.loads(state_file.read_text())
    assert data["role"] == "overhead"


def test_post_invalid_role(client):
    report = {
        "pi": "hapax-pi6",
        "role": "invalid",
        "ts": "2026-03-29T14:30:00-05:00",
        "motion_delta": 0.0,
    }
    resp = client.post("/api/pi/invalid/ir", json=report)
    assert resp.status_code == 422


def test_get_pi_status_empty(client):
    resp = client.get("/api/pi/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "desk" in data
    assert data["desk"]["online"] is False


def test_get_pi_status_with_data(client, tmp_path):
    report = {"pi": "hapax-pi6", "role": "overhead", "ts": "2026-03-29T14:30:00-05:00"}
    (tmp_path / "overhead.json").write_text(json.dumps(report))
    resp = client.get("/api/pi/status")
    assert resp.status_code == 200
    assert resp.json()["overhead"]["online"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/logos/test_pi_routes.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement route module**

Create `logos/api/routes/pi.py` with:
- `POST /{role}/ir` — validates `IrDetectionReport`, atomic write to state file, rate limit 1/s
- `GET /status` — returns online/offline + freshness for each role
- Uses `IR_STATE_DIR` from `ir_signals.py`
- Router prefix: `/api/pi`

- [ ] **Step 4: Register route in app.py**

In `logos/api/app.py`, add import after line 144:
```python
from logos.api.routes.pi import router as pi_router
```

Add after line 164:
```python
app.include_router(pi_router)
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/logos/test_pi_routes.py -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```
feat: add Logos API receiver for Pi NoIR detection reports
```

---

## Task 5: Register Backend + Presence Signal

**Files:**
- Modify: `agents/hapax_voice/__main__.py:665-705`
- Modify: `agents/hapax_voice/presence_engine.py:27-39`

- [ ] **Step 1: Add IR presence signal weight**

In `agents/hapax_voice/presence_engine.py`, add to `DEFAULT_SIGNAL_WEIGHTS` dict after `room_occupancy` (line 39):

```python
    "ir_person_detected": (0.90, 0.10),  # lighting-invariant IR detection
```

- [ ] **Step 2: Add signal reading to _read_signals**

In `presence_engine.py` `_read_signals` method, add after existing `room_occupancy` reading:

```python
        # IR person detected (from Pi NoIR edge cameras)
        b = behaviors.get("ir_person_detected")
        obs["ir_person_detected"] = b.value if b is not None else None
```

- [ ] **Step 3: Register IrPresenceBackend in daemon**

In `agents/hapax_voice/__main__.py`, add after the mixer_input backend registration (~line 665):

```python
        try:
            from agents.hapax_voice.backends.ir_presence import IrPresenceBackend

            self.perception.register_backend(IrPresenceBackend())
        except Exception:
            log.info("IrPresenceBackend not available, skipping")
```

- [ ] **Step 4: Run presence tests**

Run: `uv run pytest tests/hapax_voice/ -k presence -v`
Expected: All pass

- [ ] **Step 5: Commit**

```
feat: register IR presence backend and add signal to presence engine
```

---

## Task 6: Perception State Writer + Interruptibility

**Files:**
- Modify: `agents/hapax_voice/_perception_state_writer.py:329-430`
- Modify: `agents/hapax_voice/perception.py:75-144`

- [ ] **Step 1: Add IR fields to perception state writer**

In `_perception_state_writer.py`, add to the `state` dict after `overhead_hand_zones` (~line 421):

```python
            # IR perception (Pi NoIR edge cameras)
            "ir_person_detected": bool(_bval("ir_person_detected", False)),
            "ir_gaze_zone": str(_bval("ir_gaze_zone", "unknown")),
            "ir_hand_activity": str(_bval("ir_hand_activity", "idle")),
            "ir_screen_looking": bool(_bval("ir_screen_looking", False)),
            "ir_drowsiness_score": _safe_float(_bval("ir_drowsiness_score", 0.0)),
            "ir_blink_rate": _safe_float(_bval("ir_blink_rate", 0.0)),
            "ir_heart_rate_bpm": _safe_int(_bval("ir_heart_rate_bpm", 0)),
            "ir_brightness": _safe_float(_bval("ir_brightness", 0.0)),
```

- [ ] **Step 2: Add drowsiness to compute_interruptibility**

In `perception.py`, add `ir_drowsiness_score: float = 0.0` parameter after `posture` (line 90).

Add scoring logic before the final return (after posture check, ~line 142):

```python
    # IR drowsiness — don't interrupt drowsy operator with low-priority items
    if ir_drowsiness_score > 0.6:
        score -= 0.2
```

- [ ] **Step 3: Find and update compute_interruptibility call site**

Grep for `compute_interruptibility(` to find the caller. Add `ir_drowsiness_score=` kwarg.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/hapax_voice/ -v -x --timeout=30`
Expected: All pass

- [ ] **Step 5: Commit**

```
feat: add IR fields to perception state writer and interruptibility
```

---

## Task 7: Pi Edge Daemon — Inference Module

**Files:**
- Create: `pi-edge/ir_inference.py`
- Create: `pi-edge/ir_hands.py`
- Create: `pi-edge/ir_models.py` (copy of shared/ir_models.py)

These are deployed to each Pi at `~/hapax-edge/`. Written in council repo under `pi-edge/` for version control.

- [ ] **Step 1: Create pi-edge directory**

Run: `mkdir -p pi-edge`

- [ ] **Step 2: Copy models**

Run: `cp shared/ir_models.py pi-edge/ir_models.py`

- [ ] **Step 3: Write inference module**

Create `pi-edge/ir_inference.py` with:
- `YoloDetector` class: loads TFLite INT8 model, `detect_persons(grey_frame)` returns `[{confidence, bbox}]`
- `FaceLandmarkDetector` class: uses `fdlite` (face-detection-tflite), `detect(grey_frame, person_bbox)` returns `{head_pose, gaze_zone, posture, ear_left, ear_right}` or None
- NMS (greedy IoU suppression)
- Greyscale → 3-channel conversion for RGB-trained models
- Quantization handling for INT8 input/output

- [ ] **Step 4: Write hand detection module**

Create `pi-edge/ir_hands.py` with:
- `detect_hands_nir(grey_frame)`: adaptive threshold on NIR (skin darker than plastic), morphological cleanup, contour detection, zone classification by position, activity classification by solidity
- `detect_screens_nir(grey_frame)`: threshold for near-zero intensity regions (LCD/OLED), rectangularity filter

- [ ] **Step 5: Commit**

```
feat: add Pi edge inference and hand detection modules
```

---

## Task 8: Pi Edge Daemon — Biometrics Module

**Files:**
- Create: `pi-edge/ir_biometrics.py`

- [ ] **Step 1: Write biometrics module**

Create `pi-edge/ir_biometrics.py` with `BiometricTracker` class:
- `update_ear(ear, timestamp)`: records EAR, detects blinks via threshold transitions
- `update_rppg_intensity(mean_intensity)`: records forehead ROI intensity for rPPG
- `perclos` property: % of time eyes closed in 60s window
- `drowsiness_score` property: composite from PERCLOS + blink rate
- `blink_rate` property: blinks/minute over last 60s
- `compute_heart_rate()`: FFT on rPPG buffer, bandpass 0.7-4Hz, returns (bpm, confidence)
- `snapshot()`: returns dict for IrBiometrics construction

- [ ] **Step 2: Commit**

```
feat: add biometric tracker for rPPG and PERCLOS drowsiness detection
```

---

## Task 9: Pi Edge Daemon — Main Script + Deployment

**Files:**
- Create: `pi-edge/hapax_ir_edge.py`
- Create: `pi-edge/hapax-ir-edge.service`
- Create: `pi-edge/setup.sh`

- [ ] **Step 1: Write main daemon script**

Create `pi-edge/hapax_ir_edge.py` with `IrEdgeDaemon` class:
- `__init__`: creates YoloDetector, FaceLandmarkDetector, BiometricTracker, httpx.AsyncClient
- `start()`: initializes picamera2 (640x480 YUV420 lores), runs async main loop
- `_main_loop()`: capture greyscale → motion gate → YOLO → face landmarks → hands → screens → biometrics → POST
- `_compute_motion()`: frame differencing, returns 0.0-1.0
- `_build_report()`: constructs IrDetectionReport from inference results
- `_post_report()`: async POST to workstation, tolerant of connection errors
- CLI: `--role {desk,room,overhead}`, `--hostname`, `--workstation`
- Signal handlers for graceful shutdown

- [ ] **Step 2: Write systemd service**

Create `pi-edge/hapax-ir-edge.service` — Type=simple, Restart=always, User=hapax, LIBCAMERA_LOG_LEVELS=*:ERROR, ExecStart with `--role=ROLE_PLACEHOLDER`. Setup script replaces placeholder.

- [ ] **Step 3: Write setup script**

Create `pi-edge/setup.sh` — installs system packages (python3-picamera2, python3-libcamera, python3-venv), creates venv with --system-site-packages, pip installs deps, ensures video group, installs systemd service with role substitution.

- [ ] **Step 4: Commit**

```
feat: add Pi edge daemon main script, systemd service, and setup script
```

---

## Task 10: Export YOLOv8n TFLite Model

- [ ] **Step 1: Export model on workstation**

```bash
cd /tmp && uv run --with ultralytics python -c "
from ultralytics import YOLO
model = YOLO('yolov8n.pt')
model.export(format='tflite', int8=True, imgsz=320)
print('Export complete')
"
```

- [ ] **Step 2: Copy to pi-edge**

```bash
cp /tmp/yolov8n_full_integer_quant.tflite pi-edge/
```

- [ ] **Step 3: Commit**

```
feat: add exported YOLOv8n INT8 TFLite model for Pi edge inference
```

---

## Task 11: Deploy to Pi-6 and End-to-End Test

- [ ] **Step 1: Create state directory on workstation**

```bash
mkdir -p ~/hapax-state/pi-noir
```

- [ ] **Step 2: Deploy files to Pi-6**

```bash
scp -r pi-edge/* hapax@hapax-pi6:~/hapax-edge/
```

- [ ] **Step 3: Run setup on Pi-6**

```bash
ssh hapax@hapax-pi6 'bash ~/hapax-edge/setup.sh overhead'
```

- [ ] **Step 4: Start daemon**

```bash
ssh hapax@hapax-pi6 'sudo systemctl start hapax-ir-edge'
```

- [ ] **Step 5: Verify daemon logs**

```bash
ssh hapax@hapax-pi6 'journalctl -u hapax-ir-edge -n 20 --no-pager'
```

Expected: camera start + inference loop + POST logs

- [ ] **Step 6: Verify state file**

```bash
cat ~/hapax-state/pi-noir/overhead.json | python3 -m json.tool
```

Expected: valid JSON with persons, hands, biometrics

- [ ] **Step 7: Verify API**

```bash
curl http://localhost:8051/api/pi/status | python3 -m json.tool
```

Expected: `overhead.online = true`

- [ ] **Step 8: Restart voice daemon**

```bash
systemctl --user restart hapax-voice
```

- [ ] **Step 9: Verify IR in perception state**

```bash
python3 -c "import json; d=json.load(open('$HOME/.cache/hapax-voice/perception-state.json')); [print(f'{k}: {v}') for k,v in sorted(d.items()) if k.startswith('ir_')]"
```

Expected: live ir_ fields

- [ ] **Step 10: Commit fixes**

```
fix: deployment adjustments from end-to-end testing
```

---

## Task 12: Full Test Suite

- [ ] **Step 1: Run all tests**

```bash
uv run pytest tests/ -v -x --timeout=30 -k "not llm"
```

Expected: All pass

- [ ] **Step 2: Lint**

```bash
uv run ruff check . && uv run ruff format --check .
```

Expected: Clean

- [ ] **Step 3: Commit**

```
chore: verify full test suite passes with IR perception system
```

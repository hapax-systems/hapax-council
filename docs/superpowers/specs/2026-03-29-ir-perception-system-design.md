# IR Perception System Design

**Date:** 2026-03-29
**Status:** Approved
**Scope:** 3-Pi NoIR edge inference + council integration

## Overview

Three Raspberry Pi 4s (Pi-1 desk, Pi-2 room, Pi-6 overhead) each run a NoIR edge
inference daemon (`hapax-ir-edge`). Each Pi captures continuously from a Pi Camera
Module 3 NoIR under 850nm IR flood illumination, runs local ML inference, and POSTs
structured JSON detections to a new council Logos API receiver. A new `ir_presence`
voice daemon backend reads the resulting state files and contributes signals to the
existing perception engine. No video streaming — only structured data crosses the
network.

## Motivation

The studio has 6 RGB cameras but they degrade severely under red/orange production
mood lighting. NIR at 850nm with active flood illumination sees identically regardless
of visible lighting, providing a continuous perception baseline that never degrades.
Additional unique capabilities: screen-blindness (LCDs emit zero NIR), superior hand
tracking on dark instrument surfaces, and biometric signals (pupil tracking, rPPG,
drowsiness detection) impossible in visible light.

## Architecture

```
Pi-1 (desk)  ──┐
Pi-2 (room)  ──┼── POST /api/pi/{role}/ir ──► Logos API receiver
Pi-6 (overhead)┘         │
                         ▼
              ~/hapax-state/pi-noir/{role}.json
                         │
                         ▼
              ir_presence backend (FAST tier)
                    │         │
         ┌──────────┘         └──────────┐
         ▼                               ▼
  PresenceEngine              PerceptionStateWriter
  (new signal weight)         (new IR fields)
         │                               │
         ▼                               ▼
  presence_probability         VLA / Stimmung / Profile
```

## Pi Allocation

| Pi | Role | Position | Co-located with | Duty |
|----|------|----------|-----------------|------|
| Pi-1 | desk | Desk area | C920-desk | Dedicated NoIR |
| Pi-2 | room | Room overview | C920-room | Dedicated NoIR |
| Pi-6 | overhead | Over operator | C920-overhead | NoIR + existing sync agents (6h timers) |

## Component 1: Pi Edge Daemon (`hapax-ir-edge`)

Single Python script per Pi. Two concurrent threads.

### Inference Loop (2-5 FPS, motion-gated)

- picamera2 continuous capture at 640x480 YUV420, Y-channel greyscale extraction
- Frame differencing → `motion_delta` (0.0-1.0). Skip inference when
  `motion_delta < 0.01` and no detection in last 30s (power saving)
- YOLOv8n TFLite INT8 at 320x320 → person bounding boxes + confidence
  - Filter: confidence > 0.4, person class only
  - Expected: 2-5 FPS on Pi 4 Cortex-A72 with 4 threads
- Face landmark detection via `face-detection-tflite` (standalone TFLite, no MediaPipe
  dependency — compatible with Python 3.13/Trixie)
  - 468 landmarks → head pose (yaw, pitch, roll) via solvePnP
  - Gaze zone classification: "at-screen", "at-synths", "at-door", "down", "away"
  - Eye Aspect Ratio (EAR) for blink detection
- Hand detection via adaptive NIR thresholding (skin vs plastic contrast)
  - No ML needed — NIR reflectance difference is sufficient
  - Zone classification based on bbox position in frame
- Screen detection: contiguous regions with near-zero NIR intensity = LCD/OLED screens

### Biometric Loop (30 FPS, face ROI only)

Requires on-axis IR LED ring (~$3/Pi, not yet ordered). Software gracefully disables
when bright pupil check fails.

- Separate 30fps capture of forehead ROI (bbox from face detection)
- Average pixel intensity per frame → bandpass filter 0.7-4Hz → FFT → heart rate
- PERCLOS: rolling 60s window of EAR values, percentage below threshold 0.22
- Blink rate: EAR transitions per minute
- Drowsiness score: weighted combination of PERCLOS + blink rate + head nod frequency

### Output Format

POST to workstation every 2-3 seconds:

```json
{
  "pi": "hapax-pi6",
  "role": "overhead",
  "ts": "2026-03-29T14:30:00-05:00",
  "motion_delta": 0.23,
  "persons": [{
    "confidence": 0.87,
    "bbox": [120, 80, 400, 460],
    "head_pose": {"yaw": -5.2, "pitch": 12.1, "roll": 1.3},
    "gaze_zone": "at-screen",
    "posture": "upright",
    "ear_left": 0.31,
    "ear_right": 0.29
  }],
  "hands": [{
    "zone": "mpc-pads",
    "bbox": [200, 300, 350, 420],
    "activity": "tapping"
  }],
  "screens": [{"bbox": [0, 0, 300, 200], "area_pct": 0.12}],
  "ir_brightness": 142,
  "inference_ms": 280,
  "biometrics": {
    "heart_rate_bpm": 72,
    "heart_rate_confidence": 0.85,
    "perclos": 0.12,
    "blink_rate": 14.2,
    "drowsiness_score": 0.15,
    "pupil_detected": false
  }
}
```

### Dependencies (Pi-side)

System packages (apt):
- `python3-picamera2`, `python3-libcamera` (camera access)

Python packages (venv with `--system-site-packages`):
- `tflite-runtime` (inference)
- `face-detection-tflite` (468 face landmarks, no MediaPipe dependency)
- `httpx` (async HTTP POST to workstation)
- `numpy` (array ops, FFT for rPPG)
- `opencv-python-headless` (image processing, solvePnP)

Model files (exported on workstation, scp'd to Pis):
- `yolov8n_full_integer_quant.tflite` (~4MB)

### systemd Service

`hapax-ir-edge.service`, Type=simple, Restart=always, User=hapax.
Environment: `LIBCAMERA_LOG_LEVELS=*:ERROR`. After=network-online.target.
ExecStart points to venv python + script in `~/hapax-edge/`.

### Hardware Requirements

| Item | Qty | Status | Required for |
|------|-----|--------|-------------|
| Pi Camera Module 3 NoIR | 3 | 1 installed (Pi-6), 2 pending | All capabilities |
| Heatsink + fan | 3 | TBD | 24/7 inference without throttling |
| 850nm IR LED ring (on-axis) | 3 | Not ordered | Pupil tracking, PERCLOS, rPPG |

## Component 2: Logos API Receiver

New route module: `logos/api/routes/pi.py`

### Endpoints

- `POST /api/pi/{role}/ir` — accepts `IrDetectionReport` JSON, atomic write to
  `~/hapax-state/pi-noir/{role}.json`
- `GET /api/pi/status` — returns status summary of all Pis (last seen, freshness)

### Behavior

- Pydantic model validation (`IrDetectionReport`)
- Atomic write (write-then-rename) to state file
- Rate limiting: max 1 POST/second per role (drop duplicates, log warning)
- No processing — receive and persist only

### State Files

```
~/hapax-state/pi-noir/
├── desk.json        (Pi-1)
├── room.json        (Pi-2)
├── overhead.json    (Pi-6)
```

## Component 3: `ir_presence` Voice Daemon Backend

New file: `agents/hapax_voice/backends/ir_presence.py`

FAST tier — reads state files from `~/hapax-state/pi-noir/`, never blocks.

### Signals Provided

| Signal | Type | Source | Description |
|--------|------|--------|-------------|
| `ir_person_detected` | bool | any Pi | At least one Pi sees a person |
| `ir_person_count` | int | max across Pis | Person count (conservative max) |
| `ir_motion_delta` | float | max across Pis | Motion intensity |
| `ir_gaze_zone` | str | best-confidence Pi | Fused gaze zone |
| `ir_head_pose_yaw` | float | desk Pi preferred | Head yaw angle |
| `ir_posture` | str | best-confidence Pi | Posture classification |
| `ir_hand_activity` | str | overhead Pi preferred | Hand activity on instruments |
| `ir_screen_looking` | bool | desk Pi | Face oriented toward NIR-dark rectangle |
| `ir_drowsiness_score` | float | desk Pi | PERCLOS-derived (0=alert, 1=asleep) |
| `ir_blink_rate` | float | desk Pi | Blinks per minute |
| `ir_heart_rate_bpm` | int | desk Pi | rPPG estimate (0 if unavailable) |
| `ir_heart_rate_conf` | float | desk Pi | rPPG confidence |
| `ir_brightness` | float | avg across Pis | Scene IR brightness |

### Fusion Logic

- Person detection: `any()` across Pis
- Gaze/posture/biometrics: prefer desk Pi (face-on), fall back by confidence
- Hand activity: prefer overhead Pi (best instrument view)
- Staleness: exclude Pi state files older than 10s

### Registration

Import and register in daemon's `_register_perception_backends()`.

## Component 4: Presence Engine Integration

Add signal weight:

```python
"ir_person_detected": (0.90, 0.10)
```

Weight 0.90 (as strong as `operator_face`) because IR detection is lighting-invariant
and highly reliable. This keeps presence_probability high when RGB cameras degrade
under mood lighting.

## Component 5: Perception State Writer Updates

Add IR fields to `_perception_state_writer.py`:

- `ir_person_detected` (bool)
- `ir_gaze_zone` (str)
- `ir_hand_activity` (str)
- `ir_screen_looking` (bool)
- `ir_drowsiness_score` (float)
- `ir_blink_rate` (float)
- `ir_heart_rate_bpm` (int)
- `ir_brightness` (float)

These flow automatically to VLA, stimmung, and profile via the existing
perception-state.json consumption pattern.

## Component 6: Stimmung Integration

No new dimension. Enrich the existing `perception_confidence` dimension: IR detection
confidence provides a floor value. When RGB cameras degrade, perception_confidence
stays elevated because IR maintains detection.

## Component 7: Interruptibility Enhancement

Add to `compute_interruptibility()`:

- `ir_drowsiness_score > 0.6` → reduce interruptibility by 0.2
- `ir_screen_looking=True` → boost "at-screen" gaze confidence

## Component 8: Cross-Modal Activity Fusion

Enrich the existing vision backend's cross-modal fusion:

- Contact mic energy + IR hands-on-pads + RGB activity → high-confidence "producing"
- Contact mic silent + IR hands-away + RGB no-face → high-confidence "away"

Soft integration — `activity_inferred` gets better inputs, no structural changes.

## Capability Tiers

### Tier 1 — Available immediately (no additional hardware)

- Lighting-invariant person detection and presence
- Head pose and gaze zone classification
- Hand tracking on dark instrument surfaces
- Screen-vs-physical activity classification
- Motion-gated power saving
- Multi-Pi fusion for robust presence

### Tier 2 — Available with on-axis IR LED ring ($3/Pi)

- Pupil detection via bright pupil effect
- PERCLOS drowsiness detection
- Blink rate monitoring
- Pupil dilation (cognitive load proxy)
- NIR rPPG heart rate estimation

## Out of Scope

- BLE mesh (Phase 4 — independent)
- Environmental sensors (Phase 2 — separate hardware)
- Stimmung-responsive lighting (Phase 5)
- VLA display changes (consumes perception-state.json automatically)
- Video streaming (structured data only)

## Deployment Sequence

1. Export YOLOv8n TFLite INT8 model on workstation
2. Provision Pi-1 and Pi-2 (Phase 0: OS, network, SSH, camera interface)
3. Install packages and deploy `hapax-ir-edge` to all 3 Pis
4. Deploy Logos API receiver (`logos/api/routes/pi.py`)
5. Deploy `ir_presence` backend + presence engine signal
6. Update perception state writer
7. Update interruptibility computation
8. Verify end-to-end: Pi capture → POST → state file → backend → perception state

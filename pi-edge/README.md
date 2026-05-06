# pi-edge — Raspberry Pi NoIR edge daemons

Edge-side code that runs on the Pi NoIR fleet (3 active Pis: ir-desk,
ir-room, ir-overhead). Captures IR perception, reports heartbeats,
and feeds the workstation council API. The corresponding workstation-side
backend is `agents/hapax_daimonion/backends/ir_presence.py`.

## Components

| File | Role |
|---|---|
| `hapax_ir_edge.py` | Main IR inference daemon — captures frames via `rpicam-still`, runs YOLOv8n person detection, face landmarks, hand + screen detection (NIR-thresholded), POSTs structured JSON reports to the council API every ~3s |
| `hapax-heartbeat.py` | System-vitals reporter — CPU temp, memory, disk, service status; POSTs to council every 60s via systemd timer |
| `cadence_controller.py` | Adaptive capture-cadence controller — backs off when nothing changes, speeds up under motion |
| `cbip_calibration.py` | Fixed-platter calibration loader — applies per-camera ROI crop plus locked exposure / white balance capture args |
| `ir_album.py` | NIR-band album-cover detection (vinyl ID for the operator's turntable surface) |
| `ir_biometrics.py` | Face-landmark biometric tracker (heart rate via rPPG, blink rate, drowsiness, head pose) — runs only when a face is detected |
| `ir_hands.py` | NIR-thresholded hand and screen detection (hand-zone classification feeds the workstation contact-mic fusion path) |
| `ir_inference.py` | Inference wrappers — YOLOv8n ONNX/TFLite + face landmark + InsightFace SCRFD |
| `ir_models.py` | Pydantic schema (`IrDetectionReport`, `IrBiometrics`, etc.) shared with the workstation backend at `shared/ir_models.py` |
| `ir_report.py` | Report builder — composes the structured JSON envelope POSTed to the council |
| `setup.sh` | Per-Pi setup script — installs dependencies, configures udev rules, copies systemd units |

## Systemd units (deployed to each Pi)

- `hapax-ir-edge.service` — `Type=simple`, runs the IR inference daemon
  continuously. Restarts on failure with 30s delay.
- `hapax-heartbeat.service` + `hapax-heartbeat.timer` — oneshot every 60s.

Units live in this directory and are deployed via `setup.sh` to each Pi.
The workstation-side `systemd/units-pi6/` directory carries Pi-6-specific
sync services (chrome, gcalendar, claude-code) — those are NOT pi-edge
scope, despite the path overlap.

## Pi fleet (per CLAUDE.md)

| Pi | IP | Role | IR inference | Co-located cam |
|---|---|---|---|---|
| Pi-1 | 192.168.68.78 | ir-desk | yes | C920-desk |
| Pi-2 | 192.168.68.52 | ir-room | yes | C920-room |
| Pi-4 | 192.168.68.53 | sentinel | no — health monitor + watch backup | — |
| Pi-5 | 192.168.68.72 | rag-edge | no — document preprocessing | — |
| Pi-6 | 192.168.68.74 | sync-hub + ir-overhead | yes | C920-overhead |

Pi-4 and Pi-5 do NOT run pi-edge code. Pi-1, Pi-2, and Pi-6 do.

## Data flow

```
Pi camera (rpicam-still)
   │
   ├── hapax_ir_edge.py — inference daemon (3s cadence)
   │      │
   │      ├── YOLOv8n person detection
   │      ├── cbip_calibration.py fixed ROI crop + capture controls
   │      ├── ir_biometrics.py rPPG + landmarks (gated on face detected)
   │      ├── ir_hands.py NIR threshold + hand-zone classification
   │      ├── ir_album.py NIR album-cover detection
   │      └── ir_report.py compose IrDetectionReport
   │              │
   │              POST /api/pi/{role}/ir
   │              │
   │              ▼
   │      ~/hapax-state/pi-noir/{role}.json
   │              │
   │              ▼
   │      agents/hapax_daimonion/backends/ir_presence.py
   │              (multi-Pi fusion → perception-state.json)
   │
   └── hapax-heartbeat.py — health reporter (60s cadence)
          │
          POST /api/pi/{hostname}/heartbeat
          │
          (Health monitor `check_pi_fleet` validates freshness +
           service status + temp + memory + disk)
```

## Inference models

- **YOLOv8n** — ONNX Runtime preferred (130ms/frame on Pi 4); TFLite
  fallback. Fine-tuned `best.onnx` on NIR studio frames.
- **Face landmarks** — MediaPipe Face Mesh (CPU) for rPPG sample regions.
- **InsightFace SCRFD** — workstation-side; the Pi only POSTs face
  bounding boxes + landmarks. The operator's face embedding match
  happens on the workstation, not the Pi.

Per-frame budget: target 200ms total (capture + inference + POST).

## Signal-quality invariants

Per `docs/superpowers/specs/2026-03-31-ir-perception-remediation-design.md`:

- Hand detection rejects frame-spanning false positives (`max_area_pct=0.25`,
  aspect ratio 0.3–3.0).
- Screen detection uses adaptive threshold (`mean_brightness × 0.3`).
- rPPG gated on face landmarks actually being available.
- `face_detected` field is exposed on `IrBiometrics`.

## Debugging

- `kill -USR1 $(pgrep -f hapax_ir_edge)` — saves a greyscale frame to
  `/tmp/ir_debug_{role}.jpg` for visual inspection.
- `scripts/cbip-calibrate-roi.py --cam-id overhead --image /tmp/ir_debug_overhead.jpg`
  — click the four fixed platter corners and write
  `~/.config/hapax/cbip-roi-overhead.json`. Use
  `--corners x,y x,y x,y x,y` for non-interactive calibration. Versioned
  defaults live in `config/cbip-calibration.yaml`; local JSON overrides are
  applied on daemon startup before downstream inference.
- `--save-frames N` — saves every Nth frame to `~/hapax-edge/captures/`
  for training data collection.
- Workstation health monitor: `agents/health_monitor/checks/pi_fleet.py`
  validates each Pi's freshness + service status.

## Deployment

`scripts/deploy-heartbeat-to-fleet.sh` (on workstation) deploys
`hapax-heartbeat.{py,service,timer}` to each active Pi. The IR
daemon is deployed manually via `setup.sh` on the target Pi (the IR
inference path has GPU-resident model weights that are too large
for batch deployment).

The systemd units carry `Restart=on-failure` + `RestartSec=30s` so
transient failures (USB camera bus-kicks, network blips) recover
without operator intervention.

## Cross-references

- Workstation backend: `agents/hapax_daimonion/backends/ir_presence.py`
- Cross-modal fusion: `agents/hapax_daimonion/backends/contact_mic_ir.py`
  (IR hand-zone + contact-mic DSP)
- Schema (shared): `shared/ir_models.py`
- Health monitor: `agents/health_monitor/checks/pi_fleet.py`
- Pi fleet expected services: `agents/health_monitor/constants.py::PI_FLEET`
- Spec: `docs/superpowers/specs/2026-03-31-ir-perception-remediation-design.md`

# Gaze Tracking Research: Webcam-Based + Multi-Camera

**Date:** 2026-03-16
**Hardware:** Logitech Brio (4K, operator-facing) + 3x C920, RTX 3090, CachyOS/Hyprland
**Purpose:** Passive attention observation for Hapax Corpora content intelligence

---

## 1. Single-Camera Software Options

### Tier A: Best candidates

**L2CS-Net** ([GitHub](https://github.com/Ahmednull/L2CS-Net))
- ResNet-50 backbone, 3.92° angular error on MPIIGaze
- 2025 GhostBlock variant cuts FLOPs ~48% with comparable accuracy
- PyTorch, unconstrained environments, no IR needed

**MobileGaze** ([GitHub](https://github.com/yakhyo/gaze-estimation))
- MobileNet v2 / MobileOne s0-s4 backends
- ONNX export for fast CPU inference, "near-instant" with MobileOne
- Best for resource-constrained continuous use

**ptgaze** ([PyPI](https://pypi.org/project/ptgaze/))
- `pip install ptgaze` then `ptgaze --mode eth-xgaze`
- MediaPipe face detection + gaze model, works out of box
- Good prototyping starting point

**gaze-tracking-pipeline** ([GitHub](https://github.com/pperle/gaze-tracking-pipeline))
- Full camera → face normalization → gaze vector → screen coordinate pipeline
- Includes calibration, 3D visualization, "laser pointer" mode
- Most directly relevant to screen-zone mapping

**GazeCapsNet** ([Paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC11860563/))
- 2025, 11.7M params, 20ms/frame, eliminates landmark step
- Capsule networks + MobileNet v2, designed for real-time

## 2. Accuracy: What's Realistic

| System | Angular Error | Screen Error (~27" monitor) |
|--------|-------------|---------------------------|
| L2CS-Net (1 cam) | 3.92° | ~4-5 cm |
| Webcam calibrated (2024 Frontiers) | 1.9° | ~2 cm / ~100px |
| Webcam vs EyeLink 1000 (2024 PMC) | 1.4° | ~1.5 cm |
| **Tri-Cam (3 cams, 2024)** | **~0.8°** | **2.06 cm** |
| Tobii Eye Tracker 5 | ~0.7° | 1.95 cm |

**Practical resolution with single camera:**
- Left/center/right third: reliable
- Quadrants (2x2): reliable
- 3x3 grid (9 zones): marginal
- Individual UI elements: not possible

**With multi-camera (3+ views):**
- 9-zone grid: reliable (Tri-Cam matches Tobii)
- Specific signal zones on Corpora: achievable
- Works even with glasses, moderate head movement

## 3. Compute Requirements

| Model | Params | VRAM (fp16) | CPU Inference |
|-------|--------|-------------|---------------|
| MobileNet v2 (MobileGaze) | 3.4M | ~10 MB | 10-20ms |
| MobileOne s0 | 5M | ~15 MB | 5-15ms |
| ResNet-18 (ptgaze) | 11M | ~23 MB | 15-30ms |
| GazeCapsNet | 11.7M | ~25 MB | 20ms |
| ResNet-50 (L2CS-Net) | 25.6M | ~45 MB | 30-60ms |

All models fit well within constraints. At 1 FPS, even CPU-only is viable.
MediaPipe Face Mesh (face detection frontend) runs <5ms on CPU.

## 4. Calibration

- Appearance models (L2CS-Net, MobileGaze) are calibration-free for gaze *direction*
- Screen coordinate mapping needs one-time 4-point calibration (~30 seconds)
- Calibration holds across sessions if camera/monitor don't move
- With multi-camera: calibration matrix computed from ChArUco board (one-time 5-min setup)

## 5. Dedicated Hardware: Not Recommended

**Tobii Eye Tracker 5** ($300): Linux effectively unsupported, hostile licensing, SDK requires $1,500/yr
**Tobii Pro Spark** ($3-4K): Linux SDK exists but overkill for zone-level attention
**Pupil Labs** ($2-6K): Requires wearing glasses at desk, impractical for passive sensing

**Verdict:** Multi-camera webcam approach matches or exceeds consumer eye tracker accuracy at zero additional hardware cost.

## 6. Privacy/Axiom Considerations

- Operator gaze data on operator: clean under `single_user` (weight 100)
- Guest present: face recognition gate — only process operator face, discard all others
- Store only zone-level aggregates, not raw coordinates
- Rolling window retention, no permanent history
- Raw gaze data stays in-memory, only derived attention weights reach content scheduler
- No export to external systems (`corporate_boundary` axiom)

## 7. Multi-Camera Advantage

With 4-6 cameras, gaze tracking transforms from "ML estimation" to "geometric computation":
- Triangulate actual gaze-screen intersection point
- Handle occlusion (face turned away from one camera → others still see)
- Robust to glasses, head movement, lighting changes
- Room-wide coverage (not just at desk)

See companion doc: `multi-camera-operator-sensing-research.md` for the full multi-view perception capability space.

## Key Software Links

- L2CS-Net: https://github.com/Ahmednull/L2CS-Net
- MobileGaze: https://github.com/yakhyo/gaze-estimation
- ptgaze: https://pypi.org/project/ptgaze/
- gaze-tracking-pipeline: https://github.com/pperle/gaze-tracking-pipeline
- MediaPipe Face Mesh: https://github.com/google-ai-edge/mediapipe
- rtmlib (body pose): https://github.com/Tau-J/rtmlib
- Caliscope (multi-cam calibration): https://github.com/mprib/caliscope

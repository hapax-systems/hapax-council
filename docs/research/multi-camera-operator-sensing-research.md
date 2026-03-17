# Multi-Camera Operator Sensing Research

**Date:** 2026-03-16
**Hardware:** 4-6 consumer webcams (Logitech Brio + C920s), RTX 3090 (24GB VRAM)
**Purpose:** Personal AI agent understanding operator physical state, attention, posture, and engagement to drive ambient display and voice assistant.

---

## 1. Multi-View 3D Gaze Estimation

### Key Finding: Tri-Cam achieves near-Tobii accuracy with 3x $10 webcams

**Tri-Cam** (2024, arXiv 2409.19554) is the most directly relevant system:
- Uses **3 non-depth RGB webcams** ($10 each) for gaze tracking
- **Triangulates eye position** across views to get depth, then projects gaze vector onto screen plane
- Accuracy: **2.06 cm** mean gaze error vs Tobii's **1.95 cm** — essentially comparable
- Supports **wider free movement area** than Tobii (not head-locked)
- Features **implicit calibration** using natural mouse clicks — no explicit calibration session needed
- Split network architecture for efficient training; auxiliary multitask validation across camera triplet

**Accuracy Ranges (consumer webcam gaze):**
- Calibrated users: ~5 degrees angular error
- Uncalibrated users: ~10 degrees angular error
- Multi-camera triangulation: **1.4-2.7 degrees** (approaching professional hardware)
- Accuracy degrades toward screen edges, especially on large displays

**Multi-View Gaze Target Estimation** (ICCV 2025) extends to identifying *what* in the scene someone is looking at from multiple camera perspectives, using geometric relationships between calibrated views.

**What 4-6 cameras add beyond Tri-Cam's 3:**
- Redundancy for occlusion (hand on face, looking away from a camera)
- Coverage when operator moves around room (not just at desk)
- Potential for higher accuracy through additional triangulation constraints

### Software
- [Multi-view gaze estimation (GitHub)](https://github.com/dongzelian/multi-view-gaze)
- [GazeOnce](https://openaccess.thecvf.com/content/CVPR2022/papers/Zhang_GazeOnce_Real-Time_Multi-Person_Gaze_Estimation_CVPR_2022_paper.pdf) — real-time multi-person gaze (CVPR 2022)

### Relevance to Council
Gaze intersection with screen plane tells the ambient display which region the operator is attending to. Combined with the visual layer's signal prioritization, this enables attention-aware rendering — dimming signals outside the operator's focal area, brightening signals they haven't noticed.

---

## 2. Multi-View 3D Head Pose Estimation

### Key Finding: Multi-camera head pose is essentially a solved geometric problem

With 2+ calibrated cameras, head pose becomes **triangulation of facial landmarks** rather than monocular ML estimation. This is dramatically more accurate than single-camera approaches.

**MediaPipe Face Mesh:**
- **468 3D face landmarks** in real-time, even on CPU
- 478 landmarks with iris refinement enabled
- Provides a **face pose transformation matrix** (rotation + translation) in metric 3D space
- Runs at **30 FPS on CPU alone** — negligible GPU cost
- When triangulated across multiple views: sub-degree head pose accuracy

**Multi-View Triangulation with MediaPipe:**
- [bodypose3d](https://github.com/TemugeB/bodypose3d) demonstrates the approach: run MediaPipe per-camera, triangulate via DLT/SVD
- RMSE of **30.9 mm** for body keypoints with consumer webcams (MediaPipe + stereo triangulation)
- Same approach works for face landmarks — even more accurate due to smaller working volume

**Head Pose as Attention Proxy:**
- Head orientation alone predicts attention direction to within **~10 degrees**
- Combined with body orientation: **~5 degree** effective accuracy
- LightNet (2025): lightweight head pose model specifically designed for engagement assessment
- Correlation between head pose and engagement is well-validated in classroom research

**Multiple View Geometry Transformers (MVGFormer, CVPR 2024):**
- Transformer-based multi-view fusion for 3D pose
- Handles variable numbers of views
- State-of-the-art on multi-view benchmarks

### Relevance to Council
Head pose is the cheapest and most reliable attention signal. At 30 FPS on CPU with MediaPipe, this costs essentially nothing. Multi-camera triangulation eliminates the single-camera failure mode of profile/rear views. Head direction + body orientation gives a robust "attention cone" for the ambient display.

---

## 3. Multi-View 3D Body Pose Estimation

### Key Finding: RTMPose at 430+ FPS on a GTX 1660 Ti — processing 6 cameras is trivially within budget

**Tier 1: Lightweight Detection (rtmlib)**
- [rtmlib](https://github.com/Tau-J/rtmlib) — RTMPose/RTMO/RTMW **without mmcv/mmpose/mmdet dependencies**
- Dependencies: only numpy, opencv, onnxruntime
- RTMPose-m: **75.8% AP on COCO, 90+ FPS on CPU (i7-11700), 430+ FPS on GTX 1660 Ti**
- Supports CPU, CUDA, MPS backends
- Modes: 'performance', 'lightweight', 'balanced'
- On an RTX 3090, expect **500+ FPS per stream** — processing 6 cameras at 5 FPS each uses <10% of capacity

**Tier 2: One-Stage Detection (RTMO, CVPR 2024)**
- No separate person detector needed — single model does detection + pose
- RTMO-l: **74.8% AP, 141 FPS on V100**
- Faster than RTMPose when >4 persons visible (irrelevant for single-operator, but useful for guest detection)
- Available in rtmlib

**Tier 3: Multi-View Triangulation Frameworks**

| Framework | Description | Camera Support | Key Feature |
|-----------|-------------|----------------|-------------|
| [Pose2Sim](https://github.com/perfanalytics/pose2sim) | Full pipeline: 2D pose → triangulation → OpenSim | Any number | Research-grade accuracy (0.35-1.6 degree joint angle error) |
| [FreeMoCap](https://github.com/freemocap/freemocap) | GUI-based markerless MoCap | 2+ webcams/GoPros/phones | ChArUco calibration, Blender output |
| [bodypose3d](https://github.com/TemugeB/bodypose3d) | Minimal MediaPipe + DLT triangulation | 2+ cameras | Simple, educational, easy to extend |
| [Caliscope](https://github.com/mprib/pyxy3d) | GUI calibration + pose estimation | Multiple webcams | Loads ONNX models (RTMPose, SLEAP, DeepLabCut) |
| [EasyMocap](https://github.com/zju3dv/EasyMocap) | ZJU multi-view MoCap | Multiple | SMPL body model fitting |
| [SelfPose3d](https://github.com/CAMMA-public/SelfPose3d) | Self-supervised multi-person multi-view | Calibrated multi-cam | No 3D ground truth needed |

**Posture State Detection from Skeleton:**
From triangulated 3D skeleton keypoints, these states are classifiable with high confidence:
- **Leaning forward** (engaged): shoulder-hip angle relative to vertical
- **Leaning back** (relaxed/disengaged): same angle, opposite direction
- **Fidgeting** (restless): variance of keypoint positions over sliding window
- **Still** (focused or asleep): low variance — disambiguated by head pose (up = focused, down = asleep)
- **Slouching**: ear-shoulder-hip alignment angle
- Transformer-based posture classifiers achieve **92.7% accuracy**, Random Forest achieves **87.6%** with <30s training

### Relevance to Council
The body skeleton is the richest physical state signal. With rtmlib on RTX 3090, processing all 6 cameras is well within compute budget even at 5-10 FPS per camera. Triangulated 3D skeleton gives posture classification that single-camera can't reliably do (e.g., leaning forward vs. camera being tilted).

---

## 4. Attention Estimation Beyond Eyes

### Key Finding: Head pose + body orientation is sufficient for attention-aware ambient display

**Head Pose Alone:**
- Predicts gaze direction to within **~10 degrees** — enough to know "looking at screen", "looking at door", "looking at phone on desk"
- LightNet (2025): purpose-built lightweight model for engagement assessment from head pose
- Accuracy of 89.36% for engagement classification using head pose + facial expression CNN

**Body Orientation Adds:**
- Torso direction provides "attention zone" even when head is briefly turned
- Unified body orientation estimation (2025 paper) achieves robust engagement detection in real classroom settings
- Body orientation + head pose together: **~5 degree effective attention accuracy**

**Micro-Movement Signals:**
- Gesture frequency correlates with cognitive load and arousal
- Stillness duration correlates with deep focus (or sleep — disambiguated by head pose)
- Postural shifts (crossing legs, shifting weight) correlate with discomfort or restlessness
- These can be extracted from skeleton keypoint time series without additional models

**Multi-Modal Fusion (Head + Body + Movement):**
- Video-based real-time engagement monitoring using MediaPipe (2025)
- Multi-feature analysis combining head pose, facial landmarks, and body posture
- Achieves reliable engagement/disengagement classification without eye tracking

### What You Don't Need Eye Tracking For
For an ambient display and voice assistant, the question is usually coarse:
1. Is the operator at the desk? (body detection)
2. Are they looking at the screen? (head pose, ~10 degree accuracy)
3. Are they engaged or idle? (posture + micro-movement)
4. Are they available for interruption? (posture + movement stability)

These do NOT require gaze-on-screen-element precision. Head pose + body pose is sufficient.

---

## 5. Emotion/Arousal from Posture and Movement

### Key Finding: Body language provides arousal/valence signals that complement watch biometrics

**Current Accuracy:**
- State-of-the-art: **83.3% accuracy for arousal, 80.2% for valence** from body movement + facial expression
- Pose estimation tools (OpenPose, MediaPipe) extract skeleton features → neural networks classify emotion
- Over 40% of 2022+ multimodal emotion papers use trimodal configurations (face + body + another modality)

**Body-Specific Signals:**
| Signal | Indicator | Detection Method |
|--------|-----------|-----------------|
| Gesture frequency increase | Rising arousal/agitation | Keypoint velocity over time window |
| Postural expansion | Confidence/comfort | Shoulder width + torso height |
| Postural contraction | Stress/discomfort | Shoulder narrowing + forward curl |
| Self-touch (face, hair) | Anxiety/thinking | Hand-to-face proximity |
| Stillness + upright | Focused attention | Low keypoint variance + vertical spine |
| Restless shifting | Boredom/discomfort | High variance without purposeful motion |
| Slumping over time | Fatigue | Gradual decrease in torso-vertical angle |

**Complementarity with Watch Biometrics:**
- Watch provides: heart rate, HRV, skin temperature, sleep state
- Camera provides: posture, gesture frequency, attention direction, fidgeting
- Together: heart rate increase + postural expansion = excitement/engagement
- Heart rate increase + postural contraction = stress/anxiety
- Low HRV + stillness + head down = deep focus or fatigue (disambiguated by time of day / sleep data)

**Key Challenge:**
Researchers note difficulty characterizing the "organic combination of body parts, movement strength, and posture of specific emotional states" — individual differences are large. For a single-operator system, this is actually an advantage: the system can learn the operator's personal baseline and deviations.

---

## 6. Multi-Camera Calibration and Fusion

### Key Finding: One-time 5-minute setup with a printed ChArUco board

**Calibration Pipeline:**
1. Print a ChArUco board (A3 or larger)
2. Wave it in view of all cameras simultaneously
3. Software automatically extracts intrinsics (per camera) and extrinsics (camera-to-camera transforms)
4. Result: all cameras mapped to a shared 3D coordinate system

**Tools (ranked by ease of use):**

| Tool | GUI? | Board Types | Notes |
|------|------|-------------|-------|
| [Caliscope](https://github.com/mprib/pyxy3d) | Yes | ChArUco | Best GUI, designed for non-experts |
| [FreeMoCap](https://freemocap.org/) | Yes | ChArUco | Full MoCap pipeline, calibration built-in |
| [Multical](https://github.com/oliver-batchelor/multical) | No (CLI) | ChArUco, AprilGrid | Robust bundle adjustment, cached detections |
| OpenCV native | No (code) | ChArUco, chessboard | `cv2.calibrateCamera()` + `cv2.stereoCalibrate()` |
| [camera-fusion](https://pypi.org/project/camera-fusion/) | No | ChArUco | Minimal Python package |

**GSoC 2025 OpenCV Project:**
A dedicated GSoC 2025 project built a multi-camera calibration pipeline directly into OpenCV, comparing chessboard vs ChArUco vs ArUco markers. ChArUco is recommended because corner accuracy is much higher than pure ArUco marker corners.

**Practical Considerations:**
- ChArUco boards are robust to partial occlusion (each corner is independently identifiable)
- Calibration should be redone if cameras are bumped — mount them firmly
- Non-overlapping camera pairs can be calibrated via CALICO method (calibration pattern on a rigid rig)
- For 4-6 cameras with overlapping views of a room: single ChArUco wave-through takes <5 minutes
- Recalibration check: periodically verify by detecting a known object at a known position

**Synchronization:**
- Consumer USB webcams are NOT hardware-synchronized
- Software sync approaches: network timestamp alignment, or FreeMoCap's automatic sync via motion correlation
- At 1-5 FPS sampling rate for continuous monitoring, sync precision of ~50ms is sufficient (human movement is slow)
- At 30 FPS for real-time tracking, frame timestamp matching within ~16ms is needed

---

## 7. Lightweight Architectures for Continuous Multi-View

### Key Finding: 6 cameras at 5 FPS uses <5% of RTX 3090 capacity

**Compute Budget Analysis:**

RTX 3090 specs: 24GB VRAM, 36 TFLOPS FP32, 70+ TFLOPS FP16 (with TensorRT)

| Component | Model | Per-Frame Cost | FPS/GPU | VRAM |
|-----------|-------|---------------|---------|------|
| Person detection + pose | RTMO-l (one-stage) | ~7ms on V100 | 141 | ~500MB |
| Pose only (with detector) | RTMPose-m | ~2.3ms on 1660 Ti | 430 | ~300MB |
| Face landmarks | MediaPipe Face Mesh | ~3ms on CPU | 30 (CPU) | ~0 GPU |
| Lightweight pose (CPU) | Lightweight OpenPose | ~38ms on i7 CPU | 26 (CPU) | ~0 GPU |

**Strategy: Hybrid CPU/GPU Pipeline**

Recommended architecture for continuous 6-camera monitoring:

```
CPU Thread Pool (per camera):
  - Frame capture (threaded, one per camera)
  - MediaPipe Face Mesh (30 FPS on CPU per camera = trivial)
  - Head pose extraction from face landmarks
  - Basic presence detection (face detected yes/no)

GPU (RTX 3090, batched):
  - RTMPose body skeleton: process all 6 cameras in round-robin
  - At 2-3 FPS per camera = 12-18 inferences/sec = <5% GPU
  - Triangulation: CPU-side linear algebra (DLT), negligible cost

Background (low-frequency):
  - Posture classification: every 1-2 seconds from skeleton history
  - Engagement estimation: every 2-5 seconds from attention signals
  - Room position update: every 1-2 seconds from multi-view detection
```

**Total estimated GPU load: 3-8% of RTX 3090**

This leaves >90% GPU capacity free for:
- LLM inference (Ollama/tabbyAPI)
- Visual layer compositor (GStreamer + custom shader)
- Anything else

**USB Bandwidth Constraints:**
- USB 2.0: **one camera per USB controller** (not per port — per controller)
- USB 3.0: **4+ cameras per USB 3.0 controller** (shared bandwidth)
- Logitech Brio is USB 3.0, C920 is USB 2.0 (but can run on USB 3.0 hub)
- **Solution:** Use separate USB 3.0 controllers. Most motherboards have 2-3. Add a PCIe USB 3.0 card (~$25) for more channels
- At 720p 5 FPS (MJPEG), bandwidth per camera is ~15 Mbps — USB 3.0's 5 Gbps handles many cameras
- Reduce resolution to 480p for body pose (skeleton detection doesn't need high res)
- Keep 720p/1080p only on the camera with best face view (for gaze)

**Round-Robin vs. Parallel:**
- At 2-3 FPS per camera, round-robin processing is fine — no need for parallel GPU streams
- Process camera 1 frame, camera 2 frame, ..., camera 6 frame, repeat
- Total cycle time: 6 * 7ms = 42ms — could actually do 20+ FPS per camera if needed

---

## 8. What Multi-Camera Opens Up That Single-Camera Cannot

### 8.1 Operator Position in Room
- Triangulated person detection gives **3D room coordinates**, not just "in frame / not in frame"
- Know if operator is at desk, at whiteboard, on couch, in kitchen area
- Sub-meter accuracy with 4+ cameras in a room
- Enables: location-aware ambient display behavior, voice assistant volume adjustment

### 8.2 Walking Away Detection
- Single camera: person disappears from frame — could be occlusion, could be leaving
- Multi-camera: person visible in at least one camera during transition; definitive "left room" when absent from all views
- Enables: reliable "operator away" state for voice daemon pause, ambient display sleep mode
- Transition tracking: "walking toward door" detectable before operator actually leaves

### 8.3 Object Interaction Detection
- Multi-view resolves hand occlusion — at least one camera sees the hands
- Detectable interactions: picking up phone, drinking coffee, typing, writing, eating
- Method: hand keypoint proximity to known object regions, or skeleton pose classification
- Enables: "operator is on phone" → suppress voice assistant; "operator drinking coffee" → don't interrupt

### 8.4 Posture Changes Over Time (Ergonomic Awareness)
- Continuous spine angle tracking from triangulated skeleton
- Slouch detection with **30.9mm RMSE** accuracy (MediaPipe + stereo triangulation)
- Track cumulative sitting time, posture degradation over hours
- Compare against baseline "good posture" calibrated per operator
- Open source tools: [PostureCV](https://github.com/richardli52/postureCV), [posture-monitor](https://github.com/mecantronic/posture-monitor), [SitPose](https://arxiv.org/html/2412.12216v1) (2024)
- Enables: gentle ambient display cue when posture degrades, standing break reminders

### 8.5 Guest Detection from Any Angle (Consent/Governance)
- Multi-camera ensures a guest is detected regardless of which direction they approach from
- Person count change: single-person baseline → two persons detected = guest present
- No facial recognition needed for the consent trigger — just "non-operator person detected"
- The operator's skeleton/appearance can be baselined; any other detection = guest
- Triggers: consent governance (interpersonal_transparency axiom), privacy mode for ambient display
- Disambiguation: operator is always present (baseline), so any additional detection = guest
- Multi-camera reduces false negatives: guest entering from any angle is caught

### 8.6 Attention Continuity Across Room
- Single camera loses the operator when they move
- Multi-camera maintains continuous attention tracking as operator moves between desk, standing area, etc.
- Enables: ambient display follows operator's position (if multiple displays), voice assistant adjusts based on room position

---

## Recommended Software Stack

### Core Pipeline
| Layer | Tool | Role | Compute |
|-------|------|------|---------|
| Capture | OpenCV VideoCapture (threaded) | Multi-camera frame grab | CPU |
| Calibration | Caliscope or Multical | Extrinsic/intrinsic estimation | One-time |
| Face/Head | MediaPipe Face Mesh | 468 landmarks, head pose matrix | CPU |
| Body Pose | rtmlib (RTMPose-m or RTMO) | 2D skeleton per camera | GPU (<5%) |
| Triangulation | DLT/SVD (numpy) | 2D→3D fusion | CPU |
| Gaze (optional) | Tri-Cam approach | Screen gaze point | GPU (light) |

### Analysis Layer
| Signal | Method | Frequency |
|--------|--------|-----------|
| Presence | Face detection any camera | 5 Hz |
| Attention direction | Head pose triangulation | 5 Hz |
| Posture state | Skeleton angle classification | 1 Hz |
| Engagement level | Posture + micro-movement | 0.5 Hz |
| Room position | Multi-view person triangulation | 1 Hz |
| Guest detection | Person count change | 1 Hz |
| Arousal estimate | Movement variance + posture | 0.2 Hz |

### Integration Points with Council
- **Visual layer**: attention-aware rendering, posture cue overlays, privacy mode on guest detection
- **Voice daemon**: interruptibility estimation, suppress when on phone, adjust volume by room position
- **Watch biometrics fusion**: body arousal + heart rate = richer state model
- **Consent engine**: guest detection → consent governance trigger
- **Reactive engine**: physical state changes as inotify-like events for agent cascading

---

## Key Papers and References

1. **Tri-Cam** (2024) — [arXiv 2409.19554](https://arxiv.org/abs/2409.19554) — 3-webcam gaze tracking, 2.06cm accuracy
2. **Multi-view Gaze Target Estimation** (ICCV 2025) — [Paper](https://openaccess.thecvf.com/content/ICCV2025/papers/Miao_Multi-view_Gaze_Target_Estimation_ICCV_2025_paper.pdf)
3. **MVGFormer** (CVPR 2024) — [Paper](https://openaccess.thecvf.com/content/CVPR2024/papers/Liao_Multiple_View_Geometry_Transformers_for_3D_Human_Pose_Estimation_CVPR_2024_paper.pdf) — Multi-view geometry transformers
4. **RTMO** (CVPR 2024) — [arXiv 2312.07526](https://arxiv.org/abs/2312.07526) — One-stage real-time pose, 74.8% AP, 141 FPS
5. **RTMPose** — [arXiv 2303.07399](https://arxiv.org/abs/2303.07399) — 75.8% AP, 430+ FPS on 1660 Ti
6. **RTMW** (2024) — [arXiv 2407.08634](https://arxiv.org/html/2407.08634v1) — Real-time 2D+3D whole-body pose
7. **SelfPose3d** (2024) — [arXiv 2404.02041](https://arxiv.org/html/2404.02041v2) — Self-supervised multi-person multi-view
8. **Markerless Multi-view 3D HPE Survey** (2024) — [arXiv 2407.03817](https://arxiv.org/html/2407.03817v1)
9. **Real-time multi-camera 3D HPE at the edge** (2024) — [ScienceDirect](https://www.sciencedirect.com/science/article/pii/S0957417424009552)
10. **LightNet** (2025) — [Springer](https://link.springer.com/article/10.1007/s44443-025-00187-z) — Lightweight head pose for engagement
11. **SitPose** (2024) — [arXiv 2412.12216](https://arxiv.org/html/2412.12216v1) — Sitting posture + sedentary detection
12. **Dual Focus-3D** (2025) — [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC12251888/) — Hybrid 3D gaze estimation

---

## Bottom Line

With 4-6 consumer webcams and an RTX 3090, you can build a continuous operator sensing system that:

1. **Knows where in the room the operator is** (sub-meter accuracy)
2. **Tracks head orientation** to ~5 degrees (head pose + body orientation)
3. **Classifies posture** (engaged/relaxed/fidgeting/slouching) at 92%+ accuracy
4. **Estimates engagement level** from posture + micro-movements without eye tracking
5. **Detects guests** from any approach angle (consent governance)
6. **Fuses with watch biometrics** for arousal/stress/fatigue estimation
7. **Uses <5% of the RTX 3090** at comfortable monitoring frequencies (1-5 Hz)
8. **Runs the face/head pipeline entirely on CPU** (MediaPipe), reserving GPU for body pose and LLM

The software stack is mature: rtmlib + MediaPipe + Caliscope/Multical + numpy triangulation. No custom ML training needed for the core pipeline. Posture/engagement classifiers can be trained on operator-specific data with simple models (Random Forest, small MLP) in minutes.

The hard part is not the ML — it's the USB bandwidth planning, camera mounting, and integration with the reactive engine.

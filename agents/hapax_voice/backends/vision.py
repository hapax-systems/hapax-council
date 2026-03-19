"""Vision perception backend — YOLO detection/pose/tracking + scene + gaze + gestures.

Processes camera frames on a background thread with GPU inference via
ultralytics YOLO11n. Round-robins across all configured cameras (~3s per
camera). VRAMLock coordinates GPU access with other models (CLAP, etc.).

Also runs CPU-only classifiers on the operator camera:
- Gaze direction via MediaPipe Face Mesh head pose estimation
- Hand gestures via MediaPipe Hands
- Scene classification via Places365 ResNet18 (GPU, ~150MB)

Tier: SLOW (~12s cadence for full camera sweep). contribute() reads from
a thread-safe cache and never blocks on inference.
"""

from __future__ import annotations

import base64
import json
import logging
import threading
import time
from typing import Any

import cv2
import numpy as np

from agents.hapax_voice.perception import PerceptionTier
from agents.hapax_voice.primitives import Behavior
from agents.hapax_voice.vram import VRAMLock

log = logging.getLogger(__name__)

_DEFAULT_POLL_INTERVAL = 3.0  # per-camera interval


_GESTURE_LABELS = {
    0: "unknown",
    1: "closed_fist",
    2: "open_palm",
    3: "pointing_up",
    4: "thumb_down",
    5: "thumb_up",
    6: "victory",
    7: "i_love_you",
}


def _estimate_gaze(face_landmarks: list, image_w: int, image_h: int) -> str:
    """Estimate gaze direction from MediaPipe FaceLandmarker landmarks.

    Uses nose tip (1), left eye outer (33), right eye outer (263)
    to approximate head yaw and pitch.

    Returns "screen", "hardware", "away", or "person".
    """
    try:
        # FaceLandmarker returns list of NormalizedLandmark with .x, .y, .z
        nose = face_landmarks[1]
        left_eye = face_landmarks[33]
        right_eye = face_landmarks[263]

        eye_mid_x = (left_eye.x + right_eye.x) / 2
        yaw = (nose.x - eye_mid_x) * image_w

        eye_mid_z = (left_eye.z + right_eye.z) / 2
        pitch = (nose.z - eye_mid_z) * image_w

        if abs(yaw) < 15 and abs(pitch) < 20:
            return "screen"
        elif abs(yaw) > 40:
            return "away"
        elif yaw > 15:
            return "hardware"
        else:
            return "person"
    except Exception:
        return "unknown"


def _infer_cross_modal_activity(
    per_camera_behaviors: dict[str, dict[str, Any]],
    audio_activity: str,
    audio_genre: str,
    audio_energy: float,
) -> tuple[str, float]:
    """Infer activity from cross-camera + audio evidence.

    Returns ``(activity, confidence)`` using rule-based pattern matching
    ordered by specificity.
    """
    op = per_camera_behaviors.get("operator", {})

    # All detected objects across cameras
    all_objects: set[str] = set()
    for b in per_camera_behaviors.values():
        for obj_str in b.get("scene_objects", "").split(","):
            if obj_str.strip():
                all_objects.add(obj_str.strip())

    person_present = any(b.get("person_count", 0) > 0 for b in per_camera_behaviors.values())

    # Music production: audio music + person + equipment visible
    if audio_activity == "production" and person_present:
        return ("producing", 0.90)

    if audio_genre and audio_genre != "unknown" and audio_energy > 0.02 and person_present:
        return ("listening", 0.80)

    # Coding: keyboard visible + person + gaze at screen
    if "keyboard" in all_objects and person_present and op.get("gaze_direction") == "screen":
        return ("coding", 0.75)

    # On phone: cell phone visible near person
    if "cell phone" in all_objects and person_present:
        return ("on_phone", 0.70)

    # Conversation: multiple people + speech
    person_count = max((b.get("person_count", 0) for b in per_camera_behaviors.values()), default=0)
    if person_count > 1 and audio_activity == "conversation":
        return ("conversation", 0.85)

    # General presence
    if person_present:
        if op.get("posture") == "upright" or op.get("pose_summary") == "seated":
            return ("at_desk", 0.60)
        return ("present", 0.50)

    return ("away", 0.90)


class _VisionCache:
    """Thread-safe cache for vision inference results.

    Stores per-camera behavior dicts and fuses them using consensus voting
    and camera specialization (operator cam for face/gaze, room cam for
    posture, union across all cameras for scene objects).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._detected_objects: str = "[]"
        self._per_camera_detections: dict[str, str] = {}  # role → JSON detections
        self._per_camera_behaviors: dict[str, dict[str, Any]] = {}  # role → behavior dict
        self._person_count: int = 0
        self._pose_summary: str = "unknown"
        self._scene_objects: str = ""
        self._scene_type: str = "unknown"
        self._gaze_direction: str = "unknown"
        self._hand_gesture: str = "none"
        self._nearest_person_distance: str = "none"
        self._ambient_brightness: float = 0.0
        self._color_temperature: str = "unknown"
        self._posture: str = "unknown"
        self._detected_action: str = "unknown"
        self._top_emotion: str = "neutral"
        self._operator_confirmed: bool = False
        self._scene_state_clip: str = ""
        self._updated_at: float = 0.0

        # Audio behaviors injected externally for cross-modal fusion
        self._audio_activity: str = "idle"
        self._audio_genre: str = "unknown"
        self._audio_energy: float = 0.0

    def _merged_detections(self) -> str:
        """Merge detections from all cameras into one JSON array."""
        import json as _json

        all_dets = []
        for role, dets_json in self._per_camera_detections.items():
            try:
                dets = _json.loads(dets_json)
                for d in dets:
                    d["camera"] = role  # tag which camera
                all_dets.extend(dets)
            except (ValueError, TypeError):
                pass
        return _json.dumps(all_dets) if all_dets else self._detected_objects

    def set_audio_context(self, *, activity: str, genre: str, energy: float) -> None:
        """Inject audio classification results for cross-modal fusion."""
        with self._lock:
            self._audio_activity = activity
            self._audio_genre = genre
            self._audio_energy = energy

    def _fused_read(self) -> dict:
        """Fuse per-camera behaviors using consensus voting and camera specialization.

        Must be called while holding ``self._lock``.
        """
        now = time.monotonic()
        stale_threshold = 15.0  # seconds

        # ── Person presence: majority vote ──────────────────────────────
        person_votes: list[bool] = []
        for behaviors in self._per_camera_behaviors.values():
            if now - behaviors.get("ts", 0) < stale_threshold:
                person_votes.append(behaviors.get("person_count", 0) > 0)
        person_present = sum(person_votes) >= max(1, len(person_votes) // 2)
        person_count = (
            max(b.get("person_count", 0) for b in self._per_camera_behaviors.values())
            if self._per_camera_behaviors
            else 0
        )

        # ── Camera specialization: authoritative camera per behavior ───
        op = self._per_camera_behaviors.get("operator", {})
        room = self._per_camera_behaviors.get("room", {})

        # Face/emotion/gaze: BRIO operator cam only (close-up)
        gaze = op.get("gaze_direction", "unknown")
        emotion = op.get("top_emotion", "neutral")
        hand_gesture = op.get("hand_gesture", "none")

        # Posture: prefer room cam (full body), fallback to operator
        posture = room.get("posture", op.get("posture", "unknown"))
        pose_summary = room.get("pose_summary", op.get("pose_summary", "unknown"))

        # Scene objects: union across all cameras
        all_objects: set[str] = set()
        for b in self._per_camera_behaviors.values():
            objs = b.get("scene_objects", "")
            if objs:
                all_objects.update(o.strip() for o in objs.split(",") if o.strip())
        scene_objects = ", ".join(sorted(all_objects))

        # ── Cross-modal activity inference ──────────────────────────────
        activity, _confidence = _infer_cross_modal_activity(
            self._per_camera_behaviors,
            self._audio_activity,
            self._audio_genre,
            self._audio_energy,
        )

        return {
            "person_count": person_count,
            "operator_present": person_present,
            "operator_confirmed": self._operator_confirmed,
            "gaze_direction": gaze,
            "top_emotion": emotion,
            "hand_gesture": hand_gesture,
            "posture": posture,
            "pose_summary": pose_summary,
            "scene_objects": scene_objects,
            # Global (not per-camera):
            "scene_type": self._scene_type,
            "ambient_brightness": self._ambient_brightness,
            "color_temperature": self._color_temperature,
            "detected_action": activity,
            "detected_objects": self._merged_detections(),
            "nearest_person_distance": self._nearest_person_distance,
            "scene_state_clip": self._scene_state_clip,
        }

    def update(
        self,
        *,
        detected_objects: str,
        person_count: int,
        pose_summary: str,
        scene_objects: str,
        scene_type: str | None = None,
        gaze_direction: str | None = None,
        hand_gesture: str | None = None,
        nearest_person_distance: str | None = None,
        ambient_brightness: float | None = None,
        color_temperature: str | None = None,
        posture: str | None = None,
        detected_action: str | None = None,
        top_emotion: str | None = None,
        operator_confirmed: bool | None = None,
        scene_state_clip: str | None = None,
    ) -> None:
        with self._lock:
            self._detected_objects = detected_objects
            # Store per-camera detections for merged output
            if hasattr(self, "_current_role"):
                self._per_camera_detections[self._current_role] = detected_objects
                # Store per-camera behaviors for consensus fusion
                self._per_camera_behaviors[self._current_role] = {
                    "person_count": person_count,
                    "gaze_direction": gaze_direction or "unknown",
                    "top_emotion": top_emotion or "neutral",
                    "hand_gesture": hand_gesture or "none",
                    "posture": posture or "unknown",
                    "pose_summary": pose_summary or "unknown",
                    "scene_objects": scene_objects or "",
                    "ts": time.monotonic(),
                }
            self._person_count = person_count
            self._pose_summary = pose_summary
            self._scene_objects = scene_objects
            if scene_type is not None:
                self._scene_type = scene_type
            if gaze_direction is not None:
                self._gaze_direction = gaze_direction
            if hand_gesture is not None:
                self._hand_gesture = hand_gesture
            if nearest_person_distance is not None:
                self._nearest_person_distance = nearest_person_distance
            if ambient_brightness is not None:
                self._ambient_brightness = ambient_brightness
            if color_temperature is not None:
                self._color_temperature = color_temperature
            if posture is not None:
                self._posture = posture
            if detected_action is not None:
                self._detected_action = detected_action
            if top_emotion is not None:
                self._top_emotion = top_emotion
            if operator_confirmed is not None:
                self._operator_confirmed = operator_confirmed
            if scene_state_clip is not None:
                self._scene_state_clip = scene_state_clip
            self._updated_at = time.monotonic()

    def read(self) -> dict:
        with self._lock:
            # Use fused read when we have per-camera data, else fall back
            if self._per_camera_behaviors:
                fused = self._fused_read()
                fused["updated_at"] = self._updated_at
                return fused
            return {
                "detected_objects": self._merged_detections(),
                "person_count": self._person_count,
                "pose_summary": self._pose_summary,
                "scene_objects": self._scene_objects,
                "scene_type": self._scene_type,
                "gaze_direction": self._gaze_direction,
                "hand_gesture": self._hand_gesture,
                "nearest_person_distance": self._nearest_person_distance,
                "ambient_brightness": self._ambient_brightness,
                "color_temperature": self._color_temperature,
                "posture": self._posture,
                "detected_action": self._detected_action,
                "top_emotion": self._top_emotion,
                "operator_confirmed": self._operator_confirmed,
                "scene_state_clip": self._scene_state_clip,
                "updated_at": self._updated_at,
            }


def _estimate_pose(keypoints: np.ndarray) -> str:
    """Estimate posture from YOLO pose keypoints.

    Keypoints layout (COCO): 0=nose, 5=left_shoulder, 6=right_shoulder,
    11=left_hip, 12=right_hip, 13=left_knee, 14=right_knee.

    Returns "seated", "standing", "leaning", or "unknown".
    """
    if keypoints is None or len(keypoints) < 15:
        return "unknown"

    # Use confidence-weighted positions — skip low-confidence points
    def _pt(idx: int) -> tuple[float, float, float]:
        if idx >= len(keypoints):
            return (0.0, 0.0, 0.0)
        return (float(keypoints[idx][0]), float(keypoints[idx][1]), float(keypoints[idx][2]))

    l_shoulder = _pt(5)
    r_shoulder = _pt(6)
    l_hip = _pt(11)
    r_hip = _pt(12)
    l_knee = _pt(13)
    r_knee = _pt(14)

    # Need at least shoulders and hips with decent confidence
    # Need at least shoulders with decent confidence
    if min(l_shoulder[2], r_shoulder[2]) < 0.3:
        return "unknown"

    shoulder_y = (l_shoulder[1] + r_shoulder[1]) / 2

    # If hips visible, use full torso analysis
    if min(l_hip[2], r_hip[2]) >= 0.1:
        hip_y = (l_hip[1] + r_hip[1]) / 2
        torso_height = hip_y - shoulder_y
        if torso_height < 10:
            return "seated"  # very short torso = close-up seated
    else:
        # Hips not visible (close-up camera) — estimate from shoulders + head
        torso_height = 200  # assume reasonable torso for lean calculation

    # If knees are visible and close to hip height → seated
    if min(l_knee[2], r_knee[2]) > 0.3:
        knee_y = (l_knee[1] + r_knee[1]) / 2
        leg_ratio = (knee_y - hip_y) / torso_height
        if leg_ratio < 0.5:
            return "seated"
        elif leg_ratio > 1.2:
            return "standing"

    # Check torso lean via shoulder-hip horizontal offset
    shoulder_x = (l_shoulder[0] + r_shoulder[0]) / 2
    hip_x = (l_hip[0] + r_hip[0]) / 2
    lean = abs(shoulder_x - hip_x) / torso_height
    if lean > 0.3:
        return "leaning"

    return "seated"  # default for desk worker


class VisionBackend:
    """PerceptionBackend providing YOLO11n detection/pose/tracking + scene + gaze + gestures.

    Provides:
      - detected_objects: str (JSON list of {label, confidence, box, track_id})
      - person_count: int (number of people detected)
      - pose_summary: str (seated/standing/leaning/unknown)
      - scene_objects: str (comma-separated unique object labels)
      - scene_type: str (Places365 scene label, e.g. "home_office")
      - gaze_direction: str (screen/hardware/away/person/unknown)
      - hand_gesture: str (open_palm/thumb_up/victory/pointing_up/none/etc.)
      - nearest_person_distance: str (close/medium/far/none)
      - ambient_brightness: float (0.0-1.0, from histogram analysis)
      - color_temperature: str (warm/neutral/cool)
      - posture: str (upright/slouching/leaning_back/leaning_forward/unknown)
      - detected_action: str (X3D-S Kinetics label, e.g. "typing")
    """

    def __init__(
        self,
        webcam_capturer: object | None = None,
        camera_roles: list[str] | None = None,
        poll_interval: float = _DEFAULT_POLL_INTERVAL,
    ) -> None:
        self._webcam_capturer = webcam_capturer
        self._camera_roles = camera_roles or [
            "operator",
            "hardware",
            "room",
            "aux",
            "room-brio",
            "aux-brio",
        ]
        self._poll_interval = poll_interval
        self._cache = _VisionCache()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()  # set = paused, clear = running
        self._vram_lock = VRAMLock()

        # Face detector for cross-camera ReID
        from agents.hapax_voice.face_detector import FaceDetector

        self._face_detector = FaceDetector(min_confidence=0.5)

        self._b_objects: Behavior[str] = Behavior("[]")
        self._b_person_count: Behavior[int] = Behavior(0)
        self._b_pose: Behavior[str] = Behavior("unknown")
        self._b_scene_objects: Behavior[str] = Behavior("")
        self._b_scene_type: Behavior[str] = Behavior("unknown")
        self._b_gaze: Behavior[str] = Behavior("unknown")
        self._b_gesture: Behavior[str] = Behavior("none")
        self._b_depth: Behavior[str] = Behavior("none")
        self._b_brightness: Behavior[float] = Behavior(0.0)
        self._b_color_temp: Behavior[str] = Behavior("unknown")
        self._b_posture: Behavior[str] = Behavior("unknown")
        self._b_action: Behavior[str] = Behavior("unknown")
        self._b_emotion: Behavior[str] = Behavior("neutral")
        self._b_operator_confirmed: Behavior[bool] = Behavior(False)
        self._b_scene_state_clip: Behavior[str] = Behavior("")
        self._b_scene_inventory: Behavior[str] = Behavior("{}")

    @property
    def name(self) -> str:
        return "vision"

    @property
    def provides(self) -> frozenset[str]:
        return frozenset(
            {
                "detected_objects",
                "person_count",
                "pose_summary",
                "scene_objects",
                "scene_type",
                "gaze_direction",
                "hand_gesture",
                "nearest_person_distance",
                "ambient_brightness",
                "color_temperature",
                "posture",
                "detected_action",
                "top_emotion",
                "operator_confirmed",
                "scene_state_clip",
                "scene_inventory",
            }
        )

    @property
    def tier(self) -> PerceptionTier:
        return PerceptionTier.SLOW

    def available(self) -> bool:
        try:
            import ultralytics  # noqa: F401

            return self._webcam_capturer is not None
        except ImportError:
            return False

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._inference_loop,
            name="vision-yolo-inference",
            daemon=True,
        )
        self._thread.start()
        log.info(
            "Vision backend started (cameras=%s, poll=%.1fs)",
            self._camera_roles,
            self._poll_interval,
        )

    def pause_for_conversation(self) -> None:
        """Pause vision inference and release GPU memory for voice models.

        Called when a voice session starts. Models move to CPU RAM for
        fast (~200-500ms) reload when conversation ends.
        """
        if self._pause_event.is_set():
            return
        self._pause_event.set()
        log.info("Vision backend paused for conversation (releasing GPU)")

    def resume_after_conversation(self) -> None:
        """Resume vision inference, reloading models to GPU."""
        if not self._pause_event.is_set():
            return
        self._pause_event.clear()
        log.info("Vision backend resumed (reloading GPU)")

    def stop(self) -> None:
        self._stop_event.set()
        self._pause_event.clear()
        if self._thread is not None:
            self._thread.join(timeout=10.0)
            self._thread = None
        log.info("Vision backend stopped")

    def contribute(self, behaviors: dict[str, Behavior]) -> None:
        """Read from cache and update behaviors. Never blocks on inference.

        Injects audio context from studio_ingestion into the cache before
        reading so the cross-modal fusion has fresh audio data.
        """
        # Inject audio context for cross-modal activity fusion
        audio_activity = str(behaviors.get("production_activity", Behavior("idle")).value)
        audio_genre = str(behaviors.get("music_genre", Behavior("unknown")).value)
        audio_energy = float(behaviors.get("audio_energy_rms", Behavior(0.0)).value or 0.0)
        self._cache.set_audio_context(
            activity=audio_activity, genre=audio_genre, energy=audio_energy
        )

        now = time.monotonic()
        cached = self._cache.read()

        self._b_objects.update(cached["detected_objects"], now)
        self._b_person_count.update(cached["person_count"], now)
        self._b_pose.update(cached["pose_summary"], now)
        self._b_scene_objects.update(cached["scene_objects"], now)
        self._b_scene_type.update(cached["scene_type"], now)
        self._b_gaze.update(cached["gaze_direction"], now)
        self._b_gesture.update(cached["hand_gesture"], now)
        self._b_depth.update(cached["nearest_person_distance"], now)
        self._b_brightness.update(cached["ambient_brightness"], now)
        self._b_color_temp.update(cached["color_temperature"], now)
        self._b_posture.update(cached["posture"], now)
        self._b_action.update(cached["detected_action"], now)
        self._b_emotion.update(cached["top_emotion"], now)
        self._b_operator_confirmed.update(cached.get("operator_confirmed", False), now)
        self._b_scene_state_clip.update(cached.get("scene_state_clip", ""), now)

        # Scene inventory snapshot
        try:
            if hasattr(self, "_inventory"):
                inv_snapshot = json.dumps(self._inventory.snapshot())
                self._b_scene_inventory.update(inv_snapshot, now)
        except Exception:
            pass  # inventory not ready yet

        behaviors["detected_objects"] = self._b_objects
        behaviors["person_count"] = self._b_person_count
        behaviors["pose_summary"] = self._b_pose
        behaviors["scene_objects"] = self._b_scene_objects
        behaviors["scene_type"] = self._b_scene_type
        behaviors["gaze_direction"] = self._b_gaze
        behaviors["hand_gesture"] = self._b_gesture
        behaviors["nearest_person_distance"] = self._b_depth
        behaviors["ambient_brightness"] = self._b_brightness
        behaviors["color_temperature"] = self._b_color_temp
        behaviors["posture"] = self._b_posture
        behaviors["detected_action"] = self._b_action
        behaviors["top_emotion"] = self._b_emotion
        behaviors["operator_confirmed"] = self._b_operator_confirmed
        behaviors["scene_state_clip"] = self._b_scene_state_clip
        behaviors["scene_inventory"] = self._b_scene_inventory

    def _run_gaze_estimation(self, frame: np.ndarray) -> str:
        """Estimate gaze direction from SCRFD 5-point face landmarks.

        Uses geometric analysis of the landmark constellation to estimate
        head yaw and pitch. More robust than PnP for 5-point landmarks.
        """
        try:
            from insightface.app import FaceAnalysis

            if not hasattr(self, "_gaze_app"):
                self._gaze_app = FaceAnalysis(
                    name="buffalo_sc",
                    providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
                    allowed_modules=["detection"],
                )
                self._gaze_app.prepare(ctx_id=0, det_size=(320, 320))
                log.info("SCRFD gaze estimator initialized")

            faces = self._gaze_app.get(frame)
            if not faces:
                return "unknown"

            face = max(faces, key=lambda f: f.det_score)
            kps = face.kps  # 5x2: right_eye, left_eye, nose, right_mouth, left_mouth
            right_eye, left_eye, nose, right_mouth, left_mouth = kps

            # Yaw: nose offset from eye midpoint, normalized by inter-eye distance
            eye_mid_x = (left_eye[0] + right_eye[0]) / 2
            eye_dist = float(np.linalg.norm(left_eye - right_eye))
            if eye_dist < 1:
                return "unknown"
            yaw_ratio = (nose[0] - eye_mid_x) / eye_dist
            yaw_deg = yaw_ratio * 90  # approximate degrees

            # Pitch: nose Y relative to expected position on eye-mouth line
            eye_mid_y = (left_eye[1] + right_eye[1]) / 2
            mouth_mid_y = (left_mouth[1] + right_mouth[1]) / 2
            face_height = mouth_mid_y - eye_mid_y
            if face_height < 1:
                return "unknown"
            nose_expected_y = eye_mid_y + face_height * 0.5
            pitch_ratio = (nose[1] - nose_expected_y) / face_height
            pitch_deg = pitch_ratio * 90

            # Map to gaze categories
            if abs(yaw_deg) < 15 and abs(pitch_deg) < 15:
                return "screen"
            elif abs(yaw_deg) > 40:
                return "away"
            elif yaw_deg > 15:
                return "hardware"
            else:
                return "person"

        except Exception as exc:
            log.debug("Gaze estimation failed: %s", exc)
        return "unknown"

    def _run_hand_gesture(self, frame: np.ndarray) -> str:
        """Run MediaPipe GestureRecognizer (CPU-only)."""
        try:
            import mediapipe as mp
            from mediapipe.tasks.python.vision import (
                GestureRecognizer,
                GestureRecognizerOptions,
            )

            if not hasattr(self, "_gesture_recognizer"):
                from pathlib import Path

                model_path = Path(__file__).resolve().parents[3] / "gesture_recognizer.task"
                if not model_path.exists():
                    log.debug("gesture_recognizer.task not found at %s", model_path)
                    self._gesture_available = False
                    return "none"
                base_options = mp.tasks.BaseOptions(model_asset_path=str(model_path))
                options = GestureRecognizerOptions(
                    base_options=base_options,
                    num_hands=1,
                )
                self._gesture_recognizer = GestureRecognizer.create_from_options(options)
                self._gesture_available = True

            if not getattr(self, "_gesture_available", False):
                return "none"

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            result = self._gesture_recognizer.recognize(mp_image)
            if result.gestures and result.gestures[0]:
                top = result.gestures[0][0]
                return top.category_name if top.category_name != "None" else "none"
        except Exception as exc:
            log.debug("Hand gesture recognition failed: %s", exc)
            self._gesture_available = False
        return "none"

    # Custom scene labels for zero-shot SigLIP 2 classification
    _SCENE_LABELS = [
        "music production studio",
        "home recording studio",
        "home office with computer",
        "empty room",
        "bedroom",
        "living room",
        "kitchen",
        "hallway",
        "workspace with equipment",
    ]

    def _run_scene_classification(self, frame: np.ndarray) -> str:
        """Run SigLIP 2 zero-shot scene classification (GPU, ~300MB).

        Uses open_clip ViT-B-16-SigLIP2-256 with custom scene labels.
        Much more accurate than Places365 for specific studio environments.
        """
        try:
            import open_clip
            import torch
            from PIL import Image

            if not hasattr(self, "_scene_model"):
                model, _, preprocess = open_clip.create_model_and_transforms(
                    "ViT-B-16-SigLIP2-256",
                    pretrained="webli",
                    device="cuda" if torch.cuda.is_available() else "cpu",
                )
                model.eval()
                self._scene_model = model
                self._scene_preprocess = preprocess
                self._scene_device = "cuda" if torch.cuda.is_available() else "cpu"

                # Pre-compute text embeddings for custom labels
                tokenizer = open_clip.get_tokenizer("ViT-B-16-SigLIP2-256")
                text_tokens = tokenizer(self._SCENE_LABELS).to(self._scene_device)
                with torch.no_grad():
                    self._scene_text_features = model.encode_text(text_tokens)
                    self._scene_text_features /= self._scene_text_features.norm(
                        dim=-1, keepdim=True
                    )
                log.info("SigLIP 2 scene model loaded (%d labels)", len(self._SCENE_LABELS))

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(rgb)
            input_tensor = self._scene_preprocess(pil_img).unsqueeze(0).to(self._scene_device)

            with torch.no_grad():
                image_features = self._scene_model.encode_image(input_tensor)
                image_features /= image_features.norm(dim=-1, keepdim=True)
                similarity = (image_features @ self._scene_text_features.T).squeeze(0)
                idx = similarity.argmax().item()

            return self._SCENE_LABELS[idx]
        except Exception as exc:
            log.debug("Scene classification failed: %s", exc)
        return "unknown"

    def _run_emotion_recognition(self, frame: np.ndarray) -> str:
        """Run HSEmotion on SCRFD face crops for emotion classification.

        Uses InsightFace SCRFD to detect and crop faces, then HSEmotion-onnx
        enet_b2_8 model for 8-class emotion classification.
        """
        try:
            from insightface.app import FaceAnalysis

            if not hasattr(self, "_emotion_face_app"):
                self._emotion_face_app = FaceAnalysis(
                    name="buffalo_sc",
                    providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
                    allowed_modules=["detection"],
                )
                self._emotion_face_app.prepare(ctx_id=0, det_size=(320, 320))

                from hsemotion_onnx.facial_emotions import HSEmotionRecognizer

                self._emotion_recognizer = HSEmotionRecognizer(model_name="enet_b2_8_best")
                log.info("HSEmotion + SCRFD emotion pipeline initialized")

            faces = self._emotion_face_app.get(frame)
            if not faces:
                return "neutral"

            face = max(faces, key=lambda f: f.det_score)
            bbox = face.bbox.astype(int)
            x1, y1, x2, y2 = bbox
            h, w = frame.shape[:2]
            pad = int((x2 - x1) * 0.15)
            x1, y1 = max(0, x1 - pad), max(0, y1 - pad)
            x2, y2 = min(w, x2 + pad), min(h, y2 + pad)
            face_crop = frame[y1:y2, x1:x2]

            if face_crop.size == 0:
                return "neutral"

            # CLAHE + white balance for robust emotion in diverse lighting
            avg = face_crop.mean(axis=(0, 1))
            overall = avg.mean()
            if overall >= 1.0:
                scale = overall / np.clip(avg, 1.0, None)
                face_crop = np.clip(face_crop.astype(np.float32) * scale, 0, 255).astype(np.uint8)
            lab = cv2.cvtColor(face_crop, cv2.COLOR_BGR2LAB)
            if not hasattr(self, "_face_clahe"):
                self._face_clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(4, 4))
            lab[:, :, 0] = self._face_clahe.apply(lab[:, :, 0])
            face_crop = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)

            emotion, _ = self._emotion_recognizer.predict_emotions(face_crop, logits=True)
            return str(emotion).lower()

        except Exception as exc:
            log.debug("Emotion recognition failed: %s", exc)
            return "neutral"

    def _estimate_lighting(self, frame: np.ndarray) -> tuple[float, str]:
        """Estimate ambient brightness and color temperature from frame histogram (CPU).

        Returns (brightness 0.0-1.0, temperature "warm"/"neutral"/"cool").
        """
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        brightness = float(hsv[:, :, 2].mean()) / 255.0

        # Color temperature from average B/R ratio
        b_mean = float(frame[:, :, 0].mean())
        r_mean = float(frame[:, :, 2].mean())
        if r_mean > 0:
            br_ratio = b_mean / r_mean
            if br_ratio > 1.2:
                color_temp = "cool"
            elif br_ratio < 0.8:
                color_temp = "warm"
            else:
                color_temp = "neutral"
        else:
            color_temp = "unknown"

        return brightness, color_temp

    def _run_posture_estimation(self, frame: np.ndarray) -> str:
        """Estimate posture via MediaPipe PoseLandmarker (CPU-only).

        Returns "upright", "slouching", "leaning_back", "leaning_forward", or "unknown".
        """
        try:
            import mediapipe as mp
            from mediapipe.tasks.python.vision import PoseLandmarker, PoseLandmarkerOptions

            if not hasattr(self, "_pose_landmarker"):
                from pathlib import Path

                model_path = Path(__file__).resolve().parents[3] / "pose_landmarker_lite.task"
                if not model_path.exists():
                    log.debug("pose_landmarker_lite.task not found at %s", model_path)
                    return "unknown"
                base_options = mp.tasks.BaseOptions(model_asset_path=str(model_path))
                options = PoseLandmarkerOptions(
                    base_options=base_options,
                    num_poses=1,
                    min_pose_detection_confidence=0.5,
                )
                self._pose_landmarker = PoseLandmarker.create_from_options(options)

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            result = self._pose_landmarker.detect(mp_image)
            if not result.pose_landmarks:
                return "unknown"

            lm = result.pose_landmarks[0]
            # Shoulders: 11 (left), 12 (right)
            # Hips: 23 (left), 24 (right)
            # Ears: 7 (left), 8 (right)
            l_shoulder = lm[11]
            r_shoulder = lm[12]
            l_hip = lm[23]
            r_hip = lm[24]

            shoulder_y = (l_shoulder.y + r_shoulder.y) / 2
            hip_y = (l_hip.y + r_hip.y) / 2
            shoulder_x = (l_shoulder.x + r_shoulder.x) / 2
            hip_x = (l_hip.x + r_hip.x) / 2

            torso_height = hip_y - shoulder_y
            if torso_height < 0.05:
                return "unknown"

            lean = (shoulder_x - hip_x) / torso_height

            if lm[7].visibility > 0.5 and lm[8].visibility > 0.5:
                ear_y = (lm[7].y + lm[8].y) / 2
                neck_length = shoulder_y - ear_y
                if neck_length < 0.02:
                    return "slouching"

            if lean > 0.15:
                return "leaning_forward"
            elif lean < -0.15:
                return "leaning_back"
            else:
                return "upright"

        except Exception as exc:
            log.debug("Posture estimation failed: %s", exc)
            return "unknown"

    @staticmethod
    def _posture_from_keypoints(kpts: np.ndarray) -> str:
        """Estimate posture from YOLO pose keypoints (COCO format).

        Uses shoulder/hip/ear geometry to determine upright/slouching/leaning.
        Returns "upright", "slouching", "leaning_forward", "leaning_back", or "unknown".
        """
        if kpts is None or len(kpts) < 15:
            return "unknown"

        def _pt(idx: int) -> tuple[float, float, float]:
            if idx >= len(kpts):
                return (0.0, 0.0, 0.0)
            return (float(kpts[idx][0]), float(kpts[idx][1]), float(kpts[idx][2]))

        l_shoulder = _pt(5)
        r_shoulder = _pt(6)
        l_hip = _pt(11)
        r_hip = _pt(12)
        l_ear = _pt(3)
        r_ear = _pt(4)

        # Need shoulders and hips with decent confidence
        if min(l_shoulder[2], r_shoulder[2], l_hip[2], r_hip[2]) < 0.3:
            return "unknown"

        shoulder_y = (l_shoulder[1] + r_shoulder[1]) / 2
        hip_y = (l_hip[1] + r_hip[1]) / 2
        shoulder_x = (l_shoulder[0] + r_shoulder[0]) / 2
        hip_x = (l_hip[0] + r_hip[0]) / 2
        torso_height = hip_y - shoulder_y

        if torso_height < 10:
            return "unknown"

        lean = (shoulder_x - hip_x) / torso_height

        # Check ear-to-shoulder distance for slouching
        if min(l_ear[2], r_ear[2]) > 0.3:
            ear_y = (l_ear[1] + r_ear[1]) / 2
            neck_length = shoulder_y - ear_y
            # Very short neck = head dropped = slouching
            if neck_length < torso_height * 0.1:
                return "slouching"

        if lean > 0.15:
            return "leaning_forward"
        elif lean < -0.15:
            return "leaning_back"
        return "upright"

    @staticmethod
    def _infer_object_state(
        objects: list[dict],
        keypoints: np.ndarray | None,
    ) -> str:
        """Infer user action from spatial relationship between pose keypoints and objects.

        Heuristic rules:
        - "typing": person + keyboard + wrist near keyboard bbox
        - "on phone": person + cell phone near face
        - "drinking": cup/bottle + hand raised above shoulder
        - "reading": book detected + person looking down

        Returns inferred action or "unknown".
        """
        if not objects:
            return "unknown"

        labels = {o["label"] for o in objects}
        person_present = "person" in labels

        if not person_present:
            return "unknown"

        def _box_center(box: list[float]) -> tuple[float, float]:
            return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)

        def _dist(p1: tuple[float, float], p2: tuple[float, float]) -> float:
            return ((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2) ** 0.5

        # Get wrist and shoulder positions from keypoints if available
        l_wrist = r_wrist = l_shoulder = r_shoulder = nose = None
        if keypoints is not None and len(keypoints) >= 11:
            if keypoints[9][2] > 0.3:  # left wrist
                l_wrist = (float(keypoints[9][0]), float(keypoints[9][1]))
            if keypoints[10][2] > 0.3:  # right wrist
                r_wrist = (float(keypoints[10][0]), float(keypoints[10][1]))
            if keypoints[5][2] > 0.3:  # left shoulder
                l_shoulder = (float(keypoints[5][0]), float(keypoints[5][1]))
            if keypoints[6][2] > 0.3:  # right shoulder
                r_shoulder = (float(keypoints[6][0]), float(keypoints[6][1]))
            if keypoints[0][2] > 0.3:  # nose
                nose = (float(keypoints[0][0]), float(keypoints[0][1]))

        # Check for typing: keyboard + wrist near keyboard
        keyboard_boxes = [o["box"] for o in objects if o["label"] == "keyboard"]
        if keyboard_boxes and (l_wrist or r_wrist):
            for kb_box in keyboard_boxes:
                kb_center = _box_center(kb_box)
                kb_width = kb_box[2] - kb_box[0]
                threshold = max(100.0, kb_width * 0.5)
                for wrist in [l_wrist, r_wrist]:
                    if wrist and _dist(wrist, kb_center) < threshold:
                        return "typing"

        # Check for phone use: cell phone near face
        phone_boxes = [o["box"] for o in objects if o["label"] == "cell phone"]
        if phone_boxes and nose:
            for pb in phone_boxes:
                phone_center = _box_center(pb)
                if _dist(nose, phone_center) < 200:
                    return "on phone"

        # Check for drinking: cup/bottle + hand raised above shoulder
        drink_boxes = [o["box"] for o in objects if o["label"] in {"cup", "bottle", "wine glass"}]
        if drink_boxes and (l_wrist or r_wrist) and (l_shoulder or r_shoulder):
            shoulder_y = min(s[1] for s in [l_shoulder, r_shoulder] if s is not None)
            for wrist in [l_wrist, r_wrist]:
                if wrist and wrist[1] < shoulder_y:
                    return "drinking"

        # Check for reading: book detected
        if "book" in labels:
            return "reading"

        return "unknown"

    def _run_action_recognition(self, frame: np.ndarray) -> str:
        """Run X3D-XS action recognition on buffered frames (GPU, ~400MB).

        Buffers 4 frames at 12fps, runs inference when buffer full.
        Uses X3D-XS (extra small) for faster inference than X3D-S.
        Returns a Kinetics-400 action label.
        """
        try:
            if not hasattr(self, "_action_buffer"):
                self._action_buffer: list[np.ndarray] = []
                self._last_action = "unknown"

            # Buffer frames (keep last 4 for X3D-XS)
            small = cv2.resize(frame, (182, 182))
            rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
            self._action_buffer.append(rgb)
            if len(self._action_buffer) > 4:
                self._action_buffer = self._action_buffer[-4:]

            # Only run inference when buffer is full
            if len(self._action_buffer) < 4:
                return self._last_action

            import torch

            if not hasattr(self, "_action_model"):
                try:
                    self._action_model = torch.hub.load(
                        "facebookresearch/pytorchvideo:main",
                        "x3d_xs",
                        pretrained=True,
                    )
                    self._action_model.eval()
                    if torch.cuda.is_available():
                        self._action_model = self._action_model.cuda()

                    # Load Kinetics-400 labels
                    from pathlib import Path

                    labels_path = Path.home() / ".cache" / "hapax-voice" / "kinetics400_labels.json"
                    if not labels_path.exists():
                        import urllib.request

                        labels_path.parent.mkdir(parents=True, exist_ok=True)
                        url = "https://dl.fbaipublicfiles.com/pyslowfast/dataset/class_names/kinetics_classnames.json"
                        urllib.request.urlretrieve(url, labels_path)
                    self._action_labels = json.loads(labels_path.read_text())

                    # Pre-compute normalization tensors for video (C, T, H, W)
                    self._action_mean = torch.tensor([0.45, 0.45, 0.45]).view(3, 1, 1, 1)
                    self._action_std = torch.tensor([0.225, 0.225, 0.225]).view(3, 1, 1, 1)
                    if torch.cuda.is_available():
                        self._action_mean = self._action_mean.cuda()
                        self._action_std = self._action_std.cuda()
                    log.info("X3D-XS action recognition model loaded")
                except Exception as exc:
                    log.warning("X3D-XS model load failed: %s", exc)
                    self._action_model = None
                    return "unknown"

            if self._action_model is None:
                return "unknown"

            # Prepare input: (1, C, T, H, W) — X3D-XS expects 4 frames at 182x182
            frames_np = np.stack(self._action_buffer, axis=0)  # (T, H, W, C)
            tensor = torch.from_numpy(frames_np).permute(3, 0, 1, 2).float() / 255.0
            tensor = tensor.unsqueeze(0)  # (1, C, T, H, W)
            if torch.cuda.is_available():
                tensor = tensor.cuda()
            tensor = (tensor - self._action_mean) / self._action_std

            with torch.no_grad():
                output = self._action_model(tensor)
                pred_idx = output.argmax(1).item()

            # Map index to label
            for label, idx in self._action_labels.items():
                if idx == pred_idx:
                    self._last_action = label.replace('"', "").strip()
                    break

            # Clear buffer to avoid re-running on same frames
            self._action_buffer.clear()
            return self._last_action

        except Exception as exc:
            log.debug("Action recognition failed: %s", exc)
            return "unknown"

    def _run_depth_estimation(
        self,
        frame: np.ndarray,
        person_boxes: list[list[float]],
    ) -> str:
        """Run Depth Anything V2 Small to estimate nearest person distance (GPU, ~800MB).

        Only runs every ~30s on operator camera. Returns "close", "medium", "far", or "none".
        """
        if not person_boxes:
            return "none"

        try:
            import torch
            from transformers import pipeline

            if not hasattr(self, "_depth_pipe"):
                self._depth_pipe = pipeline(
                    "depth-estimation",
                    model="depth-anything/Depth-Anything-V2-Small-hf",
                    device=0 if torch.cuda.is_available() else -1,
                )
                self._depth_tick = 0
                log.info("Depth Anything V2 Small loaded")

            # Only run every 10 ticks (~30s at 3s interval)
            self._depth_tick = getattr(self, "_depth_tick", 0) + 1
            if self._depth_tick % 10 != 1:
                return getattr(self, "_last_depth", "none")

            from PIL import Image

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(rgb)
            result = self._depth_pipe(pil_img)
            depth_map = np.array(result["depth"])

            # Sample depth at person box centers
            min_depth = float("inf")
            h, w = depth_map.shape[:2]
            frame_h, frame_w = frame.shape[:2]
            for box in person_boxes:
                cx = int((box[0] + box[2]) / 2 * w / frame_w)
                cy = int((box[1] + box[3]) / 2 * h / frame_h)
                cx = max(0, min(w - 1, cx))
                cy = max(0, min(h - 1, cy))
                d = float(depth_map[cy, cx])
                min_depth = min(min_depth, d)

            # Depth values are relative (higher = farther)
            # Heuristic thresholds based on typical indoor scenes
            max_val = float(depth_map.max()) if depth_map.max() > 0 else 1.0
            normalized = min_depth / max_val

            if normalized < 0.3:
                result_str = "close"
            elif normalized < 0.6:
                result_str = "medium"
            else:
                result_str = "far"

            self._last_depth = result_str
            return result_str

        except Exception as exc:
            log.debug("Depth estimation failed: %s", exc)
            return "none"

    def _inference_loop(self) -> None:
        """Background thread: round-robin cameras → YOLO inference → cache."""
        import gc

        model = None
        camera_idx = 0
        _gpu_released = False

        while not self._stop_event.is_set():
            try:
                # Pause: release GPU models and wait
                if self._pause_event.is_set():
                    if not _gpu_released and model is not None:
                        try:
                            import torch

                            model.cpu()
                            # Offload Batch 5 GPU models too
                            if hasattr(self, "_movinet"):
                                self._movinet.to_cpu()
                            if hasattr(self, "_clip_scene"):
                                self._clip_scene.to_cpu()
                            torch.cuda.empty_cache()
                            gc.collect()
                            log.info("Vision models moved to CPU (freed ~2-3GB VRAM)")
                        except Exception:
                            log.debug("Vision GPU release failed", exc_info=True)
                        _gpu_released = True
                    self._stop_event.wait(1.0)  # sleep while paused
                    continue

                # Resume: reload models to GPU
                if _gpu_released and model is not None:
                    try:
                        model.to("cuda")
                        if hasattr(self, "_movinet"):
                            self._movinet.to_cuda()
                        if hasattr(self, "_clip_scene"):
                            self._clip_scene.to_cuda()
                        log.info("Vision models reloaded to GPU")
                    except Exception:
                        log.debug("Vision GPU reload failed", exc_info=True)
                        model = None  # force fresh load
                    _gpu_released = False

                if self._webcam_capturer is None:
                    self._stop_event.wait(self._poll_interval)
                    continue

                # Round-robin camera selection
                role = self._camera_roles[camera_idx % len(self._camera_roles)]
                camera_idx += 1

                # Skip cameras that aren't configured AND don't have shm snapshots
                from pathlib import Path as _P

                _role_to_shm2 = {
                    "operator": "brio-operator",
                    "hardware": "c920-hardware",
                    "room": "c920-room",
                    "aux": "c920-aux",
                    "room-brio": "brio-room",
                    "aux-brio": "brio-aux",
                }
                _shm2 = _P(f"/dev/shm/hapax-compositor/{_role_to_shm2.get(role, role)}.jpg")
                if not self._webcam_capturer.has_camera(role) and not _shm2.exists():
                    self._stop_event.wait(0.5)
                    continue

                # Try compositor snapshot first (cameras may be locked by GStreamer)
                from pathlib import Path

                # Map short role names to compositor snapshot filenames
                _role_to_shm = {
                    "operator": "brio-operator",
                    "hardware": "c920-hardware",
                    "room": "c920-room",
                    "aux": "c920-aux",
                    "room-brio": "brio-room",
                    "aux-brio": "brio-aux",
                }
                shm_name = _role_to_shm.get(role, role)
                shm_path = Path(f"/dev/shm/hapax-compositor/{shm_name}.jpg")
                frame = None
                if shm_path.exists():
                    try:
                        data = shm_path.read_bytes()
                        if len(data) > 100:
                            arr = np.frombuffer(data, dtype=np.uint8)
                            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                    except OSError:
                        pass

                # Fallback to direct camera capture
                if frame is None:
                    self._webcam_capturer.reset_cooldown(role)
                    frame_b64 = self._webcam_capturer.capture(role)
                    if frame_b64 is not None:
                        raw = base64.b64decode(frame_b64)
                        arr = np.frombuffer(raw, dtype=np.uint8)
                        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)

                if frame is None:
                    self._stop_event.wait(self._poll_interval)
                    continue

                # Acquire VRAM lock for GPU inference
                if not self._vram_lock.acquire():
                    log.debug("VRAM lock held, skipping vision inference")
                    self._stop_event.wait(self._poll_interval)
                    continue

                try:
                    # Lazy-load YOLO-World open-vocabulary detection
                    if model is None:
                        from ultralytics import YOLO

                        model = YOLO("yolov8x-worldv2.pt")

                        # ── Vocabulary manager: learned vocab replaces hardcoded ──
                        try:
                            from agents.hapax_voice.vocab_manager import VocabularyManager

                            if not hasattr(self, "_vocab_mgr"):
                                self._vocab_mgr = VocabularyManager()
                            vocab = self._vocab_mgr.get_active_vocab()
                            model.set_classes(vocab)
                            log.info(
                                "YOLO-World v2 loaded (vocab manager: %d active labels)",
                                len(vocab),
                            )
                        except Exception as exc:
                            log.warning("Vocab manager failed, falling back to hardcoded: %s", exc)
                            # Fallback: hardcoded vocabulary
                            _BASE_CLASSES = [
                                "person",
                                "face",
                                "hand",
                                "chair",
                                "desk",
                                "table",
                                "cup",
                                "bottle",
                                "phone",
                                "book",
                            ]
                            _CAM_CLASSES = {
                                "operator": [
                                    "headphones",
                                    "glasses",
                                    "watch",
                                    "computer monitor",
                                    "laptop screen",
                                    "keyboard",
                                    "mouse",
                                ],
                                "hardware": [
                                    "synthesizer",
                                    "drum machine",
                                    "turntable",
                                    "mixer",
                                    "audio interface",
                                    "MIDI controller",
                                    "cable",
                                    "studio monitor speaker",
                                    "amplifier",
                                ],
                                "room": [
                                    "speaker",
                                    "studio monitor speaker",
                                    "microphone",
                                    "poster",
                                    "shelf",
                                    "lamp",
                                    "LED light",
                                    "computer monitor",
                                ],
                                "aux": [
                                    "keyboard",
                                    "mouse",
                                    "laptop",
                                    "speaker",
                                    "headphones",
                                    "microphone",
                                    "cable",
                                ],
                            }
                            all_classes = list(
                                set(
                                    _BASE_CLASSES
                                    + [c for extras in _CAM_CLASSES.values() for c in extras]
                                )
                            )
                            model.set_classes(all_classes)
                            log.info(
                                "YOLO-World v2 loaded (hardcoded: %d labels)",
                                len(all_classes),
                            )

                    # Adaptive resolution per camera: C920 wide shots need higher
                    # resolution to detect small objects (cables, knobs, connectors)
                    if role == "operator":
                        # BRIO 1080p close-up — objects are large, standard resolution
                        results = model.track(frame, persist=True, verbose=False, conf=0.10)
                    else:
                        # C920 720p wide shots — increase resolution for small objects
                        results = model.track(
                            frame, persist=True, verbose=False, conf=0.10, imgsz=1280
                        )

                    objects: list[dict] = []
                    person_count = 0
                    labels: set[str] = set()
                    pose_summary = "unknown"
                    posture_from_yolo = "unknown"

                    if results and results[0].boxes is not None:
                        boxes = results[0].boxes
                        for i in range(len(boxes)):
                            cls_id = int(boxes.cls[i])
                            label = model.names.get(cls_id, f"class_{cls_id}")
                            conf = float(boxes.conf[i])
                            xyxy = boxes.xyxy[i].tolist()
                            track_id = int(boxes.id[i]) if boxes.id is not None else None

                            objects.append(
                                {
                                    "label": label,
                                    "confidence": round(conf, 3),
                                    "box": [round(v, 1) for v in xyxy],
                                    "track_id": track_id,
                                }
                            )
                            labels.add(label)
                            if label == "person":
                                person_count += 1

                    # ── Feed detections to scene inventory ─────────────────
                    try:
                        if not hasattr(self, "_inventory"):
                            from agents.hapax_voice.scene_inventory import SceneInventory

                            self._inventory = SceneInventory()
                        self._inventory.ingest(objects, role, time.time())
                    except Exception as exc:
                        log.debug("Scene inventory ingest failed: %s", exc)

                    # ── Record detections for vocabulary learning ──────────
                    try:
                        if hasattr(self, "_vocab_mgr"):
                            for obj in objects:
                                self._vocab_mgr.record_detection(
                                    obj["label"], obj["confidence"], role
                                )
                    except Exception as exc:
                        log.debug("Vocab recording failed: %s", exc)

                    # Pose estimation with separate pose model (operator only)
                    pose_summary = "unknown"
                    if role == "operator" and person_count > 0:
                        try:
                            if not hasattr(self, "_pose_model") or self._pose_model is None:
                                from ultralytics import YOLO as _YOLO

                                self._pose_model = _YOLO("yolo11m-pose.pt")
                                log.info("YOLO11m pose model loaded")
                            pose_results = self._pose_model.predict(frame, verbose=False)
                            if (
                                pose_results
                                and pose_results[0].keypoints is not None
                                and len(pose_results[0].keypoints.data) > 0
                            ):
                                kpts = pose_results[0].keypoints.data[0].cpu().numpy()
                                pose_summary = _estimate_pose(kpts)
                        except Exception as exc:
                            log.debug("Pose estimation failed: %s", exc)

                    # Scene classification (GPU, runs after YOLO on same frame)
                    scene_type: str | None = None
                    scene_state_clip: str | None = None
                    try:
                        scene_type = self._run_scene_classification(frame)
                    except Exception as exc:
                        log.debug("Scene classification failed: %s", exc)

                    # CLIP scene state — only run if model already loaded (non-blocking)
                    if hasattr(self, "_clip_scene") and self._clip_scene._loaded:
                        try:
                            scene_state_clip = self._clip_scene.predict(frame)
                        except Exception as exc:
                            log.warning("CLIP scene classification failed: %s", exc)
                    elif not hasattr(self, "_clip_scene"):
                        # Start background loading so it's ready for next tick
                        import threading

                        from agents.models.clip_scene import CLIPSceneClassifier

                        self._clip_scene = CLIPSceneClassifier()

                        def _bg_load_clip():
                            self._clip_scene._load()
                            log.info("CLIP scene classifier loaded in background")

                        threading.Thread(target=_bg_load_clip, daemon=True).start()
                        log.info("CLIP scene classifier loading in background thread")

                    # Depth estimation (GPU, every ~30s on operator camera only)
                    nearest_person_distance: str | None = None
                    if role == "operator" and person_count > 0:
                        person_boxes = [o["box"] for o in objects if o["label"] == "person"]
                        try:
                            nearest_person_distance = self._run_depth_estimation(
                                frame, person_boxes
                            )
                        except Exception as exc:
                            log.debug("Depth estimation failed: %s", exc)

                finally:
                    self._vram_lock.release()

                # CPU-only classifiers (no VRAM lock needed)
                gaze_direction: str | None = None
                hand_gesture: str | None = None
                ambient_brightness: float | None = None
                color_temperature: str | None = None
                posture: str | None = None
                detected_action: str | None = None
                top_emotion: str | None = None
                operator_confirmed: bool | None = None

                # ── Cross-camera person ReID via SCRFD embeddings ──────
                if person_count > 0:
                    try:
                        face_result = self._face_detector.detect(frame, camera_role=role)
                        if face_result.detected and face_result.operator_flags:
                            operator_confirmed = any(face_result.operator_flags)
                        else:
                            operator_confirmed = None  # no face → unknown
                    except Exception as exc:
                        log.debug("ReID face check failed: %s", exc)

                if role == "operator":
                    try:
                        gaze_direction = self._run_gaze_estimation(frame)
                    except Exception:
                        log.debug("Gaze estimation failed", exc_info=True)
                    try:
                        hand_gesture = self._run_hand_gesture(frame)
                    except Exception:
                        log.debug("Hand gesture failed", exc_info=True)
                    try:
                        top_emotion = self._run_emotion_recognition(frame)
                    except Exception:
                        log.debug("Emotion recognition failed", exc_info=True)
                    try:
                        posture = (
                            posture_from_yolo
                            if posture_from_yolo != "unknown"
                            else self._run_posture_estimation(frame)
                        )
                    except Exception:
                        log.debug("Posture estimation failed", exc_info=True)
                    try:
                        ambient_brightness, color_temperature = self._estimate_lighting(frame)
                    except Exception:
                        log.debug("Lighting estimation failed", exc_info=True)

                    # Action recognition: MoViNet-A2 (streaming) with X3D-XS fallback
                    _action_lock = self._vram_lock.acquire()
                    if not _action_lock:
                        log.info("VRAM lock held, skipping action recognition on %s", role)
                    if _action_lock:
                        try:
                            if not hasattr(self, "_movinet"):
                                import threading as _thr

                                from agents.models.movinet import MoViNetA2

                                self._movinet = MoViNetA2()

                                def _bg_load_movinet():
                                    self._movinet._load()
                                    log.info("MoViNet-A2 loaded in background")

                                _thr.Thread(target=_bg_load_movinet, daemon=True).start()
                                log.info("MoViNet-A2 loading in background thread")
                            if self._movinet._loaded:
                                action = self._movinet.predict(frame)
                                if action and action != "unknown":
                                    detected_action = action
                            if detected_action in (None, "unknown"):
                                detected_action = self._run_action_recognition(frame)
                        finally:
                            self._vram_lock.release()

                    # Object state heuristics as fallback/supplement
                    if detected_action in (None, "unknown"):
                        # Get keypoints from YOLO results if available
                        yolo_kpts = None
                        if (
                            results
                            and results[0].keypoints is not None
                            and len(results[0].keypoints.data) > 0
                        ):
                            yolo_kpts = results[0].keypoints.data[0].cpu().numpy()
                        heuristic = self._infer_object_state(objects, yolo_kpts)
                        if heuristic != "unknown":
                            detected_action = heuristic

                self._cache._current_role = role
                self._cache.update(
                    detected_objects=json.dumps(objects),
                    person_count=person_count,
                    pose_summary=pose_summary,
                    scene_objects=", ".join(sorted(labels)),
                    scene_type=scene_type,
                    gaze_direction=gaze_direction,
                    hand_gesture=hand_gesture,
                    nearest_person_distance=nearest_person_distance,
                    ambient_brightness=ambient_brightness,
                    color_temperature=color_temperature,
                    posture=posture,
                    detected_action=detected_action,
                    top_emotion=top_emotion,
                    operator_confirmed=operator_confirmed,
                    scene_state_clip=scene_state_clip,
                )

                # Route per-person enrichments to SceneInventory entities
                # Any Brio-class camera can enrich persons (multi-perspective)
                from shared.cameras import can_enrich_persons as _can_enrich

                if _can_enrich(role) and hasattr(self, "_inventory"):
                    try:
                        # Find the most-confident person detection on this camera
                        person_dets = [o for o in objects if o.get("label") == "person"]
                        if person_dets:
                            best = max(person_dets, key=lambda o: o.get("confidence", 0))
                            track_id = best.get("track_id")
                            if track_id is not None:
                                eid = self._inventory.find_by_track_id(role, track_id)
                                if eid:
                                    self._inventory.enrich_entity(
                                        eid,
                                        gaze_direction=gaze_direction,
                                        emotion=top_emotion,
                                        posture=posture,
                                        gesture=hand_gesture,
                                        action=detected_action,
                                        depth=nearest_person_distance,
                                    )
                    except Exception:
                        log.debug("Per-entity enrichment routing failed", exc_info=True)

            except Exception:
                log.exception("Vision inference step failed")

            self._stop_event.wait(self._poll_interval)

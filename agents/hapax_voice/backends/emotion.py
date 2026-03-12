"""Emotion perception backend — valence, arousal, and dominant emotion.

Captures frames from a V4L2 camera device, runs MediaPipe Face Mesh for
face detection + landmark extraction, then classifies emotion via
hsemotion-onnx (EfficientNet-B0, ONNX Runtime).

Supports source parameterization: ``EmotionBackend("face_cam", target="/dev/video0")``
writes to ``emotion_valence:face_cam`` instead of ``emotion_valence``.

When no ``target`` is provided, operates as a stub (``available() → False``).
"""

from __future__ import annotations

import logging
import os
import threading
import time

import numpy as np  # noqa: TC002 — used at runtime

try:
    import cv2
except ImportError:
    cv2 = None  # type: ignore[assignment]

from agents.hapax_voice.perception import PerceptionTier
from agents.hapax_voice.primitives import Behavior
from agents.hapax_voice.source_naming import qualify, validate_source_id

log = logging.getLogger(__name__)

_BASE_NAMES = ("emotion_valence", "emotion_arousal", "emotion_dominant")

# 8 discrete emotion categories from hsemotion
EMOTION_CATEGORIES = (
    "angry",
    "contempt",
    "disgust",
    "fear",
    "happy",
    "neutral",
    "sad",
    "surprise",
)

# Inference rate control
INFERENCE_INTERVAL_S = 0.333  # ~3 fps


# ---------------------------------------------------------------------------
# Camera discovery
# ---------------------------------------------------------------------------


def discover_camera(target: str) -> str | None:
    """Find a V4L2 camera device by path, by-id symlink, or substring match.

    Args:
        target: A device path (``"/dev/video0"``), a by-id path
                (``"/dev/v4l/by-id/usb-Logitech..."``), or a substring
                to match against by-id symlink names (``"Logitech"``).

    Returns:
        The resolved device path, or None if not found / not openable.
    """
    # Direct device path
    if target.startswith("/dev/"):
        try:
            cap = cv2.VideoCapture(target)
            opened = cap.isOpened()
            cap.release()
            return target if opened else None
        except Exception:
            return None

    # Search /dev/v4l/by-id/ for substring match
    by_id_dir = "/dev/v4l/by-id"
    if os.path.isdir(by_id_dir):
        try:
            for entry in os.listdir(by_id_dir):
                if target in entry:
                    link_path = os.path.join(by_id_dir, entry)
                    resolved = os.path.realpath(link_path)
                    try:
                        cap = cv2.VideoCapture(resolved)
                        opened = cap.isOpened()
                        cap.release()
                        if opened:
                            return resolved
                    except Exception:
                        continue
        except OSError:
            pass

    return None


# ---------------------------------------------------------------------------
# Frame reader — background capture thread
# ---------------------------------------------------------------------------


class _FrameReader:
    """Background thread capturing frames from a V4L2 device via OpenCV.

    Holds the latest frame in a lock-protected attribute. The capture thread
    runs at camera native rate to drain the V4L2 buffer; consumers read the
    latest frame via ``get_frame()``.
    """

    def __init__(self, device_path: str) -> None:
        self._device_path = device_path
        self._lock = threading.Lock()
        self._frame: np.ndarray | None = None
        self._cap = None
        self._thread: threading.Thread | None = None
        self._running = False

    def start(self) -> None:
        """Launch capture thread."""
        self._cap = cv2.VideoCapture(self._device_path)
        self._running = True
        self._thread = threading.Thread(
            target=self._capture_loop,
            name=f"frame-reader-{self._device_path}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Release VideoCapture, join thread."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def get_frame(self) -> np.ndarray | None:
        """Return the latest captured frame (thread-safe), or None."""
        with self._lock:
            return self._frame

    def _capture_loop(self) -> None:
        """Continuously grab frames from the camera."""
        try:
            while self._running and self._cap is not None:
                ret, frame = self._cap.read()
                if not ret:
                    if self._running:
                        log.warning("Camera read failed: %s", self._device_path)
                    break
                with self._lock:
                    self._frame = frame
        except Exception:
            if self._running:
                log.exception("Frame reader error: %s", self._device_path)


# ---------------------------------------------------------------------------
# Emotion inference — MediaPipe Face Mesh + hsemotion-onnx
# ---------------------------------------------------------------------------


class _EmotionInference:
    """Runs MediaPipe Face Mesh + hsemotion-onnx in an inference thread.

    Thread-safe: published values are read by ``contribute()`` on the main
    thread. Python's GIL makes float/str assignment atomic for CPython scalar
    types.
    """

    def __init__(self, frame_reader: _FrameReader) -> None:
        self._frame_reader = frame_reader
        self._thread: threading.Thread | None = None
        self._running = False

        # Thread-safe published values
        self.valence: float = 0.0  # 0.0-1.0 (rescaled from [-1,1])
        self.arousal: float = 0.0  # 0.0-1.0 (rescaled from [-1,1])
        self.dominant: str = "neutral"
        self.last_update: float = 0.0

        # Lazy-initialized models
        self._face_mesh = None
        self._emotion_model = None

    def start(self) -> None:
        """Launch inference thread."""
        self._running = True
        self._thread = threading.Thread(
            target=self._inference_loop,
            name="emotion-inference",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop inference thread."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        if self._face_mesh is not None:
            self._face_mesh.close()
            self._face_mesh = None

    def _ensure_models(self) -> None:
        """Lazy-initialize MediaPipe Face Mesh and hsemotion model."""
        if self._face_mesh is None:
            import mediapipe as mp

            self._face_mesh = mp.solutions.face_mesh.FaceMesh(
                static_image_mode=False,
                max_num_faces=1,
                refine_landmarks=False,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            )
        if self._emotion_model is None:
            from hsemotion_onnx.facial_emotions import HSEmotionRecognizer

            self._emotion_model = HSEmotionRecognizer(model_name="enet_b0_8_va_mtl")

    def _inference_loop(self) -> None:
        """Process frames at ~3 fps."""
        try:
            self._ensure_models()
        except Exception:
            log.exception("Failed to initialize emotion models")
            return

        while self._running:
            frame = self._frame_reader.get_frame()
            if frame is not None:
                try:
                    self._process_frame(frame)
                except Exception:
                    log.exception("Emotion inference error")
            time.sleep(INFERENCE_INTERVAL_S)

    def _process_frame(self, frame: np.ndarray) -> None:
        """Run face detection + emotion classification on a single BGR frame.

        This is the testable core: takes a numpy BGR frame, runs face mesh,
        crops the face region, runs the emotion model.
        """
        # MediaPipe expects RGB
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self._face_mesh.process(rgb)

        if not results.multi_face_landmarks:
            # No face detected — hold last values, stop advancing watermark
            return

        landmarks = results.multi_face_landmarks[0]
        h, w = frame.shape[:2]

        # Extract face bounding box from landmarks
        xs = [lm.x * w for lm in landmarks.landmark]
        ys = [lm.y * h for lm in landmarks.landmark]
        x_min, x_max = int(max(0, min(xs))), int(min(w, max(xs)))
        y_min, y_max = int(max(0, min(ys))), int(min(h, max(ys)))

        if x_max <= x_min or y_max <= y_min:
            return

        face_crop = frame[y_min:y_max, x_min:x_max]

        # hsemotion expects BGR face crop, returns (emotion_str, scores_dict)
        emotion, scores = self._emotion_model.predict_emotions(face_crop, logits=True)
        # scores is a dict or array — extract valence/arousal
        # The model returns valence and arousal as separate outputs
        valence_raw = float(scores.get("valence", 0.0)) if isinstance(scores, dict) else 0.0
        arousal_raw = float(scores.get("arousal", 0.0)) if isinstance(scores, dict) else 0.0

        # If the model returns arrays, handle that case
        if hasattr(self._emotion_model, "predict_multi_emotions"):
            # Use the multi-output API if available
            try:
                result = self._emotion_model.predict_multi_emotions(face_crop)
                if isinstance(result, dict):
                    valence_raw = float(result.get("valence", valence_raw))
                    arousal_raw = float(result.get("arousal", arousal_raw))
            except Exception:
                pass

        # Rescale from [-1, 1] to [0, 1]
        self.valence = max(0.0, min(1.0, (valence_raw + 1.0) / 2.0))
        self.arousal = max(0.0, min(1.0, (arousal_raw + 1.0) / 2.0))
        self.dominant = str(emotion) if emotion in EMOTION_CATEGORIES else "neutral"
        self.last_update = time.monotonic()


# ---------------------------------------------------------------------------
# EmotionBackend
# ---------------------------------------------------------------------------


class EmotionBackend:
    """PerceptionBackend for emotion analysis via face cam.

    Provides:
      - emotion_valence: float (0.0-1.0, rescaled from model's [-1,1])
      - emotion_arousal: float (0.0-1.0, rescaled from model's [-1,1])
      - emotion_dominant: str (one of 8 categories)

    When ``source_id`` is provided, all behavior names are source-qualified.
    When ``target`` is provided, captures from the specified V4L2 device.
    Without ``target``, operates as a stub (``available() → False``).
    """

    def __init__(self, source_id: str | None = None, target: str | None = None) -> None:
        if source_id is not None:
            validate_source_id(source_id)
        self._source_id = source_id
        self._target = target
        self._device_path: str | None = None
        self._frame_reader: _FrameReader | None = None
        self._inference: _EmotionInference | None = None

        # Internal Behaviors for contribute()
        self._b_valence: Behavior[float] = Behavior(0.0)
        self._b_arousal: Behavior[float] = Behavior(0.0)
        self._b_dominant: Behavior[str] = Behavior("neutral")

    @property
    def name(self) -> str:
        if self._source_id:
            return f"emotion:{self._source_id}"
        return "emotion"

    @property
    def provides(self) -> frozenset[str]:
        if self._source_id:
            return frozenset(qualify(b, self._source_id) for b in _BASE_NAMES)
        return frozenset(_BASE_NAMES)

    @property
    def tier(self) -> PerceptionTier:
        return PerceptionTier.SLOW

    def available(self) -> bool:
        """Check if the camera device exists and models are importable."""
        if self._target is None:
            return False
        device_path = discover_camera(self._target)
        if device_path is None:
            return False
        self._device_path = device_path

        # Check MediaPipe importable
        try:
            import mediapipe  # noqa: F401
        except ImportError:
            return False

        # Check hsemotion-onnx importable
        try:
            import hsemotion_onnx  # noqa: F401
        except ImportError:
            return False

        return True

    def contribute(self, behaviors: dict[str, Behavior]) -> None:
        """Read latest values from the inference thread and write to Behaviors."""
        if self._inference is None:
            return
        now = self._inference.last_update
        if now <= 0:
            return  # no data yet

        self._b_valence.update(self._inference.valence, now)
        self._b_arousal.update(self._inference.arousal, now)
        self._b_dominant.update(self._inference.dominant, now)

        if self._source_id:
            behaviors[qualify("emotion_valence", self._source_id)] = self._b_valence
            behaviors[qualify("emotion_arousal", self._source_id)] = self._b_arousal
            behaviors[qualify("emotion_dominant", self._source_id)] = self._b_dominant
        else:
            behaviors["emotion_valence"] = self._b_valence
            behaviors["emotion_arousal"] = self._b_arousal
            behaviors["emotion_dominant"] = self._b_dominant

    def start(self) -> None:
        if self._device_path is None:
            log.warning("Emotion backend %s: no device path, cannot start", self.name)
            return
        self._frame_reader = _FrameReader(self._device_path)
        self._frame_reader.start()
        self._inference = _EmotionInference(self._frame_reader)
        self._inference.start()
        log.info("Emotion backend started: %s (device %s)", self.name, self._device_path)

    def stop(self) -> None:
        if self._inference is not None:
            self._inference.stop()
            self._inference = None
        if self._frame_reader is not None:
            self._frame_reader.stop()
            self._frame_reader = None
        log.info("Emotion backend stopped: %s", self.name)

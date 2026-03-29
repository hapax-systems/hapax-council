"""ir_inference.py — YOLOv8n TFLite + face landmark inference for Pi NoIR."""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger(__name__)

MODEL_PATH = Path(__file__).parent / "yolov8n_full_integer_quant.tflite"
PERSON_CLASS_ID = 0
CONFIDENCE_THRESHOLD = 0.4
INPUT_SIZE = 320


class YoloDetector:
    """YOLOv8n TFLite person detector."""

    def __init__(self, model_path: Path | None = None) -> None:
        try:
            import tflite_runtime.interpreter as tflite
        except ImportError:
            from ai_edge_litert import interpreter as tflite  # Python 3.13+

        path = str(model_path or MODEL_PATH)
        self._interpreter = tflite.Interpreter(model_path=path, num_threads=4)
        self._interpreter.allocate_tensors()
        self._input_details = self._interpreter.get_input_details()
        self._output_details = self._interpreter.get_output_details()
        log.info("YOLO detector loaded from %s", path)

    def detect_persons(self, grey_frame: np.ndarray) -> list[dict]:
        """Run person detection on a greyscale frame.

        Returns list of {confidence, bbox: [x1, y1, x2, y2]} dicts.
        """
        h, w = grey_frame.shape[:2]
        resized = cv2.resize(grey_frame, (INPUT_SIZE, INPUT_SIZE))
        rgb = cv2.cvtColor(resized, cv2.COLOR_GRAY2RGB)
        input_data = np.expand_dims(rgb, axis=0)

        input_detail = self._input_details[0]
        if input_detail["dtype"] == np.int8:
            scale, zero_point = input_detail["quantization"]
            input_data = (input_data.astype(np.float32) / scale + zero_point).astype(np.int8)
        elif input_detail["dtype"] == np.uint8:
            pass
        else:
            input_data = input_data.astype(np.float32) / 255.0

        self._interpreter.set_tensor(input_detail["index"], input_data)
        self._interpreter.invoke()

        output = self._interpreter.get_tensor(self._output_details[0]["index"])
        out_detail = self._output_details[0]
        if out_detail["dtype"] in (np.int8, np.uint8):
            scale, zero_point = out_detail["quantization"]
            output = (output.astype(np.float32) - zero_point) * scale

        return self._parse_yolo_output(output, h, w)

    def _parse_yolo_output(self, output: np.ndarray, orig_h: int, orig_w: int) -> list[dict]:
        """Parse YOLOv8 TFLite output into person detections."""
        if output.ndim == 3:
            output = output[0]
        if output.shape[0] < output.shape[1]:
            output = output.T

        persons = []
        for detection in output:
            cx, cy, dw, dh = detection[:4]
            class_scores = detection[4:]
            class_id = int(np.argmax(class_scores))
            confidence = float(class_scores[class_id])

            if class_id != PERSON_CLASS_ID or confidence < CONFIDENCE_THRESHOLD:
                continue

            scale_x = orig_w / INPUT_SIZE
            scale_y = orig_h / INPUT_SIZE
            x1 = int((cx - dw / 2) * scale_x)
            y1 = int((cy - dh / 2) * scale_y)
            x2 = int((cx + dw / 2) * scale_x)
            y2 = int((cy + dh / 2) * scale_y)

            persons.append(
                {
                    "confidence": round(confidence, 3),
                    "bbox": [max(0, x1), max(0, y1), min(orig_w, x2), min(orig_h, y2)],
                }
            )

        persons.sort(key=lambda p: p["confidence"], reverse=True)
        kept = []
        for p in persons:
            if not any(_iou(p["bbox"], k["bbox"]) > 0.5 for k in kept):
                kept.append(p)
        return kept


def _iou(a: list[int], b: list[int]) -> float:
    """Compute intersection-over-union of two bboxes."""
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


class FaceLandmarkDetector:
    """Standalone TFLite face landmark detector (468 points).

    Uses face-detection-tflite (fdlite) for Python 3.13 compatibility.
    """

    def __init__(self) -> None:
        try:
            from fdlite import FaceDetection, FaceLandmark

            self._detector = FaceDetection(model_type="back")
            self._landmarker = FaceLandmark()
            self._available = True
            log.info("Face landmark detector loaded (fdlite)")
        except ImportError:
            self._available = False
            log.warning("face-detection-tflite not installed, face landmarks disabled")

    @property
    def available(self) -> bool:
        return self._available

    def detect(self, grey_frame: np.ndarray, person_bbox: list[int]) -> dict | None:
        """Detect face landmarks within a person bounding box.

        Returns dict with head_pose, gaze_zone, posture, ear_left, ear_right
        or None if no face found.
        """
        if not self._available:
            return None

        x1, y1, x2, y2 = person_bbox
        h, w = grey_frame.shape[:2]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        if x2 - x1 < 20 or y2 - y1 < 20:
            return None

        crop = grey_frame[y1:y2, x1:x2]
        rgb_crop = cv2.cvtColor(crop, cv2.COLOR_GRAY2RGB)

        try:
            from fdlite import face_detection_to_roi

            detections = self._detector(rgb_crop)
            if not detections:
                return None

            roi = face_detection_to_roi(detections[0], rgb_crop.shape[:2])
            landmarks = self._landmarker(rgb_crop, roi)
            if not landmarks:
                return None

            return self._compute_features(landmarks, crop.shape[1], crop.shape[0])
        except Exception:
            log.debug("Face landmark detection failed", exc_info=True)
            return None

    def _compute_features(self, landmarks: list, img_w: int, img_h: int) -> dict:
        """Compute head pose, gaze zone, and EAR from 468 landmarks."""
        nose_tip = landmarks[1]
        nose_x = nose_tip.x * img_w
        nose_y = nose_tip.y * img_h
        center_x = img_w / 2
        center_y = img_h / 2

        yaw = (nose_x - center_x) / center_x * 45
        pitch = (nose_y - center_y) / center_y * 35

        if abs(yaw) < 15 and abs(pitch) < 15:
            gaze_zone = "at-screen"
        elif yaw < -25:
            gaze_zone = "at-synths"
        elif yaw > 25:
            gaze_zone = "at-door"
        elif pitch > 20:
            gaze_zone = "down"
        else:
            gaze_zone = "away"

        chin = landmarks[152]
        forehead = landmarks[10]
        face_height = abs(chin.y - forehead.y)
        if face_height > 0.6:
            posture = "upright"
        elif face_height > 0.4:
            posture = "slouching"
        else:
            posture = "leaning"

        ear_left = self._compute_ear(landmarks, [362, 385, 387, 263, 373, 380])
        ear_right = self._compute_ear(landmarks, [33, 160, 158, 133, 153, 144])

        return {
            "head_pose": {"yaw": round(yaw, 1), "pitch": round(pitch, 1), "roll": 0.0},
            "gaze_zone": gaze_zone,
            "posture": posture,
            "ear_left": round(ear_left, 3),
            "ear_right": round(ear_right, 3),
        }

    @staticmethod
    def _compute_ear(landmarks: list, indices: list[int]) -> float:
        """Compute Eye Aspect Ratio from 6 landmark points."""
        try:
            pts = [(landmarks[i].x, landmarks[i].y) for i in indices]
            v1 = ((pts[1][0] - pts[5][0]) ** 2 + (pts[1][1] - pts[5][1]) ** 2) ** 0.5
            v2 = ((pts[2][0] - pts[4][0]) ** 2 + (pts[2][1] - pts[4][1]) ** 2) ** 0.5
            h = ((pts[0][0] - pts[3][0]) ** 2 + (pts[0][1] - pts[3][1]) ** 2) ** 0.5
            return (v1 + v2) / (2.0 * h) if h > 0 else 0.0
        except (IndexError, ZeroDivisionError):
            return 0.0

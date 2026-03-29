"""Classify effect — professional detection visualization via supervision library.

Renders bounding box corner brackets, smoothed tracking, halo glow on persons,
and trace trails for moving objects directly onto the video frame.

The client-side canvas overlay adds toggleable text labels, emotion badges,
and pose icons on top.

This effect reads detected_objects from the perception state and annotates
the compositor snapshot.
"""

from __future__ import annotations

import logging

import cv2
import numpy as np

try:
    import supervision as sv

    _HAS_SV = True
except ImportError:
    _HAS_SV = False

from agents.studio_fx.base import BaseEffect
from agents.studio_fx.perception import PerceptionSnapshot

log = logging.getLogger(__name__)

# YOLO class colors — muted palette for professional look
_CLASS_COLORS = {
    "person": (100, 220, 100),  # green
    "keyboard": (220, 180, 80),  # teal
    "chair": (80, 140, 200),  # warm blue
    "book": (200, 120, 200),  # mauve
    "monitor": (120, 200, 220),  # light cyan
    "laptop": (100, 180, 220),  # blue
    "mouse": (180, 180, 100),  # olive
    "cell phone": (220, 140, 100),  # orange-blue
    "cup": (140, 200, 140),  # light green
    "bottle": (200, 160, 120),  # tan
}
_DEFAULT_COLOR = (180, 180, 180)  # grey for unknown classes


class ClassifyEffect(BaseEffect):
    name = "classify"

    def __init__(self, width: int, height: int) -> None:
        super().__init__(width, height)
        self._smoother: object | None = None
        self._box_annotator: object | None = None
        self._label_annotator: object | None = None
        self._halo_annotator: object | None = None
        self._trace_annotator: object | None = None
        self._tracker: dict[int, list[tuple[float, float]]] = {}
        self._init_annotators()

    def _init_annotators(self) -> None:
        if not _HAS_SV:
            return
        self._box_annotator = sv.BoxCornerAnnotator(
            thickness=2,
            corner_length=15,
            color_lookup=sv.ColorLookup.TRACK,
        )
        self._label_annotator = sv.LabelAnnotator(
            text_scale=0.4,
            text_thickness=1,
            text_padding=4,
            color_lookup=sv.ColorLookup.TRACK,
        )
        self._halo_annotator = sv.HaloAnnotator(
            opacity=0.25,
            kernel_size=40,
            color_lookup=sv.ColorLookup.TRACK,
        )
        self._trace_annotator = sv.TraceAnnotator(
            thickness=1,
            trace_length=30,
            color_lookup=sv.ColorLookup.TRACK,
        )
        self._smoother = sv.DetectionsSmoother(length=5)

    def resize(self, width: int, height: int) -> None:
        super().resize(width, height)

    def reset(self) -> None:
        if _HAS_SV:
            self._smoother = sv.DetectionsSmoother(length=5)

    def process(self, frame: np.ndarray, p: PerceptionSnapshot, t: float) -> np.ndarray:
        if not _HAS_SV:
            return frame

        h, w = frame.shape[:2]
        out = frame.copy()

        # Parse detected objects from perception state
        detections = self._parse_detections(p, w, h)
        if detections is None or len(detections) == 0:
            return out

        # Smooth detections for jitter-free tracking
        if self._smoother is not None:
            detections = self._smoother.update_with_detections(detections)

        # Build labels
        labels = []
        for i in range(len(detections)):
            class_name = (
                detections.data.get("class_name", [""])[i]
                if "class_name" in detections.data
                else ""
            )
            conf = detections.confidence[i] if detections.confidence is not None else 0
            labels.append(f"{class_name} {conf:.0%}")

        # Annotate: halo on persons first (background glow)
        if self._halo_annotator is not None:
            person_mask = np.array(
                [
                    detections.data.get("class_name", [""])[i] == "person"
                    for i in range(len(detections))
                ]
            )
            if person_mask.any():
                person_dets = detections[person_mask]
                out = self._halo_annotator.annotate(out, person_dets)

        # Corner brackets
        if self._box_annotator is not None:
            out = self._box_annotator.annotate(out, detections)

        # Trace trails for tracked objects
        if self._trace_annotator is not None and detections.tracker_id is not None:
            out = self._trace_annotator.annotate(out, detections)

        # Labels
        if self._label_annotator is not None:
            out = self._label_annotator.annotate(out, detections, labels=labels)

        # Person enrichments: draw pose/emotion/gaze as small text near person boxes
        self._draw_person_enrichments(out, detections, p)

        return out

    def _parse_detections(
        self, p: PerceptionSnapshot, frame_w: int, frame_h: int
    ) -> sv.Detections | None:
        """Parse detected_objects JSON string into supervision Detections."""
        try:
            # Read raw detected_objects — it's a JSON string in perception state
            import json as _json
            from pathlib import Path

            state_path = Path.home() / ".cache" / "hapax-daimonion" / "perception-state.json"
            if not state_path.exists():
                return None
            state = _json.loads(state_path.read_text())
            raw = state.get("detected_objects", "[]")
            if isinstance(raw, str):
                objects = _json.loads(raw)
            else:
                objects = raw

            if not objects:
                return None

            xyxy = []
            confidences = []
            tracker_ids = []
            class_names = []

            for obj in objects:
                box = obj.get("box", [0, 0, 0, 0])
                if len(box) != 4:
                    continue
                xyxy.append(box)
                confidences.append(obj.get("confidence", 0.5))
                tid = obj.get("track_id")
                tracker_ids.append(tid if tid is not None else -1)
                class_names.append(obj.get("label", "unknown"))

            if not xyxy:
                return None

            dets = sv.Detections(
                xyxy=np.array(xyxy, dtype=np.float32),
                confidence=np.array(confidences, dtype=np.float32),
                tracker_id=np.array(tracker_ids, dtype=int),
            )
            dets.data = {"class_name": class_names}
            return dets

        except Exception:
            log.debug("Failed to parse detections", exc_info=True)
            return None

    def _draw_person_enrichments(
        self, frame: np.ndarray, detections: sv.Detections, p: PerceptionSnapshot
    ) -> None:
        """Draw pose/emotion/gaze as small badges near person bounding boxes."""
        if "class_name" not in detections.data:
            return

        for i in range(len(detections)):
            if detections.data["class_name"][i] != "person":
                continue

            x1, y1, x2, y2 = detections.xyxy[i].astype(int)

            # Collect enrichment badges
            badges = []
            if p.top_emotion and p.top_emotion != "neutral":
                badges.append(("E", p.top_emotion, (80, 80, 255)))  # red for emotion
            if p.posture and p.posture != "unknown":
                color = (80, 220, 80) if p.posture == "upright" else (80, 200, 255)
                badges.append(("P", p.posture, color))
            if p.gaze_direction and p.gaze_direction != "unknown":
                badges.append(("G", p.gaze_direction, (255, 200, 80)))

            # Draw badges inside the bottom of the person box
            badge_y = max(y1 + 15, y2 - 18 * len(badges) - 5)
            for j, (prefix, text, color) in enumerate(badges):
                by = badge_y + j * 18
                label = f"{prefix}: {text}"
                # Background pill
                (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.35, 1)
                cv2.rectangle(frame, (x1 + 2, by - th - 2), (x1 + tw + 8, by + 3), (0, 0, 0), -1)
                cv2.putText(
                    frame,
                    label,
                    (x1 + 5, by),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.35,
                    color,
                    1,
                    cv2.LINE_AA,
                )

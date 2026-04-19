"""Face bbox source abstraction + detection cadence / carry-forward (task #129).

Splits "where are the faces?" from "paint over them" so the obscure stage
(`face_obscure.py`) stays a pure pixel operation while this module owns the
detection cadence, SCRFD plumbing, and Kalman-style persistence between
detections.

Design contract (Stage 2):

* Detection runs at ~5 Hz, not every frame. At 30 fps that is every 6th frame;
  at 24 fps every 5th. We express the cadence in wall-clock milliseconds
  (``detect_interval_ms=200``) so capture pipelines running at different rates
  share the same privacy guarantee.
* Between detections, bboxes are carried forward with simple linear velocity
  extrapolation — a lightweight Kalman-style predictor that preserves the
  mask over the face during head motion without re-running SCRFD.
* Carry-forward is dropped if the last real detection is older than
  ``max_staleness_ms`` (default 500 ms). Past that point we return no bboxes,
  which under ``ALWAYS_OBSCURE`` policy degrades to pass-through — callers
  that require fail-closed must enforce it one layer up (e.g. the integration
  helper in ``face_obscure_integration.py``).

The :class:`FaceBboxSource` protocol keeps the concrete SCRFD dependency (via
``agents/hapax_daimonion/face_detector.py``) optional for tests.

Spec: ``docs/superpowers/specs/2026-04-18-facial-obscuring-hard-req-design.md``
§3.4 (cadence) and §3.5 (carry-forward).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from agents.studio_compositor.face_obscure import BBox

if TYPE_CHECKING:
    import numpy as np
else:
    import numpy as np  # noqa: TC002 — numpy is load-bearing at runtime

log = logging.getLogger(__name__)


# 5 Hz detection at 30 fps capture (every ~6th frame). Expressed as ms so it
# is cadence-independent; see module docstring.
DEFAULT_DETECT_INTERVAL_MS: float = 200.0

# Drop carry-forward after this many ms since the last real detection.
DEFAULT_MAX_STALENESS_MS: float = 500.0


@runtime_checkable
class FaceBboxSource(Protocol):
    """Anything that can turn a frame into a list of face bboxes.

    The protocol is intentionally narrow so tests can substitute a trivial
    callable object and production can wrap SCRFD / YOLO11n / future detectors
    without inheritance. Implementations must be idempotent — calling
    ``detect`` twice on the same frame must return equivalent bboxes.
    """

    def detect(self, frame: np.ndarray) -> list[BBox]:
        """Return axis-aligned face bboxes for ``frame``.

        Returns an empty list when no face is present. Never raises for empty
        or malformed frames — log and return ``[]`` instead, so upstream
        pipelines continue running.
        """
        ...


class ScrfdFaceBboxSource:
    """Wraps ``agents/hapax_daimonion/face_detector.FaceDetector`` as a source.

    The daimonion's detector is already used for presence / operator ReID, so
    reusing it keeps the SCRFD model resident in a single process slot. We
    import lazily inside ``__init__`` so test environments without InsightFace
    / ONNX Runtime can still import this module.

    ``camera_role`` is passed through to the detector so operator auto-enroll
    only fires for the canonical operator cam (BRIO), matching the behavior
    in ``face_detector.py``.
    """

    def __init__(
        self,
        *,
        camera_role: str = "unknown",
        min_confidence: float = 0.5,
    ) -> None:
        # Lazy import — avoids pulling InsightFace into every unit test run.
        from agents.hapax_daimonion.face_detector import FaceDetector

        self._detector = FaceDetector(min_confidence=min_confidence)
        self._camera_role = camera_role

    def detect(self, frame: np.ndarray) -> list[BBox]:
        try:
            result = self._detector.detect(frame, camera_role=self._camera_role)
        except Exception as exc:  # noqa: BLE001 — detector must not crash the pipeline
            log.debug("SCRFD detect() raised: %s", exc)
            return []
        if not result.detected:
            return []
        # ``FaceResult.boxes`` is list[tuple[int, ...]] of (x1, y1, x2, y2).
        return [
            BBox.from_xyxy((float(b[0]), float(b[1]), float(b[2]), float(b[3])))
            for b in result.boxes
        ]


@dataclass(slots=True)
class _CarriedBBox:
    """One tracked bbox with per-axis velocity estimated in pixels / ms."""

    bbox: BBox
    vx: float = 0.0  # dx per ms for x1 (and equivalently x2)
    vy: float = 0.0  # dy per ms for y1 (and equivalently y2)
    last_detection_ts_ms: float = 0.0

    def predict(self, now_ms: float) -> BBox:
        """Linear extrapolation of the bbox to ``now_ms``."""
        dt = max(0.0, now_ms - self.last_detection_ts_ms)
        dx = self.vx * dt
        dy = self.vy * dt
        return BBox(
            x1=self.bbox.x1 + dx,
            y1=self.bbox.y1 + dy,
            x2=self.bbox.x2 + dx,
            y2=self.bbox.y2 + dy,
        )


def _bbox_centroid(bbox: BBox) -> tuple[float, float]:
    return ((bbox.x1 + bbox.x2) * 0.5, (bbox.y1 + bbox.y2) * 0.5)


def _centroid_distance_sq(a: BBox, b: BBox) -> float:
    ax, ay = _bbox_centroid(a)
    bx, by = _bbox_centroid(b)
    return (ax - bx) ** 2 + (ay - by) ** 2


class KalmanCarryForward:
    """Persist detected bboxes between 5 Hz SCRFD calls.

    On each :meth:`update` with a real detection, we associate the new bboxes
    to the previous tracks by nearest centroid, estimate per-axis velocity
    (pixels / ms) against the prior detection, and cache the tracks. On each
    :meth:`predict`, we linearly extrapolate every live track to the current
    timestamp. Tracks older than ``max_staleness_ms`` are dropped.

    This is a deliberately minimal Kalman: no process / observation noise
    matrices, no IoU association. Face tracking over 200–500 ms windows at
    the bbox scale used here does not need the full machinery, and keeping
    the code short keeps it auditable for a privacy-critical path.
    """

    def __init__(self, *, max_staleness_ms: float = DEFAULT_MAX_STALENESS_MS) -> None:
        if max_staleness_ms <= 0:
            raise ValueError(f"max_staleness_ms must be > 0, got {max_staleness_ms}")
        self._max_staleness_ms = max_staleness_ms
        self._tracks: list[_CarriedBBox] = []

    @property
    def max_staleness_ms(self) -> float:
        return self._max_staleness_ms

    def update(self, bboxes: list[BBox], *, now_ms: float) -> None:
        """Record a fresh detection batch.

        An empty ``bboxes`` list clears the track state — an explicit
        "no faces visible" signal from the detector is authoritative and
        resets carry-forward immediately. Callers that want to keep masking
        through a single missed frame should simply not call ``update``.
        """
        if not bboxes:
            self._tracks = []
            return

        # Greedy nearest-centroid association against the previous tracks.
        prior = self._tracks
        used: set[int] = set()
        new_tracks: list[_CarriedBBox] = []
        for bb in bboxes:
            best_i = -1
            best_d = float("inf")
            for i, p in enumerate(prior):
                if i in used:
                    continue
                d = _centroid_distance_sq(p.bbox, bb)
                if d < best_d:
                    best_d = d
                    best_i = i
            if best_i >= 0:
                p = prior[best_i]
                used.add(best_i)
                dt = max(1.0, now_ms - p.last_detection_ts_ms)
                # Velocity in px / ms on top-left corner (width/height can
                # drift independently; we keep the bbox size from the new
                # detection and only extrapolate position between updates).
                vx = (bb.x1 - p.bbox.x1) / dt
                vy = (bb.y1 - p.bbox.y1) / dt
                new_tracks.append(
                    _CarriedBBox(
                        bbox=bb,
                        vx=vx,
                        vy=vy,
                        last_detection_ts_ms=now_ms,
                    )
                )
            else:
                # Unmatched → new track with zero velocity.
                new_tracks.append(_CarriedBBox(bbox=bb, last_detection_ts_ms=now_ms))
        self._tracks = new_tracks

    def predict(self, *, now_ms: float) -> list[BBox]:
        """Return bboxes extrapolated to ``now_ms``; drop stale tracks."""
        live: list[_CarriedBBox] = []
        out: list[BBox] = []
        for t in self._tracks:
            if (now_ms - t.last_detection_ts_ms) > self._max_staleness_ms:
                continue
            live.append(t)
            out.append(t.predict(now_ms))
        self._tracks = live
        return out

    def clear(self) -> None:
        self._tracks = []


@dataclass
class CadencedBboxPipeline:
    """5 Hz SCRFD + Kalman carry-forward in a single call surface.

    Callers invoke :meth:`step` once per frame. Internally:

    1. If the wall-clock gap since the last detection exceeds
       ``detect_interval_ms``, run the underlying ``source.detect`` and feed
       the result into the Kalman carry-forward buffer. Otherwise skip.
    2. Regardless, return the Kalman prediction at the current timestamp —
       so the obscure mask stays locked to the face between detection ticks.

    The ``now_ms`` parameter is injectable for deterministic tests; in
    production callers pass ``time.monotonic() * 1000``.
    """

    source: FaceBboxSource
    detect_interval_ms: float = DEFAULT_DETECT_INTERVAL_MS
    max_staleness_ms: float = DEFAULT_MAX_STALENESS_MS
    _carry: KalmanCarryForward = field(init=False)
    _last_detect_ts_ms: float = field(init=False, default=-1.0)

    def __post_init__(self) -> None:
        if self.detect_interval_ms <= 0:
            raise ValueError(f"detect_interval_ms must be > 0, got {self.detect_interval_ms}")
        self._carry = KalmanCarryForward(max_staleness_ms=self.max_staleness_ms)

    def step(self, frame: np.ndarray, *, now_ms: float | None = None) -> list[BBox]:
        """Process one captured frame and return the bboxes to obscure."""
        ts = now_ms if now_ms is not None else time.monotonic() * 1000.0
        if self._last_detect_ts_ms < 0 or (ts - self._last_detect_ts_ms) >= self.detect_interval_ms:
            detected = self.source.detect(frame)
            self._carry.update(detected, now_ms=ts)
            self._last_detect_ts_ms = ts
        return self._carry.predict(now_ms=ts)

    def reset(self) -> None:
        """Clear carry-forward state (e.g. on camera role change)."""
        self._carry.clear()
        self._last_detect_ts_ms = -1.0

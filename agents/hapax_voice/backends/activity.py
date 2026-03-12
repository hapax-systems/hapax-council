"""Activity perception backend — optical flow motion detection.

Captures frames from an overhead V4L2 camera, computes optical flow magnitude
between consecutive frames, and produces an ``activity_level`` signal (0.0-1.0).

Supports source parameterization: ``ActivityBackend("overhead_gear", target="/dev/video2")``
writes to ``activity_level:overhead_gear`` instead of ``activity_level``.

When no ``target`` is provided, operates as a stub (``available() → False``).
"""

from __future__ import annotations

import logging
import threading
import time

import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None  # type: ignore[assignment]

from agents.hapax_voice.backends.emotion import _FrameReader, discover_camera
from agents.hapax_voice.perception import PerceptionTier
from agents.hapax_voice.primitives import Behavior
from agents.hapax_voice.source_naming import qualify, validate_source_id

log = logging.getLogger(__name__)

_BASE_NAMES = ("activity_level",)

# Analysis parameters
EMA_ALPHA = 0.2  # ~250ms effective response time
RUNNING_MAX_WINDOW_S = 30.0  # adaptive normalization window
INFERENCE_INTERVAL_S = 0.333  # ~3 fps


class _OpticalFlowAnalyzer:
    """Computes optical flow magnitude between consecutive frames.

    Thread-safe: ``activity_level`` and ``last_update`` are read by
    ``contribute()`` on the main thread.
    """

    def __init__(self, frame_reader: _FrameReader) -> None:
        self._frame_reader = frame_reader
        self._thread: threading.Thread | None = None
        self._running = False

        # Thread-safe published values
        self.activity_level: float = 0.0  # 0.0-1.0
        self.last_update: float = 0.0

        # Internal state (analysis thread only)
        self._prev_gray: np.ndarray | None = None
        self._smoothed: float = 0.0
        self._running_max: float = 1e-6  # avoid div-by-zero
        self._max_history: list[tuple[float, float]] = []  # (time, magnitude)

    def start(self) -> None:
        """Launch analysis thread."""
        self._running = True
        self._thread = threading.Thread(
            target=self._analysis_loop,
            name="optical-flow-analyzer",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop analysis thread."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def _analysis_loop(self) -> None:
        """Process frames at ~3 fps."""
        while self._running:
            frame = self._frame_reader.get_frame()
            if frame is not None:
                try:
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    if self._prev_gray is not None:
                        self._process_frame_pair(self._prev_gray, gray)
                    self._prev_gray = gray
                except Exception:
                    log.exception("Optical flow analysis error")
            time.sleep(INFERENCE_INTERVAL_S)

    def _process_frame_pair(self, prev_gray: np.ndarray, curr_gray: np.ndarray) -> None:
        """Compute optical flow between two grayscale frames.

        This is the testable core: takes two grayscale numpy arrays,
        computes Farneback optical flow, EMA-smooths, and normalizes.
        """
        now = time.monotonic()

        flow = cv2.calcOpticalFlowFarneback(
            prev_gray,
            curr_gray,
            None,
            pyr_scale=0.5,
            levels=3,
            winsize=15,
            iterations=3,
            poly_n=5,
            poly_sigma=1.2,
            flags=0,
        )

        # Mean magnitude of flow vectors
        magnitude = np.sqrt(flow[..., 0] ** 2 + flow[..., 1] ** 2)
        raw_activity = float(np.mean(magnitude))

        # EMA smoothing
        self._smoothed = EMA_ALPHA * raw_activity + (1 - EMA_ALPHA) * self._smoothed

        # Update running max (adaptive normalization)
        self._max_history.append((now, raw_activity))
        cutoff = now - RUNNING_MAX_WINDOW_S
        self._max_history = [(t, v) for t, v in self._max_history if t >= cutoff]
        window_max = max(v for _, v in self._max_history) if self._max_history else 1e-6
        self._running_max = max(window_max, 1e-6)

        # Normalize to 0.0-1.0
        normalized = min(self._smoothed / self._running_max, 1.0)

        # Publish (atomic under GIL for scalar types)
        self.activity_level = normalized
        self.last_update = now


class ActivityBackend:
    """PerceptionBackend for motion-based activity detection via optical flow.

    Provides:
      - activity_level: float (0.0-1.0, EMA-smoothed, adaptively normalized)

    When ``source_id`` is provided, behavior names are source-qualified.
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
        self._analyzer: _OpticalFlowAnalyzer | None = None

        # Internal Behavior for contribute()
        self._b_activity: Behavior[float] = Behavior(0.0)

    @property
    def name(self) -> str:
        if self._source_id:
            return f"activity:{self._source_id}"
        return "activity"

    @property
    def provides(self) -> frozenset[str]:
        if self._source_id:
            return frozenset(qualify(b, self._source_id) for b in _BASE_NAMES)
        return frozenset(_BASE_NAMES)

    @property
    def tier(self) -> PerceptionTier:
        return PerceptionTier.SLOW

    def available(self) -> bool:
        """Check if the camera device exists and OpenCV is importable."""
        if self._target is None:
            return False
        device_path = discover_camera(self._target)
        if device_path is None:
            return False
        self._device_path = device_path
        return True

    def contribute(self, behaviors: dict[str, Behavior]) -> None:
        """Read latest activity level and write to Behaviors."""
        if self._analyzer is None:
            return
        now = self._analyzer.last_update
        if now <= 0:
            return  # no data yet

        self._b_activity.update(self._analyzer.activity_level, now)

        if self._source_id:
            behaviors[qualify("activity_level", self._source_id)] = self._b_activity
        else:
            behaviors["activity_level"] = self._b_activity

    def start(self) -> None:
        if self._device_path is None:
            log.warning("Activity backend %s: no device path, cannot start", self.name)
            return
        self._frame_reader = _FrameReader(self._device_path)
        self._frame_reader.start()
        self._analyzer = _OpticalFlowAnalyzer(self._frame_reader)
        self._analyzer.start()
        log.info("Activity backend started: %s (device %s)", self.name, self._device_path)

    def stop(self) -> None:
        if self._analyzer is not None:
            self._analyzer.stop()
            self._analyzer = None
        if self._frame_reader is not None:
            self._frame_reader.stop()
            self._frame_reader = None
        log.info("Activity backend stopped: %s", self.name)

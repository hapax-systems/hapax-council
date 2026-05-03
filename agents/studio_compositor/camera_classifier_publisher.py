"""Periodic camera-classification publisher — cc-task scene-classifier-publish-restore.

Restores the classifier-publish loop flagged in the 24h independent-auditor
batch (Auditor E finding #10a, audit R3): ``camera-classifications.json``
is stale because ``StudioCompositor.publish_camera_classifications()`` is
called exactly once during compositor construction. Any change to the
camera registry — config reload, dynamic per-camera classification
landing post-PR-#2246 — is invisible to ``FollowModeController`` until
the compositor service restarts.

This module follows the pattern of :mod:`scene_classifier`'s
``SceneClassifierThread``: a background daemon thread + a maybe-start
factory that respects an env-var feature flag. Running it every ~30s
gives the camera registry a refresh cadence that any downstream
classifier (static loader fix, dynamic per-camera ML classifier in
Phase 2) can write through without coupling to the compositor's
construction lifecycle.

Feature flag:
  * ``HAPAX_CAMERA_CLASSIFIER_PUBLISHER_ACTIVE`` — default ON.
    Operator opts out by setting the env var to a falsy value
    (``0`` / ``false`` / ``no`` / ``off``).

Refresh cadence:
  * 30 s by default. Override via constructor arg for tests.
  * ``maybe_start_camera_classifier_publisher`` keeps the public API
    consistent with the scene-classifier sibling.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.studio_compositor.compositor import StudioCompositor

log = logging.getLogger(__name__)

PUBLISH_INTERVAL_S: float = 30.0
PUBLISHER_ACTIVE_ENV = "HAPAX_CAMERA_CLASSIFIER_PUBLISHER_ACTIVE"
_FALSY = frozenset({"0", "false", "no", "off", ""})


def publisher_active() -> bool:
    """Whether the periodic publisher should run.

    Default-on per the same convention scene_classifier.py uses;
    operator opts out via env var.
    """
    return os.environ.get(PUBLISHER_ACTIVE_ENV, "1").strip().lower() not in _FALSY


class CameraClassifierPublisherThread(threading.Thread):
    """Background thread that re-publishes camera classifications periodically.

    Calls ``compositor.publish_camera_classifications()`` every
    ``interval_s`` seconds while running. Stops cleanly on
    ``stop()`` (set the event, join with timeout).

    The publish call is idempotent and atomic (tmp+rename inside the
    compositor method), so concurrent reads always see a complete
    file. A tick that hits a transient error logs and continues to the
    next tick — the publisher never crashes the compositor.
    """

    def __init__(
        self,
        compositor: StudioCompositor,
        *,
        interval_s: float = PUBLISH_INTERVAL_S,
    ) -> None:
        super().__init__(name="hapax-camera-classifier-publisher", daemon=True)
        self._compositor = compositor
        self._interval_s = interval_s
        self._stop_event = threading.Event()

    def run(self) -> None:
        log.info(
            "camera_classifier_publisher started (interval=%.1fs)",
            self._interval_s,
        )
        while not self._stop_event.is_set():
            try:
                self._compositor.publish_camera_classifications()
            except Exception:
                log.exception("camera_classifier_publisher tick failed; continuing")
            if self._stop_event.wait(timeout=self._interval_s):
                break
        log.info("camera_classifier_publisher stopped")

    def stop(self, *, timeout: float = 2.0) -> None:
        self._stop_event.set()
        self.join(timeout=timeout)


def maybe_start_camera_classifier_publisher(
    compositor: StudioCompositor,
    *,
    interval_s: float = PUBLISH_INTERVAL_S,
) -> CameraClassifierPublisherThread | None:
    """Start the periodic publisher iff the feature flag is on.

    Returns the running thread when started, or ``None`` when the flag
    is off or startup failed. Safe to call from the compositor's
    single-threaded startup path — exceptions are logged and swallowed
    so the compositor's start sequence cannot be broken by a publisher
    that fails to launch.
    """
    if not publisher_active():
        log.info("camera_classifier_publisher inactive (%s off)", PUBLISHER_ACTIVE_ENV)
        return None
    try:
        thread = CameraClassifierPublisherThread(compositor, interval_s=interval_s)
        thread.start()
        return thread
    except Exception:
        log.exception("camera_classifier_publisher failed to start")
        return None

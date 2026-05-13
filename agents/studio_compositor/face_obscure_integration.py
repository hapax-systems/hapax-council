"""Capture-time facial-obscuring entry point (task #129).

Thin function-oriented wrapper that glues the three independently-tested
layers together so ``camera_pipeline.py`` / ``snapshots.py`` can wire the
obscure stage in with a single call:

    from agents.studio_compositor.face_obscure_integration import (
        obscure_frame_for_camera,
    )
    jpeg_in = obscure_frame_for_camera(frame, camera_role="operator")

Reads the feature flag and policy from env on every call via
:func:`shared.face_obscure_policy.resolve_policy` — the layers below the
integration helper stay policy-agnostic so the flag can be toggled at runtime
(systemd ``EnvironmentFile`` reload) without restarting the compositor.

State is kept per-camera in a module-level dict so repeat calls for the same
role share a single SCRFD instance + Kalman buffer. The helper is safe to
call from multiple camera loops concurrently at the python level because
each role has its own pipeline instance; InsightFace's ONNX runtime session
is itself thread-safe for ``run()``.

Stage 2 scope: the bbox source is the real SCRFD detector by default. The
YOLO11n fallback + fail-closed rectangle painter (plan Task 4 / §3.6) is
deferred — the current helper degrades to pass-through if carry-forward
expires, and Stage 3 will upgrade this to a fail-closed full-frame mask.
"""

import json
import logging
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from agents.studio_compositor.face_obscure import BBox, FaceObscurer
from agents.studio_compositor.face_obscure_pipeline import (
    CadencedBboxPipeline,
    FaceBboxSource,
    ScrfdFaceBboxSource,
)
from shared.face_obscure_policy import FaceObscurePolicy, resolve_policy

try:
    # Prometheus counters are best-effort; import failure must not break the
    # capture path (e.g. in unit tests that don't import the full metrics
    # surface).
    from agents.studio_compositor.metrics import (
        record_face_obscure_error,
        record_face_obscure_frame,
    )
except Exception:  # pragma: no cover — defensive

    def record_face_obscure_frame(camera_role: str, has_faces: bool) -> None:  # noqa: ARG001
        """No-op fallback when metrics module is unavailable."""
        return

    def record_face_obscure_error(  # noqa: ARG001
        camera_role: str, exception_class: str
    ) -> None:
        """No-op fallback when metrics module is unavailable."""
        return


if TYPE_CHECKING:
    import numpy as np
else:
    import numpy as np  # noqa: TC002

log = logging.getLogger(__name__)


# Per-camera pipeline cache. Keys are camera role strings (e.g. ``"operator"``,
# ``"desk"``, ``"room"``). Each pipeline owns its own SCRFD wrapper + Kalman.
_PIPELINES: dict[str, CadencedBboxPipeline] = {}
_PIPELINES_LOCK = threading.Lock()

# Single shared obscurer — it's stateless and its config is constant.
_OBSCURER = FaceObscurer()

# Live bbox cache for the cairooverlay face-obscure painting path.
# Normalized to [0,1] so consumers only need tile dimensions to transform.
# Updated by obscure_frame_for_camera() on the snapshot thread; read by
# overlay.py on_draw() on the GStreamer streaming thread.
_LIVE_NORM_BBOXES: dict[str, list[tuple[float, float, float, float]]] = {}
_LIVE_NORM_BBOXES_LOCK = threading.Lock()

PERSON_DETECTION_FILE: Path = Path("/dev/shm/hapax-compositor/person-detection.json")
CAMERA_CLASSIFICATIONS_FILE: Path = Path("/dev/shm/hapax-compositor/camera-classifications.json")

_PERSON_FALLBACK_TRUE = frozenset({"1", "true", "yes", "on", "enabled"})
_PERSON_FALLBACK_FALSE = frozenset({"0", "false", "no", "off", "disabled"})
_PERSON_FALLBACK_DEFAULT_MAX_AGE_S = 5.0
_PERSON_FALLBACK_MIN_CONFIDENCE = 0.35
_PERSON_FALLBACK_OPERATOR_ROLES = frozenset({"brio-operator", "c920-room"})


def _person_fallback_enabled(env: dict[str, str] | None = None) -> bool:
    source = env if env is not None else os.environ
    raw = source.get("HAPAX_FACE_OBSCURE_PERSON_FALLBACK_ACTIVE")
    if raw is None:
        return True
    return raw.strip().lower() not in _PERSON_FALLBACK_FALSE


def _person_fallback_max_age_s(env: dict[str, str] | None = None) -> float:
    source = env if env is not None else os.environ
    raw = source.get("HAPAX_FACE_OBSCURE_PERSON_FALLBACK_MAX_AGE_S")
    if not raw:
        return _PERSON_FALLBACK_DEFAULT_MAX_AGE_S
    try:
        return max(0.5, float(raw))
    except ValueError:
        return _PERSON_FALLBACK_DEFAULT_MAX_AGE_S


def _read_json(path: Path) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception:
        log.debug("could not read %s", path, exc_info=True)
        return None


def _camera_role_allows_person_fallback(camera_role: str) -> bool:
    if camera_role in _PERSON_FALLBACK_OPERATOR_ROLES:
        return True
    raw = _read_json(CAMERA_CLASSIFICATIONS_FILE)
    if not isinstance(raw, dict):
        return False
    row = raw.get(camera_role)
    if not isinstance(row, dict):
        return False
    role = str(row.get("semantic_role") or "").lower()
    ontology = row.get("subject_ontology")
    subject_tokens = (
        {str(item).lower() for item in ontology if isinstance(item, str)}
        if isinstance(ontology, list)
        else set()
    )
    return bool(row.get("operator_visible")) and (
        "operator-face" in role or "room-wide" in role or "person" in subject_tokens
    )


def _person_box_to_anti_parasocial_bbox(
    box: dict[str, object],
    *,
    frame_w: int,
    frame_h: int,
) -> BBox | None:
    try:
        x1 = float(box.get("x1", 0.0))
        y1 = float(box.get("y1", 0.0))
        x2 = float(box.get("x2", 0.0))
        y2 = float(box.get("y2", 0.0))
        confidence = float(box.get("confidence", 0.0))
    except (TypeError, ValueError):
        return None
    if confidence < _PERSON_FALLBACK_MIN_CONFIDENCE:
        return None
    w = max(0.0, x2 - x1)
    h = max(0.0, y2 - y1)
    if w <= 1.0 or h <= 1.0:
        return None

    # Anti-parasocial fallback: mask likely head/face, not the whole body.
    # This preserves actionability and posture while breaking at-a-glance ID.
    fx1 = x1 + (0.18 * w)
    fx2 = x2 - (0.18 * w)
    fy1 = y1
    fy2 = y1 + (0.36 * h)
    return BBox(
        x1=max(0.0, min(float(frame_w), fx1)),
        y1=max(0.0, min(float(frame_h), fy1)),
        x2=max(0.0, min(float(frame_w), fx2)),
        y2=max(0.0, min(float(frame_h), fy2)),
    )


def _person_detection_fallback_bboxes(
    camera_role: str,
    frame: np.ndarray,
    *,
    env: dict[str, str] | None = None,
) -> list[BBox]:
    if not _person_fallback_enabled(env):
        return []
    if not _camera_role_allows_person_fallback(camera_role):
        return []
    raw = _read_json(PERSON_DETECTION_FILE)
    if not isinstance(raw, dict):
        return []
    try:
        ts = float(raw.get("timestamp", 0.0))
    except (TypeError, ValueError):
        return []
    if ts <= 0.0 or (time.time() - ts) > _person_fallback_max_age_s(env):
        return []
    cameras = raw.get("cameras")
    if not isinstance(cameras, dict):
        return []
    row = cameras.get(camera_role)
    if not isinstance(row, dict):
        return []
    boxes = row.get("boxes")
    if not isinstance(boxes, list):
        return []
    frame_h, frame_w = frame.shape[:2]
    out: list[BBox] = []
    for item in boxes:
        if not isinstance(item, dict):
            continue
        bbox = _person_box_to_anti_parasocial_bbox(item, frame_w=frame_w, frame_h=frame_h)
        if bbox is not None:
            out.append(bbox)
    return out


def _build_default_source(camera_role: str) -> FaceBboxSource:
    """Construct the production SCRFD bbox source for a given camera role."""
    return ScrfdFaceBboxSource(camera_role=camera_role)


def _get_pipeline(
    camera_role: str,
    source_factory: Callable[[str], FaceBboxSource] | None = None,
) -> CadencedBboxPipeline:
    """Return the cached pipeline for ``camera_role``, creating one if needed.

    ``source_factory`` lets tests inject a stub source without monkey-patching
    the module; in production the caller passes ``None`` and we build a real
    SCRFD source.
    """
    with _PIPELINES_LOCK:
        pipe = _PIPELINES.get(camera_role)
        if pipe is None:
            factory = source_factory or _build_default_source
            source = factory(camera_role)
            pipe = CadencedBboxPipeline(source=source)
            _PIPELINES[camera_role] = pipe
        return pipe


def _filter_by_policy(
    bboxes: list[BBox],
    *,
    policy: FaceObscurePolicy,
    operator_flags: list[bool] | None,
) -> list[BBox]:
    """Apply :class:`FaceObscurePolicy` to the predicted bbox set.

    Stage 2 treats every bbox as non-operator because the bbox pipeline does
    not propagate per-face operator flags (the detector computes them but the
    carry-forward layer doesn't track them). ``OBSCURE_NON_OPERATOR`` behaves
    as ``ALWAYS_OBSCURE`` until Stage 3 threads operator flags through
    ``KalmanCarryForward``. This is a conservative choice — it over-obscures
    the operator, not under-obscures guests.
    """
    if policy is FaceObscurePolicy.DISABLED:
        return []
    if policy is FaceObscurePolicy.ALWAYS_OBSCURE:
        return bboxes
    # OBSCURE_NON_OPERATOR: fall back to obscuring everyone in Stage 2.
    if operator_flags is None:
        return bboxes
    return [b for b, is_op in zip(bboxes, operator_flags, strict=False) if not is_op]


def obscure_frame_for_camera(
    frame: np.ndarray,
    camera_role: str,
    *,
    env: dict[str, str] | None = None,
    source_factory: Callable[[str], FaceBboxSource] | None = None,
) -> np.ndarray:
    """Obscure faces on ``frame`` for the given camera role.

    This is the single integration surface for ``camera_pipeline.py`` /
    ``snapshots.py``. It is pure with respect to its inputs (aside from the
    per-camera pipeline cache, which is an implementation detail for
    amortizing SCRFD load).

    Args:
        frame: HxWxC uint8 BGR frame straight from the V4L2 / GStreamer
            capture path. Must not be ``None``.
        camera_role: Canonical role string. Used to key the pipeline cache
            and to tell SCRFD whether this is the operator cam for ReID.
        env: Optional env mapping for testing the feature flag.
        source_factory: Optional callable that returns a :class:`FaceBboxSource`
            for a given role — lets tests avoid loading SCRFD.

    Returns:
        A new ndarray with detected face regions masked per the active
        policy, or the original ``frame`` unchanged when the flag is OFF /
        policy is DISABLED / no faces detected. Callers should always use
        the returned frame downstream.
    """
    policy = resolve_policy(env)
    if policy is FaceObscurePolicy.DISABLED:
        # Flag OFF or policy explicitly DISABLED — pass-through. §11 of the
        # spec requires this to be byte-identical to pre-feature behavior.
        # Still record the metric so Grafana can tell a quiet camera from
        # a disabled capture path.
        record_face_obscure_frame(camera_role, has_faces=False)
        return frame

    try:
        pipeline = _get_pipeline(camera_role, source_factory=source_factory)
        bboxes = pipeline.step(frame)
        if not bboxes:
            bboxes = _person_detection_fallback_bboxes(camera_role, frame, env=env)
        # Publish normalized bboxes for the cairooverlay face-obscure path.
        frame_h, frame_w = frame.shape[:2]
        if frame_w > 0 and frame_h > 0 and bboxes:
            norm = [
                (b.x1 / frame_w, b.y1 / frame_h, b.x2 / frame_w, b.y2 / frame_h) for b in bboxes
            ]
        else:
            norm = []
        with _LIVE_NORM_BBOXES_LOCK:
            _LIVE_NORM_BBOXES[camera_role] = norm
    except Exception as exc:  # noqa: BLE001 — capture path must never crash
        # FAIL-CLOSED per beta audit F-AUDIT-1061-1 2026-04-19: if the pipeline
        # raises, we cannot trust that faces were masked. A privacy-critical
        # surface must treat "pipeline broken" as "all faces present" — return
        # a full-frame Gruvbox-dark mask rather than the raw un-obscured frame.
        # The face-obscure core module provides the same (40,40,40) BGR fill
        # used by the rect-obscure path, so the failure is visually consistent.
        import numpy as np

        from .face_obscure import GRUVBOX_DARK_BGR

        exception_class = type(exc).__name__
        log.exception(
            "face obscure pipeline raised for camera=%s (%s) — failing closed to full-frame mask",
            camera_role,
            exception_class,
        )
        record_face_obscure_error(camera_role, exception_class=exception_class)
        # Build a full-frame fill matching the input shape/dtype.
        if frame.ndim == 3:
            fill = np.zeros_like(frame)
            fill[:, :, 0] = GRUVBOX_DARK_BGR[0]
            fill[:, :, 1] = GRUVBOX_DARK_BGR[1]
            fill[:, :, 2] = GRUVBOX_DARK_BGR[2]
            return fill
        # Grayscale or other shapes: solid mean-channel fill (fail-closed still).
        return np.full_like(frame, GRUVBOX_DARK_BGR[0])

    filtered = _filter_by_policy(bboxes, policy=policy, operator_flags=None)
    if not filtered:
        record_face_obscure_frame(camera_role, has_faces=False)
        return frame
    record_face_obscure_frame(camera_role, has_faces=True)
    return _OBSCURER.obscure(frame, filtered)


def get_live_bboxes() -> dict[str, list[tuple[float, float, float, float]]]:
    """Return normalized face bboxes per camera for live overlay painting.

    Each value is a list of (nx1, ny1, nx2, ny2) tuples in [0,1] range,
    representing face regions relative to the camera's capture frame.
    The cairooverlay transforms these to composite tile coordinates.
    """
    with _LIVE_NORM_BBOXES_LOCK:
        return dict(_LIVE_NORM_BBOXES)


def reset_pipeline_cache() -> None:
    """Drop all per-camera pipelines (tests + service-reload boundary)."""
    with _PIPELINES_LOCK:
        _PIPELINES.clear()
    with _LIVE_NORM_BBOXES_LOCK:
        _LIVE_NORM_BBOXES.clear()

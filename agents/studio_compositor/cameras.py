"""Camera source branches for the GStreamer pipeline."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

import cv2

from .config import SNAPSHOT_DIR
from .cuda_caps import cuda_input_caps_string
from .face_obscure_integration import obscure_frame_for_camera
from .models import CameraSpec, TileRect

if TYPE_CHECKING:
    import numpy as np
else:
    import numpy as np  # noqa: TC002 — needed at runtime for buffer reshape

log = logging.getLogger(__name__)

# JPEG quality for the obscured snapshot. Matches the previous `jpegenc
# quality=75` setting so downstream consumers see the same size/quality
# budget; the Python re-encode replaces the GStreamer ``jpegenc`` element
# so we can run face obscuring on the raw BGR buffer first.
_JPEG_QUALITY = 75


def _is_filesystem_camera(cam: CameraSpec) -> bool:
    """Return False for URL-backed cameras that have no local device path."""
    device = str(getattr(cam, "device", "") or "")
    input_format = str(getattr(cam, "input_format", "") or "")
    if input_format == "http_jpeg":
        return False
    return not device.startswith(("http://", "https://"))


def add_camera_snapshot_branch(
    compositor: Any, pipeline: Any, camera_tee: Any, cam: CameraSpec
) -> None:
    """Add per-camera snapshot branch writing JPEG to /dev/shm."""
    Gst = compositor._Gst
    role = cam.role.replace("-", "_")

    queue = Gst.ElementFactory.make("queue", f"queue-camsnap-{role}")
    queue.set_property("leaky", 2)
    queue.set_property("max-size-buffers", 2)
    convert = Gst.ElementFactory.make("videoconvert", f"camsnap-convert-{role}")
    convert.set_property("dither", 0)  # none — Bayer default creates sawtooth columns
    rate = Gst.ElementFactory.make("videorate", f"camsnap-rate-{role}")
    rate_caps = Gst.ElementFactory.make("capsfilter", f"camsnap-ratecaps-{role}")
    rate_caps.set_property("caps", Gst.Caps.from_string("video/x-raw,framerate=1/5"))
    scale = Gst.ElementFactory.make("videoscale", f"camsnap-scale-{role}")
    scale_caps = Gst.ElementFactory.make("capsfilter", f"camsnap-scalecaps-{role}")
    snap_w = min(cam.width, 640)
    snap_h = min(cam.height, 360)
    # Task #129 Stage 3: force BGR output so the appsink callback can hand a
    # contiguous HxWx3 uint8 array to ``obscure_frame_for_camera`` + cv2
    # without an extra convert pass. Previously the chain terminated in
    # ``jpegenc`` and emitted a JPEG blob; we now encode in Python after the
    # obscure stage so downstream tees read only obscured bytes.
    scale_caps.set_property(
        "caps",
        Gst.Caps.from_string(
            f"video/x-raw,format=BGR,width={snap_w},height={snap_h}",
        ),
    )
    appsink = Gst.ElementFactory.make("appsink", f"camsnap-sink-{role}")
    appsink.set_property("sync", False)
    appsink.set_property("async", False)
    appsink.set_property("drop", True)
    appsink.set_property("max-buffers", 1)

    chain = [queue, convert, rate, rate_caps, scale, scale_caps, appsink]

    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    snap_role = cam.role

    def _on_new_sample(sink: Any) -> int:
        sample = sink.emit("pull-sample")
        if sample is None:
            return 1
        buf = sample.get_buffer()
        ok, mapinfo = buf.map(compositor._Gst.MapFlags.READ)
        if not ok:
            return 0
        try:
            expected = snap_w * snap_h * 3
            # Some drivers pad rows; guard against it rather than assuming.
            if mapinfo.size < expected:
                log.warning(
                    "camsnap buffer underflow for %s: size=%d expected=%d",
                    snap_role,
                    mapinfo.size,
                    expected,
                )
                return 0
            # Build a numpy view over the mapped buffer, then copy because
            # the buffer is unmapped on exit.
            frame = np.frombuffer(mapinfo.data, dtype=np.uint8, count=expected).reshape(
                (snap_h, snap_w, 3)
            )
            # Task #129 Stage 3 — irreversible face obscure BEFORE egress.
            # This is the live privacy-leak fix: all downstream tees
            # (content injector → Reverie → pip-ur, director LLM snapshots,
            # OBS V4L2 loopback, RTMP, HLS) read ``cam-<role>.jpg`` so the
            # JPEG written below must already be obscured.
            try:
                frame = obscure_frame_for_camera(frame, snap_role)
            except Exception as exc:  # noqa: BLE001 — never crash the pipeline
                # FAIL-CLOSED per beta audit F-AUDIT-1061-1 (2026-04-19):
                # obscure_frame_for_camera fails closed internally, but this
                # outer catch covers import errors + numpy-side failures.
                # Overwrite with solid Gruvbox-dark (BGR 40,40,40) so the JPEG
                # below cannot possibly leak un-obscured pixels.
                log.exception(
                    "face obscure raised outside integration wrapper for %s "
                    "(%s) — failing closed to full-frame mask",
                    snap_role,
                    type(exc).__name__,
                )
                frame = np.zeros_like(frame)
                frame[:, :, :] = (40, 40, 40)
            ok_enc, jpeg = cv2.imencode(
                ".jpg",
                frame,
                [int(cv2.IMWRITE_JPEG_QUALITY), _JPEG_QUALITY],
            )
            if not ok_enc:
                log.warning("camsnap imencode failed for %s", snap_role)
                return 0
            data = jpeg.tobytes()
            tmp = SNAPSHOT_DIR / f"{snap_role}.jpg.tmp"
            final = SNAPSHOT_DIR / f"{snap_role}.jpg"
            fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
            try:
                written = os.write(fd, data)
            finally:
                os.close(fd)
            if written == len(data):
                tmp.rename(final)
        finally:
            buf.unmap(mapinfo)
        return 0

    appsink.set_property("emit-signals", True)
    appsink.connect("new-sample", _on_new_sample)

    for el in chain:
        pipeline.add(el)
    for i in range(len(chain) - 1):
        chain[i].link(chain[i + 1])

    tee_pad = camera_tee.request_pad(camera_tee.get_pad_template("src_%u"), None, None)
    queue_sink = queue.get_static_pad("sink")
    tee_pad.link(queue_sink)


def add_camera_branch(
    compositor: Any, pipeline: Any, comp_element: Any, cam: CameraSpec, tile: TileRect, fps: int
) -> None:
    """Add a single camera slot to the composite pipeline.

    --- ALPHA PHASE 2: CAMERA BRANCH CONSTRUCTION ---
    See docs/superpowers/specs/2026-04-12-compositor-hot-swap-architecture-design.md

    The v4l2src + watchdog + jpegdec + videoconvert chain lives in a separate
    GstPipeline managed by PipelineManager. Here we only create the
    interpipesrc consumer that subscribes to the producer's named interpipesink
    (cam_<role>) and feeds the existing compositor / recording / snapshot
    branches unchanged. Hot-swap to the fallback producer is driven by
    PipelineManager on producer-bus errors.
    """
    Gst = compositor._Gst
    role = cam.role.replace("-", "_")

    src = Gst.ElementFactory.make("interpipesrc", f"consumer_{role}")
    if src is None:
        raise RuntimeError(
            f"interpipesrc factory failed for {cam.role} — install gst-plugin-interpipe"
        )
    src.set_property("listen-to", f"cam_{role}")
    src.set_property("stream-sync", "restart-ts")
    src.set_property("allow-renegotiation", True)
    src.set_property("is-live", True)
    src.set_property("format", Gst.Format.TIME)

    compositor._element_to_role[f"consumer_{role}"] = cam.role
    pipeline.add(src)

    # Register the consumer with PipelineManager so it can hot-swap listen-to
    # on producer faults (and so delta's eventual v4l2_camera SourceRegistry
    # backend can wrap it).
    pipeline_manager = getattr(compositor, "_pipeline_manager", None)
    if pipeline_manager is not None:
        pipeline_manager.register_consumer(cam.role, src)

    if _is_filesystem_camera(cam) and not Path(cam.device).exists():
        log.warning(
            "Camera %s device %s not found — slot will start on fallback",
            cam.role,
            cam.device,
        )
        with compositor._camera_status_lock:
            compositor._camera_status[cam.role] = "offline"
        if pipeline_manager is not None:
            pipeline_manager.swap_to_fallback(cam.role)

    last = src

    camera_tee = Gst.ElementFactory.make("tee", f"tee_{role}")
    camera_tee.set_property("allow-not-linked", True)
    pipeline.add(camera_tee)
    last.link(camera_tee)
    # --- END ALPHA PHASE 2 ---

    # Compositor branch — CUDA or CPU based on runtime capability
    use_cuda = getattr(compositor, "_use_cuda", False)
    queue_comp = Gst.ElementFactory.make("queue", f"queue-comp-{role}")
    queue_comp.set_property("leaky", 2)
    queue_comp.set_property("max-size-buffers", 2)
    if use_cuda:
        upload = Gst.ElementFactory.make("cudaupload", f"upload_{role}")
        cuda_convert = Gst.ElementFactory.make("cudaconvert", f"cudaconv_{role}")
        scale = Gst.ElementFactory.make("cudascale", f"scale_{role}")
        scale.set_property("add-borders", True)
        scale_caps = Gst.ElementFactory.make("capsfilter", f"scalecaps_{role}")
        scale_caps.set_property(
            "caps",
            Gst.Caps.from_string(cuda_input_caps_string(tile.w, tile.h, fps)),
        )
        branch_elements = [queue_comp, upload, cuda_convert, scale, scale_caps]
    else:
        cpu_convert = Gst.ElementFactory.make("videoconvert", f"cpuconv_{role}")
        cpu_convert.set_property("dither", 0)
        scale = Gst.ElementFactory.make("videoscale", f"scale_{role}")
        scale.set_property("add-borders", True)
        scale_caps = Gst.ElementFactory.make("capsfilter", f"scalecaps_{role}")
        scale_caps.set_property(
            "caps",
            Gst.Caps.from_string(f"video/x-raw,format=I420,width={tile.w},height={tile.h}"),
        )
        branch_elements = [queue_comp, cpu_convert, scale, scale_caps]

    for el in branch_elements:
        pipeline.add(el)
    # Link chain
    for i in range(len(branch_elements) - 1):
        branch_elements[i].link(branch_elements[i + 1])

    tee_pad = camera_tee.request_pad(camera_tee.get_pad_template("src_%u"), None, None)
    queue_sink = queue_comp.get_static_pad("sink")
    tee_pad.link(queue_sink)

    pad_template = comp_element.get_pad_template("sink_%u")
    pad = comp_element.request_pad(pad_template, None, None)
    if pad is None:
        raise RuntimeError(f"Failed to get compositor sink pad for {cam.role}")
    pad.set_property("xpos", tile.x)
    pad.set_property("ypos", tile.y)
    pad.set_property("width", tile.w)
    pad.set_property("height", tile.h)

    src_pad = scale_caps.get_static_pad("src")
    if src_pad.link(pad) != Gst.PadLinkReturn.OK:
        raise RuntimeError(f"Failed to link {cam.role} to compositor")

    from .recording import add_recording_branch

    if compositor.config.recording.enabled:
        add_recording_branch(compositor, pipeline, camera_tee, cam, fps)

    add_camera_snapshot_branch(compositor, pipeline, camera_tee, cam)

    if not hasattr(compositor, "_camera_elements"):
        compositor._camera_elements = {}
        compositor._camera_specs = {}
    compositor._camera_elements[cam.role] = {
        "src": src,
        "tee": camera_tee,
        "comp_pad": pad,
    }
    compositor._camera_specs[cam.role] = cam

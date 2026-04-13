"""Camera source branches for the GStreamer pipeline."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from .config import SNAPSHOT_DIR
from .models import CameraSpec, TileRect

log = logging.getLogger(__name__)


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
    scale_caps.set_property(
        "caps", Gst.Caps.from_string(f"video/x-raw,width={snap_w},height={snap_h}")
    )
    encoder = Gst.ElementFactory.make("jpegenc", f"camsnap-jpeg-{role}")
    encoder.set_property("quality", 75)
    appsink = Gst.ElementFactory.make("appsink", f"camsnap-sink-{role}")
    appsink.set_property("sync", False)
    appsink.set_property("async", False)
    appsink.set_property("drop", True)
    appsink.set_property("max-buffers", 1)

    chain = [queue, convert, rate, rate_caps, scale, scale_caps, encoder, appsink]

    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    snap_role = cam.role

    def _on_new_sample(sink: Any) -> int:
        sample = sink.emit("pull-sample")
        if sample is None:
            return 1
        buf = sample.get_buffer()
        ok, mapinfo = buf.map(compositor._Gst.MapFlags.READ)
        if ok:
            try:
                tmp = SNAPSHOT_DIR / f"{snap_role}.jpg.tmp"
                final = SNAPSHOT_DIR / f"{snap_role}.jpg"
                data = bytes(mapinfo.data)
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

    if not Path(cam.device).exists():
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
        scale_caps = Gst.ElementFactory.make("capsfilter", f"scalecaps_{role}")
        scale_caps.set_property(
            "caps",
            Gst.Caps.from_string(f"video/x-raw(memory:CUDAMemory),width={tile.w},height={tile.h}"),
        )
        branch_elements = [queue_comp, upload, cuda_convert, scale, scale_caps]
    else:
        cpu_convert = Gst.ElementFactory.make("videoconvert", f"cpuconv_{role}")
        cpu_convert.set_property("dither", 0)
        scale = Gst.ElementFactory.make("videoscale", f"scale_{role}")
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

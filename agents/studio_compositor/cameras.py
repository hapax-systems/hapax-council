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
    rate = Gst.ElementFactory.make("videorate", f"camsnap-rate-{role}")
    rate_caps = Gst.ElementFactory.make("capsfilter", f"camsnap-ratecaps-{role}")
    rate_caps.set_property("caps", Gst.Caps.from_string("video/x-raw,framerate=5/1"))
    scale = Gst.ElementFactory.make("videoscale", f"camsnap-scale-{role}")
    scale_caps = Gst.ElementFactory.make("capsfilter", f"camsnap-scalecaps-{role}")
    scale_caps.set_property(
        "caps", Gst.Caps.from_string(f"video/x-raw,width={cam.width},height={cam.height}")
    )
    encoder = Gst.ElementFactory.make("jpegenc", f"camsnap-jpeg-{role}")
    encoder.set_property("quality", 92)
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
    """Add a single camera source branch to the pipeline."""
    Gst = compositor._Gst
    role = cam.role.replace("-", "_")
    compositor._element_to_role[f"src_{role}"] = cam.role

    src = Gst.ElementFactory.make("v4l2src", f"src_{role}")
    src.set_property("device", cam.device)

    if not Path(cam.device).exists():
        log.warning("Camera %s device %s not found, skipping", cam.role, cam.device)
        with compositor._camera_status_lock:
            compositor._camera_status[cam.role] = "offline"
        return

    if cam.input_format == "mjpeg":
        src_caps = Gst.ElementFactory.make("capsfilter", f"srccaps_{role}")
        src_caps.set_property(
            "caps",
            Gst.Caps.from_string(
                f"image/jpeg,width={cam.width},height={cam.height},framerate={fps}/1"
            ),
        )
        decoder = Gst.ElementFactory.make("jpegdec", f"dec_{role}")
        for el in [src, src_caps, decoder]:
            pipeline.add(el)
        src.link(src_caps)
        src_caps.link(decoder)
        last = decoder
    else:
        src_caps = Gst.ElementFactory.make("capsfilter", f"srccaps_{role}")
        pix_fmt = cam.pixel_format or "GRAY8"
        src_caps.set_property(
            "caps",
            Gst.Caps.from_string(
                f"video/x-raw,format={pix_fmt},width={cam.width},height={cam.height},"
                f"framerate={fps}/1"
            ),
        )
        convert = Gst.ElementFactory.make("videoconvert", f"rawconv_{role}")
        for el in [src, src_caps, convert]:
            pipeline.add(el)
        src.link(src_caps)
        src_caps.link(convert)
        last = convert

    camera_tee = Gst.ElementFactory.make("tee", f"tee_{role}")
    camera_tee.set_property("allow-not-linked", True)
    pipeline.add(camera_tee)
    last.link(camera_tee)

    # Compositor branch
    queue_comp = Gst.ElementFactory.make("queue", f"queue-comp-{role}")
    queue_comp.set_property("leaky", 1)
    queue_comp.set_property("max-size-buffers", 2)
    upload = Gst.ElementFactory.make("cudaupload", f"upload_{role}")
    cuda_convert = Gst.ElementFactory.make("cudaconvert", f"cudaconv_{role}")
    scale = Gst.ElementFactory.make("cudascale", f"scale_{role}")
    scale_caps = Gst.ElementFactory.make("capsfilter", f"scalecaps_{role}")
    scale_caps.set_property(
        "caps",
        Gst.Caps.from_string(f"video/x-raw(memory:CUDAMemory),width={tile.w},height={tile.h}"),
    )

    for el in [queue_comp, upload, cuda_convert, scale, scale_caps]:
        pipeline.add(el)
    queue_comp.link(upload)
    upload.link(cuda_convert)
    cuda_convert.link(scale)
    scale.link(scale_caps)

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
    compositor._camera_elements[cam.role] = {"src": src, "tee": camera_tee}
    compositor._camera_specs[cam.role] = cam

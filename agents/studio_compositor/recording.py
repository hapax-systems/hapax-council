"""Recording and HLS output branches for the GStreamer pipeline."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import CameraSpec

log = logging.getLogger(__name__)


def add_recording_branch(
    compositor: Any, pipeline: Any, camera_tee: Any, cam: CameraSpec, fps: int
) -> None:
    """Add per-camera recording branch: tee -> queue -> valve -> nvh264enc -> splitmuxsink."""
    Gst = compositor._Gst
    role = cam.role.replace("-", "_")
    rec_cfg = compositor.config.recording

    queue = Gst.ElementFactory.make("queue", f"queue-rec-{role}")
    queue.set_property("leaky", 2)
    queue.set_property("max-size-buffers", 10)
    queue.set_property("max-size-time", 5 * 1_000_000_000)
    valve = Gst.ElementFactory.make("valve", f"rec-valve-{role}")
    valve.set_property("drop", not compositor._consent_recording_allowed)
    rec_upload = Gst.ElementFactory.make("cudaupload", f"rec-upload-{role}")
    rec_cuda_convert = Gst.ElementFactory.make("cudaconvert", f"rec-cudaconv-{role}")
    nv12_caps = Gst.ElementFactory.make("capsfilter", f"rec-nv12caps-{role}")
    nv12_caps.set_property(
        "caps", Gst.Caps.from_string("video/x-raw(memory:CUDAMemory),format=NV12")
    )
    encoder = Gst.ElementFactory.make("nvh264enc", f"rec-enc-{role}")
    encoder.set_property("preset", 2)
    encoder.set_property("rc-mode", 3)
    encoder.set_property("qp-const", rec_cfg.qp)
    parser = Gst.ElementFactory.make("h264parse", f"rec-parse-{role}")

    mux_sink = Gst.ElementFactory.make("splitmuxsink", f"rec-mux-{role}")
    mux_sink.set_property("max-size-time", rec_cfg.segment_seconds * 1_000_000_000)
    mux_sink.set_property("muxer", Gst.ElementFactory.make("matroskamux", None))
    mux_sink.set_property("async-handling", True)

    rec_dir = Path(rec_cfg.output_dir) / cam.role
    rec_dir.mkdir(parents=True, exist_ok=True)
    cam_role = cam.role

    def _format_location(splitmux: Any, fragment_id: int) -> str:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        return str(rec_dir / f"{cam_role}_{ts}_{fragment_id:04d}.mkv")

    mux_sink.connect("format-location-full", lambda s, fid, _sample: _format_location(s, fid))

    elements = [queue, valve, rec_upload, rec_cuda_convert, nv12_caps, encoder, parser, mux_sink]
    for el in elements:
        pipeline.add(el)

    queue.link(valve)
    valve.link(rec_upload)
    rec_upload.link(rec_cuda_convert)
    rec_cuda_convert.link(nv12_caps)
    nv12_caps.link(encoder)
    encoder.link(parser)
    parser.link(mux_sink)

    tee_pad = camera_tee.request_pad(camera_tee.get_pad_template("src_%u"), None, None)
    queue_sink = queue.get_static_pad("sink")
    tee_pad.link(queue_sink)

    compositor._recording_valves[cam.role] = valve
    compositor._recording_muxes[cam.role] = mux_sink

    with compositor._recording_status_lock:
        compositor._recording_status[cam.role] = "active"


def add_hls_branch(compositor: Any, pipeline: Any, tee: Any, fps: int) -> None:
    """Add HLS output branch: tee -> queue -> valve -> nvh264enc -> h264parse -> hlssink2."""
    Gst = compositor._Gst
    hls_cfg = compositor.config.hls

    queue = Gst.ElementFactory.make("queue", "queue-hls")
    queue.set_property("leaky", 2)
    queue.set_property("max-size-buffers", 20)
    queue.set_property("max-size-time", 3 * 1_000_000_000)
    valve = Gst.ElementFactory.make("valve", "hls-valve")
    valve.set_property("drop", not compositor._consent_recording_allowed)
    encoder = Gst.ElementFactory.make("nvh264enc", "hls-enc")
    encoder.set_property("preset", 2)
    encoder.set_property("rc-mode", 3)
    encoder.set_property("qp-const", 26)
    encoder.set_property("gop-size", fps * hls_cfg.target_duration)
    parser = Gst.ElementFactory.make("h264parse", "hls-parse")

    hls_dir = Path(hls_cfg.output_dir)
    hls_dir.mkdir(parents=True, exist_ok=True)

    hls_sink = Gst.ElementFactory.make("hlssink2", "hls-sink")
    hls_sink.set_property("target-duration", hls_cfg.target_duration)
    hls_sink.set_property("playlist-length", hls_cfg.playlist_length)
    hls_sink.set_property("max-files", hls_cfg.max_files)
    hls_sink.set_property("location", str(hls_dir / "segment%05d.ts"))
    hls_sink.set_property("playlist-location", str(hls_dir / "stream.m3u8"))
    hls_sink.set_property("async-handling", True)

    elements = [queue, valve, encoder, parser, hls_sink]
    for el in elements:
        pipeline.add(el)

    compositor._hls_valve = valve

    queue.link(valve)
    valve.link(encoder)
    encoder.link(parser)
    parser.link(hls_sink)

    tee_pad = tee.request_pad(tee.get_pad_template("src_%u"), None, None)
    queue_sink = queue.get_static_pad("sink")
    tee_pad.link(queue_sink)

"""Recording and HLS output branches for the GStreamer pipeline."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import CameraSpec

log = logging.getLogger(__name__)


def _element_name(element: Any) -> str:
    try:
        return str(element.get_name())
    except Exception:
        return repr(element)


def _make_element(Gst: Any, factory: str, name: str, branch: str) -> Any:
    element = Gst.ElementFactory.make(factory, name)
    if element is None:
        raise RuntimeError(f"{branch}: failed to create {factory} element ({name})")
    return element


def _link_or_raise(src: Any, dst: Any, branch: str) -> None:
    if not src.link(dst):
        raise RuntimeError(f"{branch}: failed to link {_element_name(src)} -> {_element_name(dst)}")


def _add_render_stage_probe(Gst: Any, element: Any, pad_name: str, stage: str) -> None:
    try:
        pad = element.get_static_pad(pad_name)
        if pad is None:
            log.debug(
                "HLS render-stage probe skipped: %s.%s missing", _element_name(element), pad_name
            )
            return

        def _probe(_pad: Any, _info: Any) -> Any:
            try:
                from . import metrics

                metrics.record_render_stage_frame(stage)
            except Exception:
                pass
            return Gst.PadProbeReturn.OK

        pad.add_probe(Gst.PadProbeType.BUFFER, _probe)
    except Exception:
        log.debug("HLS render-stage probe install failed for %s", stage, exc_info=True)


def _pad_link_ok(Gst: Any, result: Any) -> bool:
    ok = getattr(getattr(Gst, "PadLinkReturn", None), "OK", None)
    if ok is not None:
        return result == ok
    return result == 0


def _release_request_pad(element: Any, pad: Any) -> None:
    try:
        element.release_request_pad(pad)
    except Exception:
        log.debug("failed to release request pad after link failure", exc_info=True)


def _link_tee_to_sink_or_raise(Gst: Any, tee: Any, sink: Any, branch: str) -> Any:
    template = tee.get_pad_template("src_%u")
    if template is None:
        raise RuntimeError(f"{branch}: failed to find tee src_%u pad template")

    tee_pad = tee.request_pad(template, None, None)
    if tee_pad is None:
        raise RuntimeError(f"{branch}: failed to request tee src pad")

    queue_sink = sink.get_static_pad("sink")
    if queue_sink is None:
        _release_request_pad(tee, tee_pad)
        raise RuntimeError(f"{branch}: failed to get {_element_name(sink)} sink pad")

    result = tee_pad.link(queue_sink)
    if not _pad_link_ok(Gst, result):
        _release_request_pad(tee, tee_pad)
        raise RuntimeError(
            f"{branch}: failed to link tee pad to {_element_name(sink)} sink pad: {result}"
        )
    return tee_pad


def _request_sink_pad_or_raise(
    Gst: Any,
    sink_element: Any,
    template_name: str,
    *,
    branch: str,
) -> Any:
    template = sink_element.get_pad_template(template_name)
    if template is None:
        raise RuntimeError(
            f"{branch}: failed to find {_element_name(sink_element)} {template_name} pad template"
        )

    pad = sink_element.request_pad(template, None, None)
    if pad is None:
        raise RuntimeError(f"{branch}: failed to request {_element_name(sink_element)} pad")
    return pad


def _link_src_to_request_sink_pad_or_raise(
    Gst: Any,
    src_element: Any,
    sink_element: Any,
    sink_template_name: str,
    *,
    branch: str,
) -> Any:
    src_pad = src_element.get_static_pad("src")
    if src_pad is None:
        raise RuntimeError(f"{branch}: failed to get {_element_name(src_element)} src pad")

    sink_pad = _request_sink_pad_or_raise(
        Gst,
        sink_element,
        sink_template_name,
        branch=branch,
    )
    result = src_pad.link(sink_pad)
    if not _pad_link_ok(Gst, result):
        _release_request_pad(sink_element, sink_pad)
        raise RuntimeError(
            f"{branch}: failed to link {_element_name(src_element)} src pad "
            f"to {_element_name(sink_element)} {sink_template_name} pad: {result}"
        )
    return sink_pad


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
    # Drop #47 C2: pin nvh264enc to the same CUDA device as cudacompositor
    # (GPU 0 under CUDA_DEVICE_ORDER=PCI_BUS_ID + CUDA_VISIBLE_DEVICES=0).
    # Prevents the per-camera recording encoder from drifting to GPU 1 if
    # CUDA enumeration order ever changes.
    try:
        encoder.set_property("cuda-device-id", 0)
    except Exception:
        log.debug("nvh264enc (rec-enc-%s): cuda-device-id not supported", role, exc_info=True)
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
    """Add HLS output branch with an explicit CUDA/NV12 encoder handoff."""
    Gst = compositor._Gst
    hls_cfg = compositor.config.hls
    branch = "HLS branch"

    queue = _make_element(Gst, "queue", "queue-hls", branch)
    queue.set_property("leaky", 2)
    queue.set_property("max-size-buffers", 20)
    queue.set_property("max-size-time", 3 * 1_000_000_000)
    valve = _make_element(Gst, "valve", "hls-valve", branch)
    valve.set_property("drop", not compositor._consent_recording_allowed)

    upload = _make_element(Gst, "cudaupload", "hls-upload", branch)
    cuda_convert = _make_element(Gst, "cudaconvert", "hls-cudaconv", branch)
    for cuda_element, label in ((upload, "cudaupload"), (cuda_convert, "cudaconvert")):
        try:
            cuda_element.set_property("cuda-device-id", 0)
        except Exception:
            log.debug("%s (HLS): cuda-device-id not supported", label, exc_info=True)
    nv12_caps = _make_element(Gst, "capsfilter", "hls-nv12caps", branch)
    nv12_caps.set_property(
        "caps", Gst.Caps.from_string("video/x-raw(memory:CUDAMemory),format=NV12")
    )

    encoder = _make_element(Gst, "nvh264enc", "hls-enc", branch)
    # Drop #47 C2: pin HLS nvh264enc to GPU 0 for the same reasons as the
    # rtmp_output and rec-enc branches — cudacompositor lives on GPU 0,
    # and forcing the encoder to the same device avoids cross-GPU texture
    # copies when CUDA enumeration order drifts.
    try:
        encoder.set_property("cuda-device-id", 0)
    except Exception:
        log.debug("nvh264enc (hls-enc): cuda-device-id not supported", exc_info=True)
    encoder.set_property("preset", 2)
    # Delta 2026-04-14-encoder-output-path-walk finding #2: the previous
    # config set ``rc-mode=3`` (VBR) but then overrode it with
    # ``qp-const=26``, which is constant-QP mode. The ``HlsConfig.bitrate``
    # field was never read — dead config. Honor it by switching to CBR
    # (matches the RTMP bin) and wiring the configured ``hls_cfg.bitrate``
    # value through, so operators tuning HLS bandwidth get the expected
    # behaviour instead of a silently-ignored number.
    encoder.set_property("rc-mode", 2)  # 2 = cbr
    encoder.set_property("bitrate", hls_cfg.bitrate)
    encoder.set_property("gop-size", fps * hls_cfg.target_duration)
    parser = _make_element(Gst, "h264parse", "hls-parse", branch)

    hls_dir = Path(hls_cfg.output_dir)
    hls_dir.mkdir(parents=True, exist_ok=True)

    hls_sink = _make_element(Gst, "hlssink2", "hls-sink", branch)
    hls_sink.set_property("target-duration", hls_cfg.target_duration)
    hls_sink.set_property("playlist-length", hls_cfg.playlist_length)
    hls_sink.set_property("max-files", hls_cfg.max_files)
    hls_sink.set_property("location", str(hls_dir / "segment%05d.ts"))
    hls_sink.set_property("playlist-location", str(hls_dir / "stream.m3u8"))
    hls_sink.set_property("async-handling", True)

    elements = [queue, valve, upload, cuda_convert, nv12_caps, encoder, parser, hls_sink]
    for el in elements:
        pipeline.add(el)

    for src, dst in zip(elements[:-2], elements[1:-1], strict=False):
        _link_or_raise(src, dst, branch)
    _link_src_to_request_sink_pad_or_raise(Gst, parser, hls_sink, "video", branch=branch)

    _add_render_stage_probe(Gst, queue, "sink", "hls_queue_sink")
    _add_render_stage_probe(Gst, valve, "src", "hls_valve_src")
    _add_render_stage_probe(Gst, encoder, "sink", "hls_encoder_sink")
    _add_render_stage_probe(Gst, parser, "src", "hls_parser_src")

    _link_tee_to_sink_or_raise(Gst, tee, queue, branch)

    compositor._hls_valve = valve

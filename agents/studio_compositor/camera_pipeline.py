"""Isolated per-camera GstPipeline producing a named interpipesink.

See docs/superpowers/specs/2026-04-12-compositor-hot-swap-architecture-design.md

Each camera lives in its own GstPipeline instance rather than as a branch of
the composite pipeline. Errors are bounded to the producer pipeline and do
not propagate to the composite bus. The composite pipeline consumes via
`interpipesrc listen-to=cam_<role>` — hot-swappable at runtime to the
paired fallback producer via a thread-safe GObject property write.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

from .models import CameraSpec

log = logging.getLogger(__name__)


class CameraPipeline:
    """Single v4l2 camera as an isolated producer GstPipeline.

    Graph:
        v4l2src device=/dev/v4l/by-id/...
          ! capsfilter (image/jpeg or raw, native dimensions)
          ! watchdog timeout=2000
          ! jpegdec              (if mjpeg)
          ! videoconvert
          ! capsfilter (video/x-raw, format=NV12, native dimensions)
          ! interpipesink name=cam_<role> sync=false async=false forward-events=false
    """

    def __init__(
        self,
        spec: CameraSpec,
        *,
        gst: Any,
        fps: int,
        on_error: Callable[[str, str], None] | None = None,
        on_frame: Callable[[], None] | None = None,
    ) -> None:
        self._spec = spec
        self._Gst = gst
        self._fps = fps
        self._on_error = on_error
        self._on_frame = on_frame

        self._role_safe = spec.role.replace("-", "_")
        self._sink_name = f"cam_{self._role_safe}"
        self._pipeline_name = f"camera_pipeline_{self._role_safe}"

        self._pipeline: Any = None
        self._bus: Any = None
        self._bus_signal_id: int = 0
        self._state_lock = threading.RLock()
        self._last_frame_monotonic: float = 0.0
        self._rebuild_count = 0
        self._started = False
        self._http_appsrc: Any = None
        self._http_stop_event = threading.Event()
        self._http_thread: threading.Thread | None = None

    @property
    def role(self) -> str:
        return self._spec.role

    @property
    def sink_name(self) -> str:
        return self._sink_name

    @property
    def rebuild_count(self) -> int:
        return self._rebuild_count

    @property
    def last_frame_age_seconds(self) -> float:
        if self._last_frame_monotonic <= 0.0:
            return float("inf")
        return time.monotonic() - self._last_frame_monotonic

    def clear_frame_observation(self) -> None:
        """Forget prior pad-probe evidence before a fresh start/rebuild.

        Reaching PLAYING is not proof that a newly rebuilt source has produced
        a post-rebuild frame. Clearing the timestamp prevents the recovery FSM
        from treating a pre-fault frame as proof that the repaired pipeline is
        live.
        """
        self._last_frame_monotonic = 0.0

    def build(self) -> None:
        """Construct the GstPipeline graph. Idempotent (no-op if already built)."""
        with self._state_lock:
            if self._pipeline is not None:
                return

            if self._is_http_jpeg_source():
                self._build_http_jpeg_pipeline()
                return

            Gst = self._Gst
            pipeline = Gst.Pipeline.new(self._pipeline_name)

            src = Gst.ElementFactory.make("v4l2src", f"src_{self._role_safe}")
            if src is None:
                raise RuntimeError(f"{self._spec.role}: v4l2src factory failed")
            src.set_property("device", self._spec.device)
            src.set_property("do-timestamp", True)

            src_caps = Gst.ElementFactory.make("capsfilter", f"srccaps_{self._role_safe}")
            if self._spec.input_format == "mjpeg":
                src_caps.set_property(
                    "caps",
                    Gst.Caps.from_string(
                        f"image/jpeg,width={self._spec.width},"
                        f"height={self._spec.height},framerate={self._fps}/1"
                    ),
                )
            else:
                pix_fmt = self._spec.pixel_format or "YUY2"
                src_caps.set_property(
                    "caps",
                    Gst.Caps.from_string(
                        f"video/x-raw,format={pix_fmt},width={self._spec.width},"
                        f"height={self._spec.height},framerate={self._fps}/1"
                    ),
                )

            watchdog = Gst.ElementFactory.make("watchdog", f"watchdog_{self._role_safe}")
            if watchdog is None:
                raise RuntimeError(f"{self._spec.role}: watchdog element missing")
            watchdog.set_property("timeout", 2000)  # ms

            decoder: Any = None
            # Delta 2026-04-14-camera-pipeline-systematic-walk finding F1:
            # decouple JPEG decode latency from v4l2 capture via a small
            # upstream queue. Without this, a decode stall backpressures
            # directly into v4l2src and the kernel's uvcvideo buffer queue
            # exhausts, silently dropping frames at the kernel layer
            # (``studio_camera_kernel_drops_total`` is the drop #2 false-zero
            # for MJPG and won't surface the loss). A 1-element leaky queue
            # absorbs short decode stalls without adding perceptible
            # latency: 1 frame at 30fps is 33 ms, well under the
            # STALENESS_THRESHOLD_S=2.0 window. ``leaky=downstream`` so
            # back-pressure on the decoder still drops frames at the
            # queue, not at v4l2.
            decode_queue: Any = None
            if self._spec.input_format == "mjpeg":
                decode_queue = Gst.ElementFactory.make("queue", f"decq_{self._role_safe}")
                if decode_queue is None:
                    raise RuntimeError(f"{self._spec.role}: queue factory failed")
                # Drop #31 cam-stability rollup Ring 2 fix C: bump from 1 to
                # 5 buffers. The original 1-buffer queue could only absorb
                # a single stalled jpegdec frame; brio-operator's drop #2
                # H6 (CPU jpegdec back-pressure) needed more cushion.
                # 5 buffers × 33 ms = 165 ms of decode-stall absorption,
                # still well under the 2 s STALENESS_THRESHOLD_S window.
                # leaky=downstream keeps the queue fresh — old frames are
                # dropped first so the queue never grows unbounded under
                # sustained back-pressure.
                decode_queue.set_property("max-size-buffers", 5)
                decode_queue.set_property("max-size-bytes", 0)
                decode_queue.set_property("max-size-time", 0)
                decode_queue.set_property("leaky", 2)  # downstream

                # A+ Stage 1 (2026-04-17) attempt reverted: nvjpegdec
                # outputs `video/x-raw(memory:CUDAMemory)` which does not
                # negotiate with the downstream CPU `videoconvert`, and
                # v4l2src → nvjpegdec fails with error (-5) across all 6
                # cameras in under 2 seconds. Re-enabling hardware MJPEG
                # decode requires a caps-compatible downstream path
                # (cudadownload → videoconvert, or a full NVMM path
                # through cudacompositor). Deferred to Stage 2 under
                # the broader GPU-memory-throughout rebuild. Force
                # software jpegdec for now.
                decoder = Gst.ElementFactory.make("jpegdec", f"dec_{self._role_safe}")
                if decoder is None:
                    raise RuntimeError(f"{self._spec.role}: jpegdec factory failed")

            convert = Gst.ElementFactory.make("videoconvert", f"vc_{self._role_safe}")
            convert.set_property("dither", 0)

            out_caps = Gst.ElementFactory.make("capsfilter", f"outcaps_{self._role_safe}")
            out_caps.set_property(
                "caps",
                Gst.Caps.from_string(
                    f"video/x-raw,format=NV12,width={self._spec.width},"
                    f"height={self._spec.height},framerate={self._fps}/1"
                ),
            )

            sink = Gst.ElementFactory.make("interpipesink", self._sink_name)
            if sink is None:
                raise RuntimeError(
                    f"{self._spec.role}: interpipesink factory failed — "
                    "install gst-plugin-interpipe"
                )
            sink.set_property("sync", False)
            sink.set_property("async", False)
            sink.set_property("forward-events", False)
            sink.set_property("forward-eos", False)

            elements = [src, src_caps, watchdog]
            if decode_queue is not None:
                elements.append(decode_queue)
            if decoder is not None:
                elements.append(decoder)
            elements.extend([convert, out_caps, sink])

            for el in elements:
                pipeline.add(el)

            for i in range(len(elements) - 1):
                if not elements[i].link(elements[i + 1]):
                    raise RuntimeError(
                        f"{self._spec.role}: failed to link "
                        f"{elements[i].get_name()} -> {elements[i + 1].get_name()}"
                    )

            # Frame-flow observation: a pad probe on the interpipesink sink pad
            # updates the monotonic timestamp on every buffer. Used by Phase 4
            # metrics exporter and by the Type=notify watchdog.
            sink_pad = sink.get_static_pad("sink")
            if sink_pad is not None:
                sink_pad.add_probe(Gst.PadProbeType.BUFFER, self._on_buffer_probe)

            self._pipeline = pipeline
            self._bus = pipeline.get_bus()
            self._bus.add_signal_watch()
            self._bus_signal_id = self._bus.connect("message", self._on_bus_message)

            log.info(
                "camera_pipeline %s built (device=%s, %dx%d@%dfps, format=%s)",
                self._spec.role,
                self._spec.device,
                self._spec.width,
                self._spec.height,
                self._fps,
                self._spec.input_format,
            )

    def start(self) -> bool:
        """Transition to PLAYING. Returns False on failure."""
        with self._state_lock:
            if self._pipeline is None:
                log.error("camera_pipeline %s: start called without build", self._spec.role)
                return False

            if self._is_http_jpeg_source():
                if not self._http_source_reachable():
                    log.warning(
                        "camera_pipeline %s: HTTP JPEG source %s not reachable, deferring start",
                        self._spec.role,
                        self._spec.device,
                    )
                    return False
            elif not Path(self._spec.device).exists():
                log.warning(
                    "camera_pipeline %s: device %s not present, deferring start",
                    self._spec.role,
                    self._spec.device,
                )
                return False

            Gst = self._Gst
            self.clear_frame_observation()
            ret = self._pipeline.set_state(Gst.State.PLAYING)
            if ret == Gst.StateChangeReturn.FAILURE:
                log.error("camera_pipeline %s: set_state(PLAYING) FAILURE", self._spec.role)
                return False
            self._started = True
            if self._is_http_jpeg_source():
                self._start_http_push_thread()
            log.info(
                "camera_pipeline %s started (state change=%s)", self._spec.role, ret.value_nick
            )
            return True

    def stop(self) -> None:
        """Transition to NULL. Idempotent.

        Waits for the NULL transition to complete. Without this, fast
        rebuild cycles interrupt GStreamer's async cleanup before
        v4l2src's buffer pool releases its dmabuf handles, leaking fds
        at ~150/min under a rebuild-thrash fault. See drop #52.
        """
        with self._state_lock:
            if self._pipeline is None:
                return
            Gst = self._Gst
            self._stop_http_push_thread()
            self._pipeline.set_state(Gst.State.NULL)
            teardown_start = time.monotonic()
            ret, state, pending = self._pipeline.get_state(timeout=5 * Gst.SECOND)
            teardown_ms = (time.monotonic() - teardown_start) * 1000.0
            # Drop #52 FDL-4: observe the NULL-transition wall-clock. Normal
            # teardowns finish in <100 ms; long tails mean v4l2/CUDA cleanup
            # is blocking, which is what makes rebuild-thrash costly.
            try:
                from . import metrics as _metrics

                if _metrics.COMP_PIPELINE_TEARDOWN_DURATION_MS is not None:
                    _metrics.COMP_PIPELINE_TEARDOWN_DURATION_MS.labels(
                        role=self._spec.role
                    ).observe(teardown_ms)
            except Exception:
                log.debug("teardown duration histogram observe failed", exc_info=True)
            if ret == Gst.StateChangeReturn.FAILURE:
                log.warning(
                    "camera_pipeline %s: NULL transition failed, resources may leak",
                    self._spec.role,
                )
            elif state != Gst.State.NULL:
                log.warning(
                    "camera_pipeline %s: NULL transition timed out at state=%s pending=%s",
                    self._spec.role,
                    state.value_nick,
                    pending.value_nick if pending else "?",
                )
            self._started = False

    def _is_http_jpeg_source(self) -> bool:
        device = str(getattr(self._spec, "device", "") or "")
        return getattr(self._spec, "input_format", "") == "http_jpeg" or device.startswith(
            ("http://", "https://")
        )

    def _is_v4l2loopback_source(self) -> bool:
        device = str(getattr(self._spec, "device", "") or "")
        if not device.startswith("/dev/video"):
            return False
        name_path = Path("/sys/class/video4linux") / Path(device).name / "name"
        try:
            name = name_path.read_text(encoding="utf-8").strip().lower()
        except OSError:
            return False
        return "v4l2loopback" in name or name.startswith(
            ("hapax-rtsp-", "studiocompositor", "youtube")
        )

    def _buffer_allocation_error_context(self) -> str:
        if self._is_v4l2loopback_source():
            return (
                "v4l2 loopback producer stopped, starved, or changed format mid-read "
                "(kernel -ENODEV; GStreamer surfaced this as 'Failed to allocate a buffer' "
                "— not an OOM). Check the upstream RTSP/loopback producer for this role; "
                "reconnect supervisor will retry."
            )
        return (
            "v4l2 device vanished mid-read (kernel -ENODEV; GStreamer surfaced this as "
            "'Failed to allocate a buffer' — not an OOM). USB bus-kick or cable disconnect "
            "— reconnect supervisor will retry."
        )

    def _effective_http_fps(self) -> float:
        raw = os.environ.get("HAPAX_HTTP_JPEG_CAMERA_FPS", "10")
        try:
            value = float(raw)
        except ValueError:
            log.warning("Invalid HAPAX_HTTP_JPEG_CAMERA_FPS=%r; using 10", raw)
            value = 10.0
        return max(1.0, min(float(self._fps), value))

    def _http_timeout_s(self) -> float:
        raw = os.environ.get("HAPAX_HTTP_JPEG_CAMERA_TIMEOUT_S", "1.0")
        try:
            return max(0.1, float(raw))
        except ValueError:
            log.warning("Invalid HAPAX_HTTP_JPEG_CAMERA_TIMEOUT_S=%r; using 1.0", raw)
            return 1.0

    def _build_http_jpeg_pipeline(self) -> None:
        Gst = self._Gst
        pipeline = Gst.Pipeline.new(self._pipeline_name)

        src = Gst.ElementFactory.make("appsrc", f"src_{self._role_safe}")
        if src is None:
            raise RuntimeError(f"{self._spec.role}: appsrc factory failed")
        src.set_property("is-live", True)
        src.set_property("format", Gst.Format.TIME)
        src.set_property("do-timestamp", True)
        src.set_property("block", False)
        # Advertise the compositor cadence even though the fetch loop may
        # push repeated/stale frames more slowly. Some downstream elements
        # treat the source caps as the branch contract; using the reduced
        # HTTP fetch rate here caused IR producer negotiation churn.
        src.set_property(
            "caps",
            Gst.Caps.from_string(f"image/jpeg,framerate={self._fps}/1"),
        )

        src_caps = Gst.ElementFactory.make("capsfilter", f"srccaps_{self._role_safe}")
        if src_caps is None:
            raise RuntimeError(f"{self._spec.role}: capsfilter factory failed")
        src_caps.set_property("caps", Gst.Caps.from_string(f"image/jpeg,framerate={self._fps}/1"))

        watchdog = Gst.ElementFactory.make("watchdog", f"watchdog_{self._role_safe}")
        if watchdog is None:
            raise RuntimeError(f"{self._spec.role}: watchdog element missing")
        watchdog.set_property("timeout", 2500)

        decode_queue = Gst.ElementFactory.make("queue", f"decq_{self._role_safe}")
        if decode_queue is None:
            raise RuntimeError(f"{self._spec.role}: queue factory failed")
        decode_queue.set_property("max-size-buffers", 5)
        decode_queue.set_property("max-size-bytes", 0)
        decode_queue.set_property("max-size-time", 0)
        decode_queue.set_property("leaky", 2)

        jpegparse = Gst.ElementFactory.make("jpegparse", f"parse_{self._role_safe}")
        decoder = Gst.ElementFactory.make("jpegdec", f"dec_{self._role_safe}")
        if decoder is None:
            raise RuntimeError(f"{self._spec.role}: jpegdec factory failed")

        convert = Gst.ElementFactory.make("videoconvert", f"vc_{self._role_safe}")
        if convert is None:
            raise RuntimeError(f"{self._spec.role}: videoconvert factory failed")
        convert.set_property("dither", 0)

        scale = Gst.ElementFactory.make("videoscale", f"scale_{self._role_safe}")
        if scale is None:
            raise RuntimeError(f"{self._spec.role}: videoscale factory failed")

        out_caps = Gst.ElementFactory.make("capsfilter", f"outcaps_{self._role_safe}")
        if out_caps is None:
            raise RuntimeError(f"{self._spec.role}: output capsfilter factory failed")
        out_caps.set_property(
            "caps",
            Gst.Caps.from_string(
                f"video/x-raw,format=NV12,width={self._spec.width},"
                f"height={self._spec.height},framerate={self._fps}/1"
            ),
        )

        sink = Gst.ElementFactory.make("interpipesink", self._sink_name)
        if sink is None:
            raise RuntimeError(
                f"{self._spec.role}: interpipesink factory failed — install gst-plugin-interpipe"
            )
        sink.set_property("sync", False)
        sink.set_property("async", False)
        sink.set_property("forward-events", False)
        sink.set_property("forward-eos", False)

        elements = [src, src_caps, watchdog, decode_queue]
        if jpegparse is not None:
            elements.append(jpegparse)
        elements.extend([decoder, convert, scale, out_caps, sink])

        for el in elements:
            pipeline.add(el)
        for i in range(len(elements) - 1):
            if not elements[i].link(elements[i + 1]):
                raise RuntimeError(
                    f"{self._spec.role}: failed to link "
                    f"{elements[i].get_name()} -> {elements[i + 1].get_name()}"
                )

        sink_pad = sink.get_static_pad("sink")
        if sink_pad is not None:
            sink_pad.add_probe(Gst.PadProbeType.BUFFER, self._on_buffer_probe)

        self._http_appsrc = src
        self._pipeline = pipeline
        self._bus = pipeline.get_bus()
        self._bus.add_signal_watch()
        self._bus_signal_id = self._bus.connect("message", self._on_bus_message)

        log.info(
            "camera_pipeline %s built (http_jpeg=%s, %dx%d@%dfps, fetch=%.1ffps)",
            self._spec.role,
            self._spec.device,
            self._spec.width,
            self._spec.height,
            self._fps,
            self._effective_http_fps(),
        )

    def _http_source_reachable(self) -> bool:
        try:
            req = urllib_request.Request(
                str(self._spec.device),
                headers={"User-Agent": "hapax-studio-compositor/1.0"},
            )
            with urllib_request.urlopen(req, timeout=self._http_timeout_s()) as response:
                return 200 <= int(getattr(response, "status", 200)) < 400
        except (OSError, urllib_error.URLError, TimeoutError):
            return False

    def _start_http_push_thread(self) -> None:
        if self._http_appsrc is None:
            return
        if self._http_thread is not None and self._http_thread.is_alive():
            return
        self._http_stop_event.clear()
        self._http_thread = threading.Thread(
            target=self._http_push_loop,
            name=f"http-jpeg-{self._role_safe}",
            daemon=True,
        )
        self._http_thread.start()

    def _stop_http_push_thread(self) -> None:
        self._http_stop_event.set()
        appsrc = self._http_appsrc
        if appsrc is not None:
            try:
                appsrc.emit("end-of-stream")
            except Exception:
                log.debug("camera_pipeline %s: appsrc EOS failed", self._spec.role, exc_info=True)
        thread = self._http_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        self._http_thread = None

    def _http_fetch_frame(self) -> bytes | None:
        try:
            req = urllib_request.Request(
                str(self._spec.device),
                headers={"User-Agent": "hapax-studio-compositor/1.0"},
            )
            with urllib_request.urlopen(req, timeout=self._http_timeout_s()) as response:
                status = int(getattr(response, "status", 200))
                if not 200 <= status < 400:
                    return None
                data = response.read()
        except (OSError, urllib_error.URLError, TimeoutError):
            return None
        if not data:
            return None
        return data

    def _http_push_loop(self) -> None:
        Gst = self._Gst
        appsrc = self._http_appsrc
        if appsrc is None:
            return
        frame_index = 0
        last_good: bytes | None = None
        interval = 1.0 / self._effective_http_fps()
        duration_ns = int(interval * Gst.SECOND)
        while not self._http_stop_event.is_set():
            loop_start = time.monotonic()
            frame = self._http_fetch_frame()
            if frame is not None:
                last_good = frame
            elif last_good is None:
                self._http_stop_event.wait(min(interval, 0.25))
                continue
            else:
                frame = last_good

            buf = Gst.Buffer.new_allocate(None, len(frame), None)
            buf.fill(0, frame)
            buf.pts = frame_index * duration_ns
            buf.dts = buf.pts
            buf.duration = duration_ns
            frame_index += 1
            try:
                ret = appsrc.emit("push-buffer", buf)
            except Exception:
                log.debug("camera_pipeline %s: appsrc push raised", self._spec.role, exc_info=True)
                break
            if ret != Gst.FlowReturn.OK:
                log.debug("camera_pipeline %s: appsrc push returned %s", self._spec.role, ret)
                break

            elapsed = time.monotonic() - loop_start
            self._http_stop_event.wait(max(0.0, interval - elapsed))

    def teardown(self) -> None:
        """Full teardown: NULL + bus disconnect + element release. Idempotent."""
        with self._state_lock:
            if self._pipeline is None:
                return
            self.stop()
            if self._bus is not None and self._bus_signal_id:
                try:
                    self._bus.disconnect(self._bus_signal_id)
                except (TypeError, ValueError):
                    pass
                self._bus_signal_id = 0
                try:
                    self._bus.remove_signal_watch()
                except (TypeError, ValueError):
                    pass
            self._bus = None
            self._pipeline = None

    def rebuild(self) -> bool:
        """Teardown and rebuild from scratch. Returns True on successful restart."""
        with self._state_lock:
            self._rebuild_count += 1
            # Drop #52 FDL-3: cumulative rebuild counter per role.
            # Rate spikes are the signature of rebuild-thrash faults
            # (drop #51 root cause). Alert candidate: rate >5/min/role.
            try:
                from . import metrics as _metrics

                if _metrics.COMP_CAMERA_REBUILD_TOTAL is not None:
                    _metrics.COMP_CAMERA_REBUILD_TOTAL.labels(role=self._spec.role).inc()
            except Exception:
                log.debug("rebuild counter inc failed", exc_info=True)
            self.teardown()
            try:
                self.build()
            except Exception:
                log.exception("camera_pipeline %s: rebuild build() failed", self._spec.role)
                return False
            return self.start()

    def is_playing(self) -> bool:
        with self._state_lock:
            if self._pipeline is None:
                return False
            Gst = self._Gst
            _, current, _ = self._pipeline.get_state(timeout=0)
            return current == Gst.State.PLAYING

    # A+ Stage 3 (2026-04-17): sample one frame every N ticks into the
    # last-good-frame cache so the fallback pipeline can render that
    # frame instead of a black card when the primary drops.
    #
    # 2026-05-05: reduced from 15 (2 Hz at 30fps) to 3 (10 Hz at 30fps).
    # The PackedCamerasCairoSource renders at 6fps and reuses cached
    # surfaces when id(frame.data) hasn't changed. At 2 Hz, 4 out of 6
    # render ticks showed stale content; the glfeedback shader chain's
    # temporal feedback accumulated the slow-updating tiles into visible
    # horizontal banding on the livestream. 10 Hz keeps the cache fresh
    # relative to the 6fps runner cadence. Cost: ~1.4 MiB NV12 copy
    # ×10/sec/camera = ~14 MiB/s/camera bandwidth — negligible on tmpfs.
    _FRAME_CACHE_SAMPLE_EVERY_N = 3

    def _on_buffer_probe(self, pad: Any, info: Any) -> Any:
        """GStreamer pad probe: note frame arrival, update Phase 4 metrics,
        sample into last-good-frame cache, passthrough."""
        self._last_frame_monotonic = time.monotonic()
        try:
            from . import metrics

            metrics.pad_probe_on_buffer(pad, info, self._spec.role)
        except Exception:
            log.exception("camera_pipeline %s: metrics pad probe raised", self._spec.role)
        # A+ Stage 3: freeze-frame snapshot. Sampling counter lives on
        # the instance so the cost is per-camera (no dict contention).
        self._frame_cache_tick = getattr(self, "_frame_cache_tick", 0) + 1
        if self._frame_cache_tick >= self._FRAME_CACHE_SAMPLE_EVERY_N:
            self._frame_cache_tick = 0
            try:
                self._snapshot_into_frame_cache(info)
            except Exception:
                log.debug(
                    "camera_pipeline %s: frame cache snapshot raised",
                    self._spec.role,
                    exc_info=True,
                )
        if self._on_frame is not None:
            try:
                self._on_frame()
            except Exception:
                log.exception("camera_pipeline %s: on_frame callback raised", self._spec.role)
        return self._Gst.PadProbeReturn.OK

    def _snapshot_into_frame_cache(self, info: Any) -> None:
        """Copy the current NV12 buffer into ``frame_cache`` under this role.

        Called from the pad probe every 15 frames. Maps the buffer for
        read, copies into a ``bytes`` object, stores in the cache, and
        unmaps. Never holds a reference to the GstBuffer memory across
        the call.
        """
        if info is None:
            return
        buf = info.get_buffer()
        if buf is None:
            return
        Gst = self._Gst
        ok, map_info = buf.map(Gst.MapFlags.READ)
        if not ok:
            return
        try:
            from . import frame_cache

            frame_cache.update(
                role=self._spec.role,
                data=map_info.data,
                width=self._spec.width,
                height=self._spec.height,
                fmt="NV12",
            )
        finally:
            buf.unmap(map_info)

    def _on_bus_message(self, bus: Any, message: Any) -> bool:
        """Handle bus messages scoped to this producer pipeline only."""
        Gst = self._Gst
        t = message.type
        if t == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            src = message.src.get_name() if message.src else "unknown"
            # Queue 023 item #35: the v4l2src element surfaces
            # ``-ENODEV`` (USB bus-kick / device vanished mid-read) as the
            # GStreamer-generic "Failed to allocate a buffer" message,
            # which reads as an OOM and is actively misleading. Rewrite
            # the log line to name the underlying condition so the
            # operator does not hunt for a memory leak. The upstream
            # message is preserved in the debug field for forensics.
            message_text = err.message
            if "Failed to allocate a buffer" in message_text:
                message_text = self._buffer_allocation_error_context()
            log.error(
                "camera_pipeline %s error (element=%s): %s (debug=%s)",
                self._spec.role,
                src,
                message_text,
                debug,
            )
            if self._on_error is not None:
                try:
                    self._on_error(self._spec.role, err.message)
                except Exception:
                    log.exception("camera_pipeline %s: on_error callback raised", self._spec.role)
        elif t == Gst.MessageType.WARNING:
            err, debug = message.parse_warning()
            log.warning(
                "camera_pipeline %s warning: %s (debug=%s)",
                self._spec.role,
                err.message,
                debug,
            )
        return True

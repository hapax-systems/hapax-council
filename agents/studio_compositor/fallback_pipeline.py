"""Synthetic fallback producer GstPipeline per camera.

See docs/superpowers/specs/2026-04-12-compositor-hot-swap-architecture-design.md

Each camera has a paired FallbackPipeline that always runs. When the primary
camera goes offline, PipelineManager flips the composite's interpipesrc
listen-to property from `cam_<role>` to `fb_<role>` and the fallback frames
feed the composite slot instantly (no state change, no caps renegotiation
since the fallback emits matching NV12 caps).

The fallback uses `videotestsrc pattern=ball` (bouncing ball) rather than
`pattern=smpte` (SMPTE bars) because the bouncing ball is immediately
recognizable as "no camera here" while SMPTE bars look plausible as a
valid broadcast frame.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from .gst_appsrc_limits import configure_live_appsrc_queue
from .models import CameraSpec

log = logging.getLogger(__name__)


class FallbackPipeline:
    """Always-running videotestsrc producer for a given camera slot.

    Graph:
        videotestsrc pattern=ball is-live=true
          ! video/x-raw,format=BGRA,width=W,height=H,framerate=F/1
          ! textoverlay text="CAMERA <ROLE> OFFLINE" ...
          ! videoconvert
          ! video/x-raw,format=NV12,width=W,height=H,framerate=F/1
          ! interpipesink name=fb_<role>
    """

    # A+ Stage 0 (2026-04-17): fallback producer framerate. The primary
    # pipeline runs at 30fps (compositor canvas rate); the fallback is a
    # static "CAMERA X OFFLINE" card with a bouncing ball that no one sees
    # while the primary is healthy. Running it at 1fps saves ~20-25% CPU
    # across all 6 fallback producers (8 fbsrc_*/queue threads at
    # 24-35% CPU each in the thread dump) without perceptibly degrading
    # swap-to-fallback latency (interpipesrc stream-sync=restart-ts
    # handles the timestamp jump).
    FALLBACK_FPS = 1

    def __init__(self, spec: CameraSpec, *, gst: Any, fps: int) -> None:
        self._spec = spec
        self._Gst = gst
        # Accept the primary fps for API compatibility but clamp fallback
        # to FALLBACK_FPS — the primary pipeline's cadence is independent.
        self._fps = min(fps, self.FALLBACK_FPS)

        self._role_safe = spec.role.replace("-", "_")
        self._sink_name = f"fb_{self._role_safe}"
        self._pipeline_name = f"fallback_pipeline_{self._role_safe}"

        self._pipeline: Any = None
        self._state_lock = threading.RLock()

    @property
    def role(self) -> str:
        return self._spec.role

    @property
    def sink_name(self) -> str:
        return self._sink_name

    def build(self) -> None:
        with self._state_lock:
            if self._pipeline is not None:
                return
            Gst = self._Gst
            pipeline = Gst.Pipeline.new(self._pipeline_name)

            # A+ Stage 3 (2026-04-17): freeze-frame-capable fallback.
            # appsrc replaces videotestsrc + videoconvert. A Python
            # thread pushes NV12 buffers to the appsrc at FALLBACK_FPS
            # (1Hz), choosing each tick between (a) the last-good frame
            # from frame_cache[role] — ATEM/vMix freeze-frame UX, and
            # (b) a pre-baked black NV12 buffer if the cache is empty.
            # No colorspace conversion in the hot path; appsrc emits
            # NV12 directly, matching the interpipesink caps.
            # Override via HAPAX_FALLBACK_FREEZE_FRAME=0 to force the
            # legacy black-only behavior.
            import os as _os

            self._freeze_frame_enabled = _os.environ.get("HAPAX_FALLBACK_FREEZE_FRAME", "1") == "1"

            src = Gst.ElementFactory.make("appsrc", f"fbsrc_{self._role_safe}")
            if src is None:
                raise RuntimeError(f"{self._spec.role}: appsrc factory failed")
            src.set_property("is-live", True)
            src.set_property("format", 3)  # TIME
            src.set_property("do-timestamp", True)
            src.set_property("block", False)
            configure_live_appsrc_queue(src)
            src.set_property(
                "caps",
                Gst.Caps.from_string(
                    f"video/x-raw,format=NV12,width={self._spec.width},"
                    f"height={self._spec.height},framerate={self._fps}/1"
                ),
            )

            out_caps = Gst.ElementFactory.make("capsfilter", f"fbcaps_{self._role_safe}")
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

            self._appsrc = src
            self._push_thread: threading.Thread | None = None
            self._push_stop = threading.Event()
            # Pre-bake a black NV12 buffer at this camera's dimensions.
            # NV12 = Y plane (w*h bytes of 0x10 = luma black) + UV plane
            # (w*h/2 bytes of 0x80 = neutral chroma). Zero-bytes is
            # sufficient for "visually black" in most decoders and
            # matches what videotestsrc pattern=black would have emitted.
            y_size = self._spec.width * self._spec.height
            uv_size = y_size // 2
            self._black_nv12 = bytes(y_size + uv_size)

            elements = [src, out_caps, sink]

            for el in elements:
                pipeline.add(el)
            for i in range(len(elements) - 1):
                if not elements[i].link(elements[i + 1]):
                    raise RuntimeError(
                        f"{self._spec.role}: fallback link "
                        f"{elements[i].get_name()} -> {elements[i + 1].get_name()} failed"
                    )

            self._pipeline = pipeline
            log.info("fallback_pipeline %s built (sink=%s)", self._spec.role, self._sink_name)

    def start(self) -> bool:
        with self._state_lock:
            if self._pipeline is None:
                return False
            Gst = self._Gst
            ret = self._pipeline.set_state(Gst.State.PLAYING)
            if ret == Gst.StateChangeReturn.FAILURE:
                return False
            # A+ Stage 3: spawn the freeze-frame push thread on first
            # start. Idempotent — stop() joins it before returning to
            # NULL so calling start() again restarts the thread cleanly.
            if self._push_thread is None or not self._push_thread.is_alive():
                self._push_stop.clear()
                self._push_thread = threading.Thread(
                    target=self._push_loop,
                    daemon=True,
                    name=f"fb-push-{self._role_safe}",
                )
                self._push_thread.start()
            return True

    def stop(self) -> None:
        with self._state_lock:
            if self._pipeline is None:
                return
            # Stop the push thread before NULLing the pipeline so appsrc
            # doesn't receive pushes mid-teardown.
            self._push_stop.set()
            thread = self._push_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        with self._state_lock:
            Gst = self._Gst
            self._pipeline.set_state(Gst.State.NULL)

    def _push_loop(self) -> None:
        """A+ Stage 3: push one NV12 buffer per tick to the appsrc.

        Emits the last-good frame from ``frame_cache`` if available;
        otherwise emits the pre-baked black NV12 buffer. Runs at
        FALLBACK_FPS (1 Hz by default) so even the most conservative
        visual refresh is <= 1 second of staleness.
        """
        from . import frame_cache

        Gst = self._Gst
        duration_ns = int(1_000_000_000 / self._fps)
        pts = 0
        while not self._push_stop.is_set():
            data: bytes
            if self._freeze_frame_enabled:
                cached = frame_cache.get(self._spec.role)
                if (
                    cached is not None
                    and cached.format == "NV12"
                    and (cached.width == self._spec.width and cached.height == self._spec.height)
                ):
                    data = cached.data
                else:
                    data = self._black_nv12
            else:
                data = self._black_nv12
            try:
                buf = Gst.Buffer.new_wrapped(data)
                buf.pts = pts
                buf.duration = duration_ns
                pts += duration_ns
                ret = self._appsrc.emit("push-buffer", buf)
                if ret != Gst.FlowReturn.OK:
                    # Pipeline tearing down (FLUSHING) or appsrc paused —
                    # back off briefly and let the stop flag end the loop.
                    self._push_stop.wait(0.5)
                    continue
            except Exception:
                log.debug(
                    "fallback_pipeline %s push failed; will retry",
                    self._spec.role,
                    exc_info=True,
                )
            # Wait for the next tick OR an early wakeup from stop().
            self._push_stop.wait(1.0 / self._fps)

    def teardown(self) -> None:
        with self._state_lock:
            self.stop()
            self._pipeline = None

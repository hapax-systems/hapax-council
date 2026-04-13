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

    def __init__(self, spec: CameraSpec, *, gst: Any, fps: int) -> None:
        self._spec = spec
        self._Gst = gst
        self._fps = fps

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

            src = Gst.ElementFactory.make("videotestsrc", f"fbsrc_{self._role_safe}")
            if src is None:
                raise RuntimeError(f"{self._spec.role}: videotestsrc factory failed")
            src.set_property("pattern", 18)  # ball — recognizable as non-camera
            src.set_property("is-live", True)

            raw_caps = Gst.ElementFactory.make("capsfilter", f"fbrawcaps_{self._role_safe}")
            raw_caps.set_property(
                "caps",
                Gst.Caps.from_string(
                    f"video/x-raw,format=BGRA,width={self._spec.width},"
                    f"height={self._spec.height},framerate={self._fps}/1"
                ),
            )

            overlay = Gst.ElementFactory.make("textoverlay", f"fbtext_{self._role_safe}")
            role_up = self._spec.role.upper().replace("-", " ")
            if overlay is not None:
                overlay.set_property("text", f"CAMERA {role_up} OFFLINE")
                overlay.set_property("font-desc", "Sans Bold 60")
                overlay.set_property("halignment", 1)  # center
                overlay.set_property("valignment", 4)  # center
                overlay.set_property("line-alignment", 1)  # center
                overlay.set_property("shaded-background", True)

            convert = Gst.ElementFactory.make("videoconvert", f"fbconv_{self._role_safe}")
            convert.set_property("dither", 0)

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

            elements = [src, raw_caps]
            if overlay is not None:
                elements.append(overlay)
            elements.extend([convert, out_caps, sink])

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
            return ret != Gst.StateChangeReturn.FAILURE

    def stop(self) -> None:
        with self._state_lock:
            if self._pipeline is None:
                return
            Gst = self._Gst
            self._pipeline.set_state(Gst.State.NULL)

    def teardown(self) -> None:
        with self._state_lock:
            self.stop()
            self._pipeline = None

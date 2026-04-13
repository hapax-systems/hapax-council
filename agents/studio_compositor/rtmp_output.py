"""Native GStreamer RTMP output bin — Phase 5 of the camera 24/7 resilience epic.

Closes epic A7 (eliminate OBS as the RTMP encoder).

See docs/superpowers/specs/2026-04-12-native-rtmp-delivery-design.md

The RTMP bin is a detachable GstBin attached to the composite pipeline's
output tee via a request pad. On NVENC or rtmp2sink errors, the bin is
torn down and rebuilt in place without disturbing the rest of the pipeline.
Encoder errors are bounded to this bin via src-name filtering in the
composite pipeline's bus message handler.

Default topology:

    tee → queue → videoconvert → nvh264enc → h264parse →
        flvmux name=mux ← aacparse ← voaacenc ← audioconvert ← pipewiresrc
    mux → rtmp2sink location=rtmp://127.0.0.1:1935/studio

All elements are named with a `rtmp_` prefix so the bus message handler
can route errors back to this bin without affecting other pipeline errors.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

log = logging.getLogger(__name__)


class RtmpOutputBin:
    """Detachable RTMP encoder bin for the studio compositor."""

    def __init__(
        self,
        *,
        gst: Any,
        video_tee: Any,
        rtmp_location: str = "rtmp://127.0.0.1:1935/studio",
        bitrate_kbps: int = 6000,
        gop_size: int = 60,
        audio_target: str | None = None,
    ) -> None:
        self._Gst = gst
        self._video_tee = video_tee
        self._rtmp_location = rtmp_location
        self._bitrate_kbps = bitrate_kbps
        self._gop_size = gop_size
        self._audio_target = audio_target

        self._bin: Any = None
        self._video_tee_pad: Any = None
        self._state_lock = threading.RLock()
        self._rebuild_count = 0

    @property
    def rebuild_count(self) -> int:
        with self._state_lock:
            return self._rebuild_count

    def is_attached(self) -> bool:
        with self._state_lock:
            return self._bin is not None

    def build_and_attach(self, composite_pipeline: Any) -> bool:
        """Construct the bin and attach it to the composite tee."""
        with self._state_lock:
            if self._bin is not None:
                log.info("rtmp bin already attached")
                return True

            Gst = self._Gst
            bin_ = Gst.Bin.new("rtmp_output_bin")

            # --- Video path ---
            video_queue = Gst.ElementFactory.make("queue", "rtmp_video_queue")
            if video_queue is None:
                log.error("rtmp bin: queue factory failed")
                return False
            video_queue.set_property("max-size-buffers", 30)
            video_queue.set_property("max-size-time", 2 * Gst.SECOND)
            video_queue.set_property("leaky", 2)  # downstream

            video_convert = Gst.ElementFactory.make("videoconvert", "rtmp_video_convert")
            if video_convert is None:
                log.error("rtmp bin: videoconvert factory failed")
                return False

            encoder = Gst.ElementFactory.make("nvh264enc", "rtmp_nvh264enc")
            if encoder is None:
                log.error("rtmp bin: nvh264enc factory failed")
                return False
            encoder.set_property("bitrate", self._bitrate_kbps)
            encoder.set_property("rc-mode", 2)  # 2 = cbr
            encoder.set_property("gop-size", self._gop_size)
            encoder.set_property("zerolatency", True)
            encoder.set_property("preset", 11)  # 11 = p4 medium
            encoder.set_property("tune", 2)  # 2 = low-latency

            h264_parse = Gst.ElementFactory.make("h264parse", "rtmp_h264parse")
            if h264_parse is None:
                log.error("rtmp bin: h264parse factory failed")
                return False
            h264_parse.set_property("config-interval", -1)

            # --- Audio path ---
            audio_src = Gst.ElementFactory.make("pipewiresrc", "rtmp_audio_src")
            if audio_src is None:
                log.warning("rtmp bin: pipewiresrc unavailable, falling back to audiotestsrc")
                audio_src = Gst.ElementFactory.make("audiotestsrc", "rtmp_audio_src")
                if audio_src is not None:
                    audio_src.set_property("is-live", True)
                    audio_src.set_property("wave", 4)  # silence
            elif self._audio_target:
                audio_src.set_property("target-object", self._audio_target)

            if audio_src is None:
                log.error("rtmp bin: no audio source element available")
                return False

            audio_convert = Gst.ElementFactory.make("audioconvert", "rtmp_audio_convert")
            audio_resample = Gst.ElementFactory.make("audioresample", "rtmp_audio_resample")
            audio_caps = Gst.ElementFactory.make("capsfilter", "rtmp_audio_caps")
            audio_caps.set_property(
                "caps",
                Gst.Caps.from_string("audio/x-raw,rate=48000,channels=2,format=S16LE"),
            )

            audio_encoder = Gst.ElementFactory.make("voaacenc", "rtmp_voaacenc")
            if audio_encoder is None:
                log.warning("rtmp bin: voaacenc unavailable, trying avenc_aac")
                audio_encoder = Gst.ElementFactory.make("avenc_aac", "rtmp_voaacenc")
            if audio_encoder is None:
                log.error("rtmp bin: no AAC encoder available")
                return False
            if hasattr(audio_encoder.props, "bitrate"):
                audio_encoder.set_property("bitrate", 128000)

            aac_parse = Gst.ElementFactory.make("aacparse", "rtmp_aacparse")

            # --- Mux + sink ---
            mux = Gst.ElementFactory.make("flvmux", "rtmp_flvmux")
            if mux is None:
                log.error("rtmp bin: flvmux factory failed")
                return False
            mux.set_property("streamable", True)
            mux.set_property("latency", 100_000_000)  # 100 ms

            sink = Gst.ElementFactory.make("rtmp2sink", "rtmp_sink")
            if sink is None:
                log.warning("rtmp bin: rtmp2sink unavailable, falling back to rtmpsink")
                sink = Gst.ElementFactory.make("rtmpsink", "rtmp_sink")
            if sink is None:
                log.error("rtmp bin: no RTMP sink available")
                return False
            sink.set_property("location", self._rtmp_location)
            sink.set_property("async-connect", True)

            # --- Add elements + link ---
            elements = [
                video_queue,
                video_convert,
                encoder,
                h264_parse,
                audio_src,
                audio_convert,
                audio_resample,
                audio_caps,
                audio_encoder,
                aac_parse,
                mux,
                sink,
            ]
            for el in elements:
                bin_.add(el)

            # Link video branch into flvmux video pad
            if not video_queue.link(video_convert):
                log.error("rtmp bin: video_queue -> video_convert link failed")
                return False
            if not video_convert.link(encoder):
                log.error("rtmp bin: video_convert -> encoder link failed")
                return False
            if not encoder.link(h264_parse):
                log.error("rtmp bin: encoder -> h264parse link failed")
                return False
            if not h264_parse.link_pads("src", mux, "video"):
                log.error("rtmp bin: h264parse -> mux.video link failed")
                return False

            # Link audio branch into flvmux audio pad
            if not audio_src.link(audio_convert):
                log.error("rtmp bin: audio_src -> audio_convert link failed")
                return False
            if not audio_convert.link(audio_resample):
                log.error("rtmp bin: audio_convert -> audio_resample link failed")
                return False
            if not audio_resample.link(audio_caps):
                log.error("rtmp bin: audio_resample -> audio_caps link failed")
                return False
            if not audio_caps.link(audio_encoder):
                log.error("rtmp bin: audio_caps -> audio_encoder link failed")
                return False
            if not audio_encoder.link(aac_parse):
                log.error("rtmp bin: audio_encoder -> aac_parse link failed")
                return False
            if not aac_parse.link_pads("src", mux, "audio"):
                log.error("rtmp bin: aac_parse -> mux.audio link failed")
                return False

            # Mux → sink
            if not mux.link(sink):
                log.error("rtmp bin: mux -> sink link failed")
                return False

            # Ghost pad for the bin's video sink
            video_queue_sink_pad = video_queue.get_static_pad("sink")
            ghost_pad = Gst.GhostPad.new("video_sink", video_queue_sink_pad)
            ghost_pad.set_active(True)
            bin_.add_pad(ghost_pad)

            # Add the bin to the composite pipeline
            composite_pipeline.add(bin_)

            # Request a new tee src pad and link to the ghost pad
            tee_src_pad = self._video_tee.request_pad(
                self._video_tee.get_pad_template("src_%u"), None, None
            )
            if tee_src_pad is None:
                log.error("rtmp bin: failed to request tee src pad")
                composite_pipeline.remove(bin_)
                return False

            if tee_src_pad.link(ghost_pad) != Gst.PadLinkReturn.OK:
                log.error("rtmp bin: failed to link tee pad to bin ghost pad")
                self._video_tee.release_request_pad(tee_src_pad)
                composite_pipeline.remove(bin_)
                return False

            # Sync bin state to the composite pipeline state (PLAYING)
            if not bin_.sync_state_with_parent():
                log.warning("rtmp bin: sync_state_with_parent returned False (may be transient)")

            self._bin = bin_
            self._video_tee_pad = tee_src_pad

            log.info(
                "rtmp bin attached (location=%s, bitrate=%dkbps, rebuild_count=%d)",
                self._rtmp_location,
                self._bitrate_kbps,
                self._rebuild_count,
            )
            return True

    def detach_and_teardown(self, composite_pipeline: Any) -> None:
        """Remove the bin from the composite pipeline cleanly."""
        with self._state_lock:
            if self._bin is None:
                return

            Gst = self._Gst

            # Unlink the tee src pad and release it
            if self._video_tee_pad is not None:
                try:
                    ghost_pad = self._bin.get_static_pad("video_sink")
                    if ghost_pad is not None:
                        self._video_tee_pad.unlink(ghost_pad)
                    self._video_tee.release_request_pad(self._video_tee_pad)
                except Exception:
                    log.exception("rtmp bin: tee unlink raised")
                self._video_tee_pad = None

            # Set bin to NULL and remove from pipeline
            try:
                self._bin.set_state(Gst.State.NULL)
            except Exception:
                log.exception("rtmp bin: set_state(NULL) raised")
            try:
                composite_pipeline.remove(self._bin)
            except Exception:
                log.exception("rtmp bin: remove from composite pipeline raised")

            self._bin = None
            log.info("rtmp bin detached")

    def rebuild_in_place(self, composite_pipeline: Any) -> bool:
        """Tear down and rebuild the bin. Called from the compositor's bus
        error handler on NVENC/rtmp failures."""
        with self._state_lock:
            self._rebuild_count += 1
            self.detach_and_teardown(composite_pipeline)
            return self.build_and_attach(composite_pipeline)

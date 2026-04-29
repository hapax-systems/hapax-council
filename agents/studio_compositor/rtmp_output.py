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

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def _aac_input_caps_string(encoder_factory: str) -> str:
    """Return raw audio caps accepted by the selected AAC encoder."""
    audio_format = "F32LE" if encoder_factory == "avenc_aac" else "S16LE"
    return f"audio/x-raw,rate=48000,channels=2,format={audio_format}"


class RtmpOutputBin:
    """Detachable RTMP encoder bin for the studio compositor."""

    def __init__(
        self,
        *,
        gst: Any,
        video_tee: Any,
        rtmp_location: str = "rtmp://127.0.0.1:1935/studio",
        bitrate_kbps: int = 9000,
        gop_size: int = 30,
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

            # A+ Stage 1 (2026-04-17): CPU videoconvert (BGRA→NV12) → GPU
            # cudaupload + cudaconvert. The per-camera recording branch
            # already uses this pattern (recording.py:29-33). Moving the
            # colorspace conversion onto the CUDA copy engine + SM
            # (~negligible cost vs NVENC) frees a full CPU thread that
            # was doing per-frame colorspace math before the encoder.
            # Falls back to software videoconvert if CUDA elements
            # aren't available (e.g., GStreamer built without nvcodec).
            video_convert = Gst.ElementFactory.make("cudaupload", "rtmp_cudaupload")
            video_convert2 = Gst.ElementFactory.make("cudaconvert", "rtmp_cudaconvert")
            if video_convert is None or video_convert2 is None:
                log.warning(
                    "rtmp bin: cudaupload/cudaconvert unavailable, "
                    "falling back to software videoconvert"
                )
                video_convert = Gst.ElementFactory.make("videoconvert", "rtmp_video_convert")
                video_convert2 = None
                if video_convert is None:
                    log.error("rtmp bin: videoconvert factory failed")
                    return False
            else:
                try:
                    video_convert.set_property("cuda-device-id", 0)
                    video_convert2.set_property("cuda-device-id", 0)
                except Exception:
                    log.debug("cudaupload/cudaconvert: cuda-device-id not supported", exc_info=True)
                # Feed encoder NV12 in CUDA memory, not CPU BGRA.
                cuda_caps = Gst.ElementFactory.make("capsfilter", "rtmp_cuda_caps")
                cuda_caps.set_property(
                    "caps",
                    Gst.Caps.from_string("video/x-raw(memory:CUDAMemory),format=NV12"),
                )

            # Delta 2026-04-14-encoder-output-path-walk finding #5: queue
            # between videoconvert and nvh264enc. Without it, colorspace
            # conversion and the encoder share a thread so an NVENC stall
            # backpressures videoconvert → input queue drops oldest. With
            # this queue the two elements are thread-isolated and
            # videoconvert keeps draining the input even if NVENC briefly
            # stalls.
            video_encoder_queue = Gst.ElementFactory.make("queue", "rtmp_video_encoder_queue")
            if video_encoder_queue is None:
                log.error("rtmp bin: video_encoder_queue factory failed")
                return False
            video_encoder_queue.set_property("max-size-buffers", 10)
            video_encoder_queue.set_property("max-size-time", 500 * Gst.MSECOND)
            video_encoder_queue.set_property("leaky", 2)  # downstream

            encoder = Gst.ElementFactory.make("nvh264enc", "rtmp_nvh264enc")
            if encoder is None:
                log.error("rtmp bin: nvh264enc factory failed")
                return False
            # Drop #47 C2 + sprint-5-delta-audit F1: pin nvh264enc to
            # the same CUDA device as cudacompositor so the session cannot
            # drift off GPU 0 if the CUDA enumeration order ever changes
            # (e.g. under a different systemd unit override or a kernel
            # upgrade). Mirrors the `cuda-device-id` set in `pipeline.py`
            # for `cudacompositor`. Try/except because older nvh264enc
            # builds didn't expose the property.
            try:
                encoder.set_property("cuda-device-id", 0)
            except Exception:
                log.debug("nvh264enc: cuda-device-id property not supported", exc_info=True)
            encoder.set_property("bitrate", self._bitrate_kbps)
            encoder.set_property("rc-mode", 2)  # 2 = cbr
            encoder.set_property("gop-size", self._gop_size)
            encoder.set_property("zerolatency", True)
            # 2026-04-20 (post-Tauri-decom): preset p1 → p5. The A+ Stage 0
            # cut (2026-04-17) traded preset quality for SM headroom while
            # the WebKit decoder was burning encoder-adjacent GPU on the
            # Tauri preview. With hapax-logos decommissioned, the SM is
            # available; p5 produces visibly cleaner motion at the new
            # 9000 kbps ceiling (the bitrate-pinned argument from A+
            # Stage 0 holds at 3000 but loosens substantially at 9000).
            # Per docs/research/2026-04-20-tauri-decommission-freed-
            # resources.md §11.
            # String nick "p7" is build-stable across gst-plugins-bad
            # versions; the legacy integer enum 7 maps to "lossless-hp"
            # in older builds, NOT to p7. Always pass the nick.
            encoder.set_property("preset", "p7")
            # A+ Stage 0: tune=ull (ultra low latency). ll keeps lookahead
            # buffer for quality; at CBR the buffer gains nothing since
            # bitrate is pinned. ull disables B-frames, lookahead, reorder.
            encoder.set_property("tune", 3)  # 3 = ultra-low-latency
            # A+ Stage 0: explicit b-frames=0. Critical for low-latency
            # CBR broadcasting; removes any remaining reorder delay.
            try:
                encoder.set_property("bframes", 0)
            except Exception:
                log.debug("nvh264enc: bframes property not available", exc_info=True)
            # Free NVENC quality wins, each conditional on encoder support.
            # Per gst-plugins-bad nvh264enc property table:
            #   rc-lookahead — extra lookahead frames (improves bitrate
            #     allocation under CBR; up to 32 frames is the documented
            #     useful upper bound for h264).
            #   spatial-aq — adaptive quantization across regions of one
            #     frame. Pulls bits toward visually demanding areas
            #     (edges, faces) and away from flat zones.
            #   temporal-aq — same idea over time; benefits motion regions.
            #   weighted-pred — only meaningful when bframes>0 (we set 0
            #     above), so this property typically no-ops on our pipe.
            #     Kept for forward compatibility if the b-frames decision
            #     reverses on a future tune.
            for prop, value in (
                ("rc-lookahead", 32),
                ("spatial-aq", True),
                ("temporal-aq", True),
                ("weighted-pred", True),
            ):
                try:
                    encoder.set_property(prop, value)
                except Exception:
                    log.debug("nvh264enc: %s property not available", prop, exc_info=True)

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

            # Delta 2026-04-14-encoder-output-path-walk finding #4: the
            # audio path previously had ZERO queues, so voaacenc stalls
            # backpressured directly into pipewiresrc → xruns upstream.
            # With flvmux.latency=100ms the A/V alignment window was
            # tight enough that any audio jitter exceeding 100 ms caused
            # the mux to drop video waiting for audio. Two queues: one
            # after the source to decouple from the PipeWire thread, one
            # before the encoder to decouple audioresample from voaacenc.
            audio_src_queue = Gst.ElementFactory.make("queue", "rtmp_audio_src_queue")
            if audio_src_queue is None:
                log.error("rtmp bin: audio_src_queue factory failed")
                return False
            audio_src_queue.set_property("max-size-buffers", 20)
            audio_src_queue.set_property("max-size-time", 500 * Gst.MSECOND)
            audio_src_queue.set_property("leaky", 2)  # downstream

            audio_convert = Gst.ElementFactory.make("audioconvert", "rtmp_audio_convert")
            audio_resample = Gst.ElementFactory.make("audioresample", "rtmp_audio_resample")
            audio_caps = Gst.ElementFactory.make("capsfilter", "rtmp_audio_caps")

            # Finding #4 continued: second queue in front of voaacenc so
            # the encoder runs on its own thread, not the audioresample/
            # pipewiresrc thread. Brief encoder stalls now park frames
            # in the queue instead of propagating back to PipeWire.
            audio_encoder_queue = Gst.ElementFactory.make("queue", "rtmp_audio_encoder_queue")
            if audio_encoder_queue is None:
                log.error("rtmp bin: audio_encoder_queue factory failed")
                return False
            audio_encoder_queue.set_property("max-size-buffers", 20)
            audio_encoder_queue.set_property("max-size-time", 500 * Gst.MSECOND)
            audio_encoder_queue.set_property("leaky", 2)  # downstream

            audio_encoder_factory = "voaacenc"
            audio_encoder = Gst.ElementFactory.make("voaacenc", "rtmp_voaacenc")
            if audio_encoder is None:
                log.warning("rtmp bin: voaacenc unavailable, trying avenc_aac")
                audio_encoder_factory = "avenc_aac"
                audio_encoder = Gst.ElementFactory.make("avenc_aac", "rtmp_voaacenc")
            if audio_encoder is None:
                log.error("rtmp bin: no AAC encoder available")
                return False
            audio_caps.set_property(
                "caps",
                Gst.Caps.from_string(_aac_input_caps_string(audio_encoder_factory)),
            )
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
            sink.set_property("async-connect", False)

            # --- Add elements + link ---
            elements = [
                video_queue,
                video_convert,
                video_encoder_queue,
                encoder,
                h264_parse,
                audio_src,
                audio_src_queue,
                audio_convert,
                audio_resample,
                audio_caps,
                audio_encoder_queue,
                audio_encoder,
                aac_parse,
                mux,
                sink,
            ]
            # A+ Stage 1: cudaconvert + caps inserted between cudaupload
            # and the encoder queue when the GPU path is live. ``cuda_caps``
            # is only defined in the cudaupload branch.
            if video_convert2 is not None:
                elements.insert(elements.index(video_convert) + 1, video_convert2)
                elements.insert(elements.index(video_convert2) + 1, cuda_caps)
            for el in elements:
                bin_.add(el)

            # Link video branch into flvmux video pad
            if not video_queue.link(video_convert):
                log.error("rtmp bin: video_queue -> video_convert link failed")
                return False
            if video_convert2 is not None:
                if not video_convert.link(video_convert2):
                    log.error("rtmp bin: cudaupload -> cudaconvert link failed")
                    return False
                if not video_convert2.link(cuda_caps):
                    log.error("rtmp bin: cudaconvert -> cuda_caps link failed")
                    return False
                if not cuda_caps.link(video_encoder_queue):
                    log.error("rtmp bin: cuda_caps -> video_encoder_queue link failed")
                    return False
            else:
                if not video_convert.link(video_encoder_queue):
                    log.error("rtmp bin: video_convert -> video_encoder_queue link failed")
                    return False
            if not video_encoder_queue.link(encoder):
                log.error("rtmp bin: video_encoder_queue -> encoder link failed")
                return False
            if not encoder.link(h264_parse):
                log.error("rtmp bin: encoder -> h264parse link failed")
                return False
            if not h264_parse.link_pads("src", mux, "video"):
                log.error("rtmp bin: h264parse -> mux.video link failed")
                return False

            # Link audio branch into flvmux audio pad
            if not audio_src.link(audio_src_queue):
                log.error("rtmp bin: audio_src -> audio_src_queue link failed")
                return False
            if not audio_src_queue.link(audio_convert):
                log.error("rtmp bin: audio_src_queue -> audio_convert link failed")
                return False
            if not audio_convert.link(audio_resample):
                log.error("rtmp bin: audio_convert -> audio_resample link failed")
                return False
            if not audio_resample.link(audio_caps):
                log.error("rtmp bin: audio_resample -> audio_caps link failed")
                return False
            if not audio_caps.link(audio_encoder_queue):
                log.error("rtmp bin: audio_caps -> audio_encoder_queue link failed")
                return False
            if not audio_encoder_queue.link(audio_encoder):
                log.error("rtmp bin: audio_encoder_queue -> audio_encoder link failed")
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


class MobileRtmpOutputBin:
    """Detachable portrait RTMP encoder bin for the mobile substream."""

    _WIDTH = 1080
    _HEIGHT = 1920
    _OVERLAY_FPS = 10

    def __init__(
        self,
        *,
        gst: Any,
        glib: Any,
        video_tee: Any,
        source_width: int,
        source_height: int,
        rtmp_location: str | None = None,
        rtmp_key: str | None = None,
        bitrate_kbps: int = 3500,
        gop_size: int = 60,
        audio_target: str | None = None,
        crop_params_path: Path = Path("/dev/shm/hapax-compositor/mobile-roi.json"),
        overlay_path: Path = Path("/dev/shm/hapax-compositor/mobile-overlay.rgba"),
    ) -> None:
        self._Gst = gst
        self._GLib = glib
        self._video_tee = video_tee
        self._source_width = int(source_width)
        self._source_height = int(source_height)
        self._rtmp_location = self._with_stream_key(
            rtmp_location
            or os.environ.get("HAPAX_MOBILE_RTMP_URL")
            or "rtmp://127.0.0.1:1935/mobile",
            rtmp_key if rtmp_key is not None else os.environ.get("HAPAX_MOBILE_RTMP_KEY", ""),
        )
        self._bitrate_kbps = bitrate_kbps
        self._gop_size = gop_size
        self._audio_target = audio_target
        self._crop_params_path = crop_params_path
        self._overlay_path = overlay_path

        self._bin: Any = None
        self._video_tee_pad: Any = None
        self._state_lock = threading.RLock()
        self._rebuild_count = 0
        self._overlay_stop = threading.Event()
        self._overlay_thread: threading.Thread | None = None
        self._crop_stop = threading.Event()
        self._crop_thread: threading.Thread | None = None

    @property
    def rebuild_count(self) -> int:
        with self._state_lock:
            return self._rebuild_count

    @property
    def bitrate_kbps(self) -> int:
        return self._bitrate_kbps

    def is_attached(self) -> bool:
        with self._state_lock:
            return self._bin is not None

    def build_and_attach(self, composite_pipeline: Any) -> bool:
        with self._state_lock:
            if self._bin is not None:
                log.info("mobile RTMP bin already attached")
                return True

            Gst = self._Gst
            bin_ = Gst.Bin.new("mobile_rtmp_output_bin")

            video_queue = Gst.ElementFactory.make("queue", "mobile_rtmp_video_queue")
            crop = Gst.ElementFactory.make("videocrop", "mobile_rtmp_crop")
            scale = Gst.ElementFactory.make("videoscale", "mobile_rtmp_scale")
            video_convert = Gst.ElementFactory.make("videoconvert", "mobile_rtmp_video_convert")
            mobile_caps = Gst.ElementFactory.make("capsfilter", "mobile_rtmp_portrait_caps")
            mixer = Gst.ElementFactory.make("compositor", "mobile_rtmp_mixer")
            mixer_queue = Gst.ElementFactory.make("queue", "mobile_rtmp_mixer_queue")
            overlay_src = Gst.ElementFactory.make("appsrc", "mobile_rtmp_overlay_src")
            overlay_queue = Gst.ElementFactory.make("queue", "mobile_rtmp_overlay_queue")
            if any(
                el is None
                for el in (
                    video_queue,
                    crop,
                    scale,
                    video_convert,
                    mobile_caps,
                    mixer,
                    mixer_queue,
                    overlay_src,
                    overlay_queue,
                )
            ):
                log.error("mobile RTMP bin: required video/overlay factory failed")
                return False

            video_queue.set_property("max-size-buffers", 30)
            video_queue.set_property("max-size-time", 2 * Gst.SECOND)
            video_queue.set_property("leaky", 2)
            mixer_queue.set_property("max-size-buffers", 10)
            mixer_queue.set_property("max-size-time", 500 * Gst.MSECOND)
            mixer_queue.set_property("leaky", 2)
            overlay_queue.set_property("max-size-buffers", 3)
            overlay_queue.set_property("max-size-time", 500 * Gst.MSECOND)
            overlay_queue.set_property("leaky", 2)

            self._apply_crop(crop, self._default_crop())
            mobile_caps.set_property(
                "caps",
                Gst.Caps.from_string(
                    "video/x-raw,format=BGRA,width=1080,height=1920,framerate=30/1"
                ),
            )
            overlay_src.set_property("is-live", True)
            overlay_src.set_property("block", False)
            overlay_src.set_property("do-timestamp", True)
            overlay_src.set_property("format", Gst.Format.TIME)
            overlay_src.set_property(
                "caps",
                Gst.Caps.from_string(
                    "video/x-raw,format=BGRA,width=1080,height=1920,framerate=10/1"
                ),
            )

            cuda_upload = Gst.ElementFactory.make("cudaupload", "mobile_rtmp_cudaupload")
            cuda_convert = Gst.ElementFactory.make("cudaconvert", "mobile_rtmp_cudaconvert")
            cuda_caps = None
            if cuda_upload is not None and cuda_convert is not None:
                try:
                    cuda_upload.set_property("cuda-device-id", 0)
                    cuda_convert.set_property("cuda-device-id", 0)
                except Exception:
                    log.debug("mobile RTMP CUDA device property unavailable", exc_info=True)
                cuda_caps = Gst.ElementFactory.make("capsfilter", "mobile_rtmp_cuda_caps")
                cuda_caps.set_property(
                    "caps",
                    Gst.Caps.from_string(
                        "video/x-raw(memory:CUDAMemory),format=NV12,width=1080,height=1920"
                    ),
                )
            else:
                cuda_upload = Gst.ElementFactory.make("videoconvert", "mobile_rtmp_sw_convert")
                cuda_convert = None
                if cuda_upload is None:
                    log.error("mobile RTMP bin: no color-conversion path available")
                    return False

            video_encoder_queue = Gst.ElementFactory.make(
                "queue", "mobile_rtmp_video_encoder_queue"
            )
            encoder = Gst.ElementFactory.make("nvh264enc", "mobile_rtmp_nvh264enc")
            h264_parse = Gst.ElementFactory.make("h264parse", "mobile_rtmp_h264parse")
            if video_encoder_queue is None or encoder is None or h264_parse is None:
                log.error("mobile RTMP bin: encoder path factory failed")
                return False
            video_encoder_queue.set_property("max-size-buffers", 10)
            video_encoder_queue.set_property("max-size-time", 500 * Gst.MSECOND)
            video_encoder_queue.set_property("leaky", 2)
            try:
                encoder.set_property("cuda-device-id", 0)
            except Exception:
                log.debug("mobile nvh264enc cuda-device-id unavailable", exc_info=True)
            encoder.set_property("bitrate", self._bitrate_kbps)
            encoder.set_property("rc-mode", 2)
            encoder.set_property("gop-size", self._gop_size)
            encoder.set_property("zerolatency", True)
            encoder.set_property("preset", "p7")
            encoder.set_property("tune", 3)
            try:
                encoder.set_property("bframes", 0)
            except Exception:
                log.debug("mobile nvh264enc bframes unavailable", exc_info=True)
            for prop, value in (
                ("rc-lookahead", 16),
                ("spatial-aq", True),
                ("temporal-aq", True),
            ):
                try:
                    encoder.set_property(prop, value)
                except Exception:
                    log.debug("mobile nvh264enc %s unavailable", prop, exc_info=True)
            h264_parse.set_property("config-interval", -1)

            audio_src = Gst.ElementFactory.make("pipewiresrc", "mobile_rtmp_audio_src")
            if audio_src is None:
                log.warning("mobile RTMP bin: pipewiresrc unavailable, using silence")
                audio_src = Gst.ElementFactory.make("audiotestsrc", "mobile_rtmp_audio_src")
                if audio_src is not None:
                    audio_src.set_property("is-live", True)
                    audio_src.set_property("wave", 4)
            elif self._audio_target:
                audio_src.set_property("target-object", self._audio_target)
            if audio_src is None:
                log.error("mobile RTMP bin: no audio source available")
                return False

            audio_src_queue = Gst.ElementFactory.make("queue", "mobile_rtmp_audio_src_queue")
            audio_convert = Gst.ElementFactory.make("audioconvert", "mobile_rtmp_audio_convert")
            audio_resample = Gst.ElementFactory.make("audioresample", "mobile_rtmp_audio_resample")
            audio_caps = Gst.ElementFactory.make("capsfilter", "mobile_rtmp_audio_caps")
            audio_encoder_queue = Gst.ElementFactory.make(
                "queue", "mobile_rtmp_audio_encoder_queue"
            )
            audio_encoder_factory = "voaacenc"
            audio_encoder = Gst.ElementFactory.make("voaacenc", "mobile_rtmp_voaacenc")
            if audio_encoder is None:
                log.warning("mobile RTMP bin: voaacenc unavailable, trying avenc_aac")
                audio_encoder_factory = "avenc_aac"
                audio_encoder = Gst.ElementFactory.make("avenc_aac", "mobile_rtmp_voaacenc")
            aac_parse = Gst.ElementFactory.make("aacparse", "mobile_rtmp_aacparse")
            mux = Gst.ElementFactory.make("flvmux", "mobile_rtmp_flvmux")
            sink = Gst.ElementFactory.make("rtmp2sink", "mobile_rtmp_sink")
            if sink is None:
                sink = Gst.ElementFactory.make("rtmpsink", "mobile_rtmp_sink")
            if any(
                el is None
                for el in (
                    audio_src_queue,
                    audio_convert,
                    audio_resample,
                    audio_caps,
                    audio_encoder_queue,
                    audio_encoder,
                    aac_parse,
                    mux,
                    sink,
                )
            ):
                log.error("mobile RTMP bin: required audio/mux/sink factory failed")
                return False
            audio_src_queue.set_property("max-size-buffers", 20)
            audio_src_queue.set_property("max-size-time", 500 * Gst.MSECOND)
            audio_src_queue.set_property("leaky", 2)
            audio_encoder_queue.set_property("max-size-buffers", 20)
            audio_encoder_queue.set_property("max-size-time", 500 * Gst.MSECOND)
            audio_encoder_queue.set_property("leaky", 2)
            audio_caps.set_property(
                "caps",
                Gst.Caps.from_string(_aac_input_caps_string(audio_encoder_factory)),
            )
            if hasattr(audio_encoder.props, "bitrate"):
                audio_encoder.set_property("bitrate", 128000)
            mux.set_property("streamable", True)
            mux.set_property("latency", 100_000_000)
            sink.set_property("location", self._rtmp_location)
            sink.set_property("async-connect", False)

            elements = [
                video_queue,
                crop,
                scale,
                video_convert,
                mobile_caps,
                mixer,
                mixer_queue,
                overlay_src,
                overlay_queue,
                cuda_upload,
                video_encoder_queue,
                encoder,
                h264_parse,
                audio_src,
                audio_src_queue,
                audio_convert,
                audio_resample,
                audio_caps,
                audio_encoder_queue,
                audio_encoder,
                aac_parse,
                mux,
                sink,
            ]
            if cuda_convert is not None and cuda_caps is not None:
                elements.insert(elements.index(cuda_upload) + 1, cuda_convert)
                elements.insert(elements.index(cuda_convert) + 1, cuda_caps)
            for el in elements:
                bin_.add(el)

            if not video_queue.link(crop):
                log.error("mobile RTMP bin: video_queue -> crop link failed")
                return False
            if not crop.link(scale):
                log.error("mobile RTMP bin: crop -> scale link failed")
                return False
            if not scale.link(video_convert):
                log.error("mobile RTMP bin: scale -> video_convert link failed")
                return False
            if not video_convert.link(mobile_caps):
                log.error("mobile RTMP bin: video_convert -> mobile_caps link failed")
                return False
            if not self._link_to_mixer(mobile_caps, mixer, zorder=0, alpha=1.0):
                return False
            if not overlay_src.link(overlay_queue):
                log.error("mobile RTMP bin: overlay_src -> overlay_queue link failed")
                return False
            if not self._link_to_mixer(overlay_queue, mixer, zorder=1, alpha=1.0):
                return False
            if not mixer.link(mixer_queue):
                log.error("mobile RTMP bin: mixer -> mixer_queue link failed")
                return False
            if not mixer_queue.link(cuda_upload):
                log.error("mobile RTMP bin: mixer_queue -> encoder convert link failed")
                return False
            if cuda_convert is not None and cuda_caps is not None:
                if not cuda_upload.link(cuda_convert):
                    log.error("mobile RTMP bin: cudaupload -> cudaconvert link failed")
                    return False
                if not cuda_convert.link(cuda_caps):
                    log.error("mobile RTMP bin: cudaconvert -> cuda_caps link failed")
                    return False
                if not cuda_caps.link(video_encoder_queue):
                    log.error("mobile RTMP bin: cuda_caps -> video_encoder_queue link failed")
                    return False
            elif not cuda_upload.link(video_encoder_queue):
                log.error("mobile RTMP bin: sw_convert -> video_encoder_queue link failed")
                return False
            if not video_encoder_queue.link(encoder):
                log.error("mobile RTMP bin: video_encoder_queue -> encoder link failed")
                return False
            if not encoder.link(h264_parse):
                log.error("mobile RTMP bin: encoder -> h264parse link failed")
                return False
            if not h264_parse.link_pads("src", mux, "video"):
                log.error("mobile RTMP bin: h264parse -> mux.video link failed")
                return False

            if not audio_src.link(audio_src_queue):
                log.error("mobile RTMP bin: audio_src -> audio_src_queue link failed")
                return False
            if not audio_src_queue.link(audio_convert):
                log.error("mobile RTMP bin: audio_src_queue -> audio_convert link failed")
                return False
            if not audio_convert.link(audio_resample):
                log.error("mobile RTMP bin: audio_convert -> audio_resample link failed")
                return False
            if not audio_resample.link(audio_caps):
                log.error("mobile RTMP bin: audio_resample -> audio_caps link failed")
                return False
            if not audio_caps.link(audio_encoder_queue):
                log.error("mobile RTMP bin: audio_caps -> audio_encoder_queue link failed")
                return False
            if not audio_encoder_queue.link(audio_encoder):
                log.error("mobile RTMP bin: audio_encoder_queue -> audio_encoder link failed")
                return False
            if not audio_encoder.link(aac_parse):
                log.error("mobile RTMP bin: audio_encoder -> aacparse link failed")
                return False
            if not aac_parse.link_pads("src", mux, "audio"):
                log.error("mobile RTMP bin: aacparse -> mux.audio link failed")
                return False
            if not mux.link(sink):
                log.error("mobile RTMP bin: mux -> sink link failed")
                return False

            try:
                h264_parse.get_static_pad("src").add_probe(
                    Gst.PadProbeType.BUFFER, self._frame_probe
                )
            except Exception:
                log.debug("mobile RTMP frame probe install failed", exc_info=True)

            video_queue_sink_pad = video_queue.get_static_pad("sink")
            ghost_pad = Gst.GhostPad.new("video_sink", video_queue_sink_pad)
            ghost_pad.set_active(True)
            bin_.add_pad(ghost_pad)

            composite_pipeline.add(bin_)
            tee_src_pad = self._video_tee.request_pad(
                self._video_tee.get_pad_template("src_%u"), None, None
            )
            if tee_src_pad is None:
                log.error("mobile RTMP bin: failed to request tee src pad")
                composite_pipeline.remove(bin_)
                return False
            if tee_src_pad.link(ghost_pad) != Gst.PadLinkReturn.OK:
                log.error("mobile RTMP bin: failed to link tee pad to ghost pad")
                self._video_tee.release_request_pad(tee_src_pad)
                composite_pipeline.remove(bin_)
                return False

            if not bin_.sync_state_with_parent():
                log.warning("mobile RTMP bin: sync_state_with_parent returned False")

            self._bin = bin_
            self._video_tee_pad = tee_src_pad
            self._start_overlay_thread(overlay_src)
            self._start_crop_thread(crop)
            self._publish_metrics(attached=True)
            log.info(
                "mobile RTMP bin attached (location=%s, bitrate=%dkbps, rebuild_count=%d)",
                self._redacted_location(),
                self._bitrate_kbps,
                self._rebuild_count,
            )
            return True

    def detach_and_teardown(self, composite_pipeline: Any) -> None:
        with self._state_lock:
            if self._bin is None:
                return
            Gst = self._Gst
            self._stop_worker_threads()
            if self._video_tee_pad is not None:
                try:
                    ghost_pad = self._bin.get_static_pad("video_sink")
                    if ghost_pad is not None:
                        self._video_tee_pad.unlink(ghost_pad)
                    self._video_tee.release_request_pad(self._video_tee_pad)
                except Exception:
                    log.exception("mobile RTMP bin: tee unlink raised")
                self._video_tee_pad = None
            try:
                self._bin.set_state(Gst.State.NULL)
            except Exception:
                log.exception("mobile RTMP bin: set_state(NULL) raised")
            try:
                composite_pipeline.remove(self._bin)
            except Exception:
                log.exception("mobile RTMP bin: remove from composite pipeline raised")
            self._bin = None
            self._publish_metrics(attached=False)
            log.info("mobile RTMP bin detached")

    def rebuild_in_place(self, composite_pipeline: Any) -> bool:
        with self._state_lock:
            self._rebuild_count += 1
            self.detach_and_teardown(composite_pipeline)
            return self.build_and_attach(composite_pipeline)

    def _link_to_mixer(self, upstream: Any, mixer: Any, *, zorder: int, alpha: float) -> bool:
        src_pad = upstream.get_static_pad("src")
        sink_pad = mixer.request_pad(mixer.get_pad_template("sink_%u"), None, None)
        if src_pad is None or sink_pad is None:
            log.error("mobile RTMP bin: failed to allocate mixer pad")
            return False
        try:
            sink_pad.set_property("xpos", 0)
            sink_pad.set_property("ypos", 0)
            sink_pad.set_property("width", self._WIDTH)
            sink_pad.set_property("height", self._HEIGHT)
            sink_pad.set_property("zorder", zorder)
            sink_pad.set_property("alpha", alpha)
        except Exception:
            log.debug("mobile RTMP mixer pad property unavailable", exc_info=True)
        if src_pad.link(sink_pad) != self._Gst.PadLinkReturn.OK:
            log.error("mobile RTMP bin: upstream -> mixer link failed")
            return False
        return True

    def _frame_probe(self, pad: Any, info: Any) -> Any:
        del pad, info
        try:
            from . import metrics

            if metrics.HAPAX_MOBILE_SUBSTREAM_FRAMES_TOTAL is not None:
                metrics.HAPAX_MOBILE_SUBSTREAM_FRAMES_TOTAL.inc()
        except Exception:
            pass
        return self._Gst.PadProbeReturn.OK

    def _start_overlay_thread(self, appsrc: Any) -> None:
        self._overlay_stop.clear()

        def _run() -> None:
            Gst = self._Gst
            frame_size = self._WIDTH * self._HEIGHT * 4
            duration = Gst.SECOND // self._OVERLAY_FPS
            pts = 0
            while not self._overlay_stop.is_set():
                data = self._read_overlay_bytes(frame_size)
                try:
                    buf = Gst.Buffer.new_allocate(None, frame_size, None)
                    buf.fill(0, data)
                    buf.pts = pts
                    buf.duration = duration
                    pts += duration
                    appsrc.emit("push-buffer", buf)
                except Exception:
                    log.debug("mobile RTMP overlay push failed", exc_info=True)
                self._overlay_stop.wait(1.0 / self._OVERLAY_FPS)

        self._overlay_thread = threading.Thread(
            target=_run,
            daemon=True,
            name="mobile-rtmp-overlay-push",
        )
        self._overlay_thread.start()

    def _start_crop_thread(self, crop: Any) -> None:
        self._crop_stop.clear()

        def _run() -> None:
            last: tuple[int, int, int, int] | None = None
            while not self._crop_stop.is_set():
                params = self._read_crop_params()
                if params is not None and params != last:
                    last = params
                    self._GLib.idle_add(lambda p=params: (self._apply_crop(crop, p), False)[1])
                self._crop_stop.wait(2.0)

        self._crop_thread = threading.Thread(
            target=_run,
            daemon=True,
            name="mobile-rtmp-crop-update",
        )
        self._crop_thread.start()

    def _stop_worker_threads(self) -> None:
        self._overlay_stop.set()
        self._crop_stop.set()
        if self._overlay_thread is not None:
            self._overlay_thread.join(timeout=2.0)
            self._overlay_thread = None
        if self._crop_thread is not None:
            self._crop_thread.join(timeout=2.0)
            self._crop_thread = None

    def _read_overlay_bytes(self, expected_size: int) -> bytes:
        try:
            data = self._overlay_path.read_bytes()
        except OSError:
            return b"\x00" * expected_size
        if len(data) != expected_size:
            return b"\x00" * expected_size
        return data

    def _read_crop_params(self) -> tuple[int, int, int, int] | None:
        try:
            data = json.loads(self._crop_params_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        source_crop = data.get("source_crop")
        raw = source_crop if isinstance(source_crop, dict) else data
        try:
            return self._crop_tuple(
                x=float(raw["x"]),
                y=float(raw["y"]),
                width=float(raw["width"]),
                height=float(raw["height"]),
                source_width=float(raw.get("source_width", 1920)),
                source_height=float(raw.get("source_height", 1080)),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def _default_crop(self) -> tuple[int, int, int, int]:
        try:
            from agents.studio_compositor.mobile_layout import load_mobile_layout

            crop = load_mobile_layout().hero_cam.source_crop
            return self._crop_tuple(
                x=float(crop.x),
                y=float(crop.y),
                width=float(crop.width),
                height=float(crop.height),
                source_width=1920.0,
                source_height=1080.0,
            )
        except Exception:
            portrait_width = max(1, int(self._source_height * 9 / 16))
            x = max(0, int((self._source_width - portrait_width) / 2))
            return self._crop_tuple(
                x=float(x),
                y=0.0,
                width=float(portrait_width),
                height=float(self._source_height),
                source_width=float(self._source_width),
                source_height=float(self._source_height),
            )

    def _crop_tuple(
        self,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        source_width: float,
        source_height: float,
    ) -> tuple[int, int, int, int]:
        if x + width > self._source_width or y + height > self._source_height:
            sx = self._source_width / max(1.0, source_width)
            sy = self._source_height / max(1.0, source_height)
            x *= sx
            width *= sx
            y *= sy
            height *= sy
        x_i = max(0, min(self._source_width - 1, int(round(x))))
        y_i = max(0, min(self._source_height - 1, int(round(y))))
        width_i = max(1, min(self._source_width - x_i, int(round(width))))
        height_i = max(1, min(self._source_height - y_i, int(round(height))))
        left = x_i
        top = y_i
        right = max(0, self._source_width - x_i - width_i)
        bottom = max(0, self._source_height - y_i - height_i)
        return left, top, right, bottom

    @staticmethod
    def _apply_crop(crop: Any, values: tuple[int, int, int, int]) -> None:
        left, top, right, bottom = values
        crop.set_property("left", left)
        crop.set_property("top", top)
        crop.set_property("right", right)
        crop.set_property("bottom", bottom)

    def _publish_metrics(self, *, attached: bool) -> None:
        try:
            from . import metrics

            if metrics.RTMP_CONNECTED is not None:
                metrics.RTMP_CONNECTED.labels(endpoint="mobile").set(1 if attached else 0)
            if metrics.HAPAX_MOBILE_SUBSTREAM_BITRATE_KBPS is not None:
                metrics.HAPAX_MOBILE_SUBSTREAM_BITRATE_KBPS.set(
                    self._bitrate_kbps if attached else 0
                )
        except Exception:
            log.debug("mobile RTMP metric publish failed", exc_info=True)

    @staticmethod
    def _with_stream_key(location: str, stream_key: str | None) -> str:
        key = (stream_key or "").strip()
        if not key:
            return location
        return f"{location.rstrip('/')}/{key.lstrip('/')}"

    def _redacted_location(self) -> str:
        if "?" in self._rtmp_location:
            return self._rtmp_location.split("?", 1)[0] + "?..."
        parts = self._rtmp_location.rstrip("/").split("/")
        if len(parts) > 4:
            return "/".join(parts[:-1]) + "/..."
        return self._rtmp_location

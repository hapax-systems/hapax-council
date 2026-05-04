"""Steam Deck capture pipeline + SHM writer.

Spawns a GStreamer pipeline that reads the Magewell-captured Steam
Deck HDMI feed (V4L2 ``/dev/video<N>``), applies the redaction mask,
converts to BGRA, and writes each frame atomically to
``/dev/shm/hapax-sources/steamdeck-display.rgba`` (tmp + rename).
A sidecar JSON next to the SHM file carries width / height / stride
+ epoch timestamp so the compositor's ``shm_rgba`` backend can size
its surface correctly across resolution changes.

Format mirrors the M8 ward byte-for-byte (BGRA, stride = 4 × width)
so the existing :class:`agents.studio_compositor.shm_rgba_reader.ShmRgbaReader`
handles the Steam Deck source without code change.

Hardware-free design: GStreamer is lazy-imported inside :meth:`start`
so unit tests can construct :class:`SteamDeckCapture`, inspect its
caps + redaction settings, and call :meth:`build_pipeline_description`
without the GStreamer typelibs needing to load.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path

from agents.hapax_steamdeck_bridge.redaction import (
    DEFAULT_REDACTION_MODE,
    RedactionMode,
    RedactionZone,
    mode_from_env,
    redaction_zones_for_mode,
)

log = logging.getLogger(__name__)

DEFAULT_CAPTURE_WIDTH = 1920
DEFAULT_CAPTURE_HEIGHT = 1080
DEFAULT_CAPTURE_FPS = 60

DEFAULT_SHM_DIR = Path("/dev/shm/hapax-sources")
DEFAULT_SHM_PATH = DEFAULT_SHM_DIR / "steamdeck-display.rgba"
DEFAULT_SIDECAR_PATH = DEFAULT_SHM_DIR / "steamdeck-display.json"

# Bytes per pixel — BGRA matches what the compositor's ``shm_rgba``
# backend reads. Stride = width * 4 with no padding.
_BYTES_PER_PIXEL = 4


def _videobox_args(zone: RedactionZone, width: int, height: int) -> str:
    """Render a single ``videobox`` element with the given mask zone.

    GStreamer ``videobox`` crops *or* fills depending on the sign of
    the offsets. We want fill (a black rectangle over the redacted
    region), which is achieved with ``fill=black`` + negative crops
    that exactly match the redaction rectangle. The ``alpha=1.0`` is
    redundant for opaque BGRA but kept for explicitness.

    Coordinates are clipped to the capture frame so an overzealous
    operator-supplied zone cannot push the videobox into negative
    space.
    """

    left = max(0, zone.x)
    top = max(0, zone.y)
    right = max(0, width - min(width, zone.right))
    bottom = max(0, height - min(height, zone.bottom))
    return (
        f"videobox name=mask_{zone.name} "
        f"left={-left} right={-right} top={-top} bottom={-bottom} "
        f"fill=black alpha=1.0"
    )


def build_pipeline_description(
    *,
    v4l2_device: str,
    width: int = DEFAULT_CAPTURE_WIDTH,
    height: int = DEFAULT_CAPTURE_HEIGHT,
    fps: int = DEFAULT_CAPTURE_FPS,
    redaction_zones: tuple[RedactionZone, ...] = (),
    appsink_name: str = "shm_sink",
) -> str:
    """Compose the gst-launch-style pipeline string.

    Pure string composition so tests can assert structure without
    spinning up the runtime. The order of elements matters:

    1. ``v4l2src`` — the Magewell capture device.
    2. ``videoconvert`` — normalize input format to BGRA.
    3. one ``videobox`` per active redaction zone — masks happen
       BEFORE the appsink so redacted pixels never leave the
       pipeline boundary.
    4. ``video/x-raw,format=BGRA,…`` caps filter — locks the SHM
       writer's stride invariant.
    5. ``appsink`` — pulls the buffer into Python for the SHM write.

    Sync is forced off on the appsink so the writer runs at source
    rate even if the compositor is dropping frames.
    """

    elements = [
        f"v4l2src device={v4l2_device}",
        "videoconvert",
    ]
    elements.extend(_videobox_args(z, width, height) for z in redaction_zones)
    elements.append(f"video/x-raw,format=BGRA,width={width},height={height},framerate={fps}/1")
    elements.append(f"appsink name={appsink_name} sync=false drop=true max-buffers=2")
    return " ! ".join(elements)


class SteamDeckCapture:
    """GStreamer capture daemon — V4L2 → BGRA → SHM.

    Constructed by :class:`monitor.SteamDeckMonitor` once an HDMI
    signal is detected. ``start()`` builds the pipeline and a
    background thread services the appsink. ``stop()`` tears the
    pipeline down and removes the SHM files (so a downstream consumer
    sees ``ENOENT`` rather than a stale frame from the previous
    session).
    """

    def __init__(
        self,
        *,
        v4l2_device: str,
        shm_path: Path = DEFAULT_SHM_PATH,
        sidecar_path: Path = DEFAULT_SIDECAR_PATH,
        width: int = DEFAULT_CAPTURE_WIDTH,
        height: int = DEFAULT_CAPTURE_HEIGHT,
        fps: int = DEFAULT_CAPTURE_FPS,
        redaction_mode: RedactionMode | None = None,
        sample_callback: Callable[[bytes, float], None] | None = None,
    ) -> None:
        self._v4l2_device = v4l2_device
        self._shm_path = shm_path
        self._sidecar_path = sidecar_path
        self._width = width
        self._height = height
        self._fps = fps
        self._redaction_mode = redaction_mode or mode_from_env(DEFAULT_REDACTION_MODE)
        self._sample_callback = sample_callback or self._write_to_shm
        self._pipeline = None
        self._stop_evt = threading.Event()

    # ── Public API ────────────────────────────────────────────────────

    @property
    def expected_stride(self) -> int:
        """Bytes per row in the BGRA SHM frame."""

        return self._width * _BYTES_PER_PIXEL

    @property
    def expected_frame_size(self) -> int:
        return self.expected_stride * self._height

    @property
    def redaction_mode(self) -> RedactionMode:
        return self._redaction_mode

    def pipeline_description(self) -> str:
        """Return the gst-launch description this capture will build.

        Exposed publicly so the operator (and tests) can ``gst-launch-1.0``
        the pipeline by hand for debugging.
        """

        zones = redaction_zones_for_mode(self._redaction_mode)
        return build_pipeline_description(
            v4l2_device=self._v4l2_device,
            width=self._width,
            height=self._height,
            fps=self._fps,
            redaction_zones=zones,
        )

    def start(self) -> None:
        """Construct + run the GStreamer pipeline.

        Lazy-imports ``gi.repository.Gst`` so the rest of the package
        (and its tests) can run on systems without GStreamer typelibs.
        Runtime failures (Gst missing, pipeline build error) raise
        :class:`RuntimeError` so the monitor can log + retry.
        """

        try:
            import gi

            gi.require_version("Gst", "1.0")
            from gi.repository import Gst
        except (ImportError, ValueError) as exc:
            raise RuntimeError(f"GStreamer 1.0 unavailable: {exc}") from exc

        if not Gst.is_initialized():
            Gst.init(None)

        description = self.pipeline_description()
        log.info("steamdeck capture pipeline: %s", description)
        try:
            pipeline = Gst.parse_launch(description)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"pipeline parse failed: {exc}") from exc

        appsink = pipeline.get_by_name("shm_sink")
        if appsink is None:
            raise RuntimeError("appsink shm_sink not present in pipeline")
        appsink.set_property("emit-signals", True)
        appsink.connect("new-sample", self._on_new_sample)

        self._pipeline = pipeline
        pipeline.set_state(Gst.State.PLAYING)

    def stop(self) -> None:
        """Stop the pipeline + remove SHM files.

        Removing the SHM files on stop matches the M8 path: a
        compositor that polls SHM during the gap between unplug and
        next plug-in sees ENOENT instead of a stale last-frame.
        """

        self._stop_evt.set()
        if self._pipeline is not None:
            try:
                from gi.repository import Gst

                self._pipeline.set_state(Gst.State.NULL)
            except Exception:  # noqa: BLE001
                log.warning("failed to set pipeline NULL", exc_info=True)
            self._pipeline = None
        for path in (self._shm_path, self._sidecar_path):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                log.debug("could not remove %s", path, exc_info=True)

    # ── Sample handler ────────────────────────────────────────────────

    def _on_new_sample(self, appsink) -> int:
        """``new-sample`` signal callback — pull buffer + dispatch.

        Returns the GStreamer ``FLOW_OK`` integer (0). On any
        exception we log + return FLOW_OK regardless: a single bad
        buffer must not kill the pipeline. The Steam Deck typically
        emits 60 frames / s and this code path is in the hot loop,
        so we keep work minimal.
        """

        try:
            sample = appsink.emit("pull-sample")
            if sample is None:
                return 0
            buf = sample.get_buffer()
            success, mapinfo = buf.map(_get_map_read_flag())
            if not success:
                return 0
            try:
                data = bytes(mapinfo.data)
            finally:
                buf.unmap(mapinfo)
            self._sample_callback(data, time.time())
        except Exception:  # noqa: BLE001
            log.exception("steamdeck appsink sample handler raised; skipping")
        return 0

    def _write_to_shm(self, data: bytes, ts: float) -> None:
        """Default sample callback — atomic SHM + sidecar write.

        Tmp + rename so a reader (the compositor's ``ShmRgbaReader``)
        never sees a torn buffer. Sidecar carries the metadata the
        reader needs to size + reinterpret the SHM bytes.
        """

        if len(data) != self.expected_frame_size:
            log.warning(
                "steamdeck capture buffer size mismatch: got %d bytes, expected %d",
                len(data),
                self.expected_frame_size,
            )
            return

        self._shm_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_fd, tmp_path_str = tempfile.mkstemp(
            prefix=f".{self._shm_path.name}.",
            suffix=".tmp",
            dir=str(self._shm_path.parent),
        )
        try:
            with os.fdopen(tmp_fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path_str, self._shm_path)
        except OSError:
            try:
                os.unlink(tmp_path_str)
            except OSError:
                pass
            log.warning("steamdeck SHM write failed", exc_info=True)
            return

        sidecar = {
            "width": self._width,
            "height": self._height,
            "stride": self.expected_stride,
            "format": "BGRA",
            "ts": ts,
            "fps": self._fps,
            "redaction_mode": self._redaction_mode.value,
        }
        try:
            tmp_fd, tmp_path_str = tempfile.mkstemp(
                prefix=f".{self._sidecar_path.name}.",
                suffix=".tmp",
                dir=str(self._sidecar_path.parent),
            )
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
                json.dump(sidecar, fh)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path_str, self._sidecar_path)
        except OSError:
            log.debug("steamdeck sidecar write failed", exc_info=True)


def _get_map_read_flag() -> int:
    """Look up Gst.MapFlags.READ at call time.

    Gst.init may not have been invoked yet at module-load time; the
    flag enum is only well-defined after init. Looking it up lazily
    keeps the import cycle clean.
    """

    from gi.repository import Gst

    return Gst.MapFlags.READ

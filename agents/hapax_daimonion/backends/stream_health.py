"""Stream health perception backend — OBS stats via obs-websocket.

Polls OBS GetStreamStatus + GetStats to feed stream health Behaviors
into the OBS governance chain (bitrate, dropped frames, encoding lag).
"""

from __future__ import annotations

import logging
import time
from typing import Any

from agents.hapax_daimonion.perception import PerceptionTier
from agents.hapax_daimonion.primitives import Behavior

log = logging.getLogger(__name__)

try:
    import obsws_python
except ImportError:
    obsws_python = None  # type: ignore[assignment]


class StreamHealthBackend:
    """Polls OBS stream stats via obs-websocket.

    Provides:
      - stream_bitrate: float (kbps)
      - stream_dropped_frames: float (percentage)
      - stream_encoding_lag: float (ms)
    """

    def __init__(self, host: str = "localhost", port: int = 4455) -> None:
        self._host = host
        self._port = port
        self._client: Any = None

        self._b_bitrate: Behavior[float] = Behavior(0.0)
        self._b_dropped: Behavior[float] = Behavior(0.0)
        self._b_encoding_lag: Behavior[float] = Behavior(0.0)

    @property
    def name(self) -> str:
        return "stream_health"

    @property
    def provides(self) -> frozenset[str]:
        return frozenset({"stream_bitrate", "stream_dropped_frames", "stream_encoding_lag"})

    @property
    def tier(self) -> PerceptionTier:
        return PerceptionTier.SLOW

    def available(self) -> bool:
        if obsws_python is None:
            return False
        try:
            client = obsws_python.ReqClient(host=self._host, port=self._port)
            client.disconnect()
            return True
        except Exception:
            return False

    def start(self) -> None:
        if obsws_python is None:
            log.info("obsws-python not installed, stream health backend unavailable")
            return
        try:
            self._client = obsws_python.ReqClient(host=self._host, port=self._port)
            log.info("Stream health backend connected to OBS at %s:%d", self._host, self._port)
        except Exception as exc:
            log.info("OBS connection failed for stream health: %s", exc)

    def stop(self) -> None:
        if self._client is not None:
            try:
                self._client.disconnect()
            except Exception:
                pass
            self._client = None

    def contribute(self, behaviors: dict[str, Behavior]) -> None:
        """Poll OBS stats and update behaviors."""
        if self._client is None:
            return

        now = time.monotonic()
        try:
            stats = self._client.get_stats()
            stream_status = self._client.get_stream_status()

            # Extract metrics
            bitrate = getattr(stream_status, "output_bytes", 0) * 8 / 1000  # kbps estimate
            if hasattr(stream_status, "output_skipped_frames") and hasattr(
                stream_status, "output_total_frames"
            ):
                total = stream_status.output_total_frames
                skipped = stream_status.output_skipped_frames
                dropped_pct = (skipped / total * 100) if total > 0 else 0.0
            else:
                dropped_pct = 0.0

            render_lag = getattr(stats, "average_frame_render_time", 0.0)

            self._b_bitrate.update(bitrate, now)
            self._b_dropped.update(dropped_pct, now)
            self._b_encoding_lag.update(render_lag, now)

        except Exception as exc:
            log.debug("OBS stats poll failed: %s", exc)
            self._client = None  # force reconnect

        behaviors["stream_bitrate"] = self._b_bitrate
        behaviors["stream_dropped_frames"] = self._b_dropped
        behaviors["stream_encoding_lag"] = self._b_encoding_lag

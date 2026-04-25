"""Caption JSONL reader + audio↔video offset alignment (ytb-009 Phase 1).

Reads timestamped caption events from the daimonion-written stream
at ``/dev/shm/hapax-captions/live.jsonl`` and exposes a generator
shape suitable for a GStreamer ``cc708overlay`` consumer.

## Event format

One JSON object per line, daimonion-emitted::

    {"ts": 1709876543.123,        # epoch seconds, audio-clock domain
     "text": "the operator says",  # caption text (utf-8)
     "duration_ms": 1800,          # how long to display
     "speaker": "oudepode"}        # optional, for future diarization

The ``speaker`` field is ignored at this layer (out of scope per
ytb-009); reserved so the writer can populate it without a schema
break when the diarization follow-up lands.

## Audio↔video offset

The daimonion timestamps captions in the audio capture clock
domain. The broadcast video clock runs ~50–250 ms ahead due to
encoder + RTMP buffering. ``CaptionReader`` keeps a moving-average
of the offset and applies it on read so the consumer sees timestamps
already aligned to the video clock.

The offset is updated by ``observe_av_offset(audio_ts, video_ts)``
called from the GStreamer pipeline (alpha's follow-up). Tests
inject offsets directly. Without observations the offset stays at
zero — the reader still works, captions just lead the video by a
few hundred ms.
"""

from __future__ import annotations

import json
import logging
import os
from collections import deque
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_CAPTIONS_PATH = Path(
    os.environ.get(
        "HAPAX_CAPTIONS_PATH",
        "/dev/shm/hapax-captions/live.jsonl",
    )
)
# Maximum drift (seconds) per the spec's acceptance criterion.
MAX_AV_DRIFT_S: float = float(os.environ.get("HAPAX_CAPTIONS_MAX_DRIFT_S", "5.0"))
# Moving-average window for the audio↔video offset estimator.
AV_OFFSET_WINDOW: int = int(os.environ.get("HAPAX_CAPTIONS_AV_OFFSET_WINDOW", "16"))


@dataclass(frozen=True)
class CaptionEvent:
    """One caption emitted by the daimonion STT pipeline."""

    ts: float
    """Audio-clock epoch seconds when the speech started."""

    text: str
    """Caption text (utf-8). Daimonion already enforces register / consent."""

    duration_ms: int
    """How long the caption should be on screen."""

    speaker: str | None = None
    """Optional speaker tag. Ignored until the diarization follow-up."""

    def video_aligned(self, av_offset_s: float) -> CaptionEvent:
        """Return a copy with ``ts`` shifted by the audio↔video offset."""
        return CaptionEvent(
            ts=self.ts + av_offset_s,
            text=self.text,
            duration_ms=self.duration_ms,
            speaker=self.speaker,
        )


class CaptionReader:
    """Tail captions JSONL + apply moving-average AV offset on read.

    Constructor parameters
    ----------------------
    captions_path:
        Source JSONL path. Defaults to
        ``/dev/shm/hapax-captions/live.jsonl``.
    cursor_path:
        Optional path for byte-offset cursor persistence. ``None``
        keeps cursor in-memory only (fine for the GStreamer-attached
        consumer that owns lifecycle).
    offset_window:
        How many ``observe_av_offset`` samples to average. Default 16
        gives a ~few-second smoothing horizon at typical caption rates.
    max_drift_s:
        Outlier guard — observations whose magnitude exceeds this are
        dropped (spurious clock jumps shouldn't poison the average).
    """

    def __init__(
        self,
        *,
        captions_path: Path = DEFAULT_CAPTIONS_PATH,
        cursor_path: Path | None = None,
        offset_window: int = AV_OFFSET_WINDOW,
        max_drift_s: float = MAX_AV_DRIFT_S,
    ) -> None:
        self._captions_path = captions_path
        self._cursor_path = cursor_path
        self._cursor: int = self._bootstrap_cursor()
        self._offset_samples: deque[float] = deque(maxlen=max(1, offset_window))
        self._max_drift_s = max_drift_s

    # ── Offset estimator ──────────────────────────────────────────────

    def observe_av_offset(self, audio_ts: float, video_ts: float) -> None:
        """Record one (audio_ts, video_ts) sample for the offset average.

        The offset is ``video_ts - audio_ts``: positive means the video
        clock is ahead of the audio clock, negative means behind. Out-
        of-bounds samples (|offset| > max_drift_s) are dropped: a
        single spike from an encoder hiccup should not wreck the
        smoothing window.
        """
        delta = video_ts - audio_ts
        if abs(delta) > self._max_drift_s:
            log.warning(
                "AV offset sample %.3fs exceeds drift cutoff %.3fs; dropping",
                delta,
                self._max_drift_s,
            )
            return
        self._offset_samples.append(delta)

    @property
    def av_offset_s(self) -> float:
        """Current moving-average AV offset, or 0.0 with no samples."""
        if not self._offset_samples:
            return 0.0
        return sum(self._offset_samples) / len(self._offset_samples)

    # ── Caption stream ────────────────────────────────────────────────

    def read_pending(self):
        """Drain new caption lines; yield ``CaptionEvent`` per valid one.

        Each event is video-clock-aligned via the current moving-average
        offset. Malformed lines and missing files are tolerated; failures
        log and yield nothing rather than raising.
        """
        if not self._captions_path.exists():
            return
        try:
            with self._captions_path.open("rb") as fh:
                fh.seek(self._cursor)
                for raw in fh:
                    self._cursor += len(raw)
                    text = raw.decode("utf-8", errors="replace").strip()
                    if not text:
                        continue
                    try:
                        data = json.loads(text)
                    except json.JSONDecodeError:
                        log.debug("malformed caption line at byte %d", self._cursor)
                        continue
                    event = _parse_event(data)
                    if event is None:
                        continue
                    yield event.video_aligned(self.av_offset_s)
        except OSError:
            log.warning("captions read failed at %s", self._captions_path, exc_info=True)
            return
        self._write_cursor(self._cursor)

    # ── Cursor persistence ───────────────────────────────────────────

    def _bootstrap_cursor(self) -> int:
        """Load cursor from disk; on first ever startup, seek to end."""
        if self._cursor_path is None:
            return self._end_of_file()
        if self._cursor_path.exists():
            try:
                return int(self._cursor_path.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                log.warning(
                    "captions cursor at %s unreadable; seeking to end",
                    self._cursor_path,
                    exc_info=True,
                )
        end = self._end_of_file()
        self._write_cursor(end)
        return end

    def _end_of_file(self) -> int:
        try:
            return self._captions_path.stat().st_size
        except OSError:
            return 0

    def _write_cursor(self, byte_offset: int) -> None:
        if self._cursor_path is None:
            return
        try:
            self._cursor_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._cursor_path.with_suffix(".tmp")
            tmp.write_text(str(byte_offset), encoding="utf-8")
            tmp.replace(self._cursor_path)
        except OSError:
            log.warning(
                "captions cursor write failed at %s",
                self._cursor_path,
                exc_info=True,
            )


def _parse_event(data: object) -> CaptionEvent | None:
    """Parse one caption dict; return None on missing required fields."""
    if not isinstance(data, dict):
        return None
    try:
        ts = float(data["ts"])
        text = str(data["text"])
        duration_ms = int(data.get("duration_ms", 0))
    except (KeyError, TypeError, ValueError):
        return None
    if not text:
        return None
    speaker = data.get("speaker")
    speaker = str(speaker) if speaker else None
    return CaptionEvent(ts=ts, text=text, duration_ms=duration_ms, speaker=speaker)


__all__ = [
    "AV_OFFSET_WINDOW",
    "MAX_AV_DRIFT_S",
    "CaptionEvent",
    "CaptionReader",
]

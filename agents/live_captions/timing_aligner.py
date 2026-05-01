"""Audio-to-video clock-offset estimator for live captions.

Daimonion's STT produces caption events stamped on the audio clock
(``time.time()`` at transcription completion). The GStreamer pipeline
runs on the video clock (PTS in nanoseconds, advancing at the encoded
frame rate). The two clocks are not perfectly aligned: there is a
fixed pipeline latency plus small drift over time.

This module provides a :class:`TimingAligner` that maintains a running
estimate of the offset ``audio_ts - video_pts`` from observed pairs,
and exposes :meth:`align` to project an audio timestamp onto the
video PTS axis.

Pure-logic — no I/O, no async. The Phase 5c GStreamer injector calls
:meth:`record_pair` whenever a fresh ``(audio_ts, video_pts)`` pair
is available (e.g., from a sidechain envelope detector or known TTS
emission boundary) and :meth:`align` for each caption emit.

Algorithm
---------

The aligner stores up to ``window`` recent ``(audio_ts, video_pts)``
pairs and reports the mean offset. The ringbuffer evicts the oldest
sample when full. ``align(audio_ts) -> video_pts`` returns
``audio_ts - mean_offset``. When the window is empty the aligner has
no estimate and returns ``audio_ts`` unchanged with a flag the caller
must check.

Why a simple ring-mean rather than EMA: the operator's pipeline has
small bounded latency drift (microseconds, not seconds), and a fixed
window length gives a hard guarantee that observations older than
``window`` ticks have zero residual influence. Tests pin both the
math and the eviction order.

References
----------

- R5 spec §5 — "Use a running offset estimate (e.g., moving average
  of ``audio_ts - video_pts``)".
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Final

#: Default sample window size. Each pair-observation is one slot; the
#: aligner reports the mean offset across the most recent ``window``
#: samples. 32 samples at the Daimonion ~5/sec sidechain estimate
#: rate gives a ~6-second window.
DEFAULT_WINDOW_SIZE: Final[int] = 32


@dataclass(frozen=True)
class AlignmentResult:
    """Outcome of an ``audio_ts → video_pts`` projection.

    ``video_pts`` is the predicted video-clock value. ``had_estimate``
    is ``False`` when the aligner has not yet recorded any pairs (i.e.
    the projection is just an identity pass-through and the caller
    SHOULD NOT stamp captions on a real frame yet).
    """

    video_pts: float
    had_estimate: bool


@dataclass
class TimingAligner:
    """Running ``audio_ts - video_pts`` offset estimator.

    Construct with default :data:`DEFAULT_WINDOW_SIZE` or override per
    use. ``window`` MUST be a positive integer; values less than 1
    raise :class:`ValueError`.

    Not thread-safe. Callers running the aligner across an event loop
    + GStreamer thread should serialize access via the loop or a
    lock — this module deliberately doesn't take a dependency on
    asyncio or threading primitives.
    """

    window: int = DEFAULT_WINDOW_SIZE
    _offsets: deque[float] = field(default_factory=lambda: deque(maxlen=DEFAULT_WINDOW_SIZE))
    _running_sum: float = 0.0

    def __post_init__(self) -> None:
        if self.window < 1:
            raise ValueError(f"window must be >= 1, got {self.window}")
        # Reseat the deque with the requested maxlen if it differs from
        # the default (the field's default-factory binds to DEFAULT,
        # not to ``self.window``).
        if self._offsets.maxlen != self.window:
            self._offsets = deque(self._offsets, maxlen=self.window)

    @property
    def sample_count(self) -> int:
        """Number of pairs currently retained (caps at ``window``)."""
        return len(self._offsets)

    @property
    def has_estimate(self) -> bool:
        """``True`` once at least one pair has been recorded."""
        return self.sample_count > 0

    @property
    def mean_offset(self) -> float:
        """Mean ``audio_ts - video_pts`` across retained samples.

        ``0.0`` when no samples have been recorded — callers should
        prefer :attr:`has_estimate` to a numeric check, since
        ``mean_offset == 0.0`` is also a legitimate post-observation
        outcome (perfectly aligned clocks).
        """
        if not self._offsets:
            return 0.0
        return self._running_sum / len(self._offsets)

    def record_pair(self, audio_ts: float, video_pts: float) -> None:
        """Record one ``(audio_ts, video_pts)`` observation.

        Maintains an O(1) running sum so :attr:`mean_offset` reads in
        constant time regardless of window size. When the window is
        full, the oldest sample is evicted from both the ringbuffer
        and the running sum.

        Non-finite inputs (``nan`` / ``inf``) are rejected with
        :class:`ValueError` so the running sum stays clean. The
        Phase 5c injector should validate at the boundary so this
        guard is defensive only.
        """
        for label, value in (("audio_ts", audio_ts), ("video_pts", video_pts)):
            if not math.isfinite(value):
                raise ValueError(f"{label}={value!r} is not finite")

        offset = audio_ts - video_pts
        if len(self._offsets) == self.window:
            # Deque is full; the next append evicts the leftmost.
            evicted = self._offsets[0]
            self._running_sum -= evicted
        self._offsets.append(offset)
        self._running_sum += offset

    def align(self, audio_ts: float) -> AlignmentResult:
        """Project an audio timestamp onto the video PTS axis.

        Before any pair has been recorded, the aligner has no estimate
        and returns the input unchanged with ``had_estimate=False``.
        Callers in this state SHOULD hold the caption (or emit a
        filler pair) rather than stamping it on a guessed frame.
        """
        if not self.has_estimate:
            return AlignmentResult(video_pts=audio_ts, had_estimate=False)
        return AlignmentResult(
            video_pts=audio_ts - self.mean_offset,
            had_estimate=True,
        )

    def reset(self) -> None:
        """Clear all observations and reset the running sum.

        Use after a long pipeline gap (operator paused the stream,
        camera dropouts, etc.) where the prior offset estimate would
        be stale.
        """
        self._offsets.clear()
        self._running_sum = 0.0

"""IR VLM motion-gated runner (Phase 2 of cc-task
``ir-perception-replace-zones-with-vlm-classification``).

Council-side companion to the Phase 1 pure-logic helper
(:mod:`shared.ir_vlm_classifier`). This module wraps the classifier in
the budget-and-cache machinery the cc-task spec asks for:

- **Motion gate**: skip the VLM call when the IR frame is nearly
  identical to the previous frame the runner saw. The operator's
  desk is static for long stretches; firing the VLM at the Pi's
  ~3 s cadence would cost dozens of calls per minute for no signal
  change. The gate uses a perceptual hash (16×16 grayscale + mean
  threshold, identical to the existing
  ``scripts/album-identifier.py::image_hash``) and rejects the call
  when the Hamming distance to the prior frame is below threshold.
- **Cache**: when the runner DOES fire, the resulting
  :class:`shared.ir_vlm_classifier.HandSemantics` is held for
  ``cache_ttl_s`` seconds. Repeated calls inside the TTL window
  return the cached value without re-invoking the VLM, even on
  high-motion frames — protects against bursts (e.g., operator
  walks past the camera).
- **Stats**: every tick increments one of four counters (call_made,
  call_skipped_no_motion, call_skipped_cache_hit, call_failed) so
  the daemon owner can surface budget telemetry without reaching
  inside the runner's state.

Pure-logic apart from the injected ``runner`` callable. The
forthcoming systemd unit (Phase 2b) supplies a real LiteLLM HTTP
runner; tests inject a stub.

Out of scope for this slice
---------------------------

- Pi-side fetching of the IR JPEG (the runner takes bytes; the
  daemon owner is responsible for fetching from
  ``http://pi-6:8090/frame.jpg`` or wherever).
- The systemd timer that calls :meth:`tick` on a cadence (Phase 2b).
- Consumer migration — ``_vinyl_probably_playing``,
  ``vinyl_spinning_engine``, perceptual-field populator continue to
  read the legacy ``ir_hand_zone`` enum until Phase 4.
- Persisting the latest ``HandSemantics`` to ``/dev/shm`` so the
  consumers can read it (Phase 2b — depends on the daemon owner
  picking the path).
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Final

from shared.ir_vlm_classifier import HandSemantics, classify_hand_via_vlm

log = logging.getLogger(__name__)

#: Default Hamming-distance threshold below which two frames are
#: considered "the same scene". 0..256 range over a 16×16=256-bit
#: phash; 12 corresponds to about 5% of bits flipped, which empirically
#: catches typing/desk-shift while ignoring sensor noise.
DEFAULT_MOTION_THRESHOLD: Final[int] = 12

#: Default cache TTL — at the Pi's ~3 s cadence this caps the runner
#: at one VLM call per ~5 frames even on continuous motion.
DEFAULT_CACHE_TTL_S: Final[float] = 15.0

#: Length in bytes of the perceptual-hash digest. 16×16 = 256 bits.
_PHASH_BITS: Final[int] = 256


@dataclass
class IrVlmRunnerStats:
    """Counters surfaced for budget telemetry."""

    call_made: int = 0
    call_skipped_no_motion: int = 0
    call_skipped_cache_hit: int = 0
    call_failed: int = 0


@dataclass
class IrVlmRunnerState:
    """Mutable state across :meth:`MotionGatedVlmRunner.tick` calls.

    Held outside the runner class so callers can inject a pre-loaded
    state (e.g., from a persisted snapshot when the daemon restarts).
    """

    last_phash: bytes | None = None
    last_call_ts: float | None = None
    cached: HandSemantics | None = None
    stats: IrVlmRunnerStats = field(default_factory=IrVlmRunnerStats)


def _perceptual_hash(jpeg_bytes: bytes) -> bytes:
    """Return a 256-bit perceptual hash of ``jpeg_bytes``.

    Same shape as the album-identifier helper: downscale to 16×16
    grayscale via PIL, threshold each pixel against the frame's mean,
    pack the resulting bit pattern. Two visually similar frames
    produce phashes with low Hamming distance.

    PIL is the only dependency. When the input bytes do not decode,
    raises :class:`ValueError` so the runner can count the failure
    distinct from a successful no-motion skip.
    """
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover — PIL is required
        raise RuntimeError("PIL is required for the IR VLM runner") from exc
    import io

    try:
        img = Image.open(io.BytesIO(jpeg_bytes)).convert("L").resize((16, 16))
    except Exception as exc:
        raise ValueError(f"could not decode JPEG: {exc}") from exc
    pixels = list(img.getdata())
    avg = sum(pixels) / len(pixels) if pixels else 0
    bits = 0
    for i, p in enumerate(pixels):
        if p > avg:
            bits |= 1 << i
    return bits.to_bytes(_PHASH_BITS // 8, "big")


def _hamming_distance(a: bytes, b: bytes) -> int:
    """Return the Hamming distance between two equal-length byte strings."""
    if len(a) != len(b):
        raise ValueError(f"phash length mismatch: {len(a)} vs {len(b)}")
    return sum(bin(x ^ y).count("1") for x, y in zip(a, b, strict=True))


@dataclass
class TickOutcome:
    """Result of one :meth:`MotionGatedVlmRunner.tick` call.

    ``semantics`` carries the latest :class:`HandSemantics` (cached or
    freshly classified). ``reason`` is one of
    ``"call-made"``, ``"no-motion"``, ``"cache-hit"``, ``"call-failed"``,
    ``"decode-failed"`` and feeds telemetry / log lines.
    """

    semantics: HandSemantics | None
    reason: str


class MotionGatedVlmRunner:
    """Wraps :func:`classify_hand_via_vlm` with motion gating + cache.

    Construct once per daemon process. ``runner`` is the same callable
    shape :func:`classify_hand_via_vlm` requires (Phase 2b supplies a
    real LiteLLM HTTP wrapper; tests inject stubs).
    """

    def __init__(
        self,
        *,
        runner,  # type: ignore[no-untyped-def]
        motion_threshold: int = DEFAULT_MOTION_THRESHOLD,
        cache_ttl_s: float = DEFAULT_CACHE_TTL_S,
        state: IrVlmRunnerState | None = None,
        model: str = "fast",
    ) -> None:
        if motion_threshold < 0:
            raise ValueError(f"motion_threshold must be >= 0, got {motion_threshold}")
        if cache_ttl_s <= 0:
            raise ValueError(f"cache_ttl_s must be > 0, got {cache_ttl_s}")
        self._runner = runner
        self._motion_threshold = motion_threshold
        self._cache_ttl_s = cache_ttl_s
        self._model = model
        self._state = state if state is not None else IrVlmRunnerState()

    @property
    def state(self) -> IrVlmRunnerState:
        return self._state

    @property
    def stats(self) -> IrVlmRunnerStats:
        return self._state.stats

    @property
    def cached(self) -> HandSemantics | None:
        return self._state.cached

    def tick(
        self,
        jpeg_bytes: bytes,
        *,
        now: float | None = None,
    ) -> TickOutcome:
        """One frame in, one outcome out.

        Decision tree:

        1. Decode the frame to a phash. If decode fails, count
           ``call_failed`` and return the cached value (if any).
        2. If the cache is fresh (``now - last_call_ts < cache_ttl_s``),
           skip the VLM call and return the cached value as
           ``"cache-hit"``.
        3. If we have a prior phash AND the Hamming distance to it is
           below ``motion_threshold``, skip the VLM call and return the
           cached value as ``"no-motion"``. (The phash is updated
           regardless so a sequence of small changes can accumulate.)
        4. Otherwise call the VLM. On success, update ``cached`` +
           ``last_call_ts`` + ``last_phash`` and count ``call_made``.
           On runner failure (returns ``None`` or raises), count
           ``call_failed`` and return the prior cached value.
        """
        ts_now = now if now is not None else time.time()

        try:
            phash = _perceptual_hash(jpeg_bytes)
        except ValueError:
            self._state.stats.call_failed += 1
            return TickOutcome(semantics=self._state.cached, reason="decode-failed")

        # Cache freshness: a recently-fired call returns its result for
        # `cache_ttl_s` regardless of motion, capping the per-period
        # call count.
        if (
            self._state.last_call_ts is not None
            and ts_now - self._state.last_call_ts < self._cache_ttl_s
        ):
            self._state.stats.call_skipped_cache_hit += 1
            self._state.last_phash = phash
            return TickOutcome(semantics=self._state.cached, reason="cache-hit")

        # Motion gate: low Hamming distance to the prior phash means
        # the scene is essentially unchanged; reuse the cached value
        # without re-firing the VLM.
        if self._state.last_phash is not None:
            dist = _hamming_distance(phash, self._state.last_phash)
            if dist < self._motion_threshold:
                self._state.stats.call_skipped_no_motion += 1
                self._state.last_phash = phash
                return TickOutcome(semantics=self._state.cached, reason="no-motion")

        # Fresh call.
        result = classify_hand_via_vlm(jpeg_bytes, runner=self._runner, model=self._model)
        if result is None:
            self._state.stats.call_failed += 1
            self._state.last_phash = phash
            return TickOutcome(semantics=self._state.cached, reason="call-failed")

        self._state.cached = result
        self._state.last_call_ts = ts_now
        self._state.last_phash = phash
        self._state.stats.call_made += 1
        return TickOutcome(semantics=result, reason="call-made")


def fingerprint_image(jpeg_bytes: bytes) -> str:
    """Return a short hex fingerprint of ``jpeg_bytes`` for log lines.

    Public helper so Phase 2b daemon logs can correlate which
    rendered frame led to which VLM call without recomputing phashes.
    """
    return hashlib.md5(jpeg_bytes, usedforsecurity=False).hexdigest()[:8]

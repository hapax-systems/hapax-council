"""Unified audio reactivity contract (CVS #149).

Formalizes the operator directive that *any* signal pumped into the Studio
24c (room mic, contact mic, line-in, instrument, YT player) is a first-class
reactivity source — not a bespoke per-source wiring.

Today (pre-bus) two DSP consumers run against 24c virtual sources and they
are not symmetric:

- ``mixer_master`` (FR / Input 2) → ``CompositorAudioCapture`` → shader
  uniforms. 18+ signals.
- ``contact_mic`` (FL / Input 1) → ``ContactMicBackend`` → perception engine
  only. Does not reach shaders.
- Inputs 3-8 → unmapped.

This module declares a ``AudioReactivitySource`` Protocol and a
``UnifiedReactivityBus`` that polls all registered sources, blends
per-band (max wins per bass/mid/treble band), and publishes a snapshot to
``/dev/shm/hapax-compositor/unified-reactivity.json`` at 60 Hz.

Consumer migration is opt-in via ``HAPAX_UNIFIED_REACTIVITY_ACTIVE``
(default OFF). When OFF, direct-AudioCapture paths remain authoritative;
the bus is dormant.

Spec: ``docs/superpowers/specs/2026-04-18-audio-reactivity-contract-design.md``
Sync gap audit (CVS #148): this file also pins the snapshot-before-decay
invariant via ``tests/studio_compositor/test_audio_signal_sync.py``.
"""

from __future__ import annotations

import json
import logging
import math
import os
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

log = logging.getLogger(__name__)

# ── Feature flag ────────────────────────────────────────────────────────────

# When unset/False the bus is dormant and legacy direct-AudioCapture paths
# remain authoritative. Flip ON via environment once consumers have
# migrated and byte-identical behavior has been verified in research mode.
ACTIVE_ENV = "HAPAX_UNIFIED_REACTIVITY_ACTIVE"


def is_active() -> bool:
    """Return True when consumers should read from the unified bus."""
    return os.environ.get(ACTIVE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


# ── Shared-memory publish path ──────────────────────────────────────────────

SHM_DIR = Path(os.environ.get("HAPAX_COMPOSITOR_SHM", "/dev/shm/hapax-compositor"))
SHM_PATH = SHM_DIR / "unified-reactivity.json"

# 60 Hz publish cadence (≈16.67 ms) when driven by ``tick()`` at the
# compositor render rate. Consumers that poll directly should treat any
# snapshot older than ~100 ms as stale.
PUBLISH_PERIOD_S = 1.0 / 60.0
SNAPSHOT_STALE_S = 0.100

# RMS floor below which a source is considered inactive and excluded from
# the blend. Matches the DSP AGC floor used in ``audio_capture.py``.
ACTIVITY_FLOOR_RMS = 1e-4


# ── Signal dataclass ────────────────────────────────────────────────────────


def _safe_float(value: float, *, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp a float to [lo, hi], rejecting NaN / inf.

    Audio DSP occasionally produces NaN (silent buffer → division by zero
    in the normalizer) and inf (overflow on near-clipping input). The bus
    must never propagate these onward to JSON (not a valid JSON token) or
    to the WGSL uniform buffer (NaN * 0 = NaN in shaders, corrupts the
    entire pass). Clamp aggressively at the boundary.
    """
    if not math.isfinite(value):
        return lo
    if value < lo:
        return lo
    if value > hi:
        return hi
    return float(value)


@dataclass(frozen=True)
class AudioSignals:
    """Frozen, NaN-safe snapshot of one source's reactivity state.

    All fields are normalized to [0, 1] at the source boundary except
    ``bpm_estimate`` (0..300, a cycle/min approximation) and
    ``energy_delta`` ([-1, 1]). Consumers must not mutate; bus blending
    produces a new instance.
    """

    rms: float
    onset: float
    centroid: float
    zcr: float
    bpm_estimate: float
    energy_delta: float
    bass_band: float
    mid_band: float
    treble_band: float

    def __post_init__(self) -> None:
        # Validate on construction. Frozen dataclass → use object.__setattr__
        # to replace out-of-range values with clamped safe copies.
        object.__setattr__(self, "rms", _safe_float(self.rms))
        object.__setattr__(self, "onset", _safe_float(self.onset))
        object.__setattr__(self, "centroid", _safe_float(self.centroid))
        object.__setattr__(self, "zcr", _safe_float(self.zcr))
        object.__setattr__(self, "bpm_estimate", _safe_float(self.bpm_estimate, lo=0.0, hi=300.0))
        object.__setattr__(self, "energy_delta", _safe_float(self.energy_delta, lo=-1.0, hi=1.0))
        object.__setattr__(self, "bass_band", _safe_float(self.bass_band))
        object.__setattr__(self, "mid_band", _safe_float(self.mid_band))
        object.__setattr__(self, "treble_band", _safe_float(self.treble_band))

    @classmethod
    def zero(cls) -> AudioSignals:
        """Return the zero signal (silent source / no input)."""
        return cls(
            rms=0.0,
            onset=0.0,
            centroid=0.0,
            zcr=0.0,
            bpm_estimate=0.0,
            energy_delta=0.0,
            bass_band=0.0,
            mid_band=0.0,
            treble_band=0.0,
        )

    def to_dict(self) -> dict[str, float]:
        """Serialize to a plain dict (used by JSON publish path)."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, float]) -> AudioSignals:
        """Inverse of ``to_dict`` — used by consumers reading SHM.

        Raises ``TypeError`` when ``data`` is not a mapping (caller should
        treat this as schema drift and fall back to the zero signal). The
        caller in :func:`read_shm_snapshot` catches the TypeError so a
        corrupt writer cannot propagate AttributeError up to consumer code.
        """
        if not isinstance(data, dict):
            raise TypeError(f"AudioSignals.from_dict expected mapping, got {type(data).__name__}")
        return cls(**{k: float(data.get(k, 0.0)) for k in _SIGNAL_FIELDS})


_SIGNAL_FIELDS: tuple[str, ...] = (
    "rms",
    "onset",
    "centroid",
    "zcr",
    "bpm_estimate",
    "energy_delta",
    "bass_band",
    "mid_band",
    "treble_band",
)


# ── Source Protocol ─────────────────────────────────────────────────────────


@runtime_checkable
class AudioReactivitySource(Protocol):
    """Any PipeWire-fed source that can emit reactivity signals.

    Implementers wrap an existing DSP pipeline (``CompositorAudioCapture``,
    ``ContactMicBackend``, …) and expose its output in the unified
    ``AudioSignals`` shape. ``name`` is the source prefix used in the bus
    snapshot dict (e.g. ``"mixer"``, ``"desk"``, ``"voice"``, ``"yt"``).
    """

    @property
    def name(self) -> str:
        """Source identifier. Must be unique per registration."""
        ...

    def get_signals(self) -> AudioSignals:
        """Poll the underlying DSP for the latest snapshot.

        Called once per bus tick. Implementations should be lock-light
        (copy-under-lock, not DSP-under-lock) and never block longer than
        the tick period.
        """
        ...

    def is_active(self) -> bool:
        """Return True when the source has meaningful input this tick.

        The bus excludes inactive sources from the per-band blend so a
        silent contact mic does not drag down the treble band from a
        loud mixer. Default implementation: ``rms > ACTIVITY_FLOOR_RMS``.
        """
        ...


# ── Unified bus ─────────────────────────────────────────────────────────────


@dataclass
class BusSnapshot:
    """Blended per-band output + per-source breakdown.

    ``per_source`` preserves attribution for consumers that want to route
    a specific source (e.g. director logic reading only ``desk.onset``).
    ``blended`` is the max-per-band merge used for the shader uniform
    bridge by default. ``published_at`` is Unix epoch seconds from the
    writer and lets SHM readers reject stale control input.
    """

    blended: AudioSignals
    per_source: dict[str, AudioSignals] = field(default_factory=dict)
    active_sources: list[str] = field(default_factory=list)
    published_at: float | None = None

    def to_json(self) -> str:
        payload = {
            "blended": self.blended.to_dict(),
            "per_source": {name: sig.to_dict() for name, sig in self.per_source.items()},
            "active_sources": self.active_sources,
        }
        if self.published_at is not None and math.isfinite(self.published_at):
            payload["published_at"] = float(self.published_at)
        return json.dumps(payload, separators=(",", ":"))


class UnifiedReactivityBus:
    """Polls registered sources, blends per-band, publishes to SHM.

    Design notes:

    * Per-band blend strategy is ``max`` per band. The loudest bass source
      drives bass, the loudest treble source drives treble, etc. This
      matches operator intent — patching an instrument into Input 3 should
      make its band dominant without having to touch presets.
    * Onset is also max-blended (any source firing → global onset), while
      RMS is max-blended (loudest source sets the "master" RMS used for
      stimmung + ducking consumers).
    * Inactive sources (``is_active() == False``) are skipped entirely.
    * Publish is atomic (tmp+rename) so partial writes never reach consumers.
    """

    def __init__(
        self,
        *,
        shm_path: Path | None = None,
        ledger_path: Path | None = None,
        ledger_durable_dir: Path | None = None,
        ledger_enabled: bool | None = None,
        ledger_min_period_s: float | None = None,
    ) -> None:
        self._sources: dict[str, AudioReactivitySource] = {}
        self._lock = threading.Lock()
        self._shm_path = shm_path or SHM_PATH
        self._last_snapshot: BusSnapshot | None = None
        if ledger_enabled is None:
            ledger_enabled = shm_path is None or ledger_path is not None
        self._ledger_publisher = None
        if ledger_enabled:
            from shared.audio_source_evidence import (
                DEFAULT_DURABLE_DIR,
                DEFAULT_LEDGER_PATH,
                DEFAULT_LEDGER_PUBLISH_MIN_PERIOD_S,
                AudioSourceLedgerPublisher,
            )

            self._ledger_publisher = AudioSourceLedgerPublisher(
                ledger_path=ledger_path or DEFAULT_LEDGER_PATH,
                durable_dir=ledger_durable_dir or DEFAULT_DURABLE_DIR,
                min_period_s=(
                    DEFAULT_LEDGER_PUBLISH_MIN_PERIOD_S
                    if ledger_min_period_s is None
                    else ledger_min_period_s
                ),
            )

    # ── registration ────────────────────────────────────────────────────

    def register(self, source: AudioReactivitySource) -> None:
        """Register a source. Overwriting silently is a common usage
        pattern during compositor restart — the bus has no lifecycle
        concern beyond "is this name live right now".
        """
        with self._lock:
            self._sources[source.name] = source
        log.info("unified-reactivity: registered source %s", source.name)

    def unregister(self, name: str) -> None:
        with self._lock:
            self._sources.pop(name, None)
        log.info("unified-reactivity: unregistered source %s", name)

    def sources(self) -> list[str]:
        with self._lock:
            return list(self._sources.keys())

    # ── tick ────────────────────────────────────────────────────────────

    def tick(self, *, publish: bool = True) -> BusSnapshot:
        """Poll all sources, blend, optionally publish to SHM.

        Returns the snapshot so in-process consumers (fx_tick) can read
        without a SHM round-trip. SHM publish is for cross-process
        consumers (reverie imagination daemon, daimonion).
        """
        with self._lock:
            sources = dict(self._sources)

        per_source: dict[str, AudioSignals] = {}
        active: list[str] = []
        for name, src in sources.items():
            try:
                signals = src.get_signals()
            except Exception:
                log.debug("unified-reactivity: source %s get_signals raised", name, exc_info=True)
                signals = AudioSignals.zero()
            per_source[name] = signals
            try:
                if src.is_active():
                    active.append(name)
            except Exception:
                log.debug("unified-reactivity: source %s is_active raised", name, exc_info=True)

        blended = self._blend([per_source[name] for name in active])
        snapshot = BusSnapshot(
            blended=blended,
            per_source=per_source,
            active_sources=active,
            published_at=time.time(),
        )
        self._last_snapshot = snapshot

        if publish:
            self._publish(snapshot)
        return snapshot

    # ── blend strategy ──────────────────────────────────────────────────

    @staticmethod
    def _blend(signals: list[AudioSignals]) -> AudioSignals:
        """Max-per-band blend.

        Empty input (no active sources) → zero signal. Single source →
        returned as-is. Multiple → per-field max. Centroid and ZCR are
        averaged across active sources rather than max-blended: two
        sources both peaking treble should report "very bright", not one
        source's centroid alone.
        """
        if not signals:
            return AudioSignals.zero()
        if len(signals) == 1:
            return signals[0]
        return AudioSignals(
            rms=max(s.rms for s in signals),
            onset=max(s.onset for s in signals),
            centroid=sum(s.centroid for s in signals) / len(signals),
            zcr=sum(s.zcr for s in signals) / len(signals),
            bpm_estimate=max(s.bpm_estimate for s in signals),
            energy_delta=max(s.energy_delta for s in signals),
            bass_band=max(s.bass_band for s in signals),
            mid_band=max(s.mid_band for s in signals),
            treble_band=max(s.treble_band for s in signals),
        )

    # ── publish ─────────────────────────────────────────────────────────

    def _publish(self, snapshot: BusSnapshot) -> None:
        """Atomic write to SHM. Swallows IO errors — the bus must not
        crash the compositor if /dev/shm is full.
        """
        try:
            self._shm_path.parent.mkdir(parents=True, exist_ok=True)
            payload = snapshot.to_json()
            fd, tmp_path = tempfile.mkstemp(
                dir=str(self._shm_path.parent),
                prefix=f".{self._shm_path.name}.",
                suffix=".tmp",
            )
            try:
                with os.fdopen(fd, "w") as fh:
                    fh.write(payload)
                os.replace(tmp_path, self._shm_path)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except Exception:
            log.debug("unified-reactivity: publish failed", exc_info=True)
            return

        if self._ledger_publisher is not None:
            self._ledger_publisher.maybe_publish(snapshot)

    # ── consumer read path ─────────────────────────────────────────────

    def last_snapshot(self) -> BusSnapshot | None:
        """In-process access to the most recent tick's snapshot.

        Cross-process consumers should read ``SHM_PATH`` directly via
        ``read_shm_snapshot``.
        """
        return self._last_snapshot


def read_shm_snapshot(
    path: Path | None = None,
    *,
    max_age_s: float | None = SNAPSHOT_STALE_S,
    now: float | None = None,
) -> BusSnapshot | None:
    """Read and deserialize the last published bus snapshot.

    Returns None when:
    - SHM file missing (bus not running)
    - SHM file malformed (mid-write race, filesystem corruption)
    - SHM file has a timestamp older than ``max_age_s``
    - SHM file contains the zero signal across the board (caller may
      prefer direct-AudioCapture fallback in that case)

    Legacy snapshots without ``published_at`` are still accepted during
    rollout. Pass ``max_age_s=None`` to bypass freshness checking.
    """
    shm_path = path or SHM_PATH
    try:
        raw = shm_path.read_text()
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        log.debug("unified-reactivity: malformed SHM snapshot")
        return None
    if not isinstance(data, dict):
        log.debug(
            "unified-reactivity: SHM root is %s, expected mapping",
            type(data).__name__,
        )
        return None
    try:
        published_at_raw = data.get("published_at")
        published_at: float | None = None
        if published_at_raw is not None:
            published_at = float(published_at_raw)
            if not math.isfinite(published_at):
                raise ValueError("published_at must be finite")
            if max_age_s is not None:
                effective_now = time.time() if now is None else float(now)
                if effective_now - published_at > max_age_s:
                    log.debug(
                        "unified-reactivity: stale SHM snapshot age %.3fs > %.3fs",
                        effective_now - published_at,
                        max_age_s,
                    )
                    return None
        blended = AudioSignals.from_dict(data.get("blended", {}))
        per_source_raw = data.get("per_source", {}) or {}
        if not isinstance(per_source_raw, dict):
            raise TypeError(f"per_source must be a mapping, got {type(per_source_raw).__name__}")
        per_source = {name: AudioSignals.from_dict(sig) for name, sig in per_source_raw.items()}
        active_raw = data.get("active_sources", [])
        if not isinstance(active_raw, list):
            raise TypeError(f"active_sources must be a list, got {type(active_raw).__name__}")
        active = [str(item) for item in active_raw]
    except (TypeError, ValueError):
        log.debug("unified-reactivity: SHM snapshot schema drift", exc_info=True)
        return None
    return BusSnapshot(
        blended=blended,
        per_source=per_source,
        active_sources=active,
        published_at=published_at,
    )


# ── Singleton accessor ──────────────────────────────────────────────────────

_BUS_SINGLETON: UnifiedReactivityBus | None = None
_BUS_SINGLETON_LOCK = threading.Lock()


def get_bus() -> UnifiedReactivityBus:
    """Process-local bus singleton. Each service (compositor, daimonion)
    runs its own instance — the bus is not cross-process except via the
    SHM publish path.
    """
    global _BUS_SINGLETON
    with _BUS_SINGLETON_LOCK:
        if _BUS_SINGLETON is None:
            _BUS_SINGLETON = UnifiedReactivityBus()
        return _BUS_SINGLETON


def reset_bus_for_tests() -> None:
    """Clear the process-local singleton. Tests only."""
    global _BUS_SINGLETON
    with _BUS_SINGLETON_LOCK:
        _BUS_SINGLETON = None

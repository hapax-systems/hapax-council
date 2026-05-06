"""Ward ↔ FX bidirectional event bus.

HOMAGE Phase 6 Layer 5 — the operator-directive "wards are supposed to be
highly dynamically integrated with the composite layer: engaging in
rotation, cycling, etc whose motions and dynamism is supported by
composite effect layers or usage" (2026-04-19).

Two event types flow through a single thread-safe pubsub bus:

* :class:`WardEvent` — published when a ward FSM transitions (entering,
  emphasized, exiting, etc.). Consumed by the FX chain reactor to
  modulate shader params / preset-family bias.
* :class:`FXEvent` — published when the FX chain fires a significant
  event (preset family change, audio kick onset, chain swap, intensity
  spike). Consumed by Cairo ward sources + the rendering layer to
  trigger accent-pulses / scale bumps / brightness spikes.

The bus is a process-local in-memory pubsub with a ring buffer of the
last 100 events mirrored to
``/dev/shm/hapax-compositor/ward-fx-events.jsonl`` for cross-agent
observability (daimonion reads this to align voice register; Grafana /
debugging can tail it).

Thread-safety: the compositor is multi-threaded (GStreamer streaming
threads, Cairo render threads, GLib main loop, prometheus poll thread).
Publish / subscribe / ring-buffer reads are guarded by a single
``threading.Lock`` — event volume is low (~ones per second, not
thousands), so lock contention is not a performance concern. Subscribers
are invoked *outside* the lock so a slow subscriber never starves the
producer.

Why two event types on one bus: the coupling is bidirectional, and both
sides want to see both flows in the observability stream (e.g. an
``audio_kick_onset`` immediately followed by an ``ENTERING`` ward event
is a visible causal chain worth reading back in a single jsonl tail).
Separate ``WardEvent`` / ``FXEvent`` classes keep the types honest.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

log = logging.getLogger(__name__)


# ── Event types ──────────────────────────────────────────────────────────


WardTransition = Literal[
    "ABSENT_TO_ENTERING",
    "ENTERING_TO_HOLD",
    "HOLD_TO_EMPHASIZED",
    "EMPHASIZED_TO_HOLD",
    "HOLD_TO_EXITING",
    "EMPHASIZED_TO_EXITING",
    "EXITING_TO_ABSENT",
]
"""FSM transition names broadcast by ward sources.

Derived from :class:`agents.studio_compositor.homage.transitional_source.TransitionState`
plus the EMPHASIZED sub-state some wards declare for environmental
salience emphasis. Producers emit the string pair; the reactor routes."""


WardDomain = Literal[
    "communication",
    "presence",
    "token",
    "music",
    "cognition",
    "director",
    "perception",
]
"""Coarse classification every ward is tagged with. Drives the
domain → preset-family bias in :mod:`ward_fx_mapping`. Every Cairo
ward/PiP/overlay-zone maps to exactly one domain; wards that legitimately
straddle (e.g. ``recruitment_candidate_panel`` is cognition + director)
pick the stronger signal for their primary. Ambiguous wards default to
``perception`` so domain-aware modulation stays conservative."""


FXEventKind = Literal[
    "preset_family_change",
    "audio_kick_onset",
    "chain_swap",
    "intensity_spike",
]


@dataclass(frozen=True, slots=True)
class WardEvent:
    """One FSM-transition event published by a ward source.

    ``intensity`` is optional [0.0, 1.0] — producers that track salience
    (e.g. the environmental-salience pipeline, HARDM's weighted bias)
    attach it so the reactor can scale FX modulation by ward importance.
    Absent / unknown intensity defaults to ``0.5`` in the reactor so the
    default behaviour is middling modulation, not zero.
    """

    ward_id: str
    transition: WardTransition
    domain: WardDomain
    intensity: float = 0.5
    ts: float = field(default_factory=time.monotonic)


@dataclass(frozen=True, slots=True)
class FXEvent:
    """One FX-chain event published by the preset selector / fx_tick.

    ``preset_family`` is ``""`` for non-family events (``audio_kick_onset``,
    ``intensity_spike``) so consumers can always read the field safely.
    ``strength`` is a normalized [0.0, 1.0] event magnitude. Producers that only
    know that an event happened can omit it and retain the historical full-strength
    ward reaction.

    The [0.0, 1.0] invariant on ``strength`` is enforced at construction
    (``__post_init__``) — this is the SINGLE canonical attenuation site.
    Producers and consumers trust the invariant; neither needs to re-clamp.
    """

    kind: FXEventKind
    preset_family: str = ""
    strength: float = 1.0
    ts: float = field(default_factory=time.monotonic)

    def __post_init__(self) -> None:
        clamped = max(0.0, min(1.0, float(self.strength)))
        if clamped != self.strength:
            object.__setattr__(self, "strength", clamped)


# ── Bus ──────────────────────────────────────────────────────────────────


_RING_BUFFER_CAPACITY: int = 100
"""How many recent events to retain in memory + mirror to JSONL.

100 covers ~5–10 s of typical bidirectional traffic, enough for the
daimonion voice-register alignment use case and for interactive
debugging without turning the SHM file into an unbounded log."""


_JSONL_PATH: Path = Path("/dev/shm/hapax-compositor/ward-fx-events.jsonl")
"""Ring-buffer mirror. Overwritten (atomic tmp+rename) every publish so
readers always see the current last-100 snapshot, not a monotonically
growing file. `tail -f` does NOT work here by design — consumers poll.

Environment override: ``HAPAX_WARD_FX_JSONL_PATH`` — tests and ops
can redirect the sink without monkeypatching the module global."""


def _resolved_jsonl_path() -> Path:
    override = os.environ.get("HAPAX_WARD_FX_JSONL_PATH")
    if override:
        return Path(override)
    return _JSONL_PATH


_WardSubscriber = Callable[[WardEvent], None]
_FXSubscriber = Callable[[FXEvent], None]


class WardFxBus:
    """Process-local pubsub for ward ↔ FX events.

    Construct once (see :func:`get_bus`). Subscribers register callables
    via :meth:`subscribe_ward` / :meth:`subscribe_fx`. Producers call
    :meth:`publish_ward` / :meth:`publish_fx`. Every publish also
    appends to the in-memory ring buffer + writes the mirrored JSONL
    snapshot atomically (tmp+rename).

    The bus never raises into the producer's hot path: subscriber
    exceptions are logged + swallowed. The JSONL mirror is best-effort —
    a failing write is logged at DEBUG and discarded.
    """

    def __init__(self, *, jsonl_path: Path | None = None) -> None:
        self._lock = threading.Lock()
        self._ward_subscribers: list[_WardSubscriber] = []
        self._fx_subscribers: list[_FXSubscriber] = []
        self._ring: deque[dict] = deque(maxlen=_RING_BUFFER_CAPACITY)
        self._jsonl_path = jsonl_path if jsonl_path is not None else _resolved_jsonl_path()

    # ── Subscription ─────────────────────────────────────────────────

    def subscribe_ward(self, callback: _WardSubscriber) -> None:
        """Register a callback for every WardEvent published hereafter."""
        with self._lock:
            self._ward_subscribers.append(callback)

    def subscribe_fx(self, callback: _FXSubscriber) -> None:
        """Register a callback for every FXEvent published hereafter."""
        with self._lock:
            self._fx_subscribers.append(callback)

    def unsubscribe_ward(self, callback: _WardSubscriber) -> None:
        with self._lock:
            try:
                self._ward_subscribers.remove(callback)
            except ValueError:
                pass

    def unsubscribe_fx(self, callback: _FXSubscriber) -> None:
        with self._lock:
            try:
                self._fx_subscribers.remove(callback)
            except ValueError:
                pass

    # ── Publish ──────────────────────────────────────────────────────

    def publish_ward(self, event: WardEvent) -> None:
        """Broadcast one WardEvent to every subscriber + mirror to JSONL."""
        with self._lock:
            subscribers = list(self._ward_subscribers)
            self._ring.append(
                {"kind": "ward", "data": asdict(event), "logged_at": time.monotonic()}
            )
            ring_snapshot = list(self._ring)
        self._dispatch_ward(subscribers, event)
        self._mirror_jsonl(ring_snapshot)
        self._emit_counter("ward", event.transition, event.ward_id, preset_family="")

    def publish_fx(self, event: FXEvent) -> None:
        """Broadcast one FXEvent to every subscriber + mirror to JSONL."""
        with self._lock:
            subscribers = list(self._fx_subscribers)
            self._ring.append({"kind": "fx", "data": asdict(event), "logged_at": time.monotonic()})
            ring_snapshot = list(self._ring)
        self._dispatch_fx(subscribers, event)
        self._mirror_jsonl(ring_snapshot)
        self._emit_counter("fx", event.kind, ward_id="", preset_family=event.preset_family)

    # ── Latency observation ──────────────────────────────────────────

    def observe_coupling_latency(self, seconds: float, direction: str) -> None:
        """Record the ward→FX (or FX→ward) response latency.

        ``direction`` ∈ {``"ward_to_fx"``, ``"fx_to_ward"``}. Best-
        effort — failures are swallowed so a missing prometheus_client
        never trips the hot path.
        """
        try:
            from agents.studio_compositor import metrics as _metrics

            hist = getattr(_metrics, "HAPAX_WARD_FX_LATENCY_SECONDS", None)
            if hist is not None:
                hist.labels(direction=direction).observe(max(0.0, float(seconds)))
        except Exception:
            log.debug("ward_fx_bus latency observe failed", exc_info=True)

    # ── Inspection ───────────────────────────────────────────────────

    def recent(self) -> tuple[dict, ...]:
        """Return an immutable snapshot of the last N ring-buffer events."""
        with self._lock:
            return tuple(self._ring)

    def ward_subscriber_count(self) -> int:
        with self._lock:
            return len(self._ward_subscribers)

    def fx_subscriber_count(self) -> int:
        with self._lock:
            return len(self._fx_subscribers)

    # ── Internals ────────────────────────────────────────────────────

    def _dispatch_ward(self, subscribers: list[_WardSubscriber], event: WardEvent) -> None:
        for cb in subscribers:
            try:
                cb(event)
            except Exception:
                log.warning("ward_fx_bus: ward subscriber %r raised", cb, exc_info=True)

    def _dispatch_fx(self, subscribers: list[_FXSubscriber], event: FXEvent) -> None:
        for cb in subscribers:
            try:
                cb(event)
            except Exception:
                log.warning("ward_fx_bus: fx subscriber %r raised", cb, exc_info=True)

    def _mirror_jsonl(self, ring_snapshot: list[dict]) -> None:
        """Atomic overwrite of the ring-buffer mirror."""
        try:
            path = self._jsonl_path
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            with tmp.open("w", encoding="utf-8") as fh:
                for entry in ring_snapshot:
                    fh.write(json.dumps(entry))
                    fh.write("\n")
            tmp.replace(path)
        except Exception:
            log.debug("ward_fx_bus: jsonl mirror failed", exc_info=True)

    def _emit_counter(
        self,
        direction: str,
        kind: str,
        ward_id: str,
        *,
        preset_family: str,
    ) -> None:
        """Increment the hapax_ward_fx_events_total counter. Best-effort."""
        try:
            from agents.studio_compositor import metrics as _metrics

            counter = getattr(_metrics, "HAPAX_WARD_FX_EVENTS_TOTAL", None)
            if counter is None:
                return
            counter.labels(
                direction=direction,
                kind=kind,
                ward_id=ward_id,
                preset_family=preset_family,
            ).inc()
        except Exception:
            log.debug("ward_fx_bus counter emit failed", exc_info=True)


# ── Module singleton ─────────────────────────────────────────────────────


_bus_lock = threading.Lock()
_bus: WardFxBus | None = None


def get_bus() -> WardFxBus:
    """Return the process-global :class:`WardFxBus` singleton."""
    global _bus
    if _bus is None:
        with _bus_lock:
            if _bus is None:
                _bus = WardFxBus()
    return _bus


def reset_bus_for_testing() -> None:
    """Tests use this to drop the singleton between cases.

    Not for production callers — subscribers connected to the previous
    bus instance become orphaned. The new bus instance also inherits the
    env-var JSONL override, so tests that monkeypatch
    ``HAPAX_WARD_FX_JSONL_PATH`` get an isolated sink.
    """
    global _bus
    with _bus_lock:
        _bus = None


__all__ = [
    "FXEvent",
    "FXEventKind",
    "WardDomain",
    "WardEvent",
    "WardFxBus",
    "WardTransition",
    "get_bus",
    "reset_bus_for_testing",
]

"""Micromove advance consumer (cc-task u4-micromove-advance-tick-consumer Phase 1).

Per ``/tmp/wsjf-path-director-moves.md`` §4 item 2 + §3 G7: U4 substrate
(8-slot micromove cycle, ``shared/micromove_cycle.py``) shipped via PR
#2328 but the advance consumer is missing — substrate is dormant. This
module ships the consumer that ACTUALLY advances slots + emits visible
parameter deltas + increments the Prometheus counter.

Cadence: per-tick, **15-second wall clock** (the slower of the two
choices in the cc-task — director-loop-cadence-bump may land separately,
but 15 s is the ward-evidence cadence that survives independent of that).
Over a 5-minute window: 20 ticks → 2.5 full cycles → ≥6 of 8 slots
guaranteed to fire (acceptance criterion).

Output paths:
- ``/dev/shm/hapax-compositor/micromove-advance.json``: latest slot +
  hint, atomic-rename. Compositor camera-tile transform / shader uniform
  bridge consume this on next render. Single-writer (this consumer);
  many-reader (compositor render path).
- Prometheus counter ``hapax_micromove_advance_total{slot}``: emitted
  via the prometheus_client default registry. Scraped at the existing
  ``:9482`` compositor metrics endpoint.

Phase 2 wiring (out of scope for this PR; ``u4-micromove-render-bridge``):
- Compositor camera-tile transform reads micromove-advance.json on next
  render (camera scale/pan/rotate per slot hint).
- Shader uniform bridge writes corresponding ``noise.frequency_offset``
  / ``colorgrade.hue_shift`` deltas into uniforms.json (the
  visual-chain → GPU bridge already wires uniforms.json into the
  reverie pipeline).

Per memory ``feedback_no_presets_use_parametric_modulation``: the
consumer is parametric — modulating per-node params, NOT swapping
presets. The slot hint is a delta within an envelope, applied
per-node by the downstream compositor on next render.

Per memory ``feedback_no_expert_system_rules``: the slot → param
mapping is the declarative table in ``MICROMOVE_SLOTS`` (substrate
side, PR #2328); this consumer is a pure dispatcher.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Final

from prometheus_client import Counter

from shared.micromove_cycle import MICROMOVE_SLOTS, MicromoveAction, MicromoveCycle

log = logging.getLogger(__name__)

#: Default 15-second cadence — chosen as the slower of the two
#: per-tick options in the cc-task. Long enough that scrape jitter
#: doesn't double-fire; short enough that ≥6 of 8 slots fire in a
#: 5-minute live-verification window.
DEFAULT_TICK_INTERVAL_S: Final[float] = 15.0

#: Default output path for the latest advance state. tmpfs (/dev/shm)
#: chosen so writes are atomic + fast + don't survive reboot (consumer
#: re-establishes on each compositor restart).
DEFAULT_ADVANCE_STATE_PATH: Final[Path] = Path("/dev/shm/hapax-compositor/micromove-advance.json")

#: Prometheus counter — increments per advance, labelled by slot index
#: 0-7 to match ``MICROMOVE_SLOTS``.
hapax_micromove_advance_total: Counter = Counter(
    "hapax_micromove_advance_total",
    "Number of micromove cycle advances per slot",
    labelnames=("slot",),
)


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    """Write JSON with atomic rename so the compositor never sees half-written.

    Uses tempfile in same directory so rename is on the same filesystem
    (atomic). Mode 0o644 — the compositor reads it; no need for tighter.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_str = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_str)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f, sort_keys=True)
        os.replace(tmp, path)
    except Exception:
        # Best-effort cleanup if fdopen / json.dump raised.
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


class MicromoveAdvanceConsumer:
    """Drives a ``MicromoveCycle`` forward + emits state for downstream consumers.

    Usage:
        consumer = MicromoveAdvanceConsumer()
        # In a periodic loop (systemd timer, asyncio task, etc.):
        consumer.advance()  # one slot per call

    The consumer is **idempotent within a single call**: each call
    advances exactly one slot and emits exactly one record + one counter
    increment. Re-entering ``advance()`` from another thread is
    safe (cycle is internally locked).

    Output schema (the JSON file written each tick):

        {
            "slot": 3,
            "name": "pan-right",
            "axis": "spatial",
            "description": "Drift attention right — invite peripheral curiosity",
            "hint": { "compositor_transform": {"pan_x": 0.04}, ... },
            "advanced_at": 1717..., # epoch seconds
        }
    """

    def __init__(
        self,
        *,
        cycle: MicromoveCycle | None = None,
        state_path: Path = DEFAULT_ADVANCE_STATE_PATH,
        clock: object = None,
    ) -> None:
        self._cycle = cycle if cycle is not None else MicromoveCycle()
        self._state_path = state_path
        # ``clock`` is a callable returning epoch seconds; defaults to
        # ``time.time``. Tests inject a fake for determinism.
        self._clock = clock if clock is not None else time.time

    @property
    def cycle(self) -> MicromoveCycle:
        """Read-only accessor for the underlying cycle (test introspection)."""
        return self._cycle

    @property
    def state_path(self) -> Path:
        return self._state_path

    def advance(self) -> MicromoveAction:
        """Advance one slot, write state, increment counter.

        Returns the new current action so callers (e.g. the periodic
        driver) can log + telemetry without re-reading state.
        """
        action = self._cycle.tick()

        # Increment counter BEFORE writing state — if the write fails
        # (disk full, /dev/shm not mounted), the metrics still reflect
        # that the advance happened. The compositor's render path is
        # tolerant of a missing state file (treats as no-op).
        hapax_micromove_advance_total.labels(slot=str(action.slot)).inc()

        payload: dict[str, object] = {
            "slot": action.slot,
            "name": action.name,
            "axis": action.axis,
            "description": action.description,
            "hint": dict(action.hint),
            "advanced_at": float(self._clock()),
        }
        try:
            _atomic_write_json(self._state_path, payload)
        except OSError:
            log.warning(
                "micromove advance state write failed; counter still incremented",
                exc_info=True,
            )

        return action

    def latest_state(self) -> dict[str, object] | None:
        """Read the last-written state (None if file missing)."""
        if not self._state_path.is_file():
            return None
        try:
            with self._state_path.open() as f:
                payload = json.load(f)
            if not isinstance(payload, dict):
                return None
            return payload
        except (OSError, json.JSONDecodeError):
            log.debug("latest_state() read failed", exc_info=True)
            return None


def all_slot_indices() -> tuple[int, ...]:
    """Return the canonical slot index tuple (0..7).

    Helper for tests + driver code that wants to verify all 8 slots
    have fired without re-walking ``MICROMOVE_SLOTS``.
    """
    return tuple(action.slot for action in MICROMOVE_SLOTS)


__all__ = [
    "DEFAULT_ADVANCE_STATE_PATH",
    "DEFAULT_TICK_INTERVAL_S",
    "MicromoveAdvanceConsumer",
    "all_slot_indices",
    "hapax_micromove_advance_total",
]

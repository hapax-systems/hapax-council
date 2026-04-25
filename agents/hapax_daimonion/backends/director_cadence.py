"""Director cadence missed → SystemDegradedEngine signal adapter (Phase 6d-i.B).

Fourth of four Phase 6d-i.B signal adapters (closing the loop with
#1362 ``engine_queue_depth.py`` + ``drift_significant.py`` +
``gpu_pressure.py``). Wraps the director loop's emission cadence into
the ``director_cadence_missed`` observation shape consumed by
``SystemDegradedEngine``.

Director cadence is a meta-signal about Hapax's expression pipeline:
when impingements are queued AND the director has not emitted narration
for several consecutive ticks, something downstream is wedged
(LLM-call hang, recruitment veto storm, capability gate misfire). The
default threshold (``ticks_since_last_emission > 2`` with ``queued > 0``)
matches the original SystemDegradedEngine docstring's heuristic and
catches the wedge within a few ticks while remaining tolerant of normal
queue-empty quiet periods.

Reference doc: ``docs/operations/2026-04-25-workstream-realignment-v4-audit-incorporated.md``
§5.1 beta queue (Phase 6d-i.B remaining 3-of-4 signals).
"""

from __future__ import annotations

from typing import Protocol

# Default cadence-miss threshold — strictly more than this many ticks
# without an emission counts as missed cadence. 2 ticks mirrors the
# SystemDegradedEngine docstring (engine.py:63) and the engine's
# k_enter=2 dwell, so a sustained cadence miss flips the meta-claim
# DEGRADED in a single dwell window.
DEFAULT_TICK_THRESHOLD: int = 2


class _DirectorCadenceSource(Protocol):
    """Anything exposing
    ``director_cadence_state() -> tuple[int, int]``
    (ticks_since_last_emission, queued_impingements) is acceptable.

    Production sources include the director loop's tick counter +
    ``/dev/shm/hapax-dmn/impingements.jsonl`` queue depth derived from
    the impingement-cursor delta; tests use a stub.
    """

    def director_cadence_state(self) -> tuple[int, int]: ...


def director_cadence_observation(
    source: _DirectorCadenceSource,
    *,
    tick_threshold: int = DEFAULT_TICK_THRESHOLD,
) -> dict[str, bool | None]:
    """Build a single-tick observation dict for SystemDegradedEngine.

    Returns ``{"director_cadence_missed": True}`` only when BOTH:
    1. ``ticks_since_last_emission > tick_threshold``, AND
    2. ``queued_impingements > 0``

    Otherwise emits ``{"director_cadence_missed": False}``. The conjoined
    gate prevents quiet-period false positives (no impingements queued
    means there is nothing for the director to emit narration about, so
    silence is correct rather than degraded).

    Caller pattern::

        from agents.hapax_daimonion.system_degraded_engine import SystemDegradedEngine
        from agents.hapax_daimonion.backends.director_cadence import director_cadence_observation

        engine = SystemDegradedEngine()
        engine.contribute(director_cadence_observation(director_loop))
    """
    ticks_since, queued = source.director_cadence_state()
    return {
        "director_cadence_missed": ticks_since > tick_threshold and queued > 0,
    }


__all__ = [
    "DEFAULT_TICK_THRESHOLD",
    "director_cadence_observation",
]

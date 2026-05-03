"""Perceptual dB-domain ramp (cc-task audio-audit-C-perceptual-db-ramp Phase 0).

The current ducker linearly interpolates ``volume`` in [0, 1] between attack
and release endpoints. Listeners perceive linear amplitude as logarithmic,
so a linear ramp feels "wrong" at both ends — fast at the loud end, slow
at the quiet end. Auditor C wants a true dB-domain ramp:

    gain_db = lerp(start_db, end_db, t)
    amplitude = 10 ** (gain_db / 20)

Phase 0 (this module): the interpolator + amplitude conversion + tests for
the 3 canonical envelope shapes (-inf -> 0 dB attack-end, 0 -> -12 dB
attack-start, -12 -> 0 dB release). No call-site swap; that's Phase 1.

The function takes start_db / end_db / t and returns the linear amplitude
that the ducker writes to PipeWire — so the caller doesn't have to remember
the dB-to-amplitude conversion at every call site.
"""

from __future__ import annotations

# A "fully ducked" floor below which we treat the gain as -inf for amplitude
# purposes (and clamp the ramp to amplitude 0 at the deep end).  -60 dB =
# 0.001 amplitude — well below typical noise floors. Going deeper gains us
# nothing audibly and risks denormal arithmetic on the GPU/DSP downstream.
DUCK_FLOOR_DB: float = -60.0

# Floor on t to handle pathological zero-length envelopes (attack_ms=0).
# Caller passes t = elapsed_ms / window_ms, so t can hit inf if window=0.
# We clamp [0, 1] inside the lerp to keep the contract simple.


def lerp_db(start_db: float, end_db: float, t: float) -> float:
    """Linear interpolation in dB-domain.

    ``t`` is clamped to [0, 1]. Either endpoint may be ``-inf`` (e.g.
    "fully ducked"); the result is ``-inf`` only when both endpoints are
    ``-inf`` OR when the relevant endpoint is reached at the clamped t.
    """
    t_clamped = max(0.0, min(1.0, t))

    # Treat very-low values as -inf for the amplitude conversion later.
    # Avoid float arithmetic with -inf when only one endpoint is below
    # the floor; carry the floor value through instead.
    s = max(start_db, DUCK_FLOOR_DB)
    e = max(end_db, DUCK_FLOOR_DB)
    return s + (e - s) * t_clamped


def amplitude_from_db(db: float) -> float:
    """Convert dB to linear amplitude in [0.0, 1.0].

    ``db == 0`` -> ``1.0``; ``db <= DUCK_FLOOR_DB`` -> ``0.0``;
    ``db > 0`` -> clamped to ``1.0`` (write-time amplitude is bounded).
    """
    if db >= 0.0:
        return 1.0
    if db <= DUCK_FLOOR_DB:
        return 0.0
    return 10.0 ** (db / 20.0)


def perceptual_ramp_amplitude(
    start_db: float,
    end_db: float,
    t: float,
) -> float:
    """Compose ``lerp_db`` + ``amplitude_from_db`` into a single call.

    This is the function the ducker FSM calls per tick: pass start/end of
    the current envelope (attack: 0 -> target_db; release: target_db -> 0)
    and the elapsed-fraction t, get back the amplitude to write.
    """
    return amplitude_from_db(lerp_db(start_db, end_db, t))

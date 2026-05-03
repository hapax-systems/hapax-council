"""Multi-source duck composition (cc-task audio-audit-C-multi-source-product-composition Phase 0).

Today the ducker uses ``max()`` across active sidechain sources. When operator
speech AND a YT clip both want to duck, the result is the deeper of the two
— not the cumulative effect. Auditor C wants product-of-attenuations
(equivalent to summing dB attenuations) so that a 6 dB duck + a 6 dB duck
produces a 12 dB total duck rather than 6 dB.

Phase 0 (this module): a pure function that composes per-source attenuations
in dB-domain and clamps to a max-attenuation envelope. No call-site swap;
that's Phase 1.

Why factor it this way:
- The composition rule is a simple, testable, mostly-pure function. Pinning
  it as a standalone helper means Phase 1 is just "import + replace max()
  call" — no behavioural ambiguity left to argue about during the swap.
- The clamp value (MAX_TOTAL_ATTEN_DB = -24 dB) is the load-bearing
  constant. Pinning it now means a future tweak shows up as a one-line
  diff with full test coverage instead of a buried magic number.
- The amplitude conversion at write-time (``amplitude_from_db``) is a
  trivial helper, but worth co-locating because the ducker's PipeWire
  writer ultimately needs an amplitude, not a dB value.
"""

from __future__ import annotations

from collections.abc import Iterable

# Maximum total attenuation (in dB) the composition will produce.
# - -24 dB = ~0.063 amplitude = -24 dBFS at unity input.
# - Beyond -24 dB, listeners stop perceiving "more duck"; further attenuation
#   just degrades the music to "barely audible" without aiding speech clarity.
# - Operator can override per-call via the max_db arg.
MAX_TOTAL_ATTEN_DB: float = -24.0


def compose_attenuations(
    per_source_db: Iterable[float],
    *,
    max_db: float = MAX_TOTAL_ATTEN_DB,
) -> float:
    """Sum per-source attenuations in dB and clamp to ``max_db``.

    Each ``per_source_db`` value is expected to be 0.0 (no duck) or negative
    (duck). Positive values are silently clamped to 0.0 — a "boost" request
    is not a meaningful ducker semantic; it would manifest as the ducker
    increasing music volume during operator speech.

    Returns the composed attenuation in dB (0.0 or negative), never below
    ``max_db``. The caller converts to amplitude via ``amplitude_from_db``.
    """
    if max_db > 0.0:
        raise ValueError(f"max_db must be <= 0.0, got {max_db}")

    total = 0.0
    for source_db in per_source_db:
        # Boost requests are nonsensical for a ducker; clamp positive to 0.
        if source_db < 0.0:
            total += source_db

    return max(total, max_db)


def amplitude_from_db(db: float) -> float:
    """Convert a dB attenuation (0.0 or negative) to a linear amplitude in [0.0, 1.0].

    ``amp = 10 ** (db / 20)``; ``db == 0`` → ``1.0`` (unity), ``db == -20`` →
    ``0.1``, ``db == -inf`` → ``0.0``. Positive ``db`` is treated as 0
    (unity) — the ducker's amplitude write always lands in [0.0, 1.0].
    """
    if db >= 0.0:
        return 1.0
    return 10.0 ** (db / 20.0)

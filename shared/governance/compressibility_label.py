"""shared/governance/compressibility_label.py — HACL compressibility lattice.

A NEW 4-element total order classifying how compression-safe a context item
is, derived from its DLM ``ConsentLabel`` (``agentgov.consent_label``). This
is the *lattice* organ (organ 2) of the Hapax Adaptive Compression Layer: the
downstream Compressibility Gate (organ 3) folds these labels over a batch and
denies lossy compression unless the supremum is ``SAFE``.

Order (least to most restrictive)::

    SAFE < GUARDED < PROTECTED < UNKNOWN

- ``SAFE``      — public data (``ConsentLabel.bottom()``); lossy-eligible.
- ``GUARDED``   — any non-bottom consent policy attaches; lossless only.
- ``PROTECTED`` — an operator-owned policy attaches; never lossy-compressed.
- ``UNKNOWN``   — unclassified payload (no ``Labeled`` wrapper); fail-closed top.

Join is ``max`` over the total order, so one GUARDED/PROTECTED/UNKNOWN message
poisons a batch upward — there is no way to launder a restrictive item through
aggregation.

Distinct from the ``ConsentLabel`` policy-union join-semilattice itself: that
lattice tracks *who may read*; this one is a verdict ladder for *whether the
bytes may be lossily rewritten*. Pure algebra + mapping; no call-site wiring.

Spec: hapax-research/specs/2026-06-08-hacl-context-compression-design.md
"""

from __future__ import annotations

import enum
from collections.abc import Iterable

from agentgov.consent_label import ConsentLabel
from agentgov.labeled import Labeled

__all__ = [
    "DEFAULT_OPERATOR_IDS",
    "CompressibilityLabel",
    "compressibility_of",
    "join",
    "supremum",
]

#: Principal ids treated as the operator for the PROTECTED rule.
#: Mirrors the convention in ``shared/governance/qdrant_gate.py``.
DEFAULT_OPERATOR_IDS: frozenset[str] = frozenset({"operator", "hapax"})


class CompressibilityLabel(enum.IntEnum):
    """Total order over compression safety; higher = more restrictive."""

    SAFE = 0
    GUARDED = 1
    PROTECTED = 2
    UNKNOWN = 3


def join(a: CompressibilityLabel, b: CompressibilityLabel) -> CompressibilityLabel:
    """Least upper bound: the more restrictive of the two labels."""
    return max(a, b)


def supremum(labels: Iterable[CompressibilityLabel]) -> CompressibilityLabel:
    """Fold ``join`` over a batch. ``SAFE`` (the join identity) for an empty batch.

    One restrictive label poisons the whole batch upward.
    """
    result = CompressibilityLabel.SAFE
    for label in labels:
        result = join(result, label)
    return result


def _of_label(label: ConsentLabel, operator_ids: frozenset[str]) -> CompressibilityLabel:
    if not label.policies:
        return CompressibilityLabel.SAFE
    if any(owner in operator_ids for owner, _readers in label.policies):
        return CompressibilityLabel.PROTECTED
    return CompressibilityLabel.GUARDED


def compressibility_of(
    payload: object,
    surface: str,
    *,
    operator_ids: frozenset[str] = DEFAULT_OPERATOR_IDS,
) -> CompressibilityLabel:
    """Map a context item to its compressibility label. Fail-closed.

    Rules (HACL spec):
    - ``Labeled`` wrapper / bare ``ConsentLabel``: ``bottom()`` => SAFE;
      operator-owned policy => PROTECTED; any other policy => GUARDED.
    - ``None`` / empty payload => SAFE (nothing to protect).
    - Non-empty payload with no ``Labeled`` wrapper => UNKNOWN (fail-closed).

    ``surface`` is the registry surface name the item flows on; the v1 mapping
    is label-driven, but the gate passes it through so per-surface mapping
    policy can land here without an API break.
    """
    del surface  # reserved for per-surface mapping policy (see docstring)
    if isinstance(payload, Labeled):
        return _of_label(payload.label, operator_ids)
    if isinstance(payload, ConsentLabel):
        return _of_label(payload, operator_ids)
    if payload is None:
        return CompressibilityLabel.SAFE
    # Duck-typed emptiness (avoids the runtime-checkable Sized isinstance,
    # which pyrefly flags as an unsafe protocol overlap on `object` payloads).
    sized_len = getattr(payload, "__len__", None)
    if callable(sized_len) and sized_len() == 0:
        return CompressibilityLabel.SAFE
    return CompressibilityLabel.UNKNOWN

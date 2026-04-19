"""Consent live-egress gate — RETIRED by default.

Originally Phase 6 of the volitional-director epic (PR #1017, spec §5 Phase 6),
hardened to fail-closed in Epic 2 Phase A2.

**Retired 2026-04-18:** the face-obscure pipeline (#129) now masks every
camera frame with a Gruvbox-dark pixelation veneer OR full-frame fill at
capture time — BEFORE any tee to RTMP/HLS/V4L2 egress. The face-obscure
fail-closed pipeline is strictly stronger than this layout-swap gate:
it guarantees no un-obscured camera pixel reaches egress, while the
layout swap merely hid camera sources + ward PiPs at the compositor
level (redundant once face-obscure is authoritative).

Axiom `it-irreversible-broadcast` and `interpersonal_transparency` are
now honored at the face-obscure layer, not at the compositor layout
layer. Consent contracts (Agatha, Simon, Jason, …) continue to govern
audio + transcription + interaction recording — those do NOT pass
through face-obscure and retain full consent-contract enforcement.

**Default behavior flipped:** gate is DISABLED by default. Set
``HAPAX_CONSENT_EGRESS_GATE=1|true|on|enabled`` to restore legacy
fail-closed layout-swap behavior. Rationale + governance:
``docs/governance/consent-safe-gate-retirement.md``.

See also: #129 face-obscure spec, ``shared/consent.py``,
``axioms/contracts/``.
"""

from __future__ import annotations

import logging
import os
from typing import Protocol

log = logging.getLogger(__name__)


class _OverlayDataLike(Protocol):
    """Minimal shape the predicate needs from OverlayData."""

    consent_phase: str | None
    guest_present: bool | None
    persistence_allowed: bool | None


# Whitelist of consent phases under which broadcast is permitted.
# The only explicitly-safe phase is `consent_granted` (active contract
# for a present non-operator). A solo-operator state is represented by
# `consent_phase = None` with `guest_present in (None, False)`; that's
# handled separately.
_SAFE_CONSENT_PHASES: frozenset[str] = frozenset({"consent_granted"})

# Phases that must fire compose-safe immediately (legacy gate-enabled
# path only — the default path returns False unconditionally).
_UNSAFE_CONSENT_PHASES: frozenset[str] = frozenset(
    {
        "guest_detected",
        "consent_pending",
        "consent_refused",
    }
)


def should_egress_compose_safe(
    overlay_data: _OverlayDataLike | None,
    *,
    state_is_stale: bool = False,
) -> bool:
    """Return True if the current overlay state requires compose-safe egress.

    **Default (gate disabled):** always returns False. The face-obscure
    pipeline (#129) is the canonical privacy floor — it masks every
    camera frame before any egress tee, so the compositor layout swap
    is redundant and over-protective.

    **Legacy (gate enabled via ``HAPAX_CONSENT_EGRESS_GATE=1``):**
    axiom it-irreversible-broadcast T0 — fail-closed on ambiguity.
    Broadcast is only permitted when all of these hold:

    - ``overlay_data is not None``
    - ``not state_is_stale``
    - EITHER ``consent_phase == "consent_granted"`` (active contract) OR
      solo-operator state (``consent_phase is None`` and
      ``guest_present in (None, False)``)
    - ``guest_present`` is not True without persistence_allowed
    - ``consent_phase`` is not a known-unsafe value
    - ``consent_phase`` is not an unknown string (future phases fail closed)

    Returns True (compose-safe) if any condition is violated AND the
    gate is enabled. Returns False unconditionally when the gate is
    disabled (the new default).
    """
    # Default path: gate disabled — face-obscure is the canonical
    # privacy floor and the compositor layout swap is redundant.
    if not _gate_enabled:
        return False

    if overlay_data is None:
        return True
    if state_is_stale:
        return True

    phase = getattr(overlay_data, "consent_phase", None)
    guest_present = getattr(overlay_data, "guest_present", None)
    persistence_allowed = getattr(overlay_data, "persistence_allowed", None)

    # Known unsafe phases.
    if isinstance(phase, str) and phase in _UNSAFE_CONSENT_PHASES:
        return True

    # Unknown future phases fail closed.
    if isinstance(phase, str) and phase not in _SAFE_CONSENT_PHASES:
        return True

    # Solo-operator is OK: no guest observed, phase unset.
    solo_operator = phase is None and guest_present in (None, False)
    if solo_operator:
        return False

    # Active-contract state: must also have persistence allowance + no
    # flagged guest without allowance.
    if guest_present is True and persistence_allowed is not True:
        return True

    # Phase == "consent_granted" and guest accounted for — broadcast OK.
    # Any other state (phase None but guest_present True, etc.) fails closed.
    return phase != "consent_granted"


def _is_gate_enabled() -> bool:
    """Return True only if the operator has explicitly opted in to the
    legacy fail-closed layout-swap gate via HAPAX_CONSENT_EGRESS_GATE.

    Enabling values: ``1``, ``true``, ``on``, ``enabled``. Anything
    else (including unset) leaves the gate disabled.
    """
    value = os.environ.get("HAPAX_CONSENT_EGRESS_GATE", "").strip().lower()
    return value in {"1", "true", "on", "enabled"}


_gate_enabled = _is_gate_enabled()
if _gate_enabled:
    log.warning(
        "HAPAX_CONSENT_EGRESS_GATE enabled at module load — "
        "legacy fail-closed layout-swap behavior restored. Compose-safe "
        "layout will activate on any ambiguous consent state. Note: "
        "face-obscure (#129) is already authoritative for visual privacy; "
        "this gate is redundant and over-protective for livestream aesthetics."
    )
else:
    log.info(
        "Compose-safe egress gate is DISABLED by default — face-obscure "
        "(#129) provides the canonical privacy floor at all egress paths. "
        "Set HAPAX_CONSENT_EGRESS_GATE=1 to restore legacy fail-closed "
        "layout-swap behavior."
    )


# Location of the consent-safe fallback layout (retained for legacy
# gate-enabled path + any consumer references).
CONSENT_SAFE_LAYOUT_NAME: str = "consent-safe.json"


__all__ = [
    "should_egress_compose_safe",
    "CONSENT_SAFE_LAYOUT_NAME",
]

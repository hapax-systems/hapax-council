"""Quiet-frame programme — zero-opt-in Programme for safety holds.

Phase 11 of ``docs/superpowers/plans/2026-04-20-demonetization-safety-
plan.md``. A prebuilt ``Programme`` the operator (or governance
automation) activates to gate ALL medium-risk capabilities and bias
toward minimum-risk tier bands during sensitive moments:

- Pre-monetization windows (first ~30 s of each stream start — the
  YouTube ContentID classifier is running its first-pass fingerprint
  scan; any brand-name in a title or audible music snippet risks an
  immediate claim)
- Sensitive discussions (operator is talking about something that
  shouldn't surface any external content)
- Cooldown after a ContentID hit (15-min minimum pause on anything
  medium-or-above)

The programme is ``ProgrammeRole.AMBIENT`` with empty
``monetization_opt_ins`` and ``voice_tier_band_prior=(0, 2)`` so the
MonetizationRiskGate blocks everything above ``low``-risk on any
surface and the voice-tier resolver picks a band that stays
intelligible (0-2 = UNADORNED through BROADCAST_GHOST).

Activation model:

- ``operator`` invokes via the CLI or a slash command
- ``governance`` automation activates on ContentID hit detection
  (wiring lands with Phase 3 Ring 2 classifier — task #202)
- Either path writes the programme to the ProgrammePlanStore via
  ``activate(programme_id, now)`` which enforces the one-ACTIVE
  invariant — the quiet frame deactivates any prior Programme
  automatically.

Reference:
    - docs/superpowers/plans/2026-04-20-demonetization-safety-
      plan.md §11
    - docs/governance/monetization-risk-classification.md §medium
    - shared/programme.py — Programme primitive
    - shared/programme_store.py — persistence + activation invariant
"""

from __future__ import annotations

import time
from typing import Final

from shared.programme import (
    Programme,
    ProgrammeConstraintEnvelope,
    ProgrammeRole,
    ProgrammeStatus,
)
from shared.programme_store import ProgrammePlanStore, default_store

QUIET_FRAME_PROGRAMME_ID: Final[str] = "governance.quiet_frame"
QUIET_FRAME_SHOW_ID: Final[str] = "governance.zeroing"
QUIET_FRAME_DEFAULT_DURATION_S: Final[float] = 900.0  # 15 min cooldown default

# Voice-tier band: 0–2 = UNADORNED, RADIO, BROADCAST_GHOST. Picks an
# intelligible band; never engages the granular engine; never needs
# Mode D mutex.
QUIET_FRAME_TIER_BAND: Final[tuple[int, int]] = (0, 2)


def build_quiet_frame_programme(
    *,
    duration_s: float = QUIET_FRAME_DEFAULT_DURATION_S,
    status: ProgrammeStatus = ProgrammeStatus.PENDING,
    reason: str = "governance safety hold",
) -> Programme:
    """Construct the canonical quiet-frame Programme.

    Exact same shape every time — this is the safety default, not a
    user-configurable programme. Operator tweaks ``duration_s`` when
    a cooldown should be longer than the 15-minute default.
    """
    constraints = ProgrammeConstraintEnvelope(
        # Empty opt-ins means EVERY medium-risk capability is blocked by
        # MonetizationRiskGate; high-risk capabilities are already blocked
        # unconditionally.
        monetization_opt_ins=set(),
        # Voice tier band prior — 0–2 keeps speech intelligible, never
        # engages granular engine, never risks Content ID false-positive
        # on tape-loop-like tiers (5–6).
        voice_tier_band_prior=QUIET_FRAME_TIER_BAND,
    )
    return Programme(
        programme_id=QUIET_FRAME_PROGRAMME_ID,
        role=ProgrammeRole.AMBIENT,
        status=status,
        planned_duration_s=duration_s,
        parent_show_id=QUIET_FRAME_SHOW_ID,
        constraints=constraints,
        notes=f"quiet-frame: {reason}",
    )


def activate_quiet_frame(
    store: ProgrammePlanStore | None = None,
    *,
    duration_s: float = QUIET_FRAME_DEFAULT_DURATION_S,
    reason: str = "governance safety hold",
    now: float | None = None,
) -> Programme:
    """Ensure the quiet-frame programme exists + activate it.

    Idempotent with respect to the store: if the quiet-frame programme
    already exists, the record is updated in place; otherwise it's
    added. Either way the store's one-ACTIVE invariant then transitions
    any prior ACTIVE programme to COMPLETED and promotes the quiet
    frame to ACTIVE.

    Args:
        store: Optional ``ProgrammePlanStore`` to activate against.
            Defaults to the module-level ``default_store()``.
        duration_s: Override the default 15-min cooldown.
        reason: Human-readable note appended to the Programme (shows
            up in logs + the store file).
        now: Override clock for testing.

    Returns:
        The ACTIVE Programme as returned by ``store.activate``.
    """
    st = store if store is not None else default_store()
    ts = now if now is not None else time.time()
    existing = st.get(QUIET_FRAME_PROGRAMME_ID)
    programme = build_quiet_frame_programme(
        duration_s=duration_s,
        status=ProgrammeStatus.PENDING,
        reason=reason,
    )
    if existing is None:
        st.add(programme)
    else:
        # Replace the stored record with the freshly-built one (new
        # duration + reason). The store dedupes by programme_id, so
        # re-adding equals overwrite.
        st.add(programme)
    return st.activate(QUIET_FRAME_PROGRAMME_ID, now=ts)


def deactivate_quiet_frame(
    store: ProgrammePlanStore | None = None,
    *,
    now: float | None = None,
) -> Programme | None:
    """Deactivate the quiet-frame programme if currently active.

    Returns None when the quiet frame is not in the store or already
    terminated. Does NOT activate any successor programme — the caller
    decides what comes next.
    """
    st = store if store is not None else default_store()
    existing = st.get(QUIET_FRAME_PROGRAMME_ID)
    if existing is None or existing.status != ProgrammeStatus.ACTIVE:
        return None
    ts = now if now is not None else time.time()
    return st.deactivate(QUIET_FRAME_PROGRAMME_ID, now=ts)

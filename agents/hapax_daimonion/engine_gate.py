"""Engine-gated activation wrappers — Mode D × voice-tier mutex integration.

Phase 2 of ``docs/research/2026-04-20-mode-d-voice-tier-mutex.md``.
Composes ``shared.evil_pet_state.acquire_engine()`` with the two
capabilities that configure the Evil Pet granular engine:

- ``VocalChainCapability.apply_tier`` — voice tiers 0–6
- ``VinylChainCapability.activate_mode_d`` — vinyl anti-DMCA wash

Why external wrappers instead of embedding the gate in each chain:
keeping the chain modules pure (MIDI emission only) preserves the
composable-primitives architecture and keeps the chain tests free of
SHM filesystem pollution. Production callers (daimonion bootstrap,
director_loop, operator CLI) use these gated wrappers; the ungated
methods remain available for isolated unit tests and Phase 1+ of the
mutex (flag-only, no CC emission) that landed alongside this module.

Behaviour:

- ``apply_tier_gated(chain, tier)`` — acquires the appropriate
  ``voice_tier_N`` mode under ``writer='director'``; on
  ``accepted=False`` the tier is NOT applied (no CC emission, no
  state mutation on the chain). Caller inspects the returned
  ``ArbitrationResult`` for logging/telemetry.
- ``activate_mode_d_gated(chain)`` — acquires ``mode_d`` under the
  caller-supplied writer (operator explicit or programme opt-in).
  On block, Mode D is not engaged.
- ``deactivate_mode_d_gated(chain)`` — transitions to ``bypass``
  through the same arbitration so a writer with sufficient authority
  can always release the engine. On success, the legacy flag is
  cleared by ``write_state`` as a side effect.

Telemetry: every call emits a single ``log.info`` or ``log.debug``
line with from/to/writer/reason. No Prometheus metrics in this phase;
the counters described in research §7 land alongside the director-
loop integration in Phase 3.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from shared.evil_pet_state import (
    DEFAULT_STATE_PATH,
    LEGACY_MODE_D_FLAG,
    ArbitrationResult,
    EvilPetMode,
    acquire_engine,
)

if TYPE_CHECKING:
    from shared.voice_tier import VoiceTier

log = logging.getLogger(__name__)


def voice_tier_to_engine_mode(tier: VoiceTier | int) -> EvilPetMode:
    """Map ``VoiceTier`` (or its int value) to the corresponding ``EvilPetMode``.

    The voice-tier spectrum is 0..6; engine modes are ``voice_tier_0``
    through ``voice_tier_6``. Raises ValueError on out-of-range values
    so a mistyped caller fails loud rather than silently selecting the
    wrong tier.
    """
    t = int(tier)
    if not 0 <= t <= 6:
        raise ValueError(f"voice_tier out of range: {t} (expected 0..6)")
    return EvilPetMode(f"voice_tier_{t}")


def apply_tier_gated(
    vocal_chain: Any,
    tier: VoiceTier | int,
    *,
    writer: str = "director",
    programme_opt_in: bool = False,
    state_path: Path = DEFAULT_STATE_PATH,
    legacy_flag: Path = LEGACY_MODE_D_FLAG,
    impingement: Any | None = None,
    now: float | None = None,
) -> ArbitrationResult:
    """Acquire engine → apply tier. On block, no CCs emit and chain is not mutated.

    Args:
        vocal_chain: VocalChainCapability instance. Must expose
            ``apply_tier(tier, impingement=None)`` (Phase 2 of the
            voice-tier spectrum plan).
        tier: ``VoiceTier`` or its integer value.
        writer: Priority-tagged writer identity. ``'director'`` is the
            default for recruitment-driven selection; callers coming
            from an operator CLI or governance revert MUST override.
        programme_opt_in: Pass-through to ``acquire_engine`` for the
            SHM record. Relevant when the director picks a tier inside
            a Programme that has opted in to a T5/T6 excursion.
        state_path / legacy_flag: Injectable for test isolation. The
            production code path uses the module defaults which land in
            ``/dev/shm/hapax-compositor/``.
        impingement: Passed through to ``apply_tier`` for telemetry
            attribution.
        now: Clock-override for deterministic tests.

    Returns:
        ArbitrationResult — ``accepted=True`` means the tier was
        applied; ``accepted=False`` means the chain is untouched and
        the reason code explains why (e.g. ``blocked_by_operator``,
        ``debounce_0.5s``).
    """
    target = voice_tier_to_engine_mode(tier)
    result = acquire_engine(
        target_mode=target,
        writer=writer,
        programme_opt_in=programme_opt_in,
        path=state_path,
        legacy_flag=legacy_flag,
        now=now,
    )
    if not result.accepted:
        log.info(
            "apply_tier_gated: %s blocked (writer=%s, reason=%s)",
            target.value,
            writer,
            result.reason,
        )
        return result
    vocal_chain.apply_tier(tier, impingement=impingement)
    return result


def activate_from_impingement_gated(
    vocal_chain: Any,
    impingement: Any,
    pipeline_score: float,
    *,
    writer: str = "director",
    state_path: Path = DEFAULT_STATE_PATH,
    now: float | None = None,
) -> ArbitrationResult:
    """Gate per-dimension CC emission behind engine ownership.

    Unlike ``apply_tier_gated`` (which transitions the full tier), this
    gates the fine-grained per-dimension activation that the pipeline
    recruits. If the engine is held by Mode D (or any higher-priority
    writer), CCs are suppressed — the vocal chain must not thrash CCs
    against a vinyl regime.

    Acquires the engine in its CURRENT voice-tier mode (heartbeat
    refresh) so ownership doesn't lapse during sustained vocal activity.
    If the engine is in bypass, acquires voice_tier_0 as the baseline.
    """
    import time as _time

    from shared.evil_pet_state import EvilPetMode, read_state

    ts = now if now is not None else _time.time()
    current = read_state(path=state_path, now=ts)

    if current.mode == EvilPetMode.MODE_D and not current.is_stale(ts):
        log.debug(
            "activate_from_impingement_gated: blocked by mode_d (writer=%s)",
            current.writer,
        )
        return ArbitrationResult(
            accepted=False,
            state=current,
            reason="blocked_by_mode_d",
        )

    target = current.mode if current.mode.value.startswith("voice_tier_") else EvilPetMode.VOICE_TIER_0
    result = acquire_engine(
        target_mode=target,
        writer=writer,
        path=state_path,
        now=ts,
    )
    if not result.accepted:
        log.debug(
            "activate_from_impingement_gated: blocked (reason=%s)",
            result.reason,
        )
        return result

    vocal_chain.activate_from_impingement(impingement)
    return result


def activate_mode_d_gated(
    vinyl_chain: Any,
    *,
    writer: str = "operator",
    programme_opt_in: bool = True,
    state_path: Path = DEFAULT_STATE_PATH,
    legacy_flag: Path = LEGACY_MODE_D_FLAG,
    now: float | None = None,
) -> ArbitrationResult:
    """Acquire ``mode_d`` → activate Mode D scene on the vinyl chain.

    Defaults to ``writer='operator'`` because today's primary trigger
    is the ``hapax-vinyl-mode on`` CLI invocation. Programme-driven
    Mode D (once the Programme planner wires in) must pass
    ``writer='programme'`` so the arbitration layer can correctly
    rank governance reverts against it.

    On block, Mode D is NOT engaged and the vinyl chain's
    ``_mode_d_active`` flag is not set. Caller inspects
    ``ArbitrationResult`` to report to the operator.
    """
    result = acquire_engine(
        target_mode=EvilPetMode.MODE_D,
        writer=writer,
        programme_opt_in=programme_opt_in,
        path=state_path,
        legacy_flag=legacy_flag,
        now=now,
    )
    if not result.accepted:
        log.info(
            "activate_mode_d_gated: mode_d blocked (writer=%s, reason=%s)",
            writer,
            result.reason,
        )
        return result
    vinyl_chain.activate_mode_d()
    return result


def deactivate_mode_d_gated(
    vinyl_chain: Any,
    *,
    writer: str = "operator",
    state_path: Path = DEFAULT_STATE_PATH,
    legacy_flag: Path = LEGACY_MODE_D_FLAG,
    now: float | None = None,
) -> ArbitrationResult:
    """Release the engine to ``bypass`` and revert Mode D scene CCs.

    Governance-initiated revert (``writer='governance'``) shares
    priority with operator, so a Programme opt-in revocation can
    always pull the engine out of Mode D even mid-track. The vinyl
    chain's ``deactivate_mode_d()`` writes the restore sequence
    (grains=0, mix=50, shimmer=0) only on accept.
    """
    result = acquire_engine(
        target_mode=EvilPetMode.BYPASS,
        writer=writer,
        programme_opt_in=False,
        path=state_path,
        legacy_flag=legacy_flag,
        now=now,
    )
    if not result.accepted:
        log.info(
            "deactivate_mode_d_gated: bypass blocked (writer=%s, reason=%s)",
            writer,
            result.reason,
        )
        return result
    vinyl_chain.deactivate_mode_d()
    return result

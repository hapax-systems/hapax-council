"""Stream-mode transition gate (LRR Phase 6 §5 + §6).

Two safety gates that operate around the stream-mode axis:

1. **§6 presence-detect T0 block.** Blocks transitions into PUBLIC or
   PUBLIC_RESEARCH if a non-operator person is detected in the presence
   field and no active consent contract covers that person. Enforces the
   ``it-irreversible-broadcast`` implication at the moment of transition.

2. **§5 stimmung-critical auto-private closed loop.** Returns True when the
   live stimmung signal indicates a state where public broadcast is not
   safe (high stress, critical stance, broken health). Designed to be run
   on a timer; the caller sets stream mode to PRIVATE when this returns
   True.

Both are pure decision functions — they do not perform I/O or mutate
state. Callers wrap them in the appropriate action (CLI reject, systemd
timer-driven auto-transition, etc.).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from shared.stream_mode import StreamMode

STIMMUNG_STATE_FILE = Path("/dev/shm/hapax-stimmung/state.json")
# PresenceEngine writes the live presence posterior to this file at every tick.
# The "posterior" field is the Bayesian log-odds probability [0.0, 1.0] that
# a non-operator-identified person is present. Distinct from
# /dev/shm/hapax-dmn/health.json (which is a control-signal health snapshot
# for the daimonion component and does NOT contain presence).
PRESENCE_STATE_FILE = Path("/dev/shm/hapax-daimonion/presence-metrics.json")
PRESENCE_FIELD_NAME = "posterior"


@dataclass(frozen=True)
class TransitionGateResult:
    """Result of a stream-mode transition-gate check."""

    allowed: bool
    reason: str
    blocked_by: str = ""  # "presence_t0" | "stimmung_critical" | "" (when allowed)


def _requires_broadcast_consent(mode: StreamMode) -> bool:
    """True if the target mode requires broadcast-consent contracts."""
    return mode in (StreamMode.PUBLIC, StreamMode.PUBLIC_RESEARCH)


def presence_t0_gate(
    target_mode: StreamMode,
    *,
    presence_probability: float,
    active_broadcast_contracts: frozenset[str],
    presence_threshold: float = 0.5,
) -> TransitionGateResult:
    """LRR Phase 6 §6 — block public transitions on unconsented presence.

    If ``target_mode`` is PUBLIC or PUBLIC_RESEARCH and presence is detected
    (probability >= ``presence_threshold``), there MUST be at least one
    active broadcast-consent contract. Otherwise the transition is blocked.

    When ``target_mode`` is OFF or PRIVATE, the gate always allows the
    transition — only outbound broadcast paths are gated.

    **Modeling note:** presence-probability here is the PresenceEngine
    posterior (hysteresis'd). The threshold of 0.5 matches the engine's
    UNCERTAIN → PRESENT boundary; below 0.5 the system is not confident
    enough that a person is present to gate on.
    """
    if not _requires_broadcast_consent(target_mode):
        return TransitionGateResult(
            allowed=True,
            reason=f"{target_mode.value} does not require broadcast consent",
        )

    if presence_probability < presence_threshold:
        return TransitionGateResult(
            allowed=True,
            reason=(
                f"No presence detected (probability={presence_probability:.2f}"
                f" < threshold={presence_threshold})"
            ),
        )

    if not active_broadcast_contracts:
        return TransitionGateResult(
            allowed=False,
            reason=(
                f"Presence detected (probability={presence_probability:.2f}) "
                f"but no active broadcast-consent contracts. "
                f"Broadcast would violate it-irreversible-broadcast (T0)."
            ),
            blocked_by="presence_t0",
        )

    return TransitionGateResult(
        allowed=True,
        reason=(
            f"Presence detected (probability={presence_probability:.2f}); "
            f"covered by {len(active_broadcast_contracts)} active broadcast contract(s)"
        ),
    )


def stimmung_auto_private_needed(
    stimmung: dict,
    *,
    critical_stance_forces_private: bool = True,
    resource_pressure_threshold: float = 0.85,
    operator_stress_threshold: float = 0.90,
    error_rate_threshold: float = 0.70,
) -> TransitionGateResult:
    """LRR Phase 6 §5 — decide whether to force a PRIVATE transition.

    Reads the live stimmung dict (same shape as ``/dev/shm/hapax-stimmung/
    state.json``) and returns True when broadcast should be pulled back to
    private. The caller (typically a systemd timer) then invokes
    ``set_stream_mode(StreamMode.PRIVATE)``.

    Triggers (any one fires):

    - ``overall_stance == "critical"`` — regulator signal that the system
      should not be broadcasting research surfaces right now
    - ``resource_pressure > threshold`` — infra stress where compositor may
      degrade; better to pull back than broadcast degraded frames
    - ``operator_stress > threshold`` — operator signal; high stress =
      auto-privatize (executive_function axiom compensation)
    - ``error_rate > threshold`` — runtime errors propagating
    """

    def _val(key: str) -> float:
        v = stimmung.get(key)
        if isinstance(v, dict):
            return float(v.get("value", 0.0))
        if isinstance(v, int | float):
            return float(v)
        return 0.0

    stance = stimmung.get("overall_stance", "")

    if critical_stance_forces_private and stance == "critical":
        return TransitionGateResult(
            allowed=False,
            reason="stimmung.overall_stance is 'critical'",
            blocked_by="stimmung_critical",
        )

    resource = _val("resource_pressure")
    if resource > resource_pressure_threshold:
        return TransitionGateResult(
            allowed=False,
            reason=(f"resource_pressure={resource:.2f} > {resource_pressure_threshold}"),
            blocked_by="stimmung_critical",
        )

    stress = _val("operator_stress")
    if stress > operator_stress_threshold:
        return TransitionGateResult(
            allowed=False,
            reason=(f"operator_stress={stress:.2f} > {operator_stress_threshold}"),
            blocked_by="stimmung_critical",
        )

    errors = _val("error_rate")
    if errors > error_rate_threshold:
        return TransitionGateResult(
            allowed=False,
            reason=f"error_rate={errors:.2f} > {error_rate_threshold}",
            blocked_by="stimmung_critical",
        )

    return TransitionGateResult(
        allowed=True,
        reason="Stimmung within public-broadcast safe ranges",
    )


def read_stimmung_snapshot(path: Path | None = None) -> dict:
    """Best-effort read of the live stimmung snapshot.

    Returns ``{}`` on any I/O or parse error — callers should treat
    empty-dict as an unavailable-signal case.
    """
    p = path if path is not None else STIMMUNG_STATE_FILE
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def read_presence_probability(path: Path | None = None) -> float:
    """Read the live presence-probability posterior from PresenceEngine.

    Source of truth: ``/dev/shm/hapax-daimonion/presence-metrics.json``.
    The ``posterior`` field is PresenceEngine's Bayesian probability that
    a non-operator-identified person is present.

    Returns 0.0 on any I/O or parse error — no-information case, which
    means the presence gate will allow (since 0.0 < threshold). The
    fallback is OK for the presence gate specifically because a missing
    presence signal means we cannot confidently block a broadcast on
    presence grounds; the gate's role is to positively confirm presence,
    not to presume it.

    Backward-compat: if a caller passes a path whose payload has the
    legacy ``presence_probability`` key (scalar or nested), that is also
    recognised.
    """
    p = path if path is not None else PRESENCE_STATE_FILE
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0.0

    # Primary path: PresenceEngine's posterior
    val = data.get(PRESENCE_FIELD_NAME)
    if val is None:
        # Backward-compat for alternate writers / legacy tests
        val = data.get("presence_probability")
        if isinstance(val, dict):
            val = val.get("value")
    try:
        return float(val) if val is not None else 0.0
    except (TypeError, ValueError):
        return 0.0

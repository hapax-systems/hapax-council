"""Read-only recovery pressure assessment.

Recovery pressure, liveness, quota, and retry observations are support signals.
They are not authority and cannot admit an effect.  This module intentionally
retains the small pure control calculations used by the coordinator while every
legacy ``permit`` entry point returns HOLD until a caller can present a
``ValidAuthorityGrant``, ``AdmissionDecision``, and exact ``ExecutionLease`` at
the real execution boundary.

No function in this module writes state, starts or kills a process, mutates a
task or claim, mints work, or sends a notification.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, replace

PERMIT, BACKOFF, CLOSED = 0, 75, 2  # compatibility exit codes
OFF_ENV = "HAPAX_RECOVERY_GOVERNOR_OFF"
MODE_ENV = "HAPAX_RECOVERY_GOVERNOR_MODE"
HOLD_REASON = (
    "hold:missing-valid-authority-grant-admission-decision-exact-execution-lease"
)
AUTHORITY_CEILING = "support_non_authoritative"


def _psi_readable(path: str = "/proc/pressure/cpu") -> bool:
    try:
        with open(path, encoding="utf-8") as handle:
            handle.read(1)
        return True
    except OSError:
        return False


def _live_pressure_state() -> str:
    """Read current pressure without loading or persisting gate state."""

    from shared.sdlc_pressure_gate import (
        PressureReading,
        decide,
        read_load_per_core,
        read_psi,
        read_working_mode,
    )

    observed_at = time.time()
    psi = read_psi()
    reading = PressureReading(
        psi_some_avg10=psi.some_avg10,
        psi_some_avg60=psi.some_avg60,
        load_per_core=read_load_per_core(),
        working_mode=read_working_mode(),
        production_sli="unknown",
    )
    return decide(reading, None, observed_at).state


@dataclass(frozen=True)
class RecoveryParams:
    """Pure modulation parameters; none confer execution authority."""

    base_s: float = 30.0
    multiplier: float = 2.0
    cap_s: float = 1800.0
    max_attempts: int = 5
    bucket_rate: float = 0.1
    bucket_burst: int = 3
    critical_reserve: int = 1
    max_concurrent_relaunch: int = 3
    inflight_ttl_s: float = 300.0
    degraded_rate: float = 1.0 / 30.0
    degraded_burst: int = 1
    tick_cap_open: int = 6
    tick_cap_paced: int = 2
    tick_cap_closed: int = 0
    suspend_noncritical: bool = False


def aimd_backoff_delay(attempt: int, params: RecoveryParams) -> float:
    """Return the bounded nominal retry delay for support analysis."""

    nominal = params.base_s * (params.multiplier ** max(0, attempt))
    return min(nominal, params.cap_s)


def params_for_state(state: str, base: RecoveryParams) -> RecoveryParams:
    """Project an observed pressure state into non-authorizing modulation."""

    if state == "paced":
        return replace(base, base_s=base.base_s * 2.0, bucket_rate=base.bucket_rate * 0.5)
    if state == "closed":
        return replace(base, suspend_noncritical=True)
    if state == "degraded":
        return replace(base, bucket_rate=base.degraded_rate, bucket_burst=base.degraded_burst)
    return base


def converge_action_cap(
    state: str, params: RecoveryParams | None = None, *, critical_pending: bool = False
) -> int:
    """Return a support-only per-tick pressure ceiling.

    This number may modulate an already admitted execution lease.  It cannot be
    treated as an admission decision or used to create one.
    """

    params = params or RecoveryParams()
    if state == "closed":
        return params.critical_reserve if critical_pending else params.tick_cap_closed
    if state == "paced":
        return params.tick_cap_paced
    return params.tick_cap_open


@dataclass(frozen=True)
class BucketState:
    tokens: float
    updated: float


def bucket_take(
    state: BucketState, now: float, *, rate: float, burst: int, n: int = 1
) -> tuple[bool, BucketState]:
    """Pure token-bucket calculation for planning and simulation."""

    elapsed = max(0.0, now - state.updated)
    tokens = min(float(burst), state.tokens + elapsed * rate)
    if tokens >= n:
        return True, BucketState(tokens - n, now)
    return False, BucketState(tokens, now)


@dataclass(frozen=True)
class RecoveryAssessment:
    """A support assessment, never an authority or execution grant."""

    permitted: bool
    reason: str
    target_id: str
    state: str = "degraded"
    attempt: int = 0
    critical: bool = False
    shadow: bool = False
    modulation_allows: bool = False
    authority_ceiling: str = AUTHORITY_CEILING


# Compatibility for callers that imported the old, misleading name.  Instances
# remain support-only and always have ``permitted=False``.
RecoveryGrant = RecoveryAssessment


@dataclass(frozen=True)
class BackoffEntry:
    next_eligible: float
    attempt: int
    last_outcome: str


class RecoveryGovernor:
    """Read-only recovery modulation facade.

    Constructor compatibility is deliberate while downstream recovery sites are
    migrated.  Effect collaborators are accepted but never invoked.
    """

    def __init__(
        self,
        *,
        params: RecoveryParams | None = None,
        state_dir=None,
        now_fn=time.time,
        admission_fn=None,
        psi_readable_fn=None,
        jitter_fn=None,
        critical_validator_fn=None,
        notify_fn=None,
        mint_fn=None,
        shielded_fn=None,
        mode: str | None = None,
    ) -> None:
        self._params = params or RecoveryParams()
        self._now_fn = now_fn
        self._admission_fn = admission_fn
        self._psi_readable_fn = psi_readable_fn or _psi_readable
        self._critical_validator_fn = critical_validator_fn
        self._mode = mode or os.environ.get(MODE_ENV, "support")
        self._state_dir = state_dir

    def _resolve_state(self) -> tuple[str, bool]:
        try:
            readable = bool(self._psi_readable_fn())
        except Exception:
            readable = False
        if not readable:
            return "degraded", False
        try:
            fn = self._admission_fn or _live_pressure_state
            raw_state = fn()
            state = str(getattr(raw_state, "state", raw_state))
        except Exception:
            return "degraded", False
        if state not in {"open", "paced", "closed", "degraded"}:
            return "degraded", False
        return state, True

    def state(self) -> str:
        return self._resolve_state()[0]

    def effective_mode(self) -> str:
        """The governor is support-only regardless of environment settings."""

        return "support"

    def _is_critical(self, target_id: str, requested: bool) -> bool:
        if not requested or self._critical_validator_fn is None:
            return False
        try:
            return bool(self._critical_validator_fn(target_id))
        except Exception:
            return False

    def assess(
        self, target_id: str, *, critical: bool = False, now: float | None = None
    ) -> RecoveryAssessment:
        """Return a non-authorizing pressure assessment for ``target_id``."""

        del now
        state, _ = self._resolve_state()
        is_critical = self._is_critical(target_id, critical)
        modulation_allows = state != "closed" or is_critical
        return RecoveryAssessment(
            permitted=False,
            reason=HOLD_REASON,
            target_id=target_id,
            state=state,
            critical=is_critical,
            modulation_allows=modulation_allows,
        )

    def permit(
        self, target_id: str, *, critical: bool = False, now: float | None = None
    ) -> RecoveryAssessment:
        """Compatibility entry point that always returns HOLD."""

        return self.assess(target_id, critical=critical, now=now)

    def permit_batch(
        self, targets, *, now: float | None = None
    ) -> list[RecoveryAssessment]:
        return [self.assess(target, now=now) for target in targets]

    def record_outcome(
        self, target_id: str, success: bool, *, now: float | None = None
    ) -> None:
        """Retired compatibility no-op; outcome persistence requires admission."""

        del target_id, success, now

    def backoff_entry(self, target_id: str) -> BackoffEntry:
        del target_id
        return BackoffEntry(0.0, 0, "")

    def failopen_count(self) -> int:
        """Legacy diagnostic retained without reading or writing private state."""

        return 0


def _print_hold() -> None:
    print(f"recovery-governor: HOLD {HOLD_REASON}", file=sys.stderr)


def main(argv: list[str] | None = None, *, governor: RecoveryGovernor | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    gov = governor if governor is not None else RecoveryGovernor()

    if "--state" in argv:
        state = gov.state()
        print(state)
        return {"open": 0, "paced": 1, "closed": 2, "degraded": 1}.get(state, 1)

    if "--stats" in argv:
        print(
            json.dumps(
                {
                    "state": gov.state(),
                    "effective_mode": gov.effective_mode(),
                    "authority_ceiling": AUTHORITY_CEILING,
                    "effects_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 0

    if any(flag in argv for flag in ("--permit", "--permit-batch", "--record", "--kill")):
        _print_hold()
        return BACKOFF

    print("usage: recovery_governor --state|--stats|--permit|--permit-batch|--record", file=sys.stderr)
    return CLOSED


if __name__ == "__main__":
    raise SystemExit(main())

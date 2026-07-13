"""Support-only observations of dispatch refusal candidates.

Refusal text, repetition, and elapsed time are ambient signals.  They are not an
authority grant, an admission decision, or an execution lease, so this ledger
cannot cool a route, suppress work, notify, escalate, or otherwise affect the
dispatch plane.  It retains bounded process-local counts solely for an
inspectable ``held_not_admitted`` diagnostic projection.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

SUPPORT_EFFECT_STATE = "held_not_admitted"
SUPPORT_HOLD_REASON = "dispatch_refusal_support_has_no_admission_or_execution_lease"
SUPPORT_MAY_AUTHORIZE = False
MAX_ID_LENGTH = 256
MAX_REASON_LENGTH = 4096


# ── configuration ─────────────────────────────────────────────────────────────

# K: how many identical deterministic observations make the HOLD visible.
DEFAULT_K = 3

# Transient observations use a higher visibility threshold.
TRANSIENT_K = 10

# Compatibility configuration retained for callers; no backoff is materialized.
BACKOFF_BASE_S = 60.0
BACKOFF_MAX_S = 3600.0  # 1 hour cap

# Starvation-shaped support becomes a visible HOLD after this horizon.
STARVATION_HORIZON_S = 3600.0  # 1 hour


# ── classification ────────────────────────────────────────────────────────────

# Reasons that contain any of these substrings are TRANSIENT (expected to
# self-resolve without operator intervention).
_TRANSIENT_MARKERS = frozenset(
    {
        "timeout",
        "TimeoutExpired",
        "timed out",
        "connection refused",
        "ConnectionError",
        "OSError",
        "temporary",
    }
)

# An explicit route-policy / validation block is DETERMINISTIC even if its text
# happens to mention a transient marker (e.g. "route policy refuse: upstream
# timeout"). Deterministic precedence prevents a substring collision from
# silently demoting such a refusal to the transient class (K=10, no escalation),
# which would defeat the circuit breaker the no-spin law exists to provide.
_DETERMINISTIC_MARKERS = frozenset(
    {
        "blocked",
        "route policy",
        "policy refuse",
        "refuse:",
        "validation",
        "not authorized",
        "consent",
    }
)


def is_transient_reason(reason: str) -> bool:
    """True if the refusal reason is transient (timeouts, connection errors).

    Deterministic markers take precedence: a reason that is an explicit policy or
    validation block is never transient, even if it also contains a transient
    substring — otherwise a route-policy refusal mentioning "timeout" would be
    misclassified as self-healing and never escalate.
    """
    reason_lower = reason.lower()
    if any(marker in reason_lower for marker in _DETERMINISTIC_MARKERS):
        return False
    return any(marker.lower() in reason_lower for marker in _TRANSIENT_MARKERS)


def _bounded_text(value: object, field_name: str, limit: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
        or len(value) > limit
    ):
        raise ValueError(f"dispatch_refusal_{field_name}_invalid")
    return value


def _finite_now(value: float | None) -> float:
    observed = time.monotonic() if value is None else value
    if (
        isinstance(observed, bool)
        or not isinstance(observed, (int, float))
        or not math.isfinite(observed)
        or observed < 0
    ):
        raise ValueError("dispatch_refusal_observed_at_invalid")
    return float(observed)


# ── data structures ───────────────────────────────────────────────────────────


@dataclass
class RefusalEntry:
    """State for a single (task_id, lane, reason) triple."""

    task_id: str
    lane: str
    reason: str
    attempts: int = 0
    first_seen: float = 0.0  # monotonic
    last_seen: float = 0.0  # monotonic
    cooldown_until: float = 0.0  # monotonic; 0 = not in cooldown
    escalated: bool = False  # compatibility field; effects are always held
    transient: bool = False  # True if this is a transient reason
    effect_state: str = SUPPORT_EFFECT_STATE
    hold_reason: str = SUPPORT_HOLD_REASON
    may_authorize: bool = SUPPORT_MAY_AUTHORIZE
    hold_visible: bool = False


@dataclass
class StarvationState:
    """Tracks starvation-shaped support without triggering an escalation."""

    starved_since: float = 0.0  # monotonic; 0 = not starved
    escalated: bool = False  # compatibility field; effects are always held
    hold_visible: bool = False


@dataclass
class DispatchRefusalLedger:
    """Process-local, non-authorizing refusal support keyed by signal identity."""

    k: int = DEFAULT_K
    transient_k: int = TRANSIENT_K
    backoff_base_s: float = BACKOFF_BASE_S
    backoff_max_s: float = BACKOFF_MAX_S
    starvation_horizon_s: float = STARVATION_HORIZON_S
    _entries: dict[tuple[str, str, str], RefusalEntry] = field(default_factory=dict)
    _starvation: StarvationState = field(default_factory=StarvationState)
    # Compatibility callback slot. It is deliberately never invoked.
    _escalate_fn: object = None  # Callable[[str, str], None] | None

    def record_refusal(
        self, task_id: str, lane: str, reason: str, *, now: float | None = None
    ) -> RefusalEntry:
        """Record a bounded observation without producing a dispatch effect."""

        task_id = _bounded_text(task_id, "task_id", MAX_ID_LENGTH)
        lane = _bounded_text(lane, "lane", MAX_ID_LENGTH)
        reason = _bounded_text(reason, "reason", MAX_REASON_LENGTH)
        now = _finite_now(now)
        key = (task_id, lane, reason)
        entry = self._entries.get(key)
        if entry is None:
            entry = RefusalEntry(
                task_id=task_id,
                lane=lane,
                reason=reason,
                first_seen=now,
                transient=is_transient_reason(reason),
            )
            self._entries[key] = entry

        entry.attempts += 1
        entry.last_seen = now
        threshold = self.transient_k if entry.transient else self.k
        if entry.attempts >= threshold:
            first_visible_hold = not entry.hold_visible
            entry.hold_visible = True
            if first_visible_hold:
                log.warning(
                    "dispatch refusal support HOLD: (%s, %s) observation #%d (%s)",
                    task_id,
                    lane,
                    entry.attempts,
                    reason[:80],
                )

        return entry

    def is_cooled_down(
        self, task_id: str, lane: str, reason: str | None = None, *, now: float | None = None
    ) -> bool:
        """Always false: support observations cannot suppress a dispatch pair."""

        del task_id, lane, reason, now
        return False

    def any_cooldown_for_pair(self, task_id: str, lane: str, *, now: float | None = None) -> bool:
        """Always false: there is no admitted cooldown effect."""

        del task_id, lane, now
        return False

    def any_cooldown_for_task(
        self, task_id: str, *, escalated_only: bool = False, now: float | None = None
    ) -> bool:
        """Always false: observations cannot discount or reorder offered work."""

        del task_id, escalated_only, now
        return False

    def clear(self, task_id: str | None = None) -> None:
        """Clear refusal state.  If task_id is given, only clears that task's entries."""
        if task_id is None:
            self._entries.clear()
        else:
            self._entries = {k: v for k, v in self._entries.items() if k[0] != task_id}

    def tick_starvation(
        self,
        offered: int,
        dispatched: int,
        *,
        now: float | None = None,
    ) -> bool:
        """Track a starvation-shaped signal and hold every escalation effect."""

        now = _finite_now(now)
        if isinstance(offered, bool) or not isinstance(offered, int) or offered < 0:
            raise ValueError("dispatch_refusal_offered_invalid")
        if isinstance(dispatched, bool) or not isinstance(dispatched, int) or dispatched < 0:
            raise ValueError("dispatch_refusal_dispatched_invalid")
        if offered > 0 and dispatched == 0:
            if self._starvation.starved_since == 0.0:
                self._starvation.starved_since = now
            elif (
                not self._starvation.hold_visible
                and (now - self._starvation.starved_since) >= self.starvation_horizon_s
            ):
                self._starvation.hold_visible = True
                log.warning(
                    "dispatch starvation support HOLD: offered=%d observed_for=%.0fs",
                    offered,
                    now - self._starvation.starved_since,
                )
        else:
            self._starvation.starved_since = 0.0
            self._starvation.escalated = False
            self._starvation.hold_visible = False
        return False

    def stats(self, *, now: float | None = None) -> dict:
        """Diagnostic snapshot for the SHM state file."""
        del now
        return {
            "effect_state": SUPPORT_EFFECT_STATE,
            "hold_reason": SUPPORT_HOLD_REASON,
            "may_authorize": SUPPORT_MAY_AUTHORIZE,
            "refusal_triples": len(self._entries),
            "observations": sum(entry.attempts for entry in self._entries.values()),
            "visible_holds": sum(entry.hold_visible for entry in self._entries.values()),
            "cooled_down": 0,
            "escalated": 0,
            "starvation_active": self._starvation.starved_since > 0,
            "starvation_escalated": False,
            "starvation_hold_visible": self._starvation.hold_visible,
        }

    def _fire_escalation(self, task_id: str, lane: str, reason: str, attempts: int) -> None:
        """Compatibility no-op: notification requires admitted execution."""

        del task_id, lane, reason, attempts

    def _fire_starvation_escalation(self, offered: int, duration_s: float) -> None:
        """Compatibility no-op: notification requires admitted execution."""

        del offered, duration_s

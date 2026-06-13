"""Dispatch refusal ledger — the no-spin law (failure class #9 remediation).

Tracks (task_id, lane, refusal_reason) triples with per-triple attempt counts.
After K identical *deterministic* refusals the triple enters exponential-backoff
cooldown and a single ntfy escalation fires with the reason text.

Deterministic reasons (route policy refusals, validation blocks) are distinguished
from transient reasons (timeouts, OSError).  Transient reasons get backoff but a
*higher* K and no escalation — they are expected to self-resolve.

Thread-safety: the coordinator daemon is single-threaded; no locking needed.

Process-lifetime scope: the ledger is ephemeral (in-process dict).  A daemon
restart resets all cooldowns — which is the right behavior since the external
state that caused the refusal may have changed.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


# ── configuration ─────────────────────────────────────────────────────────────

# K: how many identical deterministic refusals before cooldown + escalation.
DEFAULT_K = 3

# Transient refusals (timeouts) get a higher K before backoff kicks in, and
# no escalation (they're expected to self-heal).
TRANSIENT_K = 10

# Exponential backoff: base * 2^(attempts - K), capped at max.
BACKOFF_BASE_S = 60.0
BACKOFF_MAX_S = 3600.0  # 1 hour cap

# Starvation detector: if offered>0 and dispatched=0 for this long, fire ONE
# escalation (not 120 ticks of silence).
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


def is_transient_reason(reason: str) -> bool:
    """True if the refusal reason is transient (timeouts, connection errors)."""
    reason_lower = reason.lower()
    return any(marker.lower() in reason_lower for marker in _TRANSIENT_MARKERS)


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
    escalated: bool = False  # True after the ntfy escalation has fired
    transient: bool = False  # True if this is a transient reason


@dataclass
class StarvationState:
    """Tracks the starvation detector: offered>0 and dispatched=0 continuously."""

    starved_since: float = 0.0  # monotonic; 0 = not starved
    escalated: bool = False  # True after the single starvation escalation fired


@dataclass
class DispatchRefusalLedger:
    """Process-local ledger of dispatch refusals, keyed by (task_id, lane, reason).

    The coordinator calls ``record_refusal`` on every dispatch failure, and
    ``is_cooled_down`` before attempting a dispatch.  The tick loop calls
    ``tick_starvation`` at the end to detect fleet-wide dispatch starvation.
    """

    k: int = DEFAULT_K
    transient_k: int = TRANSIENT_K
    backoff_base_s: float = BACKOFF_BASE_S
    backoff_max_s: float = BACKOFF_MAX_S
    starvation_horizon_s: float = STARVATION_HORIZON_S
    _entries: dict[tuple[str, str, str], RefusalEntry] = field(default_factory=dict)
    _starvation: StarvationState = field(default_factory=StarvationState)
    # Callback for escalation (ntfy).  Injected so tests don't send real notifications.
    _escalate_fn: object = None  # Callable[[str, str], None] | None

    def record_refusal(
        self, task_id: str, lane: str, reason: str, *, now: float | None = None
    ) -> RefusalEntry:
        """Record a dispatch refusal and return the updated entry.

        If the entry crosses the K threshold, enters cooldown and fires a SINGLE
        ntfy escalation.
        """
        now = now if now is not None else time.monotonic()
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
            # Enter exponential-backoff cooldown.
            exponent = entry.attempts - threshold
            if self.backoff_base_s <= 0:
                backoff = 0.0
            elif self.backoff_base_s >= self.backoff_max_s:
                backoff = self.backoff_max_s
            else:
                exponent_to_cap = math.ceil(math.log2(self.backoff_max_s / self.backoff_base_s))
                backoff = (
                    self.backoff_max_s
                    if exponent >= exponent_to_cap
                    else self.backoff_base_s * (2**exponent)
                )
            entry.cooldown_until = now + backoff
            log.warning(
                "no-spin: (%s, %s) refusal #%d (%s) -> cooldown %.0fs",
                task_id,
                lane,
                entry.attempts,
                reason[:80],
                backoff,
            )

            # Fire ONE escalation (never repeats for the same triple).
            if not entry.escalated and not entry.transient:
                entry.escalated = True
                self._fire_escalation(task_id, lane, reason, entry.attempts)

        return entry

    def is_cooled_down(
        self, task_id: str, lane: str, reason: str | None = None, *, now: float | None = None
    ) -> bool:
        """True if ANY (task_id, lane, *) triple is currently in cooldown.

        When ``reason`` is given, only checks that specific triple.  When None,
        checks ALL triples for this (task_id, lane) pair — the coordinator can't
        predict which reason will come back, so ANY active cooldown blocks.
        """
        now = now if now is not None else time.monotonic()
        if reason is not None:
            entry = self._entries.get((task_id, lane, reason))
            return entry is not None and entry.cooldown_until > now

        # Check all triples for this (task_id, lane) pair.
        for key, entry in self._entries.items():
            if key[0] == task_id and key[1] == lane and entry.cooldown_until > now:
                return True
        return False

    def any_cooldown_for_pair(self, task_id: str, lane: str, *, now: float | None = None) -> bool:
        """True if any refusal triple for this (task_id, lane) is in cooldown."""
        return self.is_cooled_down(task_id, lane, now=now)

    def any_cooldown_for_task(self, task_id: str, *, now: float | None = None) -> bool:
        """True if ANY (task_id, *, *) triple is in cooldown on any lane.

        Used by the starvation detector to tell a task the circuit breaker is
        already holding (its own escalation has fired) from a task that is
        genuinely starving (offered, undispatched, but not in cooldown).
        """
        now = now if now is not None else time.monotonic()
        for key, entry in self._entries.items():
            if key[0] == task_id and entry.cooldown_until > now:
                return True
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
        """Track the starvation detector.  Returns True if a starvation escalation
        just fired (for test assertions)."""
        now = now if now is not None else time.monotonic()
        if offered > 0 and dispatched == 0:
            if self._starvation.starved_since == 0.0:
                self._starvation.starved_since = now
            elif (
                not self._starvation.escalated
                and (now - self._starvation.starved_since) >= self.starvation_horizon_s
            ):
                self._starvation.escalated = True
                self._fire_starvation_escalation(offered, now - self._starvation.starved_since)
                return True
        else:
            # Reset: we dispatched at least one, or the queue is empty.
            self._starvation.starved_since = 0.0
            self._starvation.escalated = False
        return False

    def stats(self, *, now: float | None = None) -> dict:
        """Diagnostic snapshot for the SHM state file."""
        cooled = 0
        escalated = 0
        now = now if now is not None else time.monotonic()
        for entry in self._entries.values():
            if entry.cooldown_until > now:
                cooled += 1
            if entry.escalated:
                escalated += 1
        return {
            "refusal_triples": len(self._entries),
            "cooled_down": cooled,
            "escalated": escalated,
            "starvation_active": self._starvation.starved_since > 0,
            "starvation_escalated": self._starvation.escalated,
        }

    def _fire_escalation(self, task_id: str, lane: str, reason: str, attempts: int) -> None:
        """Send a single ntfy escalation for a deterministic refusal that crossed K."""
        title = "SDLC: dispatch refusal circuit breaker"
        body = (
            f"Task {task_id} refused {attempts}x on lane {lane}.\n"
            f"Reason: {reason}\n"
            f"Action: pair entered cooldown with exponential backoff. "
            f"Resolve the underlying issue or manually clear the cooldown."
        )
        log.error("no-spin escalation: %s → %s (×%d): %s", task_id, lane, attempts, reason)
        if callable(self._escalate_fn):
            try:
                self._escalate_fn(title, body)
            except Exception:  # noqa: BLE001 — ntfy is best-effort
                log.exception("no-spin ntfy escalation failed (continuing)")

    def _fire_starvation_escalation(self, offered: int, duration_s: float) -> None:
        """Send a single ntfy escalation for fleet-wide dispatch starvation."""
        title = "SDLC: dispatch starvation detected"
        body = (
            f"offered={offered} tasks, dispatched=0 for {duration_s / 60:.0f} minutes.\n"
            f"All dispatch attempts are failing or in cooldown. "
            f"Check lane health and route policy."
        )
        log.error("no-spin starvation: offered=%d, starved %.0fs", offered, duration_s)
        if callable(self._escalate_fn):
            try:
                self._escalate_fn(title, body)
            except Exception:  # noqa: BLE001
                log.exception("no-spin starvation ntfy failed (continuing)")

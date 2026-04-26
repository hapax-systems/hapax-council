"""Pure state-machine decision logic.

Inputs: current `RefusalTask`, list of `ProbeResult`s, optional
`RemovalSignal`. Output: a single `TransitionEvent`. Conservative defaults
ensure no false-acceptance under uncertainty: any probe error, any
unchanged probe, or any incomplete-evidence probe → re-affirm.

No I/O, no global state, no clock reads except for `datetime.now(UTC)` to
stamp the event timestamp.
"""

from __future__ import annotations

from datetime import UTC, datetime

from agents.refused_lifecycle.state import (
    ProbeResult,
    RefusalTask,
    RemovalSignal,
    TransitionEvent,
)

_REFUSED_STATUS = "REFUSED"
_OFFERED_STATUS = "OFFERED"
_REMOVED_STATUS = "REMOVED"

# Logical state names used in TransitionEvent.from_state / to_state.
# Distinct from the cc-task `automation_status` field — REFUSED maps 1:1
# but ACCEPTED is the logical counterpart of `automation_status: OFFERED`.
_LOGICAL_REFUSED = "REFUSED"
_LOGICAL_ACCEPTED = "ACCEPTED"
_LOGICAL_REMOVED = "REMOVED"


def _logical_state(automation_status: str) -> str:
    if automation_status == _OFFERED_STATUS:
        return _LOGICAL_ACCEPTED
    return automation_status


def decide_transition(
    task: RefusalTask,
    probes: list[ProbeResult],
    *,
    removal_signal: RemovalSignal | None = None,
) -> TransitionEvent:
    """Decide a transition from the current task state given probe results.

    REMOVED is terminal — calling on a REMOVED task raises ``ValueError``.

    Removal signals take precedence over probe results: any non-None
    ``removal_signal`` routes to REMOVED regardless of probe content.
    """
    if task.automation_status == _REMOVED_STATUS:
        raise ValueError(f"Cannot transition from REMOVED: {task.slug}")

    timestamp = datetime.now(UTC)
    current_logical = _logical_state(task.automation_status)

    if removal_signal is not None:
        return TransitionEvent(
            timestamp=timestamp,
            cc_task_slug=task.slug,
            from_state=current_logical,
            to_state=_LOGICAL_REMOVED,
            transition="removed",
            trigger=task.evaluation_trigger or ["constitutional"],
            reason=removal_signal.reason,
        )

    # Conservative defaults — apply uniformly across REFUSED and OFFERED states
    if not probes:
        return _re_affirm(task, timestamp, current_logical, "no-probes")

    first_error = next((p.error for p in probes if p.error), None)
    if first_error is not None:
        return _re_affirm(task, timestamp, current_logical, f"probe-error: {first_error}")

    if not all(p.changed for p in probes):
        return _re_affirm(
            task,
            timestamp,
            current_logical,
            "probe-content-unchanged-or-still-prohibitive",
        )

    if not all(p.evidence_url and p.snippet for p in probes):
        return _re_affirm(
            task,
            timestamp,
            current_logical,
            "probe-changed-but-evidence-incomplete",
        )

    # All probes positive AND evidence-complete — direction depends on current state
    if task.automation_status == _REFUSED_STATUS:
        return TransitionEvent(
            timestamp=timestamp,
            cc_task_slug=task.slug,
            from_state=_LOGICAL_REFUSED,
            to_state=_LOGICAL_ACCEPTED,
            transition="accepted",
            trigger=task.evaluation_trigger or ["constitutional"],
            evidence_url=probes[0].evidence_url,
            reason="probe-clear: " + ", ".join((p.snippet or "")[:80] for p in probes),
        )

    # OFFERED + all-clear probes = regression: lift-keyword disappeared,
    # constraint re-imposed, or upstream policy shifted back. Preserve audit
    # trail by routing to REFUSED.
    return TransitionEvent(
        timestamp=timestamp,
        cc_task_slug=task.slug,
        from_state=_LOGICAL_ACCEPTED,
        to_state=_LOGICAL_REFUSED,
        transition="regressed",
        trigger=task.evaluation_trigger or ["constitutional"],
        evidence_url=probes[0].evidence_url,
        reason="regression-detected: " + ", ".join((p.snippet or "")[:80] for p in probes),
    )


def _re_affirm(
    task: RefusalTask,
    timestamp: datetime,
    current_logical: str,
    reason: str,
) -> TransitionEvent:
    return TransitionEvent(
        timestamp=timestamp,
        cc_task_slug=task.slug,
        from_state=current_logical,
        to_state=current_logical,
        transition="re-affirmed",
        trigger=task.evaluation_trigger or ["constitutional"],
        reason=reason,
    )


__all__ = ["decide_transition"]

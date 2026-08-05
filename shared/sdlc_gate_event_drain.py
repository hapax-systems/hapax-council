"""N1 world-to-record observe: drain gate-events into SdlcRouter posteriors.

Default mode is **report-only**: count how many witnessed learning events would
move a Thompson posterior without writing router state or changing dispatch.

``apply=True`` persists updated router state when events apply — still does **not**
select routes or enforce ``HAPAX_ROUTE_ENVELOPE_GATE``.

Does not enable ``HAPAX_OUTCOME_GATE_ON_CLOSE`` (close-side emit remains flag-gated).
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shared.gate_log import DEFAULT_GATE_LOG, GateEvent, read_gate_events
from shared.sdlc_router import (
    DEFAULT_SDLC_ROUTER_STATE,
    LEARNING_GATE_RESULTS,
    LEARNING_GATE_TYPES,
    SdlcRouter,
    gate_event_hash,
    gate_event_thompson_update_allowed,
)

# Shared with scripts/cc-task-closure-check.py — single truth for close-side emit gate.
OUTCOME_GATE_ON_CLOSE_ENV = "HAPAX_OUTCOME_GATE_ON_CLOSE"
_OUTCOME_GATE_TRUTHY = frozenset({"1", "true", "yes", "on"})


@dataclass(frozen=True)
class GateEventDrainReport:
    """Observe-only summary of a gate-event drain pass."""

    gate_log_path: str
    router_state_path: str
    total_events: int
    eligible_witnessed_learning: int
    would_apply: int
    applied: int
    skipped_already_applied: int
    skipped_not_learning: int
    skipped_not_witnessed: int
    skipped_ineligible: int
    applied_event_hashes: tuple[str, ...]
    mode: str  # "report" | "apply"
    state_written: bool
    selection_invoked: bool = False  # True only if a future path calls SdlcRouter.route

    def as_dict(self) -> dict[str, Any]:
        return {
            "gate_log_path": self.gate_log_path,
            "router_state_path": self.router_state_path,
            "total_events": self.total_events,
            "eligible_witnessed_learning": self.eligible_witnessed_learning,
            "would_apply": self.would_apply,
            "applied": self.applied,
            "skipped_already_applied": self.skipped_already_applied,
            "skipped_not_learning": self.skipped_not_learning,
            "skipped_not_witnessed": self.skipped_not_witnessed,
            "skipped_ineligible": self.skipped_ineligible,
            "applied_event_hashes": list(self.applied_event_hashes),
            "mode": self.mode,
            "state_written": self.state_written,
            # Derived safety facts (not free constants): selection was never invoked
            # by this drain; close-side default remains off unless env truthy now.
            "dispatch_selection_changed": self.selection_invoked,
            "outcome_gate_on_close_enabled_now": outcome_gate_on_close_enabled(),
            "outcome_gate_on_close_env": OUTCOME_GATE_ON_CLOSE_ENV,
        }


def _classify_skip(event: GateEvent) -> str | None:
    """Return a skip reason code, or None if the event is learning-eligible."""
    if event.gate_type not in LEARNING_GATE_TYPES or event.gate_result not in LEARNING_GATE_RESULTS:
        return "not_learning"
    if event.provenance != "witnessed":
        return "not_witnessed"
    if not gate_event_thompson_update_allowed(event):
        return "ineligible"
    return None


def drain_gate_events(
    *,
    gate_log: Path | str | None = None,
    router_state: Path | str | None = None,
    apply: bool = False,
    events: Iterable[GateEvent] | None = None,
) -> GateEventDrainReport:
    """Drain gate-events into router posteriors (report by default).

    When ``apply`` is False, no router state file is written. When True, events
    that ``record_gate_event`` accepts are applied and the state is saved.
    """
    log_path = Path(gate_log) if gate_log is not None else DEFAULT_GATE_LOG
    state_path = Path(router_state) if router_state is not None else DEFAULT_SDLC_ROUTER_STATE

    source: list[GateEvent] = (
        list(events) if events is not None else list(read_gate_events(path=log_path))
    )
    router = SdlcRouter.load(state_path)

    total = 0
    eligible = 0
    would_apply = 0
    applied = 0
    skipped_already = 0
    skipped_not_learning = 0
    skipped_not_witnessed = 0
    skipped_ineligible = 0
    applied_hashes: list[str] = []
    # In-pass de-dupe so report mode matches apply (first hash wins).
    seen_this_pass: set[str] = set()
    applied_persisted = set(router.state.applied_gate_event_hashes)

    for event in source:
        total += 1
        skip = _classify_skip(event)
        if skip == "not_learning":
            skipped_not_learning += 1
            continue
        if skip == "not_witnessed":
            skipped_not_witnessed += 1
            continue
        if skip == "ineligible":
            skipped_ineligible += 1
            continue
        # Mirror SdlcRouter.record_gate_event llm_acceptor refuse path so
        # report would_apply does not over-count vs --apply.
        if event.gate_type == "llm_acceptor" and not (
            router.judge_promotion is not None and router.judge_promotion.allowed
        ):
            skipped_ineligible += 1
            continue
        eligible += 1
        event_hash = gate_event_hash(event)
        if event_hash in applied_persisted or event_hash in seen_this_pass:
            skipped_already += 1
            continue
        would_apply += 1
        seen_this_pass.add(event_hash)
        if apply:
            if router.record_gate_event(event):
                applied += 1
                applied_hashes.append(event_hash)
            else:
                # Prechecks should match record_gate_event; treat residual refuse
                # as ineligible so report/apply counters stay consistent.
                skipped_ineligible += 1
                would_apply -= 1
                eligible -= 1
                seen_this_pass.discard(event_hash)

    state_written = False
    if apply and applied > 0:
        router.save(state_path)
        state_written = True

    return GateEventDrainReport(
        gate_log_path=str(log_path),
        router_state_path=str(state_path),
        total_events=total,
        eligible_witnessed_learning=eligible,
        would_apply=would_apply if not apply else applied,
        applied=applied,
        skipped_already_applied=skipped_already,
        skipped_not_learning=skipped_not_learning,
        skipped_not_witnessed=skipped_not_witnessed,
        skipped_ineligible=skipped_ineligible,
        applied_event_hashes=tuple(applied_hashes),
        mode="apply" if apply else "report",
        state_written=state_written,
        selection_invoked=False,
    )


def outcome_gate_on_close_enabled() -> bool:
    """Canonical reader for HAPAX_OUTCOME_GATE_ON_CLOSE (default off).

    Shared with ``scripts/cc-task-closure-check.py`` so status reports cannot
    disagree with the close-side emit gate.
    """
    return os.environ.get(OUTCOME_GATE_ON_CLOSE_ENV, "0").strip().lower() in _OUTCOME_GATE_TRUTHY


def observe_status(
    *,
    gate_log: Path | str | None = None,
    router_state: Path | str | None = None,
) -> dict[str, Any]:
    """Single JSON-friendly observe snapshot for operators."""
    report = drain_gate_events(gate_log=gate_log, router_state=router_state, apply=False)
    log_path = Path(report.gate_log_path)
    return {
        **report.as_dict(),
        "gate_log_exists": log_path.exists(),
        "gate_log_bytes": log_path.stat().st_size if log_path.exists() else 0,
        "next_actions": next_actions_for(report),
    }


def next_actions_for(report: GateEventDrainReport) -> list[str]:
    actions: list[str] = []
    if report.total_events == 0:
        actions.append(
            "gate log empty: enable HAPAX_OUTCOME_GATE_ON_CLOSE=1 for a governed close "
            "with complete requirement_vector (see docs/runbooks/outcome-gate-on-close-enable.md)"
        )
    elif report.would_apply > 0 and report.mode == "report":
        actions.append(
            f"{report.would_apply} witnessed learning event(s) ready; re-run with --apply "
            "to move posteriors (still no live route selection)"
        )
    elif report.applied > 0:
        actions.append(
            f"applied {report.applied} event(s); router state written; selection still WSJF "
            "until separate SdlcRouter shadow-wire (N2)"
        )
    else:
        actions.append("no new applicable events; log may be empty of witnessed learning verdicts")
    actions.append("killswitch: HAPAX_OUTCOME_GATE_ON_CLOSE=0 (default) stops new close emits")
    return actions

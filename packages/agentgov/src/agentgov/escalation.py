"""Governance escalation — route regressions and policy violations to operator."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from agentgov.replay import ReplayReport

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class EscalationEvent:
    """A governance event that needs operator attention."""

    record_id: str
    severity: str
    summary: str
    denied_by: tuple[str, ...]


def extract_escalations(report: ReplayReport) -> list[EscalationEvent]:
    """Extract escalation events from a replay report."""
    events: list[EscalationEvent] = []
    for cert in report.regressions:
        events.append(
            EscalationEvent(
                record_id=cert.record_id,
                severity="regression",
                summary=f"Decision {cert.record_id} was allowed, now denied",
                denied_by=cert.current_denied_by,
            )
        )
    return events


def format_ntfy_message(events: list[EscalationEvent]) -> str:
    """Format escalation events for ntfy notification."""
    if not events:
        return ""
    lines = [f"Governance replay: {len(events)} regression(s) detected"]
    for ev in events[:5]:
        lines.append(f"  - {ev.record_id}: denied by {', '.join(ev.denied_by)}")
    if len(events) > 5:
        lines.append(f"  ... and {len(events) - 5} more")
    return "\n".join(lines)

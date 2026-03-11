"""Incident lifecycle management for health monitoring.

Tracks incidents from detection through resolution with a timeline of events.
Persists to profiles/incidents.json.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field

from shared.config import PROFILES_DIR


class IncidentPhase(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class TimelineEvent(BaseModel):
    timestamp: str
    event_type: str  # "opened", "escalated", "acknowledged", "resolved", "note"
    message: str


class Incident(BaseModel):
    id: str  # e.g. "INC-20260303-001"
    check_name: str
    phase: IncidentPhase = IncidentPhase.OPEN
    opened_at: str = ""
    resolved_at: str = ""
    timeline: list[TimelineEvent] = Field(default_factory=list)
    summary: str = ""  # optional LLM-generated narrative (Batch 5)

    def duration_minutes(self) -> float | None:
        """Return duration in minutes, or None if still open."""
        if not self.resolved_at or not self.opened_at:
            return None
        try:
            opened = datetime.fromisoformat(self.opened_at)
            resolved = datetime.fromisoformat(self.resolved_at)
            return (resolved - opened).total_seconds() / 60
        except ValueError:
            return None


class IncidentTracker:
    """Manage incident lifecycle with persistence."""

    def __init__(self, state_path: Path | None = None):
        self.state_path = state_path or (PROFILES_DIR / "incidents.json")
        self._incidents: list[Incident] = []
        self._load()

    def _load(self) -> None:
        if not self.state_path.exists():
            return
        try:
            data = json.loads(self.state_path.read_text())
            self._incidents = [Incident.model_validate(d) for d in data]
        except (json.JSONDecodeError, OSError):
            pass

    def save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        data = [i.model_dump() for i in self._incidents]
        fd, tmp = tempfile.mkstemp(dir=str(self.state_path.parent), suffix=".json")
        try:
            with open(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, self.state_path)
        except Exception:
            Path(tmp).unlink(missing_ok=True)
            raise

    def _next_id(self) -> str:
        today = datetime.now(UTC).strftime("%Y%m%d")
        day_incidents = [i for i in self._incidents if i.id.startswith(f"INC-{today}")]
        seq = len(day_incidents) + 1
        return f"INC-{today}-{seq:03d}"

    def open_incident(self, check_name: str, message: str = "") -> Incident:
        """Open a new incident for a failing check. Returns existing if already open."""
        existing = self.get_open_for_check(check_name)
        if existing:
            return existing

        now = datetime.now(UTC).isoformat()
        incident = Incident(
            id=self._next_id(),
            check_name=check_name,
            phase=IncidentPhase.OPEN,
            opened_at=now,
            timeline=[
                TimelineEvent(
                    timestamp=now,
                    event_type="opened",
                    message=message or f"Check {check_name} entered failure state",
                )
            ],
        )
        self._incidents.append(incident)
        return incident

    def acknowledge(self, incident_id: str, message: str = "") -> bool:
        """Acknowledge an incident."""
        incident = self.get_by_id(incident_id)
        if not incident or incident.phase != IncidentPhase.OPEN:
            return False
        now = datetime.now(UTC).isoformat()
        incident.phase = IncidentPhase.ACKNOWLEDGED
        incident.timeline.append(
            TimelineEvent(
                timestamp=now,
                event_type="acknowledged",
                message=message or "Incident acknowledged",
            )
        )
        return True

    def resolve(self, check_name: str, message: str = "") -> Incident | None:
        """Resolve the open incident for a check. Returns the incident or None."""
        incident = self.get_open_for_check(check_name)
        if not incident:
            return None
        now = datetime.now(UTC).isoformat()
        incident.phase = IncidentPhase.RESOLVED
        incident.resolved_at = now
        incident.timeline.append(
            TimelineEvent(
                timestamp=now,
                event_type="resolved",
                message=message or f"Check {check_name} recovered",
            )
        )
        return incident

    def add_note(self, incident_id: str, message: str) -> bool:
        """Add a note to an incident timeline."""
        incident = self.get_by_id(incident_id)
        if not incident:
            return False
        incident.timeline.append(
            TimelineEvent(
                timestamp=datetime.now(UTC).isoformat(),
                event_type="note",
                message=message,
            )
        )
        return True

    def get_by_id(self, incident_id: str) -> Incident | None:
        for i in self._incidents:
            if i.id == incident_id:
                return i
        return None

    def get_open(self) -> list[Incident]:
        """Return all non-resolved incidents."""
        return [
            i
            for i in self._incidents
            if i.phase in (IncidentPhase.OPEN, IncidentPhase.ACKNOWLEDGED)
        ]

    def get_open_for_check(self, check_name: str) -> Incident | None:
        """Return the open incident for a specific check, if any."""
        for i in self._incidents:
            if i.check_name == check_name and i.phase in (
                IncidentPhase.OPEN,
                IncidentPhase.ACKNOWLEDGED,
            ):
                return i
        return None

    def get_recent(self, limit: int = 20) -> list[Incident]:
        """Return most recent incidents (newest first)."""
        return sorted(
            self._incidents,
            key=lambda i: i.opened_at,
            reverse=True,
        )[:limit]


async def generate_narrative(incident: Incident) -> str:
    """Generate a human-readable incident narrative using LLM.

    Summarizes the incident timeline into a coherent report. Requires LLM
    access — this function is intentionally outside IncidentTracker to keep
    the tracker zero-LLM.
    """
    from pydantic_ai import Agent

    from shared.config import get_model

    agent = Agent(
        get_model("fast"),
        system_prompt=(
            "Write a concise incident report (3-5 sentences) from the timeline data. "
            "Include what failed, when, what happened during the incident, and how it "
            "was resolved (if resolved). Use past tense. Be factual."
        ),
    )
    timeline_text = "\n".join(
        f"[{e.timestamp}] {e.event_type}: {e.message}" for e in incident.timeline
    )
    duration = incident.duration_minutes()
    prompt = (
        f"Incident {incident.id} for check {incident.check_name}\n"
        f"Phase: {incident.phase.value}\n"
        f"Duration: {f'{duration:.0f} minutes' if duration else 'ongoing'}\n\n"
        f"Timeline:\n{timeline_text}"
    )
    result = await agent.run(prompt)
    return result.output

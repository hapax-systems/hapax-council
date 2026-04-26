"""Pydantic state-machine models for the refused-lifecycle substrate.

Each cc-task in `~/Documents/Personal/20-projects/hapax-cc-tasks/active/`
with `automation_status: REFUSED` participates in a bidirectional state
machine: REFUSED ↔ ACCEPTED (cc-task `automation_status: OFFERED`) and a
terminal REMOVED state. Transitions are emitted as `TransitionEvent`
records and logged into the canonical refusal log per the refusal-as-data
constitutional substrate.

Models here are pure data — no I/O, no decision logic. The evaluator
(`evaluator.py`) decides; the runner (`runner.py`) orchestrates.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TransitionKind = Literal["created", "re-affirmed", "accepted", "removed", "regressed"]
TriggerCategory = Literal["structural", "constitutional", "conditional"]


class RefusalHistoryEntry(BaseModel):
    """One row in a cc-task's `refusal_history` list."""

    model_config = ConfigDict(extra="forbid")

    date: datetime
    transition: TransitionKind
    reason: str
    evidence_url: str | None = None


class ProbeResult(BaseModel):
    """Outcome of a single probe against the upstream signal."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    changed: bool
    evidence_url: str | None = None
    snippet: str | None = Field(default=None, max_length=500)
    error: str | None = None
    # Conditional-GET state (populated by structural watcher; persisted
    # back into task.evaluation_probe so the next probe sends If-None-Match
    # / If-Modified-Since instead of burning a full GET).
    etag: str | None = None
    last_modified: str | None = None
    fingerprint: str | None = None


class TransitionEvent(BaseModel):
    """One state-machine transition (or re-affirmation), emitted by the evaluator."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    timestamp: datetime
    cc_task_slug: str
    from_state: str
    to_state: str
    transition: TransitionKind
    trigger: list[TriggerCategory]
    evidence_url: str | None = None
    reason: str


class RefusalTask(BaseModel):
    """A REFUSED cc-task with its evaluation cadence + probe configuration."""

    model_config = ConfigDict(extra="allow")

    slug: str
    path: str
    automation_status: str  # REFUSED | OFFERED | REMOVED
    refusal_reason: str
    last_evaluated_at: datetime | None = None
    next_evaluation_at: datetime | None = None
    evaluation_trigger: list[TriggerCategory] = Field(default_factory=list)
    evaluation_probe: dict = Field(default_factory=dict)
    refusal_history: list[RefusalHistoryEntry] = Field(default_factory=list)
    superseded_by: str | None = None
    acceptance_evidence: dict | None = None


class RemovalSignal(BaseModel):
    """External signal that a refusal should transition to REMOVED.

    Distinct from probe-driven transitions (lift to ACCEPTED, regress to
    REFUSED). Removal is triggered by axiom retirement, supersession by a
    different cc-task, or explicit cc-task closure.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    reason: str
    superseded_by: str | None = None


__all__ = [
    "ProbeResult",
    "RefusalHistoryEntry",
    "RefusalTask",
    "RemovalSignal",
    "TransitionEvent",
    "TransitionKind",
    "TriggerCategory",
]

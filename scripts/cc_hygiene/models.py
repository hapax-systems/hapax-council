"""Pydantic models for the cc-hygiene sweeper.

The state file (`~/.cache/hapax/cc-hygiene-state.json`) is a stable
machine-readable contract consumed by downstream PRs (auto-actions,
PR-link hooks, waybar/Logos panel, ntfy alerts). Treat field names and
shapes as load-bearing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# ----- enums kept as Literal for forward-compat & free YAML serialization -----

CheckId = Literal[
    "stale_in_progress",
    "ghost_claimed",
    "duplicate_claim",
    "orphan_pr",
    "relay_yaml_stale",
    "wip_limit",
    "offered_stale",
    "refusal_dormancy",
]
"""The 8 check identifiers from research §2."""

Severity = Literal["info", "warning", "violation"]
"""Event severity tier. ntfy alerts (PR5) gate on `violation`."""

Role = Literal["alpha", "beta", "delta", "epsilon"]
"""Known peer-relay roles."""


class HygieneEvent(BaseModel):
    """One detected hygiene issue, append-only-logged.

    Events are emitted both to the markdown event log and to the JSON
    state file. The schema is identical in both surfaces.
    """

    timestamp: datetime
    """UTC ISO-8601 timestamp at which the sweep observed the issue."""

    check_id: CheckId
    """Which of the 8 checks fired."""

    severity: Severity
    """info / warning / violation. Drives downstream alert routing."""

    task_id: str | None = None
    """Vault `task_id` of the affected note, when applicable."""

    session: str | None = None
    """Peer-relay role implicated (alpha/beta/delta/epsilon), when applicable."""

    message: str
    """Operator-facing one-line description."""

    metadata: dict[str, str] = Field(default_factory=dict)
    """Free-form structured detail (PR numbers, ages in hours, etc.)."""


class SessionState(BaseModel):
    """Per-session current-claim summary, derived from relay yaml + vault."""

    role: str
    """Peer-relay role (alpha/beta/delta/epsilon)."""

    current_claim: str | None = None
    """`task_id` currently claimed by this session, if any."""

    relay_updated: datetime | None = None
    """Timestamp last written to `~/.cache/hapax/relay/{role}.yaml`."""

    in_progress_count: int = 0
    """Vault notes with `status: in_progress` AND `assigned_to: {role}`."""


class CheckSummary(BaseModel):
    """Aggregate counters for one check across the latest sweep."""

    check_id: CheckId
    fired: int = 0
    """How many times this check fired in the latest sweep."""


class HygieneState(BaseModel):
    """Top-level state snapshot persisted to JSON.

    Downstream PRs (waybar, Logos, ntfy) read this file. Bumping
    `schema_version` is a breaking change.
    """

    schema_version: int = 1
    """JSON Schema version. Bump on breaking field changes."""

    sweep_timestamp: datetime
    """UTC ISO-8601 of the sweep that produced this snapshot."""

    sweep_duration_ms: int
    """How long the sweep took, milliseconds."""

    killswitch_active: bool = False
    """True when `HAPAX_CC_HYGIENE_OFF=1` short-circuited the sweep."""

    sessions: list[SessionState] = Field(default_factory=list)
    """Per-session current-claim + WIP summary."""

    check_summaries: list[CheckSummary] = Field(default_factory=list)
    """Per-check fire counts for the latest sweep."""

    events: list[HygieneEvent] = Field(default_factory=list)
    """Events from the latest sweep (NOT cumulative — the markdown log is)."""


class TaskNote(BaseModel):
    """In-memory representation of a parsed vault cc-task note.

    Only the frontmatter fields the sweeper inspects are modelled — the
    note body is opaque.
    """

    path: str
    """Absolute path to the markdown file."""

    task_id: str
    """Vault frontmatter `task_id`."""

    status: str
    """offered / claimed / in_progress / pr_open / done / refused / superseded / withdrawn."""

    assigned_to: str | None = None
    """Session role currently owning the task ("unassigned" sentinel allowed)."""

    claimed_at: datetime | None = None
    branch: str | None = None
    pr: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

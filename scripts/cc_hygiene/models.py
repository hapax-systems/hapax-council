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
    "spec_staleness",
    "vault_link_integrity",
]
"""The 8 research §2 check identifiers, plus spec_staleness and the
Phase-0 vault_link_integrity recurrence guard."""

Severity = Literal["info", "warning", "violation"]
"""Event severity tier. ntfy alerts (PR5) gate on `violation`."""

type Role = str
"""Peer-relay identity. Claude uses alpha/beta/delta/epsilon; Codex uses cx-<color>."""


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
    """Peer-relay identity implicated, when applicable."""

    message: str
    """Operator-facing one-line description."""

    metadata: dict[str, str] = Field(default_factory=dict)
    """Free-form structured detail (PR numbers, ages in hours, etc.)."""


class SessionState(BaseModel):
    """Per-session current-claim summary, derived from relay yaml + vault."""

    role: str
    """Peer-relay identity."""

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

    title: str | None = None
    """Human-readable task title from frontmatter, when present."""

    status: str
    """offered / claimed / in_progress / pr_open / done / refused / superseded / withdrawn."""

    automation_status: str | None = None
    """FULL_AUTO / CONDITIONAL / REFUSED / REMOVED lifecycle state, when present."""

    priority: str | None = None
    """Priority bucket such as p0/p1/p2."""

    wsjf: float | None = None
    """WSJF score, when parseable."""

    assigned_to: str | None = None
    """Session role currently owning the task ("unassigned" sentinel allowed)."""

    claimed_at: datetime | None = None
    branch: str | None = None
    pr: int | None = None
    parent_request: str | None = None
    """Upstream request id (e.g. ``REQ-…``) resolved against hapax-requests."""
    parent_plan: str | None = None
    parent_spec: str | None = None
    tags: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None

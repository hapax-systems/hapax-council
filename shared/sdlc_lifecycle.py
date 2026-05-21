"""Shared SDLC lifecycle vocabulary and markdown closure helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass

TASK_ACTIVE_STATUSES = frozenset(
    {
        "offered",
        "claimed",
        "in_progress",
        "blocked",
        "pr_open",
        "ci_green",
        "merge_queue",
        "ready",
        "ready_for_review",
        "review_ready",
        "ready_for_merge",
    }
)

TASK_FULFILLING_CLOSED_STATUSES = frozenset(
    {"done", "completed", "complete", "closed", "fulfilled", "resolved"}
)
TASK_NON_FULFILLING_CLOSED_STATUSES = frozenset(
    {
        "withdrawn",
        "withdrawn_stale",
        "superseded",
        "closed_superseded",
        "rejected",
        "refused",
        "not_applicable",
        "deferred",
        "closed_poisoned",
    }
)
TASK_CLOSED_STATUSES = TASK_FULFILLING_CLOSED_STATUSES | TASK_NON_FULFILLING_CLOSED_STATUSES
TASK_TERMINAL_STATUSES = TASK_CLOSED_STATUSES | frozenset({"refused"})

REQUEST_TERMINAL_SKIP_STATUSES = frozenset(
    {"rejected", "deferred", "superseded", "withdrawn", "closed"}
)
REQUEST_CLOSEABLE_STATUSES = frozenset(
    {
        "",
        "captured",
        "triage",
        "clarification_needed",
        "clarification_answered",
        "normalized",
        "operator_confirmation",
        "accepted_for_planning",
        "planned",
        "active",
        "phase0_active",
    }
)

ACCEPTANCE_HEADING_RE = re.compile(r"^##\s+Acceptance\s+criteria\s*$", re.IGNORECASE | re.MULTILINE)
UNCHECKED_CHECKBOX_RE = re.compile(r"^\s*-\s+\[\s\]\s+(.*)$", re.MULTILINE)
CHECKED_CHECKBOX_RE = re.compile(r"^\s*-\s+\[[xX]\]\s+(.*)$", re.MULTILINE)
NEXT_HEADING_RE = re.compile(r"^##\s+", re.MULTILINE)


@dataclass(frozen=True)
class AcceptanceCriteriaState:
    section_present: bool
    checked_items: tuple[str, ...]
    unchecked_items: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return not self.unchecked_items


def is_fulfilling_task_status(status: str) -> bool:
    return status in TASK_FULFILLING_CLOSED_STATUSES


def is_non_fulfilling_task_status(status: str) -> bool:
    return status in TASK_NON_FULFILLING_CLOSED_STATUSES


def is_known_closed_task_status(status: str) -> bool:
    return status in TASK_CLOSED_STATUSES


def acceptance_criteria_section(text: str) -> str | None:
    match = ACCEPTANCE_HEADING_RE.search(text)
    if match is None:
        return None
    start = match.end()
    next_heading = NEXT_HEADING_RE.search(text, pos=start)
    end = next_heading.start() if next_heading else len(text)
    return text[start:end]


def acceptance_criteria_state(text: str) -> AcceptanceCriteriaState:
    section = acceptance_criteria_section(text)
    if section is None:
        return AcceptanceCriteriaState(
            section_present=False,
            checked_items=(),
            unchecked_items=(),
        )
    return AcceptanceCriteriaState(
        section_present=True,
        checked_items=tuple(
            match.group(1).strip() for match in CHECKED_CHECKBOX_RE.finditer(section)
        ),
        unchecked_items=tuple(
            match.group(1).strip() for match in UNCHECKED_CHECKBOX_RE.finditer(section)
        ),
    )

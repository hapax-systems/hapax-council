"""Shared SDLC lifecycle vocabulary and markdown closure helpers."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import yaml

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

# --- Canonical semantic status groups (coordination reform Phase 2: FM-5/G2) ---
# The single source of truth every status consumer references so the cc-task
# gate, the PR autoqueue, cc-claim/cc-close and the shape check AGREE. Before
# this, each hardcoded its own subset: the gate proceeded only on
# in_progress/claimed/pr_open/merge_queue while the autoqueue admitted the whole
# `ready` family — so ~88 active `ready` tasks were claimable-but-unmutatable
# (stranded). Spec: docs/superpowers/specs/2026-05-30-sdlc-frictionless-self-direction-design.md.

#: A fresh, unheld task may be claimed only from `offered`.
TASK_CLAIMABLE_STATUSES = frozenset({"offered"})

#: Ready-family — implementation done / under review / awaiting merge. Distinct
#: labels accumulated historically; treated as one concept everywhere.
TASK_READY_FAMILY_STATUSES = frozenset(
    {"ci_green", "ready", "ready_for_review", "review_ready", "ready_for_merge"}
)

#: The owning lane may still mutate files in these states (CI fixes, review
#: feedback, merge-queue/closeout maintenance). This is the gate proceed-set —
#: the bash gate's section-9 case MUST match this set (pinned by
#: tests/hooks/test_cc_task_gate.py::TestStatusVocabularyDrift).
TASK_MUTABLE_STATUSES = (
    frozenset({"claimed", "in_progress", "pr_open", "merge_queue"}) | TASK_READY_FAMILY_STATUSES
)

#: PRs the autoqueue may consider for merge admission (the active, not-yet-closed
#: ready states). cc-pr-autoqueue adds the fulfilling-closed states separately.
TASK_MERGE_READY_STATUSES = frozenset({"pr_open", "merge_queue"}) | TASK_READY_FAMILY_STATUSES

#: A lane may RESUME (re-claim) an owned task in these states — not a fresh claim.
TASK_RESUMABLE_STATUSES = TASK_MERGE_READY_STATUSES

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


@dataclass(frozen=True)
class TaskClosureValidity:
    """Result for whether a cc-task can satisfy downstream dependencies."""

    valid: bool
    blockers: tuple[str, ...]
    frontmatter: Mapping[str, Any]


PrStateLookup = Callable[[str], str | None]


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


def frontmatter_from_text(text: str) -> dict[str, Any]:
    """Return YAML frontmatter from a markdown note, or an empty mapping."""

    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 4)
    if end < 0:
        return {}
    raw = text[4:end].strip()
    if not raw:
        return {}
    loaded = yaml.safe_load(raw)
    if isinstance(loaded, dict):
        return loaded
    return {}


def _frontmatter_scalar(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip().strip('"').strip("'")


def _frontmatter_pr_number(frontmatter: Mapping[str, Any]) -> str | None:
    value = _frontmatter_scalar(frontmatter.get("pr"))
    if value.lower() in {"", "null", "none", "~"}:
        return None
    return value.lstrip("#")


def _route_metadata_blockers(frontmatter: Mapping[str, Any]) -> tuple[str, ...]:
    from shared.route_metadata_schema import assess_route_metadata

    assessment = assess_route_metadata(frontmatter)
    if assessment.dispatchable:
        return ()
    reasons = [
        *assessment.hold_reasons,
        *assessment.missing_fields,
        *assessment.validation_errors,
    ]
    return tuple(f"route_metadata:{reason}" for reason in reasons or ("invalid",))


def task_closure_validity(
    text: str,
    *,
    pr_state_lookup: PrStateLookup | None = None,
    require_route_metadata: bool = False,
) -> TaskClosureValidity:
    """Validate that a cc-task closure may satisfy downstream work.

    This predicate is stricter than "status is done": it requires a fulfilling
    terminal status, no unchecked Acceptance criteria boxes, a merged declared
    PR when a PR can be checked, and valid route metadata when that surface is
    required by the caller.
    """

    frontmatter = frontmatter_from_text(text)
    status = _frontmatter_scalar(frontmatter.get("status")).lower()
    blockers: list[str] = []

    if status not in TASK_FULFILLING_CLOSED_STATUSES:
        blockers.append(f"status_not_fulfilling:{status or 'missing'}")

    ac_state = acceptance_criteria_state(text)
    blockers.extend(f"unchecked_acceptance_criteria:{item}" for item in ac_state.unchecked_items)

    pr_number = _frontmatter_pr_number(frontmatter)
    if pr_number and pr_state_lookup is not None:
        state = (pr_state_lookup(pr_number) or "unknown").strip().lower()
        if state == "merged":
            pass
        elif state == "open":
            blockers.append(f"pr_open:{pr_number}")
        elif state in {"closed_unmerged", "closed"}:
            blockers.append(f"pr_closed_unmerged:{pr_number}")
        else:
            blockers.append(f"pr_unknown:{pr_number}")

    if require_route_metadata:
        blockers.extend(_route_metadata_blockers(frontmatter))

    return TaskClosureValidity(
        valid=not blockers,
        blockers=tuple(blockers),
        frontmatter=frontmatter,
    )

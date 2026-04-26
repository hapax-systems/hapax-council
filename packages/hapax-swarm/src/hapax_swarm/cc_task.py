"""cc-task SSOT — markdown-with-frontmatter task model.

The cc-task pattern stores per-task state as YAML frontmatter inside a
human-readable markdown note. It is the canonical work-state surface
for the Hapax operating environment (Obsidian-vault-native, but works
from any directory of markdown files).

Status machine::

    offered → claimed → in_progress → pr_open → ci_green → done
                                          ↓           ↓
                                      needs_review  ci_failed
                                          ↓           ↓
                                        done       fix → pr_open

Atomic transitions:

- :meth:`CcTask.claim`     — ``offered`` → ``claimed`` (assigned_to set, claimed_at stamped).
- :meth:`CcTask.start`     — ``claimed`` → ``in_progress``.
- :meth:`CcTask.open_pr`   — ``in_progress`` → ``pr_open`` (records pr URL + branch).
- :meth:`CcTask.mark_done` — any → ``done`` (completed_at stamped).

All transitions raise on illegal state, leaving the task untouched.
"""

from __future__ import annotations

import dataclasses
import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import yaml

from hapax_swarm.atomic import atomic_write_text

if TYPE_CHECKING:
    from pathlib import Path


class CcTaskStatus(StrEnum):
    OFFERED = "offered"
    CLAIMED = "claimed"
    IN_PROGRESS = "in_progress"
    PR_OPEN = "pr_open"
    CI_GREEN = "ci_green"
    CI_FAILED = "ci_failed"
    NEEDS_REVIEW = "needs_review"
    DONE = "done"
    WITHDRAWN = "withdrawn"
    SUPERSEDED = "superseded"


_FRONTMATTER_RE = re.compile(
    r"\A---\n(?P<frontmatter>.*?)\n---\n(?P<body>.*)\Z",
    re.DOTALL,
)


@dataclasses.dataclass
class CcTask:
    """A single cc-task note with parsed frontmatter and raw body.

    Construct via :meth:`CcTask.load`. Mutate via the transition
    methods. Persist via :meth:`CcTask.save`.
    """

    path: Path
    frontmatter: dict[str, Any]
    body: str

    # --- IO --------------------------------------------------------

    @classmethod
    def load(cls, path: Path) -> CcTask:
        """Load a cc-task from a markdown-with-frontmatter file."""
        text = path.read_text(encoding="utf-8")
        match = _FRONTMATTER_RE.match(text)
        if not match:
            raise ValueError(f"{path}: not a frontmatter markdown file (missing leading '---')")
        loaded = yaml.safe_load(match.group("frontmatter"))
        if not isinstance(loaded, dict):
            raise ValueError(f"{path}: frontmatter is not a mapping")
        return cls(path=path, frontmatter=loaded, body=match.group("body"))

    def save(self) -> None:
        """Atomically write the task back to ``self.path``.

        Writes ``self.frontmatter`` (re-emitted as YAML) followed by
        ``self.body`` (preserved verbatim).
        """
        fm_text = yaml.safe_dump(self.frontmatter, sort_keys=False, default_flow_style=False)
        text = f"---\n{fm_text}---\n{self.body}"
        atomic_write_text(self.path, text)

    # --- accessors -------------------------------------------------

    @property
    def task_id(self) -> str:
        value = self.frontmatter.get("task_id")
        if not isinstance(value, str) or not value:
            raise ValueError(f"{self.path}: task_id is missing or non-string")
        return value

    @property
    def status(self) -> CcTaskStatus:
        value = self.frontmatter.get("status")
        if not isinstance(value, str):
            raise ValueError(f"{self.path}: status is missing or non-string")
        return CcTaskStatus(value)

    @property
    def assigned_to(self) -> str | None:
        value = self.frontmatter.get("assigned_to")
        if value in (None, "unassigned"):
            return None
        if not isinstance(value, str):
            raise ValueError(f"{self.path}: assigned_to is non-string")
        return value

    # --- transitions -----------------------------------------------

    def claim(self, *, role: str) -> None:
        """``offered`` → ``claimed``.

        Stamps ``assigned_to`` and ``claimed_at``. Raises if status is
        not ``offered`` or ``assigned_to`` is already set.
        """
        if self.status is not CcTaskStatus.OFFERED:
            raise CcTaskStateError(
                f"cannot claim {self.task_id}: status is {self.status}, not offered"
            )
        if self.assigned_to is not None:
            raise CcTaskStateError(
                f"cannot claim {self.task_id}: already assigned to {self.assigned_to}"
            )
        now = _utc_now_iso()
        self.frontmatter["status"] = CcTaskStatus.CLAIMED.value
        self.frontmatter["assigned_to"] = role
        self.frontmatter["claimed_at"] = now
        self.frontmatter["updated_at"] = now

    def start(self) -> None:
        """``claimed`` → ``in_progress``."""
        if self.status is not CcTaskStatus.CLAIMED:
            raise CcTaskStateError(
                f"cannot start {self.task_id}: status is {self.status}, not claimed"
            )
        self.frontmatter["status"] = CcTaskStatus.IN_PROGRESS.value
        self.frontmatter["updated_at"] = _utc_now_iso()

    def open_pr(self, *, pr_url: str, branch: str) -> None:
        """``in_progress`` → ``pr_open``."""
        if self.status is not CcTaskStatus.IN_PROGRESS:
            raise CcTaskStateError(
                f"cannot open_pr {self.task_id}: status is {self.status}, not in_progress"
            )
        self.frontmatter["status"] = CcTaskStatus.PR_OPEN.value
        self.frontmatter["pr"] = pr_url
        self.frontmatter["branch"] = branch
        self.frontmatter["updated_at"] = _utc_now_iso()

    def mark_done(self) -> None:
        """Any → ``done`` (sets ``completed_at``)."""
        now = _utc_now_iso()
        self.frontmatter["status"] = CcTaskStatus.DONE.value
        self.frontmatter["completed_at"] = now
        self.frontmatter["updated_at"] = now


class CcTaskStateError(RuntimeError):
    """Raised when a state transition is illegal."""


def _utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

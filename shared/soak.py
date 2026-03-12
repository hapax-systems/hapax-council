"""Soak period tracking for auto-merged PRs.

After a PR is auto-merged, monitor health for a soak period.
If health degrades, trigger auto-revert.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class SoakEntry:
    pr_number: int
    branch: str
    merged_at: float
    soak_until: float
    category: str
    commit_sha: str = ""
    checks_passed: int = 0
    reverted: bool = False
    completed: bool = False


@dataclass
class SoakManager:
    """Track merged PRs during their soak period."""

    state_path: Path = field(default_factory=lambda: Path("profiles/soak-state.json"))
    _entries: list[SoakEntry] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self._load()

    def _load(self) -> None:
        if self.state_path.exists():
            try:
                data = json.loads(self.state_path.read_text())
                self._entries = [SoakEntry(**e) for e in data]
            except (json.JSONDecodeError, TypeError):
                self._entries = []

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps([asdict(e) for e in self._entries], indent=2))
        tmp.rename(self.state_path)

    def register_merge(
        self,
        pr_number: int,
        branch: str,
        category: str,
        commit_sha: str = "",
        soak_minutes: int = 30,
    ) -> None:
        """Register a newly merged PR for soak monitoring."""
        now = time.time()
        entry = SoakEntry(
            pr_number=pr_number,
            branch=branch,
            merged_at=now,
            soak_until=now + soak_minutes * 60,
            category=category,
            commit_sha=commit_sha,
        )
        self._entries.append(entry)
        self._save()

    def active_entries(self) -> list[SoakEntry]:
        """Return entries currently in soak period."""
        now = time.time()
        return [
            e for e in self._entries
            if not e.completed and not e.reverted and now < e.soak_until
        ]

    def record_health_check(self, healthy: bool) -> list[SoakEntry]:
        """Record a health check during soak. Returns degraded entries.

        If healthy, increment checks_passed on all active entries.
        If not healthy, return entries that should be reverted.
        """
        degraded = []
        for entry in self.active_entries():
            if healthy:
                entry.checks_passed += 1
            else:
                degraded.append(entry)
        self._save()
        return degraded

    def mark_reverted(self, pr_number: int) -> None:
        """Mark a soaking PR as reverted."""
        for entry in self._entries:
            if entry.pr_number == pr_number:
                entry.reverted = True
        self._save()

    def complete_soak(self, pr_number: int) -> None:
        """Mark a PR as having passed its soak period."""
        for entry in self._entries:
            if entry.pr_number == pr_number:
                entry.completed = True
        self._save()

    def complete_expired(self) -> list[SoakEntry]:
        """Complete all entries past their soak_until time. Returns completed entries."""
        now = time.time()
        completed = []
        for entry in self._entries:
            if not entry.completed and not entry.reverted and now >= entry.soak_until:
                entry.completed = True
                completed.append(entry)
        if completed:
            self._save()
        return completed

    def cleanup(self, max_age_days: int = 30) -> None:
        """Remove old completed/reverted entries."""
        cutoff = time.time() - max_age_days * 86400
        self._entries = [
            e for e in self._entries
            if not (e.completed or e.reverted) or e.merged_at > cutoff
        ]
        self._save()

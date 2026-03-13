"""cockpit/engine/models.py — Data models for the reactive engine event pipeline."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# Service path patterns replicated from agents/ingest.py:403-415
# to avoid importing heavy ingest dependencies.
_SERVICE_PATH_PATTERNS: dict[str, str] = {
    "rag-sources/gdrive": "gdrive",
    "rag-sources/gcalendar": "gcalendar",
    "rag-sources/gmail": "gmail",
    "rag-sources/youtube": "youtube",
    "rag-sources/takeout": "takeout",
    "rag-sources/proton": "proton",
    "rag-sources/claude-code": "claude-code",
    "rag-sources/obsidian": "obsidian",
    "rag-sources/chrome": "chrome",
    "rag-sources/audio": "ambient-audio",
    "rag-sources/health-connect": "health_connect",
}


@dataclass
class ChangeEvent:
    """A filesystem change enriched with document metadata."""

    path: Path
    event_type: str  # created | modified | deleted | moved
    doc_type: str | None
    frontmatter: dict | None
    timestamp: datetime
    data_dir: Path | None = None

    @property
    def subdirectory(self) -> str:
        """First path component relative to data_dir."""
        if self.data_dir is None:
            return str(self.path.parent.name)
        try:
            rel = self.path.relative_to(self.data_dir)
            return rel.parts[0] if rel.parts else ""
        except ValueError:
            return str(self.path.parent.name)

    @property
    def source_service(self) -> str | None:
        """For rag-sources paths, detect the service name."""
        path_str = str(self.path)
        for pattern, service in _SERVICE_PATH_PATTERNS.items():
            if pattern in path_str:
                return service
        return None


@dataclass
class Action:
    """A unit of work produced by a rule."""

    name: str
    handler: Callable[..., Awaitable[Any]]
    args: dict = field(default_factory=dict)
    priority: int = 50
    phase: int = 0
    depends_on: list[str] = field(default_factory=list)


@dataclass
class ActionPlan:
    """Accumulates actions from rule evaluation and tracks execution results."""

    actions: list[Action] = field(default_factory=list)
    results: dict[str, Any] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    skipped: set[str] = field(default_factory=set)

    def actions_by_phase(self) -> dict[int, list[Action]]:
        """Group actions by phase, sorted by priority (ascending) within each phase."""
        grouped: dict[int, list[Action]] = defaultdict(list)
        for action in self.actions:
            grouped[action.phase].append(action)
        for phase_actions in grouped.values():
            phase_actions.sort(key=lambda a: a.priority)
        return dict(grouped)


@dataclass
class DeliveryItem:
    """A notification item for the delivery queue."""

    priority: int
    category: str
    message: str
    source_action: str
    timestamp: datetime = field(default_factory=datetime.now)
    artifacts: dict[str, Any] = field(default_factory=dict)

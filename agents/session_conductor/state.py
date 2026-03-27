"""Session state model and serialization."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path


class EpicPhase(Enum):
    RESEARCH = "research"
    DESIGN = "design"
    DESIGN_GAPS = "design_gaps"
    PLANNING = "planning"
    PLANNING_GAPS = "planning_gaps"
    IMPLEMENTATION = "implementation"


EPIC_PHASE_ORDER = list(EpicPhase)

MAX_RESEARCH_ROUNDS = 5
MAX_GAP_ROUNDS = 2
CONVERGENCE_THRESHOLD = 0.30


@dataclass
class TopicState:
    slug: str
    rounds: int
    findings_per_round: list[int]
    first_seen: datetime
    prior_file: Path
    blocked_at_round: int | None = None

    def is_converging(self) -> bool:
        """True if last 2 rounds each found ≤30% of first round's findings."""
        if len(self.findings_per_round) < 3:
            return False
        first = self.findings_per_round[0]
        if first == 0:
            return True
        last_two = self.findings_per_round[-2:]
        return all(r / first <= CONVERGENCE_THRESHOLD for r in last_two)

    def is_capped(self) -> bool:
        return self.rounds >= MAX_RESEARCH_ROUNDS

    def matches_prompt(self, prompt: str) -> bool:
        """Check if a prompt is about this topic via keyword overlap."""
        slug_words = set(self.slug.split("-"))
        prompt_words = set(re.sub(r"[^a-z0-9\s]", "", prompt.lower()).split())
        if not slug_words:
            return False
        overlap = len(slug_words & prompt_words) / len(slug_words)
        return overlap >= 0.6


@dataclass
class ChildSession:
    session_id: str
    topic: str
    spawn_manifest: Path
    status: str  # pending, claimed, completed, orphaned


@dataclass
class SessionState:
    session_id: str
    pid: int
    started_at: datetime
    parent_session: str | None = None
    children: list[ChildSession] = field(default_factory=list)
    active_topics: dict[str, TopicState] = field(default_factory=dict)
    in_flight_files: set[str] = field(default_factory=set)
    epic_phase: EpicPhase | None = None
    last_relay_sync: datetime | None = None
    workstream_summary: str = ""
    smoke_test_active: bool = False

    def save(self, path: Path) -> None:
        """Serialize state to JSON file."""
        data = {
            "session_id": self.session_id,
            "pid": self.pid,
            "started_at": self.started_at.isoformat(),
            "parent_session": self.parent_session,
            "children": [
                {
                    "session_id": c.session_id,
                    "topic": c.topic,
                    "spawn_manifest": str(c.spawn_manifest),
                    "status": c.status,
                }
                for c in self.children
            ],
            "active_topics": {
                slug: {
                    "slug": t.slug,
                    "rounds": t.rounds,
                    "findings_per_round": t.findings_per_round,
                    "first_seen": t.first_seen.isoformat(),
                    "prior_file": str(t.prior_file),
                    "blocked_at_round": t.blocked_at_round,
                }
                for slug, t in self.active_topics.items()
            },
            "in_flight_files": sorted(self.in_flight_files),
            "epic_phase": self.epic_phase.value if self.epic_phase else None,
            "last_relay_sync": self.last_relay_sync.isoformat() if self.last_relay_sync else None,
            "workstream_summary": self.workstream_summary,
            "smoke_test_active": self.smoke_test_active,
        }
        path.write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls, path: Path) -> SessionState:
        """Deserialize state from JSON file."""
        data = json.loads(path.read_text())
        state = cls(
            session_id=data["session_id"],
            pid=data["pid"],
            started_at=datetime.fromisoformat(data["started_at"]),
            parent_session=data.get("parent_session"),
            workstream_summary=data.get("workstream_summary", ""),
            smoke_test_active=data.get("smoke_test_active", False),
        )
        state.children = [
            ChildSession(
                session_id=c["session_id"],
                topic=c["topic"],
                spawn_manifest=Path(c["spawn_manifest"]),
                status=c["status"],
            )
            for c in data.get("children", [])
        ]
        state.active_topics = {
            slug: TopicState(
                slug=t["slug"],
                rounds=t["rounds"],
                findings_per_round=t["findings_per_round"],
                first_seen=datetime.fromisoformat(t["first_seen"]),
                prior_file=Path(t["prior_file"]),
                blocked_at_round=t.get("blocked_at_round"),
            )
            for slug, t in data.get("active_topics", {}).items()
        }
        state.in_flight_files = set(data.get("in_flight_files", []))
        phase = data.get("epic_phase")
        state.epic_phase = EpicPhase(phase) if phase else None
        sync = data.get("last_relay_sync")
        state.last_relay_sync = datetime.fromisoformat(sync) if sync else None
        return state

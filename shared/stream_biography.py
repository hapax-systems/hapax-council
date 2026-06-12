"""Stream biography — grounding-native self-model of the livestream's narrative history.

The biography is populated exclusively by grounding queries against
chronicle and transcript. Evidence-of-absence is first-class: a null
result for "operator introduction" IS the evidence that no introduction
has occurred. Never written from configuration or rules.

CASE-NARRATIVE-ARC-AWARENESS-20260519 Layer 1.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from shared.jsonl_retention import append_bounded_jsonl_line
from shared.jsonl_rotation import iter_retained_jsonl_lines

log = logging.getLogger(__name__)

SHM_PATH = Path("/dev/shm/hapax-compositor/stream-biography.json")
PERSIST_PATH = Path.home() / "hapax-state" / "stream-biography.jsonl"
MAX_PERSISTED_SNAPSHOTS = 16


@dataclass
class GroundedConcept:
    concept: str
    evidence_refs: list[str] = field(default_factory=list)
    grounding_confidence: float = 0.0
    first_established_at: float = 0.0
    last_reinforced_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "concept": self.concept,
            "evidence_refs": self.evidence_refs,
            "grounding_confidence": self.grounding_confidence,
            "first_established_at": self.first_established_at,
            "last_reinforced_at": self.last_reinforced_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> GroundedConcept:
        return cls(
            concept=d.get("concept", ""),
            evidence_refs=d.get("evidence_refs", []),
            grounding_confidence=d.get("grounding_confidence", 0.0),
            first_established_at=d.get("first_established_at", 0.0),
            last_reinforced_at=d.get("last_reinforced_at", 0.0),
        )


@dataclass
class GroundedIntroduction:
    subject: str
    evidence_refs: list[str] = field(default_factory=list)
    introduced_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "subject": self.subject,
            "evidence_refs": self.evidence_refs,
            "introduced_at": self.introduced_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> GroundedIntroduction:
        return cls(
            subject=d.get("subject", ""),
            evidence_refs=d.get("evidence_refs", []),
            introduced_at=d.get("introduced_at", 0.0),
        )


@dataclass
class NarrativeEvent:
    event_type: str
    description: str
    timestamp: float = 0.0

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type,
            "description": self.description,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict) -> NarrativeEvent:
        return cls(
            event_type=d.get("event_type", ""),
            description=d.get("description", ""),
            timestamp=d.get("timestamp", 0.0),
        )


@dataclass
class StreamBiography:
    established_concepts: list[GroundedConcept] = field(default_factory=list)
    introductions: list[GroundedIntroduction] = field(default_factory=list)
    narrative_events: list[NarrativeEvent] = field(default_factory=list)
    total_segments_completed: int = 0
    total_stream_hours: float = 0.0
    show_started_at: float = 0.0
    last_updated_at: float = 0.0

    def concept_grounded(self, concept: str) -> float:
        for c in self.established_concepts:
            if c.concept == concept:
                return c.grounding_confidence
        return 0.0

    def has_introduction(self, subject: str) -> bool:
        return any(i.subject == subject for i in self.introductions)

    def record_concept(self, concept: GroundedConcept) -> None:
        for i, c in enumerate(self.established_concepts):
            if c.concept == concept.concept:
                self.established_concepts[i] = concept
                return
        self.established_concepts.append(concept)

    def record_introduction(self, intro: GroundedIntroduction) -> None:
        for i, existing in enumerate(self.introductions):
            if existing.subject == intro.subject:
                self.introductions[i] = intro
                return
        self.introductions.append(intro)

    def record_event(self, event: NarrativeEvent) -> None:
        self.narrative_events.append(event)

    def latest_narrative_stage(self) -> str:
        for event in reversed(self.narrative_events):
            if event.event_type == "stage_assessment" and event.description:
                return event.description
        if (
            self.total_segments_completed == 0
            and not self.established_concepts
            and not self.introductions
        ):
            return "inchoate"
        if self.total_segments_completed < 2 or not self.introductions:
            return "opening"
        if len(self.established_concepts) < 3:
            return "developing"
        return "established"

    def evidence_gaps(self) -> list[str]:
        gaps: list[str] = []
        if not self.introductions:
            gaps.append("operator/system introduction absent")
        if not self.established_concepts:
            gaps.append("no established concepts")
        if self.total_segments_completed == 0:
            gaps.append("no completed segments")
        return gaps

    def to_dict(self) -> dict:
        return {
            "established_concepts": [c.to_dict() for c in self.established_concepts],
            "introductions": [i.to_dict() for i in self.introductions],
            "narrative_events": [e.to_dict() for e in self.narrative_events],
            "total_segments_completed": self.total_segments_completed,
            "total_stream_hours": self.total_stream_hours,
            "show_started_at": self.show_started_at,
            "last_updated_at": self.last_updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> StreamBiography:
        return cls(
            established_concepts=[
                GroundedConcept.from_dict(c) for c in d.get("established_concepts", [])
            ],
            introductions=[GroundedIntroduction.from_dict(i) for i in d.get("introductions", [])],
            narrative_events=[NarrativeEvent.from_dict(e) for e in d.get("narrative_events", [])],
            total_segments_completed=d.get("total_segments_completed", 0),
            total_stream_hours=d.get("total_stream_hours", 0.0),
            show_started_at=d.get("show_started_at", 0.0),
            last_updated_at=d.get("last_updated_at", 0.0),
        )

    def to_planner_summary(self) -> str:
        parts: list[str] = []
        stage = self.latest_narrative_stage()
        parts.append(f"Narrative stage: {stage}")
        parts.append(
            f"Stream age: {self.total_stream_hours:.1f}h, {self.total_segments_completed} segments completed"
        )

        if self.established_concepts:
            parts.append(f"Established concepts ({len(self.established_concepts)}):")
            for c in self.established_concepts:
                parts.append(
                    f"  - {c.concept} (confidence={c.grounding_confidence:.2f}, refs={len(c.evidence_refs)})"
                )
        else:
            parts.append("Established concepts: NONE — stream is inchoate")

        if self.introductions:
            parts.append(f"Introductions ({len(self.introductions)}):")
            for i in self.introductions:
                parts.append(f"  - {i.subject}")
        else:
            parts.append("Introductions: NONE — operator and system have not been introduced")

        gaps = self.evidence_gaps()
        if gaps:
            parts.append("Evidence gaps:")
            for gap in gaps:
                parts.append(f"  - {gap}")

        return "\n".join(parts)


def write_shm(bio: StreamBiography, path: Path = SHM_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    bio.last_updated_at = time.time()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(bio.to_dict()), encoding="utf-8")
    tmp.replace(path)


def read_shm(path: Path = SHM_PATH) -> StreamBiography:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return StreamBiography.from_dict(data)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return StreamBiography()


def persist(
    bio: StreamBiography,
    path: Path = PERSIST_PATH,
    *,
    max_snapshots: int = MAX_PERSISTED_SNAPSHOTS,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # jsonl-rotation: exempt(inline bounded latest-state history; keeps newest snapshots)
    append_bounded_jsonl_line(path, json.dumps(bio.to_dict()), max_lines=max_snapshots)


def load_persisted(path: Path = PERSIST_PATH) -> StreamBiography | None:
    try:
        lines = [line.strip() for line in iter_retained_jsonl_lines(path) if line.strip()]
        if not lines:
            return None
        return StreamBiography.from_dict(json.loads(lines[-1]))
    except (json.JSONDecodeError, OSError):
        return None

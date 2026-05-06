"""Vocabulary manager — learns and prunes YOLO-World detection vocabulary.

Tracks detection statistics per label, manages vocabulary lifecycle
(seed -> candidate -> confirmed -> pruned), and provides the active
vocabulary list for YOLO-World open-vocabulary detection.

Vocabulary changes take effect on daemon restart (calling model.set_classes()
mid-run causes CPU/CUDA device mismatch).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

# Promotion thresholds
_PROMOTE_HIGH_CONF_COUNT = 20
_PROMOTE_MIN_CAMERAS = 2
_PROMOTE_MIN_SESSIONS = 5

# Pruning threshold
_PRUNE_UNSEEN_DAYS = 7

SEED_VOCAB = [
    "person",
    "face",
    "hand",
    "computer monitor",
    "keyboard",
    "mouse",
    "synthesizer",
    "drum machine",
    "turntable",
    "mixer",
    "audio interface",
    "studio monitor speaker",
    "headphones",
    "microphone",
    "chair",
    "desk",
    "phone",
    "cup",
    "bottle",
    "book",
    "speaker",
    "cable",
    "poster",
    "LED light",
    "MIDI controller",
    "laptop screen",
    "shelf",
    "amplifier",
]


@dataclass
class VocabEntry:
    """A single vocabulary entry with detection statistics."""

    label: str
    status: str  # "seed" | "candidate" | "confirmed" | "pruned"
    source: str  # "seed" | "auto" | "manual"
    added_at: float
    last_seen: float
    detection_count: int
    high_conf_count: int  # confidence > 0.5
    cameras_seen: set[str] = field(default_factory=set)
    session_count: int = 0

    def to_dict(self) -> dict[str, object]:
        """Serialize for JSON persistence."""
        return {
            "label": self.label,
            "status": self.status,
            "source": self.source,
            "added_at": self.added_at,
            "last_seen": self.last_seen,
            "detection_count": self.detection_count,
            "high_conf_count": self.high_conf_count,
            "cameras_seen": sorted(self.cameras_seen),
            "session_count": self.session_count,
        }

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> VocabEntry:
        """Deserialize from JSON."""
        return cls(
            label=d["label"],
            status=d.get("status", "seed"),
            source=d.get("source", "seed"),
            added_at=d.get("added_at", 0.0),
            last_seen=d.get("last_seen", 0.0),
            detection_count=d.get("detection_count", 0),
            high_conf_count=d.get("high_conf_count", 0),
            cameras_seen=set(d.get("cameras_seen", [])),
            session_count=d.get("session_count", 0),
        )


class VocabularyManager:
    """Manages YOLO-World detection vocabulary with learning and pruning."""

    def __init__(self, persist_path: Path | None = None) -> None:
        self._entries: dict[str, VocabEntry] = {}
        self._persist_path = (
            persist_path or Path.home() / ".cache" / "hapax-daimonion" / "learned-vocabulary.json"
        )
        self._session_labels: set[str] = set()  # labels seen this session
        self._load()
        self._ensure_seeds()

    def record_detection(self, label: str, confidence: float, camera: str) -> None:
        """Record a detection for vocabulary statistics."""
        entry = self._entries.get(label)
        if entry is None:
            # Auto-discovered label — add as candidate
            self.add_candidate(label, source="auto")
            entry = self._entries[label]

        entry.detection_count += 1
        entry.last_seen = time.time()
        entry.cameras_seen.add(camera)
        if confidence > 0.5:
            entry.high_conf_count += 1

        # Track session participation
        if label not in self._session_labels:
            self._session_labels.add(label)
            entry.session_count += 1

        # Check for promotion/pruning periodically
        if entry.detection_count % 50 == 0:
            self._check_promotions()
            self._check_pruning()
            self._persist()

    def get_active_vocab(self) -> list[str]:
        """Return the current active vocabulary for YOLO-World.

        Includes all seed, candidate, and confirmed labels.
        Excludes pruned labels.
        """
        return [
            e.label
            for e in self._entries.values()
            if e.status in ("seed", "candidate", "confirmed")
        ]

    def add_candidate(self, label: str, source: str = "auto") -> None:
        """Add a candidate vocabulary entry."""
        if label in self._entries:
            return
        self._entries[label] = VocabEntry(
            label=label,
            status="candidate",
            source=source,
            added_at=time.time(),
            last_seen=time.time(),
            detection_count=0,
            high_conf_count=0,
        )
        log.debug("Vocab candidate added: %s (source=%s)", label, source)

    def promote(self, label: str) -> None:
        """Promote a candidate to confirmed."""
        entry = self._entries.get(label)
        if entry and entry.status in ("candidate", "seed"):
            entry.status = "confirmed"
            log.info("Vocab promoted: %s (%d detections)", label, entry.detection_count)

    def prune(self, label: str, reason: str = "unused") -> None:
        """Move a label to pruned status."""
        entry = self._entries.get(label)
        if entry:
            entry.status = "pruned"
            log.info("Vocab pruned: %s (reason=%s)", label, reason)

    def teach(self, label: str) -> None:
        """Operator-taught label — immediately confirmed."""
        if label in self._entries:
            self._entries[label].status = "confirmed"
            self._entries[label].source = "manual"
        else:
            self._entries[label] = VocabEntry(
                label=label,
                status="confirmed",
                source="manual",
                added_at=time.time(),
                last_seen=time.time(),
                detection_count=0,
                high_conf_count=0,
            )
        log.info("Vocab taught: %s (operator)", label)
        self._persist()

    def _check_promotions(self) -> list[str]:
        """Check if any candidates should be promoted.

        Promote if: 20+ high-conf detections, seen on 2+ cameras or 5+ sessions.
        """
        promoted: list[str] = []
        for entry in self._entries.values():
            if entry.status != "candidate":
                continue
            if entry.high_conf_count >= _PROMOTE_HIGH_CONF_COUNT and (
                len(entry.cameras_seen) >= _PROMOTE_MIN_CAMERAS
                or entry.session_count >= _PROMOTE_MIN_SESSIONS
            ):
                entry.status = "confirmed"
                promoted.append(entry.label)
                log.info(
                    "Vocab auto-promoted: %s (high_conf=%d, cameras=%d, sessions=%d)",
                    entry.label,
                    entry.high_conf_count,
                    len(entry.cameras_seen),
                    entry.session_count,
                )
        return promoted

    def _check_pruning(self) -> list[str]:
        """Check if any confirmed labels should be pruned.

        Prune if: zero detections for 7+ days. Never prune seed labels.
        """
        pruned: list[str] = []
        now = time.time()
        cutoff = now - _PRUNE_UNSEEN_DAYS * 86400
        for entry in self._entries.values():
            if entry.status in ("pruned", "seed"):
                continue
            if entry.source == "manual":
                continue  # never auto-prune operator-taught labels
            if entry.last_seen < cutoff and entry.detection_count > 0:
                entry.status = "pruned"
                pruned.append(entry.label)
                log.info(
                    "Vocab auto-pruned: %s (unseen for %.1f days)",
                    entry.label,
                    (now - entry.last_seen) / 86400,
                )
        return pruned

    def _ensure_seeds(self) -> None:
        """Ensure all seed vocabulary entries exist."""
        now = time.time()
        added = 0
        for label in SEED_VOCAB:
            if label not in self._entries:
                self._entries[label] = VocabEntry(
                    label=label,
                    status="seed",
                    source="seed",
                    added_at=now,
                    last_seen=0.0,
                    detection_count=0,
                    high_conf_count=0,
                )
                added += 1
        if added:
            log.info("Vocab seeded: %d new entries (total %d)", added, len(self._entries))
            self._persist()

    def _persist(self) -> None:
        """Save vocabulary to disk."""
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "version": 1,
                "saved_at": time.time(),
                "entries": [e.to_dict() for e in self._entries.values()],
            }
            tmp = self._persist_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.rename(self._persist_path)
        except OSError:
            log.debug("Failed to persist vocabulary", exc_info=True)

    def _load(self) -> None:
        """Load vocabulary from disk on startup.

        Validates the JSON root is a mapping. ``raw.get("version")`` and
        ``raw.get("entries", [])`` are called outside the
        ``(OSError, json.JSONDecodeError)`` catch — a writer producing
        valid JSON whose root is null, a list, a string, or a number
        previously raised AttributeError out of vocabulary startup,
        crashing the daimonion vocabulary subsystem on first read. Same
        corruption-class as the other recent SHM-read fixes.
        """
        try:
            if not self._persist_path.exists():
                return
            raw = json.loads(self._persist_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            log.debug("Failed to load vocabulary", exc_info=True)
            return
        if not isinstance(raw, dict):
            log.debug(
                "vocabulary persist file root is %s, expected mapping",
                type(raw).__name__,
            )
            return
        if raw.get("version") != 1:
            return
        for entry_dict in raw.get("entries", []):
            try:
                entry = VocabEntry.from_dict(entry_dict)
                self._entries[entry.label] = entry
            except (KeyError, TypeError, ValueError):
                continue
        log.info("Vocabulary loaded: %d entries from disk", len(self._entries))

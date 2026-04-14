"""Shared schema + helpers for the LRR Phase 2 stream archive.

The stream archive takes closed HLS segments + FLAC audio files and moves
them under ``~/hapax-state/stream-archive/`` with a per-segment metadata
sidecar that captures the research context in which the segment was
recorded. The sidecar is the join key between raw media and the research
registry (``~/hapax-state/research-registry/``) for later claim analysis.

This module is the **single source of truth** for the sidecar schema. All
writers (HLS rotation, audio archive) and readers (archive-search.py,
archive-purge.py) import ``SegmentSidecar`` from here.

Atomic writes use the tmp+rename pattern (same as research-registry.py) so
partial writes cannot be read by a concurrent reader.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SIDECAR_SCHEMA_VERSION = 1
"""Bump when a field is added, removed, or its meaning changes. Readers
inspect this and fall back to legacy handling if the version is older."""


@dataclass(frozen=True)
class SegmentSidecar:
    """Per-segment metadata sidecar JSON.

    Fields mirror the epic design doc §Phase 2 item 3. The schema version
    is pinned in ``SIDECAR_SCHEMA_VERSION``; bumps require migration
    handling in the readers.
    """

    schema_version: int
    segment_id: str
    segment_path: str
    condition_id: str | None
    segment_start_ts: str  # ISO8601 UTC
    segment_end_ts: str  # ISO8601 UTC
    duration_seconds: float
    reaction_ids: list[str]
    active_activity: str | None  # study / react / chat / vinyl / observe / silence
    stimmung_snapshot: dict[str, Any]
    directives_hash: str | None
    archive_kind: str  # "hls" | "audio_flac"
    created_at: str  # ISO8601 UTC when sidecar was written

    @classmethod
    def new(
        cls,
        *,
        segment_id: str,
        segment_path: Path | str,
        condition_id: str | None,
        segment_start_ts: datetime,
        segment_end_ts: datetime,
        reaction_ids: list[str] | None = None,
        active_activity: str | None = None,
        stimmung_snapshot: dict[str, Any] | None = None,
        directives_hash: str | None = None,
        archive_kind: str = "hls",
    ) -> SegmentSidecar:
        """Construct a fully-populated sidecar, normalizing timestamps."""
        if archive_kind not in ("hls", "audio_flac"):
            raise ValueError(f"archive_kind must be 'hls' or 'audio_flac', got {archive_kind!r}")
        start_utc = segment_start_ts.astimezone(UTC)
        end_utc = segment_end_ts.astimezone(UTC)
        if end_utc < start_utc:
            raise ValueError(
                f"segment_end_ts {end_utc.isoformat()} precedes segment_start_ts {start_utc.isoformat()}"
            )
        duration = (end_utc - start_utc).total_seconds()
        return cls(
            schema_version=SIDECAR_SCHEMA_VERSION,
            segment_id=segment_id,
            segment_path=str(segment_path),
            condition_id=condition_id,
            segment_start_ts=start_utc.isoformat().replace("+00:00", "Z"),
            segment_end_ts=end_utc.isoformat().replace("+00:00", "Z"),
            duration_seconds=round(duration, 3),
            reaction_ids=reaction_ids or [],
            active_activity=active_activity,
            stimmung_snapshot=stimmung_snapshot or {},
            directives_hash=directives_hash,
            archive_kind=archive_kind,
            created_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        )

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(asdict(self), indent=indent, sort_keys=True)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SegmentSidecar:
        """Parse a sidecar dict, asserting schema compatibility."""
        version = d.get("schema_version")
        if version is None:
            raise ValueError("sidecar missing schema_version")
        if version > SIDECAR_SCHEMA_VERSION:
            raise ValueError(
                f"sidecar schema_version {version} is newer than reader support {SIDECAR_SCHEMA_VERSION}"
            )
        return cls(**d)

    @classmethod
    def from_path(cls, path: Path) -> SegmentSidecar:
        """Read + parse a sidecar JSON file."""
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))


def atomic_write_json(path: Path, payload: str) -> None:
    """Write ``payload`` to ``path`` via tmp+rename. Same pattern as
    ``scripts/research-registry.py``. Ensures a concurrent reader never
    sees a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path_s = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path_s, path)
    except Exception:
        tmp_path = Path(tmp_path_s)
        if tmp_path.exists():
            tmp_path.unlink()
        raise


def archive_root() -> Path:
    """Return the stream archive root directory, respecting ``HAPAX_ARCHIVE_ROOT``
    if set (for dedicated-disk provisioning per retention policy §Separate-disk)."""
    override = os.environ.get("HAPAX_ARCHIVE_ROOT")
    if override:
        return Path(override)
    return Path.home() / "hapax-state" / "stream-archive"


def hls_archive_dir(at: datetime | None = None) -> Path:
    """Date-stamped HLS archive directory: ``<root>/hls/YYYY-MM-DD/``."""
    now = at or datetime.now(UTC)
    return archive_root() / "hls" / now.strftime("%Y-%m-%d")


def audio_archive_dir(at: datetime | None = None) -> Path:
    """Date-stamped audio archive directory: ``<root>/audio/YYYY-MM-DD/``."""
    now = at or datetime.now(UTC)
    return archive_root() / "audio" / now.strftime("%Y-%m-%d")


def sidecar_path_for(segment_path: Path) -> Path:
    """Return the sidecar path for a given segment path (`.ts` → `.ts.json`)."""
    return segment_path.with_suffix(segment_path.suffix + ".json")


__all__ = [
    "SIDECAR_SCHEMA_VERSION",
    "SegmentSidecar",
    "atomic_write_json",
    "archive_root",
    "hls_archive_dir",
    "audio_archive_dir",
    "sidecar_path_for",
]

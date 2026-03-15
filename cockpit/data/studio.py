"""Studio ingestion data collector for the cockpit.

Reads audio processor state, archive sidecars, and storage arbiter
report to produce a StudioSnapshot for the API.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

import yaml

from shared.config import (
    AUDIO_ARCHIVE_DIR,
    AUDIO_PROCESSOR_CACHE_DIR,
    AUDIO_RAG_DIR,
    AUDIO_RAW_DIR,
    PROFILES_DIR,
)

log = logging.getLogger(__name__)


@dataclass
class ProcessorStats:
    """Audio processor aggregate statistics."""

    total_processed: int = 0
    last_run: str = ""
    total_speech_hours: float = 0.0
    total_music_hours: float = 0.0
    total_sample_sessions: int = 0
    total_vocal_notes: int = 0
    total_conversations: int = 0
    total_listening_logs: int = 0
    errors: int = 0


@dataclass
class ArchiveStats:
    """Archive inventory statistics."""

    total_files: int = 0
    total_size_mb: float = 0.0
    pending_raw: int = 0
    rag_documents: int = 0


@dataclass
class ValueDistribution:
    """Distribution of value scores across archived files."""

    high: int = 0  # >= 0.7
    medium: int = 0  # 0.3 - 0.7
    low: int = 0  # < 0.3


@dataclass
class RecentClassification:
    """A recently classified audio file."""

    filename: str
    dominant_classification: str = ""
    value_score: float = 0.0
    speech_seconds: float = 0.0
    music_seconds: float = 0.0
    processed_at: str = ""


@dataclass
class ArbiterSummary:
    """Storage arbiter report summary."""

    total_files: int = 0
    total_size_mb: float = 0.0
    files_protected: int = 0
    files_eligible_for_reap: int = 0
    last_run: str = ""


@dataclass
class CaptureStatus:
    """Status of audio/video capture services."""

    audio_recorder_active: bool = False
    video_cameras: list[str] = field(default_factory=list)


@dataclass
class CompositorStatus:
    """Studio compositor pipeline status."""

    state: str = "unknown"  # running | stopped | error | unknown
    cameras: dict[str, str] = field(default_factory=dict)  # role -> active|offline
    active_cameras: int = 0
    total_cameras: int = 0
    output_device: str = ""
    resolution: str = ""


@dataclass
class StudioSnapshot:
    """Combined studio ingestion snapshot."""

    processor: ProcessorStats = field(default_factory=ProcessorStats)
    archive: ArchiveStats = field(default_factory=ArchiveStats)
    values: ValueDistribution = field(default_factory=ValueDistribution)
    recent: list[RecentClassification] = field(default_factory=list)
    arbiter: ArbiterSummary = field(default_factory=ArbiterSummary)
    capture: CaptureStatus = field(default_factory=CaptureStatus)
    compositor: CompositorStatus = field(default_factory=CompositorStatus)


def _collect_processor_stats() -> ProcessorStats:
    """Read audio processor state file."""
    state_file = AUDIO_PROCESSOR_CACHE_DIR / "state.json"
    if not state_file.exists():
        return ProcessorStats()

    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
        files = data.get("processed_files", {})
        last_run = data.get("last_run", 0)

        total_speech = sum(f.get("speech_seconds", 0) for f in files.values())
        total_music = sum(f.get("music_seconds", 0) for f in files.values())
        errors = sum(1 for f in files.values() if f.get("error"))

        from datetime import UTC, datetime

        last_run_str = ""
        if last_run:
            last_run_str = datetime.fromtimestamp(last_run, tz=UTC).isoformat()

        return ProcessorStats(
            total_processed=len(files),
            last_run=last_run_str,
            total_speech_hours=round(total_speech / 3600, 1),
            total_music_hours=round(total_music / 3600, 1),
            total_sample_sessions=sum(f.get("sample_sessions", 0) for f in files.values()),
            total_vocal_notes=sum(f.get("vocal_notes", 0) for f in files.values()),
            total_conversations=sum(f.get("conversations", 0) for f in files.values()),
            total_listening_logs=sum(f.get("listening_logs", 0) for f in files.values()),
            errors=errors,
        )
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Failed to read audio processor state: %s", exc)
        return ProcessorStats()


def _collect_archive_stats() -> tuple[ArchiveStats, ValueDistribution, list[RecentClassification]]:
    """Scan archive sidecars for stats and recent classifications."""
    stats = ArchiveStats()
    values = ValueDistribution()
    recent: list[RecentClassification] = []

    # Count pending raw files
    if AUDIO_RAW_DIR.exists():
        stats.pending_raw = len(list(AUDIO_RAW_DIR.glob("*.flac")))

    # Count RAG documents
    if AUDIO_RAG_DIR.exists():
        stats.rag_documents = len(list(AUDIO_RAG_DIR.glob("*.md")))

    if not AUDIO_ARCHIVE_DIR.exists():
        return stats, values, recent

    sidecars = sorted(AUDIO_ARCHIVE_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)

    for sidecar in sidecars:
        flac = sidecar.with_suffix(".flac")
        if not flac.exists():
            continue

        stats.total_files += 1
        try:
            stats.total_size_mb += flac.stat().st_size / (1024 * 1024)
        except OSError:
            pass

        try:
            text = sidecar.read_text(encoding="utf-8")
            if not text.startswith("---"):
                continue
            parts = text.split("---", 2)
            if len(parts) < 3:
                continue
            fm = yaml.safe_load(parts[1])
            if not isinstance(fm, dict):
                continue

            score = fm.get("value_score", 0.0)
            if score >= 0.7:
                values.high += 1
            elif score >= 0.3:
                values.medium += 1
            else:
                values.low += 1

            # Keep last 20 for recent list
            if len(recent) < 20:
                recent.append(
                    RecentClassification(
                        filename=flac.name,
                        dominant_classification=fm.get("dominant_classification", ""),
                        value_score=round(score, 3),
                        speech_seconds=fm.get("speech_seconds", 0.0),
                        music_seconds=fm.get("music_seconds", 0.0),
                        processed_at=fm.get("processed_at", ""),
                    )
                )
        except (yaml.YAMLError, OSError):
            pass

    stats.total_size_mb = round(stats.total_size_mb, 1)
    return stats, values, recent


def _collect_arbiter_summary() -> ArbiterSummary:
    """Read the storage arbiter report."""
    report_path = PROFILES_DIR / "storage-arbiter-report.md"
    if not report_path.exists():
        return ArbiterSummary()

    try:
        text = report_path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            return ArbiterSummary()
        parts = text.split("---", 2)
        if len(parts) < 3:
            return ArbiterSummary()
        fm = yaml.safe_load(parts[1])
        if not isinstance(fm, dict):
            return ArbiterSummary()

        return ArbiterSummary(
            total_files=fm.get("total_files", 0),
            total_size_mb=fm.get("total_size_mb", 0.0),
            files_protected=fm.get("files_protected", 0),
            files_eligible_for_reap=fm.get("files_eligible_for_reap", 0),
            last_run=fm.get("timestamp", ""),
        )
    except (yaml.YAMLError, OSError) as exc:
        log.warning("Failed to read arbiter report: %s", exc)
        return ArbiterSummary()


def _collect_capture_status() -> CaptureStatus:
    """Check if audio/video capture services are running."""
    import subprocess

    status = CaptureStatus()

    # Audio recorder
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", "audio-recorder.service"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        status.audio_recorder_active = result.stdout.strip() == "active"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Video cameras
    for role in ["brio", "c920-hardware", "c920-room", "c920-aux"]:
        try:
            result = subprocess.run(
                ["systemctl", "--user", "is-active", f"hapax-video-cam@{role}.service"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.stdout.strip() == "active":
                status.video_cameras.append(role)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    return status


def _collect_compositor_status() -> CompositorStatus:
    """Read studio compositor status file."""
    from pathlib import Path

    status_file = Path.home() / ".cache" / "hapax-compositor" / "status.json"
    if not status_file.exists():
        return CompositorStatus()

    try:
        data = json.loads(status_file.read_text(encoding="utf-8"))
        return CompositorStatus(
            state=data.get("state", "unknown"),
            cameras=data.get("cameras", {}),
            active_cameras=data.get("active_cameras", 0),
            total_cameras=data.get("total_cameras", 0),
            output_device=data.get("output_device", ""),
            resolution=data.get("resolution", ""),
        )
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Failed to read compositor status: %s", exc)
        return CompositorStatus()


def collect_studio() -> StudioSnapshot:
    """Collect all studio ingestion data into a single snapshot."""
    processor = _collect_processor_stats()
    archive, values, recent = _collect_archive_stats()
    arbiter = _collect_arbiter_summary()
    capture = _collect_capture_status()
    compositor = _collect_compositor_status()

    return StudioSnapshot(
        processor=processor,
        archive=archive,
        values=values,
        recent=recent,
        arbiter=arbiter,
        capture=capture,
        compositor=compositor,
    )

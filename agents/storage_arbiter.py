"""storage_arbiter.py — Orchestrates audio archive value assessment and lifecycle.

Reads archive sidecars, computes composite value scores, writes an hourly
report to profiles/storage-arbiter-report.md. Delegates scoring to
value_judge and deletion to storage_reaper.

Tier 3 agent: no LLM calls, runs on systemd timer (hourly).

Usage:
    uv run python -m agents.storage_arbiter --run     # Run assessment cycle
    uv run python -m agents.storage_arbiter --report   # Print current report
"""

from __future__ import annotations

import argparse
import logging
from datetime import UTC, datetime
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from shared.config import AUDIO_ARCHIVE_DIR, PROFILES_DIR

log = logging.getLogger(__name__)

REPORT_PATH = PROFILES_DIR / "storage-arbiter-report.md"

# ── Scoring weights ──────────────────────────────────────────────────────────

SCORE_WEIGHTS = {
    "classification_richness": 0.25,
    "rag_reference_count": 0.20,
    "temporal_neighbors": 0.15,
    "uniqueness": 0.20,
    "recency_weight": 0.20,
}

# Sufficiency floor: minimum retention of 7 days
MIN_RETENTION_DAYS = 7


# ── Models ───────────────────────────────────────────────────────────────────


class ArchivedFile(BaseModel):
    """Parsed state of an archived audio file from its sidecar."""

    filename: str
    archive_path: Path
    sidecar_path: Path
    value_score: float = 0.0
    disposition: str = "archive"
    dominant_classification: str = "silence"
    processed_at: str = ""
    speech_seconds: float = 0.0
    music_seconds: float = 0.0
    segment_count: int = 0
    sample_sessions: int = 0
    listening_logs: int = 0

    model_config = {"arbitrary_types_allowed": True}


class ArbiterReport(BaseModel):
    """Output report from a storage arbiter run."""

    timestamp: str
    total_files: int = 0
    total_size_mb: float = 0.0
    files_assessed: int = 0
    files_below_threshold: int = 0
    files_protected: int = 0
    files_eligible_for_reap: int = 0
    top_value_files: list[str] = Field(default_factory=list)
    lowest_value_files: list[str] = Field(default_factory=list)


# ── Core logic ───────────────────────────────────────────────────────────────


def scan_archive(archive_dir: Path | None = None) -> list[ArchivedFile]:
    """Scan the archive directory for FLAC files with sidecars."""
    base = archive_dir or AUDIO_ARCHIVE_DIR
    if not base.exists():
        return []

    files = []
    for sidecar in sorted(base.glob("*.md")):
        flac = sidecar.with_suffix(".flac")
        if not flac.exists():
            continue

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

            files.append(
                ArchivedFile(
                    filename=flac.name,
                    archive_path=flac,
                    sidecar_path=sidecar,
                    value_score=fm.get("value_score", 0.0),
                    disposition=fm.get("disposition", "archive"),
                    dominant_classification=fm.get("dominant_classification", "silence"),
                    processed_at=fm.get("processed_at", ""),
                    speech_seconds=fm.get("speech_seconds", 0.0),
                    music_seconds=fm.get("music_seconds", 0.0),
                    segment_count=fm.get("segment_count", 0),
                    sample_sessions=fm.get("sample_sessions", 0),
                    listening_logs=fm.get("listening_logs", 0),
                )
            )
        except (yaml.YAMLError, OSError) as exc:
            log.warning("Failed to parse sidecar %s: %s", sidecar, exc)

    return files


def compute_composite_score(file: ArchivedFile, all_files: list[ArchivedFile]) -> float:
    """Compute a composite value score for an archived file.

    Factors:
      - classification_richness: diversity of content (multiple doc types)
      - rag_reference_count: how many RAG docs were generated
      - temporal_neighbors: files processed near the same time (session value)
      - uniqueness: inverse of how common this classification is
      - recency_weight: newer files score higher
    """
    # Classification richness: more content types = richer
    types_present = sum(
        [
            file.sample_sessions > 0,
            file.listening_logs > 0,
            file.speech_seconds > 30,
            file.music_seconds > 60,
        ]
    )
    richness = min(1.0, types_present / 3.0)

    # RAG reference count (normalized)
    rag_count = min(1.0, file.segment_count / 5.0)

    # Temporal neighbors (files within 1 hour)
    neighbor_count = 0
    if file.processed_at:
        try:
            file_time = datetime.fromisoformat(file.processed_at)
            for other in all_files:
                if other.filename == file.filename or not other.processed_at:
                    continue
                other_time = datetime.fromisoformat(other.processed_at)
                delta = abs((file_time - other_time).total_seconds())
                if delta < 3600:
                    neighbor_count += 1
        except (ValueError, TypeError):
            pass
    temporal = min(1.0, neighbor_count / 3.0)

    # Uniqueness: inverse of classification frequency
    if all_files:
        same_class = sum(
            1 for f in all_files if f.dominant_classification == file.dominant_classification
        )
        uniqueness = 1.0 - (same_class / len(all_files))
    else:
        uniqueness = 0.5

    # Recency: days since processing (decay over 30 days)
    recency = 0.5
    if file.processed_at:
        try:
            processed = datetime.fromisoformat(file.processed_at)
            age_days = (datetime.now(tz=UTC) - processed).total_seconds() / 86400
            recency = max(0.0, 1.0 - age_days / 30.0)
        except (ValueError, TypeError):
            pass

    # Weighted composite
    score = (
        SCORE_WEIGHTS["classification_richness"] * richness
        + SCORE_WEIGHTS["rag_reference_count"] * rag_count
        + SCORE_WEIGHTS["temporal_neighbors"] * temporal
        + SCORE_WEIGHTS["uniqueness"] * uniqueness
        + SCORE_WEIGHTS["recency_weight"] * recency
    )
    return round(min(1.0, score), 3)


def is_protected(file: ArchivedFile) -> bool:
    """Check if a file is protected from reaping.

    Protection rules:
      - RAG docs were generated (segment_count > 0)
      - Less than MIN_RETENTION_DAYS old
      - Contains sample sessions (highest producer value)
    """
    if file.segment_count > 0:
        return True
    if file.sample_sessions > 0:
        return True
    if file.processed_at:
        try:
            processed = datetime.fromisoformat(file.processed_at)
            age_days = (datetime.now(tz=UTC) - processed).total_seconds() / 86400
            if age_days < MIN_RETENTION_DAYS:
                return True
        except (ValueError, TypeError):
            pass
    return False


def run_assessment(archive_dir: Path | None = None) -> ArbiterReport:
    """Run a full archive assessment cycle."""
    files = scan_archive(archive_dir)
    if not files:
        return ArbiterReport(timestamp=datetime.now(tz=UTC).isoformat(), total_files=0)

    # Compute composite scores
    scored = []
    for f in files:
        composite = compute_composite_score(f, files)
        scored.append((f, composite))

    scored.sort(key=lambda x: x[1], reverse=True)

    # Classify files
    reap_threshold = 0.15
    protected = [(f, s) for f, s in scored if is_protected(f)]
    below_threshold = [(f, s) for f, s in scored if s < reap_threshold]
    eligible = [(f, s) for f, s in below_threshold if not is_protected(f)]

    # Total size
    total_bytes = sum(f.archive_path.stat().st_size for f, _ in scored if f.archive_path.exists())

    report = ArbiterReport(
        timestamp=datetime.now(tz=UTC).isoformat(),
        total_files=len(scored),
        total_size_mb=round(total_bytes / (1024 * 1024), 1),
        files_assessed=len(scored),
        files_below_threshold=len(below_threshold),
        files_protected=len(protected),
        files_eligible_for_reap=len(eligible),
        top_value_files=[f.filename for f, _ in scored[:5]],
        lowest_value_files=[f.filename for f, _ in scored[-5:]],
    )

    return report


def write_report(report: ArbiterReport, path: Path | None = None) -> None:
    """Write the arbiter report as a markdown file."""
    out = path or REPORT_PATH
    out.parent.mkdir(parents=True, exist_ok=True)

    content = f"""---
type: storage-arbiter-report
timestamp: {report.timestamp}
total_files: {report.total_files}
total_size_mb: {report.total_size_mb}
files_assessed: {report.files_assessed}
files_below_threshold: {report.files_below_threshold}
files_protected: {report.files_protected}
files_eligible_for_reap: {report.files_eligible_for_reap}
---

# Storage Arbiter Report

Generated: {report.timestamp}

## Summary

| Metric | Value |
|--------|-------|
| Total files | {report.total_files} |
| Total size | {report.total_size_mb} MB |
| Below threshold | {report.files_below_threshold} |
| Protected | {report.files_protected} |
| Eligible for reap | {report.files_eligible_for_reap} |

## Top Value Files

{chr(10).join(f"- {f}" for f in report.top_value_files) or "(none)"}

## Lowest Value Files

{chr(10).join(f"- {f}" for f in report.lowest_value_files) or "(none)"}
"""
    out.write_text(content, encoding="utf-8")
    log.info("Wrote arbiter report: %s", out)


# ── CLI ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Audio archive storage arbiter")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--run", action="store_true", help="Run assessment cycle")
    group.add_argument("--report", action="store_true", help="Print current report")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    from shared.log_setup import configure_logging

    configure_logging(agent="storage-arbiter", level="DEBUG" if args.verbose else None)

    if args.run:
        report = run_assessment()
        write_report(report)
        log.info(
            "Assessment complete: %d files, %d eligible for reap",
            report.total_files,
            report.files_eligible_for_reap,
        )
    elif args.report:
        if REPORT_PATH.exists():
            print(REPORT_PATH.read_text())
        else:
            print("No report found. Run --run first.")


if __name__ == "__main__":
    main()

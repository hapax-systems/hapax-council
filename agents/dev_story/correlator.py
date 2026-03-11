"""Correlation engine — joins conversation file changes to git commits."""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from agents.dev_story.models import Correlation, FileChange, CommitFile

log = logging.getLogger(__name__)

# Maximum time difference (minutes) for timestamp-based correlation
_TIMESTAMP_WINDOW = 30.0
# Maximum time for file-only match (hours)
_FILE_ONLY_MAX_HOURS = 12.0


def _parse_iso_timestamp(ts: str) -> datetime | None:
    """Parse various timestamp formats to timezone-aware datetime."""
    if not ts:
        return None
    # Strip trailing Z and add UTC
    ts = ts.strip()
    try:
        if ts.endswith("Z"):
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        # Handle "2026-03-10 10:00:00 -0500" format
        if " -" in ts or " +" in ts:
            # Python's fromisoformat handles this in 3.11+
            return datetime.fromisoformat(ts.replace(" -", "-").replace(" +", "+"))
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def _time_diff_minutes(ts1: str, ts2: str) -> float | None:
    """Compute absolute time difference in minutes between two timestamps."""
    dt1 = _parse_iso_timestamp(ts1)
    dt2 = _parse_iso_timestamp(ts2)
    if dt1 is None or dt2 is None:
        return None
    # Ensure both are UTC for comparison
    if dt1.tzinfo is None:
        dt1 = dt1.replace(tzinfo=timezone.utc)
    if dt2.tzinfo is None:
        dt2 = dt2.replace(tzinfo=timezone.utc)
    return abs((dt2 - dt1).total_seconds()) / 60.0


def correlate(
    file_changes: list[FileChange],
    commit_files: list[CommitFile],
    commit_dates: dict[str, str],
) -> list[Correlation]:
    """Correlate file changes from sessions with git commits.

    Args:
        file_changes: File changes extracted from session transcripts.
        commit_files: Files changed per commit from git log.
        commit_dates: Mapping of commit hash -> author_date string.

    Returns:
        List of correlations with confidence scores.
    """
    # Build index: file_path -> list of commit_files
    commit_file_index: dict[str, list[CommitFile]] = {}
    for cf in commit_files:
        commit_file_index.setdefault(cf.file_path, []).append(cf)

    # Track best correlation per (message_id, commit_hash) pair
    best: dict[tuple[str, str], Correlation] = {}

    for fc in file_changes:
        matching_commits = commit_file_index.get(fc.file_path, [])
        for cf in matching_commits:
            pair = (fc.message_id, cf.commit_hash)
            commit_date = commit_dates.get(cf.commit_hash, "")
            diff = _time_diff_minutes(fc.timestamp, commit_date)

            if diff is not None and diff <= _TIMESTAMP_WINDOW:
                # Close in time AND same file — highest confidence
                confidence = 0.95 - (diff / _TIMESTAMP_WINDOW) * 0.1  # 0.85-0.95
                method = "file_and_timestamp"
            elif diff is not None and diff <= _FILE_ONLY_MAX_HOURS * 60:
                # Same file but farther in time
                confidence = 0.7 - (diff / (_FILE_ONLY_MAX_HOURS * 60)) * 0.2  # 0.5-0.7
                method = "file_match"
            else:
                continue  # Too far apart or unparseable

            # Keep best confidence per pair, boost if multiple files match
            existing = best.get(pair)
            if existing:
                # Multiple file matches — boost confidence
                boosted = min(existing.confidence + 0.05, 1.0)
                if boosted > existing.confidence:
                    best[pair] = Correlation(
                        message_id=pair[0],
                        commit_hash=pair[1],
                        confidence=boosted,
                        method=existing.method,
                    )
            else:
                best[pair] = Correlation(
                    message_id=pair[0],
                    commit_hash=pair[1],
                    confidence=confidence,
                    method=method,
                )

    return list(best.values())

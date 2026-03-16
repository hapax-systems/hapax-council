"""shared/olaf.py — Olaf audio fingerprinting CLI wrapper.

Wraps the Olaf fingerprinting tool for:
  - fingerprint(): Extract fingerprint from audio file
  - store(): Store fingerprint in Olaf's database
  - query(): Query for matching audio (returns replay count + matches)
  - delete(): Remove fingerprints for a file (consent purge support)

Olaf must be installed separately (https://github.com/JorenSix/Olaf).
All operations are synchronous subprocess calls.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# Default Olaf binary name (must be on PATH)
_OLAF_BIN = "olaf"
_TIMEOUT = 30


@dataclass(frozen=True)
class OlafMatch:
    """A single fingerprint match result."""

    matched_file: str
    match_score: float
    time_offset: float


@dataclass(frozen=True)
class OlafResult:
    """Result from an Olaf query."""

    query_file: str
    matches: list[OlafMatch]
    replay_count: int

    @property
    def is_replay(self) -> bool:
        """True if the audio has been heard before."""
        return self.replay_count > 0


def _run_olaf(args: list[str], timeout: int = _TIMEOUT) -> subprocess.CompletedProcess:
    """Run an Olaf command and return the result."""
    cmd = [_OLAF_BIN, *args]
    log.debug("Running: %s", " ".join(cmd))
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def available() -> bool:
    """Check if Olaf is installed and accessible."""
    try:
        result = _run_olaf(["--help"], timeout=5)
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def store(audio_path: Path) -> bool:
    """Store audio fingerprints in Olaf's database.

    Args:
        audio_path: Path to audio file (WAV, FLAC, etc.)

    Returns:
        True on success, False on failure.
    """
    if not audio_path.exists():
        log.warning("Audio file not found: %s", audio_path)
        return False

    result = _run_olaf(["store", str(audio_path)])
    if result.returncode != 0:
        log.warning("Olaf store failed for %s: %s", audio_path, result.stderr.strip())
        return False

    log.info("Stored fingerprint: %s", audio_path.name)
    return True


def query(audio_path: Path) -> OlafResult:
    """Query Olaf's database for matching audio.

    Args:
        audio_path: Path to audio file to query.

    Returns:
        OlafResult with matches and replay count.
    """
    if not audio_path.exists():
        return OlafResult(query_file=str(audio_path), matches=[], replay_count=0)

    result = _run_olaf(["query", str(audio_path)])
    if result.returncode != 0:
        log.warning("Olaf query failed for %s: %s", audio_path, result.stderr.strip())
        return OlafResult(query_file=str(audio_path), matches=[], replay_count=0)

    matches = _parse_query_output(result.stdout)
    replay_count = len(matches)

    return OlafResult(
        query_file=str(audio_path),
        matches=matches,
        replay_count=replay_count,
    )


def delete(audio_path: Path) -> bool:
    """Remove fingerprints for a file from Olaf's database.

    Required for consent purge support — guest fingerprints must be
    purgeable via the carrier registry.

    Args:
        audio_path: Path to the audio file whose fingerprints to remove.

    Returns:
        True on success, False on failure.
    """
    result = _run_olaf(["delete", str(audio_path)])
    if result.returncode != 0:
        log.warning("Olaf delete failed for %s: %s", audio_path, result.stderr.strip())
        return False

    log.info("Deleted fingerprint: %s", audio_path.name)
    return True


def _parse_query_output(stdout: str) -> list[OlafMatch]:
    """Parse Olaf query output into match objects.

    Olaf outputs one match per line in the format:
    matched_file.wav  score  time_offset
    """
    matches = []
    for line in stdout.strip().splitlines():
        parts = line.strip().split()
        if len(parts) >= 3:
            try:
                matches.append(
                    OlafMatch(
                        matched_file=parts[0],
                        match_score=float(parts[1]),
                        time_offset=float(parts[2]),
                    )
                )
            except (ValueError, IndexError):
                continue
    return matches
